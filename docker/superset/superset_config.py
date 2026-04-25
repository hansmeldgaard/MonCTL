"""Superset config for MonCTL dev deployment.

Loaded via SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py.
Values pulled from env vars populated by docker-compose.superset.yml.
"""

import logging
import os

from flask_appbuilder.security.manager import AUTH_OAUTH
from superset.security import SupersetSecurityManager

logger = logging.getLogger(__name__)

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# ---------------------------------------------------------------------------
# Session lifetime — bounds the staleness window for MonCTL tenant scope
# ---------------------------------------------------------------------------
# The tenant scope (`monctl_all_tenants`, `monctl_tenant_ids`) is snapshotted
# from MonCTL at OAuth login and cached in the Flask session. A role/tenant
# change in MonCTL only propagates on the user's next sign-in. Keep the
# session short so stale scope can't leak data indefinitely — 1h is the
# upper bound we're comfortable with.
import datetime as _dt

PERMANENT_SESSION_LIFETIME = _dt.timedelta(hours=1)
SESSION_REFRESH_EACH_REQUEST = True

# Metadata DB — separate Postgres container, not the MonCTL production PG.
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{os.environ['DATABASE_USER']}:"
    f"{os.environ['DATABASE_PASSWORD']}@"
    f"{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}/"
    f"{os.environ['DATABASE_DB']}"
)

# Cache + async query results. Separate Redis DBs so they don't collide.
_REDIS_HOST = os.environ["REDIS_HOST"]
_REDIS_PORT = os.environ["REDIS_PORT"]

CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "superset_",
    "CACHE_REDIS_HOST": _REDIS_HOST,
    "CACHE_REDIS_PORT": _REDIS_PORT,
    "CACHE_REDIS_DB": 1,
}
DATA_CACHE_CONFIG = {**CACHE_CONFIG, "CACHE_KEY_PREFIX": "superset_data_"}
FILTER_STATE_CACHE_CONFIG = {**CACHE_CONFIG, "CACHE_KEY_PREFIX": "superset_filter_"}
EXPLORE_FORM_DATA_CACHE_CONFIG = {**CACHE_CONFIG, "CACHE_KEY_PREFIX": "superset_form_"}

# ---------------------------------------------------------------------------
# Reverse-proxy setup: Superset lives behind HAProxy at /superset/*
# ---------------------------------------------------------------------------

# URL prefix handling: Superset is served publicly at /bi/* via HAProxy.
# We mount the Flask WSGI app under /bi using DispatcherMiddleware — that
# strips the prefix AND populates SCRIPT_NAME automatically, so every URL
# that Flask builds via url_for() (including /static/..., /login/..., the
# OAuth callback) carries the /bi prefix. This is the only reliable way to
# deploy Superset under a subpath — APPLICATION_ROOT alone + ProxyFix
# doesn't cover hardcoded asset URLs in the HTML shell.
ENABLE_PROXY_FIX = True

# Prefix applied to static assets (fontawesome, appbuilder, favicon) via the
# `assets_prefix` template variable that Superset exposes in base.html /
# basic.html. Must match the /bi mount below.
STATIC_ASSETS_PREFIX = "/bi"


