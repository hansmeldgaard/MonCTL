"""OAuth2 / OIDC provider endpoints for third-party SSO (Superset, etc.).

Flow: authorization_code grant.

  1. Browser hits GET /v1/oauth/authorize?response_type=code&client_id=...
     &redirect_uri=...&state=...&scope=openid+profile+email
     - If user is not logged into MonCTL, redirect to /login?next=<this-url>.
     - Otherwise issue a single-use code, 302 back to redirect_uri with ?code=&state=.

  2. Client (server-side) POSTs to /v1/oauth/token with
     grant_type=authorization_code, code=..., redirect_uri=..., and HTTP Basic
     auth (client_id:client_secret). We return an access_token (MonCTL JWT),
     an id_token (OIDC claims), and a refresh_token.

  3. Client fetches GET /v1/oauth/userinfo with Bearer access_token.
     Returns {sub, username, email, name, role}.

Design choices:
  - Codes are stored in Redis with 60s TTL, deleted on first use (single-use).
  - Access tokens are regular MonCTL JWTs — require_auth accepts them via Bearer.
  - ID tokens are signed with the same HS256 key (symmetric). Clients that need
    to verify the ID token must share the secret, which is fine for a closed
    ecosystem. If we add external clients later, move to RS256 + JWKS.
  - Single client config via env (oauth_client_id / _secret / _redirect_uris).
    Move to a DB table when a second client shows up.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import secrets as _secrets
from datetime import timedelta
from urllib.parse import quote, urlencode

import jwt
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from monctl_central.config import settings
from monctl_central.dependencies import get_db
from monctl_central.storage.models import User
from monctl_common.utils import utc_now

logger = logging.getLogger(__name__)

router = APIRouter()

_CODE_TTL_SECONDS = 60
_CODE_KEY_PREFIX = "oauth_code"


def _allowed_redirect_uris() -> list[str]:
    raw = settings.oauth_redirect_uris or ""
    return [u.strip() for u in raw.split(",") if u.strip()]


def _client_configured() -> bool:
    return bool(
        settings.oauth_client_id
        and settings.oauth_client_secret
        and _allowed_redirect_uris()
    )


def _validate_client(client_id: str) -> None:
    if not _client_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth2 provider is not configured",
        )
    if client_id != settings.oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_client",
        )


def _validate_redirect_uri(redirect_uri: str) -> None:
    # Exact-match only — no wildcard, no scheme coercion. This is the main
    # defence against redirect-based token theft.
    if redirect_uri not in _allowed_redirect_uris():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid redirect_uri",
        )


async def _store_code(code: str, payload: dict) -> None:
    from monctl_central.cache import _redis

    if _redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis unavailable — OAuth codes cannot be issued",
        )
    await _redis.setex(
        f"{_CODE_KEY_PREFIX}:{code}", _CODE_TTL_SECONDS, json.dumps(payload)
    )


async def _consume_code(code: str) -> dict | None:
    """Atomically fetch+delete a code. Returns None if not found."""
    from monctl_central.cache import _redis

    if _redis is None:
        return None
    key = f"{_CODE_KEY_PREFIX}:{code}"
    # Atomic GETDEL (Redis 6.2+). If GETDEL isn't available, the pipeline
    # below would be the fallback; all our Redis deployments are ≥7.
    try:
        raw = await _redis.execute_command("GETDEL", key)
    except Exception:
        # Fall back to non-atomic for very old Redis — worst case a racing
        # duplicate redemption also succeeds, which is still bounded to
        # the 60s TTL and each code being single-client-id.
        raw = await _redis.get(key)
        if raw is not None:
            await _redis.delete(key)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        return json.loads(raw)
    except Exception:
        return None


def _effective_superset_access(user: User) -> str:
    """Resolve the effective Superset BI tier for a user.

    Stored values: 'none' | 'viewer' | 'analyst' | 'admin'.
    NULL is legacy → derived from `role` (admin → 'admin', else → 'viewer').
    The migration backfills existing rows so NULL is rare in practice, but
    the fallback keeps userinfo well-defined for any new code path that
    forgets to set the column.
    """
    val = (user.superset_access or "").strip().lower()
    if val in {"none", "viewer", "analyst", "admin"}:
        return val
    return "admin" if user.role == "admin" else "viewer"


def _parse_basic_auth(request: Request) -> tuple[str, str] | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:]).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    cid, csec = decoded.split(":", 1)
    return cid, csec


def _create_id_token(user: User, client_id: str, nonce: str | None) -> str:
    now = utc_now()
    payload = {
        "iss": settings.oauth_issuer,
        "sub": str(user.id),
        "aud": client_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        # Profile claims — Superset's get_oauth_user_info reads these.
        "preferred_username": user.username,
        "name": user.display_name or user.username,
        "email": user.email or "",
        "role": user.role,
    }
    if nonce:
        payload["nonce"] = nonce
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


# ---------------------------------------------------------------------------
# /authorize
# ---------------------------------------------------------------------------

@router.get("/oauth/authorize")
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str | None = None,
    scope: str | None = None,
    nonce: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """OAuth2 authorization endpoint.

    Behaviour:
      - User not logged into MonCTL → 302 to /login?next=<current-url>.
      - response_type must be 'code'. Anything else → 400.
      - Issue a 60s single-use code, 302 back to redirect_uri.
    """
    _validate_client(client_id)
    _validate_redirect_uri(redirect_uri)

    if response_type != "code":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported_response_type",
        )

    # Reuse the existing cookie-JWT path — we don't pull in require_auth because
    # we want to redirect to /login instead of returning 401 for unauthenticated
    # users.
    from monctl_central.dependencies import _get_user_from_cookie

    user_dict = await _get_user_from_cookie(request, db)
    if not user_dict:
        # Preserve path+query as a relative URL — LoginPage rejects next=
        # values that don't start with '/' (open-redirect protection).
        q = request.url.query
        next_url = f"{request.url.path}?{q}" if q else request.url.path
        return RedirectResponse(f"/login?next={quote(next_url, safe='')}", status_code=302)

    user = await db.get(User, user_dict["user_id"])
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_inactive",
        )

    # Per-user gate: superset_access='none' denies the OAuth flow without
    # ever issuing a code. Legacy rows (NULL) derive from `role` so the
    # behaviour stays consistent with /v1/oauth/userinfo.
    eff_access = _effective_superset_access(user)
    if eff_access == "none":
        # RFC 6749 §4.1.2.1 — redirect with error params, never expose 4xx
        # to the browser (would leak the redirect_uri to a generic error
        # page).
        err = {
            "error": "access_denied",
            "error_description": "user_not_allowed_for_client",
        }
        if state:
            err["state"] = state
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(
            f"{redirect_uri}{sep}{urlencode(err)}", status_code=302
        )

    code = _secrets.token_urlsafe(32)
    await _store_code(
        code,
        {
            "user_id": str(user.id),
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope or "",
            "nonce": nonce,
        },
    )

    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)


# ---------------------------------------------------------------------------
# /token
# ---------------------------------------------------------------------------

@router.post("/oauth/token")
async def token(
    request: Request,
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    refresh_token: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """OAuth2 token endpoint. Supports authorization_code and refresh_token grants.

    Client authenticates via HTTP Basic (preferred) or form params.
    """
    # Client auth — Basic takes precedence (RFC 6749 §2.3.1 recommends it).
    basic = _parse_basic_auth(request)
    if basic:
        client_id, client_secret = basic

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_client",
            headers={"WWW-Authenticate": "Basic"},
        )

    _validate_client(client_id)
    if not _secrets.compare_digest(client_secret, settings.oauth_client_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_client",
        )

    if grant_type == "authorization_code":
        if not code or not redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_request",
            )
        data = await _consume_code(code)
        if data is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_grant",
            )
        if data.get("client_id") != client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_grant",
            )
        if data.get("redirect_uri") != redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_grant",
            )

        user = await db.get(User, data["user_id"])
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="user_inactive",
            )

        tv = user.token_version or 0
        access = create_access_token(str(user.id), user.username, user.role, tv)
        refresh = create_refresh_token(str(user.id), tv)
        id_tok = _create_id_token(user, client_id, data.get("nonce"))

        return JSONResponse(
            {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": settings.jwt_access_token_expire_minutes * 60,
                "refresh_token": refresh,
                "id_token": id_tok,
                "scope": data.get("scope") or "",
            }
        )

    if grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_request",
            )
        try:
            payload = decode_token(refresh_token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_grant",
            )
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_grant",
            )
        user = await db.get(User, payload["sub"])
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="user_inactive",
            )
        if (user.token_version or 0) != payload.get("tv", 0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_grant",
            )
        tv = user.token_version or 0
        access = create_access_token(str(user.id), user.username, user.role, tv)
        id_tok = _create_id_token(user, client_id, None)
        # Note: we do NOT rotate the refresh token here — the regular
        # /v1/auth/refresh path is where rotation lives. For OAuth clients
        # this is acceptable and matches many provider implementations.
        return JSONResponse(
            {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": settings.jwt_access_token_expire_minutes * 60,
                "id_token": id_tok,
                "scope": "",
            }
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="unsupported_grant_type",
    )


# ---------------------------------------------------------------------------
# /userinfo
# ---------------------------------------------------------------------------

@router.get("/oauth/userinfo")
async def userinfo(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """OIDC userinfo endpoint. Bearer access_token required."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tok = header.split(None, 1)[1]
    try:
        payload = decode_token(tok)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
        )
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
        )
    user = await db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user_inactive")
    if (user.token_version or 0) != payload.get("tv", 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token_revoked")

    # Tenant scope — consumed by Superset to drive RLS. An `admin` role OR
    # the explicit `all_tenants=True` bit both short-circuit to "see
    # everything"; otherwise we enumerate the per-user tenant assignments.
    # (Role and all_tenants are orthogonal fields in MonCTL but for BI
    # purposes we treat admin as implicitly unrestricted.)
    from monctl_central.storage.models import UserTenant

    is_all_tenants = bool(user.all_tenants) or user.role == "admin"
    tenant_ids: list[str] = []
    if not is_all_tenants:
        rows = (await db.execute(
            select(UserTenant.tenant_id).where(UserTenant.user_id == user.id)
        )).scalars().all()
        tenant_ids = [str(t) for t in rows]

    return {
        "sub": str(user.id),
        "preferred_username": user.username,
        "username": user.username,
        "name": user.display_name or user.username,
        "email": user.email or "",
        "role": user.role,
        "all_tenants": is_all_tenants,
        "tenant_ids": tenant_ids,
        # Drives the Superset role mapping in oauth_user_info() —
        # see docker/superset/superset_config.py.
        "superset_access": _effective_superset_access(user),
    }


# ---------------------------------------------------------------------------
# OIDC discovery (optional — Superset doesn't need it, but nice for future)
# ---------------------------------------------------------------------------

@router.get("/.well-known/openid-configuration", include_in_schema=False)
async def openid_configuration():
    """OIDC discovery document. Mounted under /v1 — clients that expect the
    standard root path should fetch /v1/.well-known/openid-configuration."""
    if not _client_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth2 provider is not configured",
        )
    issuer = settings.oauth_issuer.rstrip("/")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/v1/oauth/authorize",
        "token_endpoint": f"{issuer}/v1/oauth/token",
        "userinfo_endpoint": f"{issuer}/v1/oauth/userinfo",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": [settings.jwt_algorithm],
        "scopes_supported": ["openid", "profile", "email"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "claims_supported": [
            "sub", "iss", "aud", "exp", "iat", "nonce",
            "preferred_username", "name", "email", "role",
        ],
    }
