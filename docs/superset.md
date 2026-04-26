# Superset BI integration

MonCTL ships an [Apache Superset](https://superset.apache.org/) deployment as the BI front-end for the ClickHouse data MonCTL collects. Superset is wired in via OAuth2 SSO against MonCTL central, served at `/bi/*` through HAProxy, and embedded in MonCTL's UI at `/analytics/superset`. Tenant scope and BI feature access are both controlled in MonCTL — operators don't manage Superset users directly.

This doc covers the architecture, the access-tier model, how tenant scope is enforced (with and without dataset-level RLS), and the day-2 operator runbook.

---

## Architecture at a glance

```
 Browser ─► HAProxy :443
              ├─ /bi/*           ─► Superset (mounted at /bi via DispatcherMiddleware)
              ├─ /v1/oauth/*     ─► central_nodes (OAuth2/OIDC provider)
              └─ /static/*       ─► /bi/static/* (webpack publicPath rewrite)

 Superset (server-to-server):
   ─► http://central1:8443/v1/oauth/{token,userinfo}

 Every Superset query against the MonCTL ClickHouse database:
   1. Dataset-level RLS adds:  WHERE tenant_id IN ('uuid1', …)
   2. SQL_QUERY_MUTATOR adds:  SETTINGS monctl_tenant_scope='uuid1,…'
                               (server-side row policies enforce again)
```

Two parallel enforcement layers — Superset's RLS clause AND a server-side ClickHouse row policy. Either layer alone would catch a tenant leak; both running together is defence-in-depth.

---

## Access tiers (`users.superset_access`)

Each MonCTL user has a `superset_access` field that maps directly to a Superset role. It's **orthogonal to MonCTL's `role`** field (`admin | user`) — that one gates MonCTL itself; this one gates Superset.

| Tier      | Superset role             | What the user can do                                                                                                                          |
| --------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `none`    | — (login denied at OAuth) | Cannot sign into Superset. Sidebar entry hidden in MonCTL; direct navigation to `/analytics/superset` shows a "no access" panel.              |
| `viewer`  | `MonCTLViewer`            | Read every dashboard / chart on MonCTL ClickHouse datasets. SQL Lab is hidden by design — raw SQL would bypass dataset RLS.                   |
| `analyst` | `MonCTLAnalyst`           | `viewer` + create/edit charts and dashboards + **SQL Lab access**. Tenant scope still applies because of the row-policy backstop (see below). |
| `admin`   | `Admin`                   | Full Superset admin — manage users, roles, datasets, alerts.                                                                                  |

### How tiers map server-side

- **`/v1/oauth/userinfo`** returns the effective tier (`auth/oauth.py:_effective_superset_access`). NULL is a legacy state — derived from `role` (admin → `admin`, otherwise → `viewer`). The migration backfilled all rows so NULL is rare in practice.
- **`/v1/oauth/authorize`** for `superset_access='none'` redirects to the Superset client with `?error=access_denied&error_description=user_not_allowed_for_client&state=…` per RFC 6749 §4.1.2.1. No code is ever issued for that user.
- **`AUTH_ROLES_MAPPING`** in `superset_config.py` keys on the tier value:
  ```python
  AUTH_ROLES_MAPPING = {
      "admin":   ["Admin"],
      "analyst": ["MonCTLAnalyst"],
      "viewer":  ["MonCTLViewer"],
      "user":    ["MonCTLViewer"],   # legacy alias for older central
  }
  ```
- **`AUTH_ROLES_SYNC_AT_LOGIN = True`** — tier changes propagate on next OAuth login. Sidebar visibility and the `/analytics/superset` page banner update on next `/v1/auth/me` (immediate after login).

### Tier vs tenant scope

The two are independent:

| Tier      | Tenant scope                   | Visible data                                                             |
| --------- | ------------------------------ | ------------------------------------------------------------------------ |
| `admin`   | `all_tenants=True`             | every row everywhere                                                     |
| `admin`   | restricted to tenants `[a, b]` | only rows for `a` and `b` (admin role still goes through the row policy) |
| `analyst` | restricted to tenant `c`       | only rows for `c`, even from SQL Lab                                     |
| `viewer`  | empty                          | nothing (fail-closed)                                                    |
| `none`    | any                            | cannot reach Superset at all                                             |

**Tenant scope is not relaxed by the tier.** A Superset Admin who only has tenant `c` assigned in MonCTL sees only `c`'s rows in dashboards. SQL Lab as Analyst gets the same treatment — raw SQL goes through ClickHouse's row policy, which reads `monctl_tenant_scope` from the per-query `SETTINGS` clause that the `SQL_QUERY_MUTATOR` injects.

---

## Tenant scope enforcement (the row-policy backstop)

Two layers fire on every Superset query against the MonCTL ClickHouse database:

### Layer A — Superset dataset RLS (Jinja-driven)

A `monctl_tenant_scope` Row Level Security filter is auto-attached to every dataset on the MonCTL ClickHouse database (`init.sh` back-fills existing datasets; an SQLAlchemy `after_insert` listener attaches it to new ones). The filter clause is:

```sql
{{ monctl_tenant_clause() }}
```

The Jinja helper expands to:

| Session state              | Clause                    |
| -------------------------- | ------------------------- |
| `monctl_all_tenants=True`  | `1=1`                     |
| `monctl_tenant_ids=[a, b]` | `tenant_id IN ('a', 'b')` |
| `monctl_tenant_ids=[]`     | `1=0` (fail-closed)       |

Session state comes from MonCTL's `/v1/oauth/userinfo` at OAuth login and is refreshed every 60s by a `before_request` hook in `superset_config.py`.

### Layer B — ClickHouse row policy (server-side)

Every tenant-scoped table (raw + `_hourly` + `_daily` + `_latest`) has a `monctl_tenant_scope` row policy:

```sql
USING (
  getSetting('monctl_tenant_scope') IN ('', '*')
  OR has(arrayMap(x -> toUUID(x),
                  splitByChar(',', getSetting('monctl_tenant_scope'))),
         tenant_id)
)
```

The SQL_QUERY_MUTATOR in `superset_config.py` appends `SETTINGS monctl_tenant_scope='<scope>'` to every query Superset sends, derived from the same Flask session. ClickHouse evaluates the policy and drops rows server-side — this fires even on raw SQL Lab queries that bypass dataset RLS.

Both layers stack, so a leak requires _both_ to fail.

### Other consumers

The same scope mechanism gates queries from MonCTL central itself (every CH query through `ClickHouseClient._PooledClient` auto-injects the setting from a `tenant_scope_var` ContextVar populated by `require_auth`). The profile default `'*'` in `clickhouse-monctl-tenant-scope.xml` keeps `clickhouse-client` one-shots and background jobs working as admin pass-through.

For the full Layer 3 design, see the `feat(security): tenant isolation` PR description.

---

## Operator runbook

### Granting / revoking access

Edit the user in MonCTL Settings → Users → Edit:

- **Superset access** dropdown: `none / viewer / analyst / admin`.
- **Tenants** stay separate — set them in the same dialog. Tier is the _what_, tenants are the _which rows_.

Or via API:

```bash
curl -X PUT https://<vip>/v1/users/<user_id> \
  -H 'content-type: application/json' \
  --cookie 'access_token=…' \
  -d '{"superset_access":"analyst"}'
```

Tier change takes effect on the user's **next OAuth login to Superset** (not their next page load). Tell them to sign out of Superset (`/bi/logout/`) and click into the Superset tab again, OR force a logout from MonCTL Settings → Users (deactivate + reactivate, or use the "reset password" button which bumps `token_version`).

Tenant changes propagate to active Superset sessions within 60s via the `before_request` userinfo refresh.

### Initial Superset deploy

For new customer clusters, Superset is deployed by `monctl_ctl deploy` on the host carrying the `superset` role — see [`INSTALL.md`](../INSTALL.md). The installer renders the compose bundle, generates the OAuth client credentials + admin password into `secrets.env`, and runs the `superset-init` one-shot.

For the dev cluster on `10.145.210.10`, the same compose lives at `/opt/superset/docker-compose.yml` and is brought up by hand:

```bash
cd /opt/superset
docker compose --env-file .env up -d
docker compose logs -f superset-init   # waits for Postgres, runs init.sh
```

`init.sh` is idempotent in both cases:

- Runs Superset DB migrations.
- Creates / resets the bootstrap admin from `.env`.
- Upserts the `MonCTL ClickHouse` database connection (URI uses `?readonly=2` so per-query settings can be applied — `readonly=1` would silently drop the `monctl_tenant_scope` setting and break every chart with `Cannot modify 'monctl_tenant_scope' setting in readonly mode`).
- Seeds the `MonCTLViewer` and `MonCTLAnalyst` roles.
  - `MonCTLViewer`: `Gamma + all_datasource_access − sql_*` permissions.
  - `MonCTLAnalyst`: `Alpha ∪ sql_lab + all_datasource_access`. Alpha alone doesn't include SQL Lab execute perms (`can_execute_sql_query` etc. live in the separate `sql_lab` role) — without merging, an Analyst would see the SQL Lab menu but no execute permission.
- Seeds the `monctl_tenant_scope` RLS filter and back-fills it onto every existing MonCTL ClickHouse dataset.

Re-run `docker compose run --rm superset-init` any time you change `init.sh` or want to back-fill RLS on a freshly created dataset.

### Where things live

| File                                                | What it does                                                                                 |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `docker/docker-compose.superset.yml`                | Compose definition (Superset, metadata Postgres, Redis)                                      |
| `docker/superset/superset_config.py`                | Flask app config: OAuth, RLS Jinja helper, SQL_QUERY_MUTATOR, role mapping, subpath mounting |
| `docker/superset/init.sh`                           | One-shot init / re-seed (admin, DB connection, roles, RLS filter)                            |
| `docker/superset/requirements-local.txt`            | Extra Python packages (`clickhouse-connect`, `psycopg2-binary`)                              |
| `docker/haproxy.cfg`                                | `/bi/*` routing + Location-header rewrite + `/static/*` rewrite                              |
| `packages/central/src/monctl_central/auth/oauth.py` | OAuth2 provider on central (`/v1/oauth/{authorize,token,userinfo}`)                          |

### Adding a new ClickHouse database to Superset

The auto-attach `after_insert` listener and the `init.sh` back-fill both check `database_name == "MonCTL ClickHouse"`. If you add a second ClickHouse connection (e.g. a secondary cluster), decide whether to apply the same RLS filter and either:

- Add the new database name to a set in `superset_config.py` and `init.sh`, or
- Create a separate filter + seeder for it.

For a non-MonCTL CH connection you don't want filtered, leave the filter off — the SQL_QUERY_MUTATOR also short-circuits when the database isn't named `MonCTL ClickHouse`.

---

## Troubleshooting

### `Cannot modify 'monctl_tenant_scope' setting in readonly mode` on every chart

The Superset CH connection URI has `?readonly=1`. Switch to `readonly=2` (still SELECT-only, but allows per-query settings):

```python
# Inside the superset container
from superset.app import create_app
app = create_app()
with app.app_context():
    from superset import db
    from superset.models.core import Database
    obj = db.session.query(Database).filter_by(database_name="MonCTL ClickHouse").one()
    obj.set_sqlalchemy_uri(obj.sqlalchemy_uri_decrypted.replace("readonly=1", "readonly=2"))
    db.session.commit()
```

Then `docker compose restart superset`. `init.sh` writes `readonly=2` from the start.

### `Unknown setting 'monctl_tenant_scope'`

The CH server-side `<custom_settings_prefixes>monctl_</...>` config isn't in place, OR the CH containers haven't been restarted since adding it. Both are required (a `SYSTEM RELOAD CONFIG` does _not_ pick this up — it's a server-startup setting). Roll-restart the ClickHouse containers and verify with:

```sql
SELECT getSetting('monctl_tenant_scope') SETTINGS monctl_tenant_scope='abc';
```

### `Couldn't restore Field from dump` at CH startup

The profile default in `clickhouse-monctl-tenant-scope.xml` must be the type-tagged form `<monctl_tenant_scope>'*'</monctl_tenant_scope>` (literal single quotes inside the XML value). Empty string and plain `*` both crash the deserializer in CH 24.3.

### A tier change didn't take effect

Tier maps at OAuth login time. Have the user sign out of `/bi/` and back in. If MonCTL admin needs to _immediately_ invalidate the user's Superset session, the cleanest way today is to deactivate the MonCTL user (which clears the iframe via the `before_request` cross-user-session-leak guard) and reactivate.

### Hans (or anyone) sees data from another tenant

In order of likelihood:

1. **Stale Superset session** — they logged in before the user-tenants edit. Wait 60s for the `before_request` refresh, or have them sign out.
2. **Dataset has no RLS filter** — pre-dates the rollout, `init.sh` back-fill hasn't run. Re-run `docker compose run --rm superset-init`.
3. **Layer 3 row policy not firing** — verify with `SHOW ROW POLICIES`. They're created by `_ensure_row_policies()` on central startup.
4. **`monctl_tenant_scope` not being set on the query** — check `system.query_log`:

```sql
SELECT user, Settings['monctl_tenant_scope'] AS scope, substring(query, 1, 200)
FROM system.query_log
WHERE event_time > now() - 60
  AND http_user_agent LIKE 'clickhouse-connect%'
ORDER BY event_time DESC LIMIT 10;
```

Every Superset-originated query should have a non-empty (and per-user-correct) `scope`.