def _mount_at_bi(app):
    """Mount Superset at /bi so SCRIPT_NAME is populated for all requests,
    AND prefix webpack-manifest entries with /bi (STATIC_ASSETS_PREFIX alone
    only handles the non-webpack static URLs baked into Jinja templates)."""
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    # -- Prefix manifest entries -----------------------------------------------
    # Superset's js_bundle/css_bundle macros iterate over js_manifest(bundle) /
    # css_manifest(bundle) and emit `<script src="{{ entry }}">` without passing
    # the entry through assets_prefix. Register a context processor that runs
    # AFTER the built-in UIManifestProcessor (which was registered earlier in
    # init_app_in_ctx) so our js_manifest/css_manifest keys override theirs.
    # Later context processors win on duplicate dict keys.
    from superset.extensions import manifest_processor

    @app.context_processor
    def _prefixed_manifest():
        prefix = app.config.get("STATIC_ASSETS_PREFIX", "") or ""
        if not prefix:
            return {}

        def _prefix(p: str) -> str:
            if p.startswith("/") and not p.startswith(prefix + "/"):
                return prefix + p
            return p

        return {
            "js_manifest": lambda bundle: [
                _prefix(p) for p in manifest_processor.get_manifest_files(bundle, "js")
            ],
            "css_manifest": lambda bundle: [
                _prefix(p) for p in manifest_processor.get_manifest_files(bundle, "css")
            ],
            "assets_prefix": prefix,
        }

    # -- Override webpack publicPath at runtime --------------------------------
    # Superset's webpack bundle has `publicPath = "/static/assets/"` baked in at
    # build time. When a lazy-loaded chunk is requested, the browser fetches
    # /static/assets/<hash>.chunk.js — NO /bi prefix, SCRIPT_NAME can't help.
    # Fix: inject `__webpack_public_path__` in the <head> before the webpack
    # runtime executes. Webpack checks that variable first.
    from flask import request

    # Runs BEFORE Superset's bundle executes:
    #   1. Sets __webpack_public_path__ so webpack lazy-loads chunks from /bi/
    #      (mostly superseded by the HAProxy /static/ rewrite, but kept as
    #      defence-in-depth).
    #   2. Strips the /bi prefix from the browser URL so Superset's React
    #      Router — which has route patterns like `/dashboard/list` without
    #      any basename — can match the current path. Links that Superset
    #      generates server-side via url_for keep the /bi prefix; when the
    #      user clicks one, the browser navigates, the server renders, and
    #      THIS same script runs again to strip the prefix before React boots.
    _INJECT = (
        b"<script>"
        b"__webpack_public_path__ = \"/bi/static/assets/\";"
        b"if(location.pathname.indexOf(\"/bi/\")===0){"
        b"history.replaceState(null,\"\","
        b"location.pathname.slice(3)+location.search+location.hash);}"
        b"</script>"
    )

    @app.after_request
    def _inject_webpack_public_path(response):
        # Only HTML responses; skip API endpoints and redirects.
        ct = (response.content_type or "").split(";")[0].strip()
        if ct != "text/html":
            return response
        # Only under /bi (DispatcherMiddleware strips before we see it, so the
        # Flask request.path is /something, but HTTP_SCRIPT_NAME tells us).
        if request.environ.get("SCRIPT_NAME", "") != "/bi":
            return response
        try:
            body = response.get_data()
            # Place before the first <script> tag so __webpack_public_path__
            # is set before any webpack runtime runs.
            needle = b"<script"
            idx = body.find(needle)
            if idx == -1:
                return response
            response.set_data(body[:idx] + _INJECT + body[idx:])
        except Exception:
            pass
        return response

    # -- MonCTL tenant RLS: seed filter + auto-attach to new datasets ---------
    # Keep this BEFORE the DispatcherMiddleware swap so ORM event listeners
    # attach to the underlying Flask app, not the middleware.
    _install_monctl_rls(app)

    # -- Periodic tenant-scope refresh ----------------------------------------
    # Session scope is snapshotted at OAuth login. If an admin revokes a
    # tenant in MonCTL, the user keeps their old scope until they sign in
    # again. Cut the staleness window to ~60s by re-fetching userinfo every
    # 60s per active session; if MonCTL rejects the stored access token
    # (expired / revoked) we clear the session so the next request starts
    # a fresh OAuth flow.
    import time as _time
    import urllib.request as _urlreq
    import json as _json

    _MONCTL_INTERNAL = os.environ.get(
        "MONCTL_INTERNAL_BASE", "http://10.145.210.41:8443"
    )
    _REFRESH_INTERVAL_SECONDS = 60

    @app.before_request
    def _refresh_monctl_tenant_scope():
        from flask import request, session
        from flask_login import current_user, logout_user
        import base64 as _b64
        import json as _json2

        # -- Cross-user session leak guard ------------------------------------
        # Superset's `session` cookie is HttpOnly and persists independently of
        # MonCTL's `access_token` cookie. If user A signs into MonCTL then
        # Superset, signs out of MonCTL, and user B signs into MonCTL on the
        # same browser → the iframe still carries user A's Superset cookies
        # and user B would see user A's Superset data. Detect the mismatch
        # and force a Superset logout so B goes through OAuth cleanly.
        mon_tok = request.cookies.get("access_token")
        sset_user = getattr(current_user, "username", None) if current_user else None
        if mon_tok and sset_user:
            try:
                # Decode without verifying the signature — we only need the
                # username claim for matching; the real auth check happens
                # against MonCTL at the next OAuth flow.
                parts = mon_tok.split(".")
                if len(parts) >= 2:
                    pad = "=" * (-len(parts[1]) % 4)
                    payload = _json2.loads(
                        _b64.urlsafe_b64decode(parts[1] + pad).decode()
                    )
                    mon_user = payload.get("username")
                    if mon_user and mon_user != sset_user:
                        logger.info(
                            "monctl/superset user mismatch: "
                            "monctl=%s superset=%s — clearing session",
                            mon_user, sset_user,
                        )
                        logout_user()
                        session.clear()
                        # Skip the scope-refresh block below.
                        return None
            except Exception:
                # Malformed cookie — don't block the request; the scope
                # refresh below will deal with any staleness.
                pass

        # Skip anonymous + unauthenticated bootstrap requests.
        if "monctl_all_tenants" not in session:
            return None
        last = session.get("monctl_scope_ts", 0)
        now = _time.time()
        if now - last < _REFRESH_INTERVAL_SECONDS:
            return None
        # Pull the current OAuth access token FAB cached for this user.
        # Stored by authlib under the provider-scoped session key.
        tok = session.get("monctl_oauth_token") or session.get("_monctl_authlib_token_")
        if not tok:
            # Scan the session for any authlib token blob; layout changes
            # between authlib versions.
            for k, v in session.items():
                if isinstance(v, dict) and "access_token" in v:
                    tok = v
                    break
        access = (tok or {}).get("access_token") if isinstance(tok, dict) else None
        if not access:
            session["monctl_scope_ts"] = now  # don't re-try every request
            return None
        try:
            req = _urlreq.Request(
                f"{_MONCTL_INTERNAL}/v1/oauth/userinfo",
                headers={"Authorization": f"Bearer {access}"},
            )
            with _urlreq.urlopen(req, timeout=3) as resp:
                data = _json.loads(resp.read().decode())
        except Exception:
            # Transient error — don't lock the user out, just skip.
            session["monctl_scope_ts"] = now
            return None
        all_t = bool(data.get("all_tenants"))
        ids = list(data.get("tenant_ids") or [])
        if (
            all_t != bool(session.get("monctl_all_tenants"))
            or ids != list(session.get("monctl_tenant_ids") or [])
        ):
            session["monctl_all_tenants"] = all_t
            session["monctl_tenant_ids"] = ids
            session.modified = True
            logger.info(
                "monctl scope refreshed: all_tenants=%s tenant_ids=%s",
                all_t, ids,
            )
        session["monctl_scope_ts"] = now
        return None

    # -- Mount at /bi so Flask sees SCRIPT_NAME=/bi via WSGI dispatcher --------
    def _not_found(environ, start_response):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Superset is served under /bi/ on this host.\n"]

    app.wsgi_app = DispatcherMiddleware(_not_found, {"/bi": app.wsgi_app})

FLASK_APP_MUTATOR = _mount_at_bi
PROXY_FIX_CONFIG = {
    "x_for": 1,
    "x_proto": 1,
    "x_host": 1,
    "x_port": 1,
    "x_prefix": 1,
}
WTF_CSRF_TRUSTED_ORIGINS = [
    os.environ.get("SUPERSET_PUBLIC_ORIGIN", "https://10.145.210.40"),
]

# ---------------------------------------------------------------------------
# OAuth2 SSO against MonCTL central
# ---------------------------------------------------------------------------

_MONCTL_OAUTH_CLIENT_ID = os.environ.get("MONCTL_OAUTH_CLIENT_ID", "")
_MONCTL_OAUTH_CLIENT_SECRET = os.environ.get("MONCTL_OAUTH_CLIENT_SECRET", "")
# Browser-facing authorize URL — goes through HAProxy on the VIP.
_MONCTL_PUBLIC_BASE = os.environ.get("MONCTL_PUBLIC_BASE", "https://10.145.210.40")
# Server-side token/userinfo URLs — direct HTTP to a single central node so
# we don't have to trust HAProxy's self-signed cert from inside this container.
# Single node is a SPOF for SSO; acceptable for dev. Upgrade path: front an
# internal-only HAProxy listener or install the central CA here.
_MONCTL_INTERNAL_BASE = os.environ.get(
    "MONCTL_INTERNAL_BASE", "http://10.145.210.41:8443"
)

if _MONCTL_OAUTH_CLIENT_ID and _MONCTL_OAUTH_CLIENT_SECRET:
    AUTH_TYPE = AUTH_OAUTH
    AUTH_USER_REGISTRATION = True
    # Default role for any user who logs in via OAuth and isn't matched by
    # AUTH_ROLES_MAPPING below. Gamma has chart/dashboard read, nothing else.
    # Fallback if AUTH_ROLES_MAPPING has no entry; also serves as the default
    # for users that get created before init.sh has run once.
    AUTH_USER_REGISTRATION_ROLE = "MonCTLViewer"
    # Re-apply role mapping on every login so a role change in MonCTL
    # (admin → viewer, etc.) takes effect on the user's next sign-in without
    # needing manual intervention in Superset.
    AUTH_ROLES_SYNC_AT_LOGIN = True
    AUTH_ROLES_MAPPING = {
        # `superset_access` claim → list of Superset FAB role names.
        # MonCTLViewer  (Gamma + all_datasource_access − sql_lab) — read only.
        # MonCTLAnalyst (Alpha + all_datasource_access + sql_lab)  — chart
        #               creation + raw SQL. Layer 3 row policies still scope
        #               rows server-side, so SQL Lab is safe.
        # Admin         — full Superset admin.
        # 'none' is rejected upstream at /v1/oauth/authorize.
        "admin": ["Admin"],
        "analyst": ["MonCTLAnalyst"],
        "viewer": ["MonCTLViewer"],
        # Backward-compat aliases for OAuth servers that still emit the
        # legacy `role` claim ("admin" or "user"). Once every client is on
        # the new `superset_access` claim these can be removed.
        "user": ["MonCTLViewer"],
    }

    OAUTH_PROVIDERS = [
        {
            "name": "monctl",
            "icon": "fa-shield",
            "token_key": "access_token",
            "remote_app": {
                "client_id": _MONCTL_OAUTH_CLIENT_ID,
                "client_secret": _MONCTL_OAUTH_CLIENT_SECRET,
                "api_base_url": f"{_MONCTL_INTERNAL_BASE}/v1/",
                "access_token_url": f"{_MONCTL_INTERNAL_BASE}/v1/oauth/token",
                "authorize_url": f"{_MONCTL_PUBLIC_BASE}/v1/oauth/authorize",
                "client_kwargs": {
                    # No "openid" — with the HS256 id_token we emit, authlib
                    # would demand a jwks_uri for verification. Stripping the
                    # OIDC scope makes this a plain OAuth2 flow; userinfo is
                    # fetched via Bearer access_token instead of parsing the
                    # id_token. Matches how AUTH_OAUTH works in FAB anyway.
                    "scope": "profile email",
                    "token_endpoint_auth_method": "client_secret_basic",
                },
            },
        }
    ]

    class MonctlSecurityManager(SupersetSecurityManager):
        def oauth_user_info(self, provider, response=None):  # noqa: ARG002
            """Fetch MonCTL userinfo and map to Superset's user shape.

            Also caches the user's MonCTL tenant scope (`tenant_ids`,
            `all_tenants`) on the request-scoped Flask `g` so that
            `_sync_monctl_tenant_scope` — called just after FAB creates or
            updates the user row — can persist it to that user's
            UserAttribute table. RLS filters consult that attribute.
            """
            if provider != "monctl":
                return {}
            res = self.appbuilder.sm.oauth_remotes[provider].get("oauth/userinfo")
            data = res.json()
            display = data.get("name") or data.get("username") or ""
            first, _, last = display.partition(" ")

            from flask import g as _g
            _g._monctl_all_tenants = bool(data.get("all_tenants"))
            _g._monctl_tenant_ids = list(data.get("tenant_ids") or [])

            # Prefer the new `superset_access` tier claim (none|viewer|
            # analyst|admin) over the legacy MonCTL `role` (admin|user).
            # Accept either so older central deployments without the
            # superset_access column keep working — AUTH_ROLES_MAPPING has
            # a fallback for "user".
            tier = data.get("superset_access") or data.get("role") or "viewer"
            return {
                "username": data.get("username") or data.get("preferred_username") or "",
                "email": data.get("email") or "",
                "first_name": first or data.get("username") or "",
                "last_name": last,
                # AUTH_ROLES_MAPPING matches on these keys.
                "role_keys": [tier],
            }

        def auth_user_oauth(self, userinfo):
            """FAB's hook after OAuth login — user row is created/updated
            here. We extend it to also persist the MonCTL tenant scope."""
            user = super().auth_user_oauth(userinfo)
            if user is not None:
                _sync_monctl_tenant_scope(self, user)
            return user

    CUSTOM_SECURITY_MANAGER = MonctlSecurityManager

    def _sync_monctl_tenant_scope(sm, user):  # noqa: ARG001
        """Persist the MonCTL tenant scope (captured in `oauth_user_info`)
        into the current Flask session. The session is the browser-scoped
        source of truth for the user's tenant filter; it's refreshed on
        every OAuth login so role/tenant changes in MonCTL propagate the
        next time the user signs in.

        Why session and not a DB table:
          - FAB's User model has no JSON/extra column.
          - Superset's `UserAttribute` has a fixed schema (welcome_dashboard
            + avatar_url only).
          - Adding a new table would need migrations and duplicate the
            lifecycle of MonCTL's user_tenants association.
          - Session data is signed and tied to a single logged-in browser,
            which is exactly the lifetime we want."""
        from flask import g as _g, session

        session["monctl_all_tenants"] = bool(getattr(_g, "_monctl_all_tenants", False))
        session["monctl_tenant_ids"] = list(getattr(_g, "_monctl_tenant_ids", []) or [])
        session.permanent = True
        session.modified = True
        logger.info(
            "monctl tenant sync: user=%s all_tenants=%s tenant_ids=%s",
            getattr(user, "username", "?"),
            session["monctl_all_tenants"],
            session["monctl_tenant_ids"],
        )

else:
    logger.warning(
        "MonCTL OAuth not configured (MONCTL_OAUTH_CLIENT_ID/SECRET unset) — "
        "falling back to AUTH_DB (local admin login)."
    )

# ---------------------------------------------------------------------------
# Tenant RLS — Jinja helpers + query mutator
# ---------------------------------------------------------------------------

def _current_user_monctl_scope():
    """Return (all_tenants: bool, tenant_ids: list[str]) for the current user,
    read from the Flask session set by `_sync_monctl_tenant_scope` on login.

    Returns (True, []) when no user is logged in — so background jobs and
    internal Superset queries that run without a request context aren't
    accidentally blocked by the RLS clause."""
    try:
        from flask import has_request_context, session
        if not has_request_context():
            return True, []
        if "monctl_all_tenants" not in session:
            # Session predates the RLS rollout (or user logged in with the
            # legacy AUTH_DB path). Fail-closed only for non-admins: if the
            # session also has no admin marker we fall through to no-data.
            return False, []
        all_t = bool(session.get("monctl_all_tenants"))
        ids = list(session.get("monctl_tenant_ids") or [])
        return all_t, ids
    except Exception:
        return False, []


def monctl_tenant_clause(column: str = "tenant_id") -> str:
    """Jinja helper: returns a SQL fragment that scopes a query to the
    current user's tenants. Used in row-level-security filter clauses.

      all_tenants=True  → "1=1"        (no filter)
      all_tenants=False → "tenant_id IN ('uuid1','uuid2')"
      no tenants        → "1=0"        (fail-closed: see nothing)
    """
    all_t, ids = _current_user_monctl_scope()
    if all_t:
        return "1=1"
    if not ids:
        return "1=0"
    # Only UUID chars allowed — defence against any upstream tampering.
    safe = [x for x in ids if all(c in "0123456789abcdefABCDEF-" for c in x)]
    if not safe:
        return "1=0"
    literals = ",".join(f"'{x}'" for x in safe)
    return f"{column} IN ({literals})"


JINJA_CONTEXT_ADDONS = {
    "monctl_tenant_clause": monctl_tenant_clause,
}


# ---------------------------------------------------------------------------
# Layer 3 — append SETTINGS monctl_tenant_scope='...' to every CH query
# ---------------------------------------------------------------------------
#
# Defence-in-depth alongside the dataset-level RLS filter above. Even if
# the RLS filter isn't attached (e.g. dataset pre-dates the RLS rollout,
# SQL Lab bypass, manual mistake), every query gets a SETTINGS clause that
# the ClickHouse-server-side row policies on every tenant-scoped table
# evaluate. With this in place:
#
#   * admin / all_tenants user → setting='*' → policy passes through (1=1)
#   * scoped user             → setting='uuid1,uuid2' → policy filters
#   * user with no tenants    → setting='ffff…ffff'    → policy returns 0 rows
#   * unauthed / system code  → setting='*' (server profile default fires)
#
# This means a non-admin Superset user CANNOT see another tenant's data
# even if they somehow load a dataset without the RLS filter, even if
# they get into SQL Lab, even if their query bypasses Jinja templating.

_SETTINGS_CLAUSE_RE = None  # lazily compiled


def _strip_trailing(sql: str) -> str:
    """Trim trailing whitespace and a single optional ';' so we can append
    a SETTINGS clause cleanly. Comments after the final statement are left
    alone — they don't affect parsing."""
    s = sql.rstrip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s


def _strip_existing_monctl_setting(sql: str) -> str:
    """If a SETTINGS clause already names monctl_tenant_scope, drop just
    that key. We don't want callers from inside Superset to accidentally
    grant themselves wider access by hand-editing the SQL — the mutator's
    value (derived from the session) wins."""
    global _SETTINGS_CLAUSE_RE
    if _SETTINGS_CLAUSE_RE is None:
        import re
        _SETTINGS_CLAUSE_RE = re.compile(
            r",?\s*monctl_tenant_scope\s*=\s*'[^']*'", re.IGNORECASE
        )
    return _SETTINGS_CLAUSE_RE.sub("", sql)


def _monctl_scope_for_session() -> str:
    """Encode the current Flask session's MonCTL scope as the value to
    pass for monctl_tenant_scope:

      ''                  → admin (matches policy's IN ('','*') branch)
      'uuid1,uuid2,…'     → scoped to those tenant UUIDs
      'ffff…ffff'         → see-nothing sentinel (hans-style user with no
                            tenants → no data; conservative default for
                            sessions that lost their scope keys)
    """
    all_t, ids = _current_user_monctl_scope()
    if all_t:
        return ""
    if not ids:
        return "ffffffff-ffff-ffff-ffff-ffffffffffff"
    safe = [x for x in ids if all(c in "0123456789abcdefABCDEF-" for c in x)]
    if not safe:
        return "ffffffff-ffff-ffff-ffff-ffffffffffff"
    return ",".join(safe)


def SQL_QUERY_MUTATOR(  # noqa: N802 — Superset config protocol
    sql: str,
    user_name=None,  # noqa: ARG001
    security_manager=None,  # noqa: ARG001
    database=None,
) -> str:
    """Append ``SETTINGS monctl_tenant_scope='<scope>'`` to every query
    against the MonCTL ClickHouse database.

    Idempotent — strips any pre-existing monctl_tenant_scope key first so
    re-mutation (e.g. saved-query expansion) doesn't duplicate the value
    or let a hand-edited SETTINGS clause override the session-derived
    one.
    """
    try:
        if database is None or getattr(database, "database_name", "") != MONCTL_DATABASE_NAME:
            return sql
        scope = _monctl_scope_for_session()
        cleaned = _strip_existing_monctl_setting(sql)
        base = _strip_trailing(cleaned)
        # Match an existing SETTINGS clause to merge into; otherwise add one.
        import re
        m = re.search(r"\bSETTINGS\b", base, re.IGNORECASE)
        if m:
            insert_pos = m.end()
            return (
                base[:insert_pos]
                + f" monctl_tenant_scope = '{scope}',"
                + base[insert_pos:]
            )
        return f"{base}\nSETTINGS monctl_tenant_scope = '{scope}'"
    except Exception:
        # Fail-closed: if scope can't be computed for any reason, fall
        # back to the see-nothing sentinel so a misbehaving session can
        # never widen access.
        return (
            f"{_strip_trailing(_strip_existing_monctl_setting(sql))}"
            f"\nSETTINGS monctl_tenant_scope = 'ffffffff-ffff-ffff-ffff-ffffffffffff'"
        )


# Name of the RLS filter we auto-create + auto-attach. Keep stable — the
# after_insert listener looks it up by name.
MONCTL_RLS_FILTER_NAME = "monctl_tenant_scope"
MONCTL_DATABASE_NAME = "MonCTL ClickHouse"


def _install_monctl_rls(app):
    """Ensure a single `Base`-type RLS filter exists and gets attached to
    every dataset created on the MonCTL ClickHouse database.

    The filter clause uses the `monctl_tenant_clause()` Jinja helper defined
    above. For admins / `all_tenants=True` operators it expands to `1=1`; for
    tenant-scoped users it becomes `tenant_id IN ('<uuid>', …)` at query time.
    Base filter means it applies regardless of role, and the clause itself
    differentiates admin vs scoped — keeps all the tenant logic in one place.
    """
    from sqlalchemy import event

    def _find_or_create_filter(session):
        from superset.connectors.sqla.models import RowLevelSecurityFilter
        from superset.utils.core import RowLevelSecurityFilterType

        existing = (
            session.query(RowLevelSecurityFilter)
            .filter_by(name=MONCTL_RLS_FILTER_NAME)
            .one_or_none()
        )
        if existing is not None:
            return existing
        rls = RowLevelSecurityFilter(
            name=MONCTL_RLS_FILTER_NAME,
            description=(
                "Auto-generated: filters every MonCTL ClickHouse dataset by "
                "the current user's tenant_ids. Admins and all-tenant "
                "operators pass through (clause expands to 1=1)."
            ),
            filter_type=RowLevelSecurityFilterType.BASE.value,
            clause="{{ monctl_tenant_clause() }}",
        )
        session.add(rls)
        session.flush()
        return rls

    # Register the listener on the actual ORM class. No need for subclass
    # propagation — SqlaTable is a concrete model that's instantiated
    # directly when a user creates a dataset via the UI or API.
    from superset.connectors.sqla.models import SqlaTable
    from superset import db as _db

    @event.listens_for(SqlaTable, "after_insert")
    def _attach_rls(_mapper, connection, target):  # noqa: ARG001
        """Attach the MonCTL RLS filter to every new dataset that lives on
        the MonCTL ClickHouse database. Runs inside the same transaction so
        it's atomic with the dataset INSERT."""
        try:
            # `target.database` isn't eagerly loaded here; resolve via FK.
            from superset.models.core import Database as CoreDatabase

            db_row = connection.execute(
                CoreDatabase.__table__.select()
                .with_only_columns(CoreDatabase.database_name)
                .where(CoreDatabase.id == target.database_id)
            ).first()
            if db_row is None or db_row[0] != MONCTL_DATABASE_NAME:
                return

            # Look up / create the RLS filter, then insert the M2M row.
            from superset.connectors.sqla.models import (
                RLSFilterTables,
                RowLevelSecurityFilter,
            )

            rls_row = connection.execute(
                RowLevelSecurityFilter.__table__.select()
                .with_only_columns(RowLevelSecurityFilter.id)
                .where(RowLevelSecurityFilter.name == MONCTL_RLS_FILTER_NAME)
            ).first()
            if rls_row is None:
                # First-dataset edge case — filter hasn't been seeded yet.
                # Skip here; the init.sh startup seed will catch it on next
                # boot and the next dataset insert will attach.
                logger.warning(
                    "MonCTL RLS filter %r not found; skipping auto-attach "
                    "for dataset id=%s",
                    MONCTL_RLS_FILTER_NAME,
                    target.id,
                )
                return
            # Idempotent insert — ignore if row already exists.
            existing = connection.execute(
                RLSFilterTables.select()
                .where(RLSFilterTables.c.rls_filter_id == rls_row[0])
                .where(RLSFilterTables.c.table_id == target.id)
            ).first()
            if existing is None:
                connection.execute(
                    RLSFilterTables.insert().values(
                        rls_filter_id=rls_row[0], table_id=target.id
                    )
                )
                logger.info(
                    "MonCTL RLS filter auto-attached to new dataset id=%s name=%r",
                    target.id,
                    target.table_name,
                )
        except Exception:
            logger.exception(
                "MonCTL RLS auto-attach failed for dataset id=%s", target.id
            )

    # Seed the filter at startup (idempotent).
    with app.app_context():
        _find_or_create_filter(_db.session)
        _db.session.commit()

# Charting quality-of-life
ROW_LIMIT = 50000
SQLLAB_TIMEOUT = 60
SUPERSET_WEBSERVER_TIMEOUT = 120

FEATURE_FLAGS = {
    "DASHBOARD_CROSS_FILTERS": True,
    "ALERT_REPORTS": False,  # needs celery beat — off for initial deploy
    "ENABLE_TEMPLATE_PROCESSING": True,
    # Needed for the MonCTL Dashboards iframe embed — Superset sets
    # Content-Security-Policy: frame-ancestors 'self' by default, blocking
    # the parent page. EMBEDDED_SUPERSET adds the parent origin.
    "EMBEDDED_SUPERSET": True,
}

# Allow the MonCTL UI to embed Superset pages in an iframe under /superset/*.
# Same-origin via HAProxy, but CSP frame-ancestors still needs explicit config.
TALISMAN_CONFIG = {
    "content_security_policy": {
        "default-src": ["'self'"],
        "img-src": ["'self'", "data:", "blob:"],
        "worker-src": ["'self'", "blob:"],
        "connect-src": ["'self'"],
        "object-src": "'none'",
        "style-src": ["'self'", "'unsafe-inline'"],
        "script-src": ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
        "frame-ancestors": [
            "'self'",
            os.environ.get("SUPERSET_PUBLIC_ORIGIN", "https://10.145.210.40"),
        ],
    },
    "force_https": False,
    "session_cookie_secure": False,
}

WEBDRIVER_BASEURL = "http://superset:8088/"
