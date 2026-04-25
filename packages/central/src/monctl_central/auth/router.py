"""Authentication endpoints for web UI login."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.audit.login_events import record_login_event
from monctl_central.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from monctl_central.config import settings
from monctl_central.dependencies import get_db
from monctl_central.storage.models import SystemSetting, User

logger = logging.getLogger(__name__)

router = APIRouter()

_ACCESS_MAX_AGE = settings.jwt_access_token_expire_minutes * 60
_REFRESH_MAX_AGE = settings.jwt_refresh_token_expire_days * 86400

# Login rate-limit tuning. A live attacker is obvious at this cadence — real
# users virtually never hit 10 failures in 10 minutes, so the blast radius on
# legitimate traffic is minimal. Shared across central nodes via Redis so an
# attacker can't spread the storm around HAProxy.
_LOGIN_FAIL_WINDOW = 600        # 10 minutes
_LOGIN_FAIL_THRESHOLD = 10      # failures before lockout
_LOGIN_LOCK_DURATION = 900      # 15 minute lockout
_LOGIN_RL_KEY = "login_rl"      # redis key prefix
_LOGIN_LOCK_KEY = "login_lock"  # redis key prefix


def _rl_client_ip(request: Request) -> str:
    """Trust X-Forwarded-For's first hop when HAProxy fronts central."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _check_login_locked(ip: str, username: str) -> None:
    """Raise 429 if (ip, username) is currently locked out. No-op if Redis is down."""
    from monctl_central.cache import _redis

    if _redis is None:
        return
    try:
        locked = await _redis.get(f"{_LOGIN_LOCK_KEY}:{ip}:{username}")
    except Exception:
        logger.warning("login_rl_redis_unavailable", exc_info=True)
        return
    if locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again in 15 minutes.",
            headers={"Retry-After": str(_LOGIN_LOCK_DURATION)},
        )


async def _record_login_failure(
    ip: str, username: str, db: AsyncSession, user_id: uuid.UUID | None
) -> None:
    """Count failure; on threshold, set a lockout key and emit an audit event."""
    from monctl_central.cache import _redis

    if _redis is None:
        return
    try:
        key = f"{_LOGIN_RL_KEY}:{ip}:{username}"
        count = await _redis.incr(key)
        if count == 1:
            await _redis.expire(key, _LOGIN_FAIL_WINDOW)
        if count >= _LOGIN_FAIL_THRESHOLD:
            await _redis.setex(
                f"{_LOGIN_LOCK_KEY}:{ip}:{username}", _LOGIN_LOCK_DURATION, "1"
            )
            # Separate audit event so operators can distinguish lockouts from
            # normal password-miss noise.
            await record_login_event(
                db,
                event_type="login_locked",
                username=username,
                user_id=user_id,
                failure_reason=f"threshold_{_LOGIN_FAIL_THRESHOLD}_in_{_LOGIN_FAIL_WINDOW}s",
            )
    except Exception:
        logger.warning("login_rl_record_failed", exc_info=True)


async def _clear_login_counters(ip: str, username: str) -> None:
    from monctl_central.cache import _redis

    if _redis is None:
        return
    try:
        await _redis.delete(
            f"{_LOGIN_RL_KEY}:{ip}:{username}",
            f"{_LOGIN_LOCK_KEY}:{ip}:{username}",
        )
    except Exception:
        pass


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=128)


# Refresh-token replay detection. Every refresh token has a `jti` claim; the
# first time `/refresh` accepts it we record the jti in Redis with TTL equal
# to the refresh lifetime. A second attempt with the same jti indicates the
# token was stolen and replayed after the legitimate holder rotated it — we
# bump the user's `token_version` which invalidates the whole family.
_REFRESH_USED_KEY = "refresh_used"


async def _mark_refresh_jti_used(jti: str) -> bool:
    """Atomically mark a jti as used. Returns True on first use, False on replay.

    If Redis is down we fail open (return True) so refresh keeps working on
    infrastructure outages — refresh rotation is defence-in-depth, not a
    primary control. The primary control is `token_version`.
    """
    from monctl_central.cache import _redis

    if _redis is None:
        return True
    try:
        # NX ensures only the first setter succeeds — subsequent callers
        # get `None` back, which is the replay signal.
        ok = await _redis.set(
            f"{_REFRESH_USED_KEY}:{jti}",
            "1",
            nx=True,
            ex=_REFRESH_MAX_AGE,
        )
        return bool(ok)
    except Exception:
        logger.warning("refresh_jti_redis_unavailable", exc_info=True)
        return True


async def _revoke_all_user_tokens(db: AsyncSession, user: User) -> None:
    """Bump `token_version` — invalidates every access + refresh JWT for this user.

    Uses its OWN session+commit rather than the request-scoped `db`. The
    replay-detection path that calls us immediately raises HTTPException(401),
    which triggers `get_db`'s rollback — so a `db.flush()` here would be
    thrown away, same shape of bug as the login-audit gotcha. Committing
    on a separate session guarantees the bump survives the 401.
    """
    _ = db  # kept for API stability / documentation
    from monctl_central.dependencies import get_session_factory
    from sqlalchemy import update
    from monctl_common.utils import utc_now

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                token_version=(user.token_version or 0) + 1,
                updated_at=utc_now(),
            )
        )
        await session.commit()
    user.token_version = (user.token_version or 0) + 1


async def _get_effective_idle_timeout(user: User, db: AsyncSession) -> int:
    """Return the effective idle timeout in minutes for this user.

    Priority: user.idle_timeout_minutes > system setting > 60 (hardcoded fallback).
    """
    if user.idle_timeout_minutes is not None:
        return user.idle_timeout_minutes

    setting = await db.get(SystemSetting, "session_idle_timeout_minutes")
    if setting and setting.value:
        try:
            return int(setting.value)
        except ValueError:
            pass
    return 60


@router.post("/login")
async def login(
    login_req: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with username + password. Sets HTTP-only cookies."""
    ip = _rl_client_ip(request)
    await _check_login_locked(ip, login_req.username)

    stmt = select(User).where(User.username == login_req.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        await _record_login_failure(ip, login_req.username, db, None)
        await record_login_event(
            db,
            event_type="login_failed",
            username=login_req.username,
            failure_reason="user_not_found",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not verify_password(login_req.password, user.password_hash):
        await _record_login_failure(ip, login_req.username, db, user.id)
        await record_login_event(
            db,
            event_type="login_failed",
            username=login_req.username,
            user_id=user.id,
            failure_reason="invalid_password",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not user.is_active:
        await _record_login_failure(ip, login_req.username, db, user.id)
        await record_login_event(
            db,
            event_type="login_failed",
            username=login_req.username,
            user_id=user.id,
            failure_reason="user_inactive",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    # Successful login — clear any accumulated failure count for this pair.
    await _clear_login_counters(ip, login_req.username)

    await record_login_event(
        db,
        event_type="login_success",
        username=user.username,
        user_id=user.id,
    )

    tv = user.token_version or 0
    access = create_access_token(str(user.id), user.username, user.role, tv)
    refresh = create_refresh_token(str(user.id), tv)

    response.set_cookie(
        "access_token", access,
        httponly=True, samesite="strict", secure=settings.cookie_secure,
        max_age=_ACCESS_MAX_AGE, path="/",
    )
    response.set_cookie(
        "refresh_token", refresh,
        httponly=True, samesite="strict", secure=settings.cookie_secure,
        max_age=_REFRESH_MAX_AGE, path="/v1/auth",
    )

    idle_timeout = await _get_effective_idle_timeout(user, db)

    return {
        "status": "success",
        "data": {
            "user_id": str(user.id),
            "username": user.username,
            "role": user.role,
            "display_name": user.display_name,
            "timezone": user.timezone,
            "table_page_size": user.table_page_size,
            "table_scroll_mode": user.table_scroll_mode,
            "idle_timeout_minutes": idle_timeout,
            "iface_status_filter": user.iface_status_filter,
            "iface_traffic_unit": user.iface_traffic_unit,
            "iface_chart_metric": user.iface_chart_metric,
            "iface_time_range": user.iface_time_range,
            "default_page": user.default_page,
            "ui_preferences": user.ui_preferences or {},
        },
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Clear authentication cookies and revoke all tokens for this user.

    Bumping `token_version` immediately invalidates every outstanding
    access + refresh JWT for the user — a leaked token no longer has the
    15 min / 7 day natural validity window it used to (F-CEN-006).
    """
    username = ""
    user_id: uuid.UUID | None = None
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = decode_token(token)
            username = payload.get("username", "") or ""
            sub = payload.get("sub")
            if sub:
                user_id = uuid.UUID(sub)
        except Exception:
            pass

    if user_id is not None:
        user = await db.get(User, user_id)
        if user is not None:
            await _revoke_all_user_tokens(db, user)

    await record_login_event(
        db,
        event_type="logout",
        username=username,
        user_id=user_id,
    )

    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/v1/auth")
    return {"status": "success"}


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Rotate refresh token + issue new access token. Detects replay.

    Behaviour (F-CEN-005):
      - First use of a refresh-token jti → issue new pair, mark jti used.
      - Second use of the same jti → replay, revoke all user tokens.
      - Token version lower than the user's current value → revoked, reject.
    """
    token = request.cookies.get("refresh_token")
    if not token:
        await record_login_event(
            db,
            event_type="token_refresh_failed",
            username="",
            failure_reason="no_refresh_token",
        )
        raise HTTPException(status_code=401, detail="No refresh token")

    try:
        payload = decode_token(token)
    except Exception:
        await record_login_event(
            db,
            event_type="token_refresh_failed",
            username="",
            failure_reason="invalid_refresh_token",
        )
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        await record_login_event(
            db,
            event_type="token_refresh_failed",
            username="",
            failure_reason="invalid_token_type",
        )
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload["sub"]
    stmt = select(User).where(User.id == uuid.UUID(user_id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        await record_login_event(
            db,
            event_type="token_refresh_failed",
            username="",
            user_id=uuid.UUID(user_id) if user_id else None,
            failure_reason="user_not_found_or_inactive",
        )
        raise HTTPException(status_code=401, detail="User not found or disabled")

    # Token-version gate: a stale refresh token that predates a logout /
    # role change is outright rejected, no rotation attempt.
    if payload.get("tv", 0) != (user.token_version or 0):
        await record_login_event(
            db,
            event_type="token_refresh_failed",
            username=user.username,
            user_id=user.id,
            failure_reason="token_version_mismatch",
        )
        raise HTTPException(status_code=401, detail="Token revoked")

    # Replay detection: atomically mark the jti as used. If it was already
    # marked, someone replayed the previous rotation's now-invalidated
    # token — treat as a compromise signal and revoke the whole family.
    jti = payload.get("jti")
    if jti:
        fresh = await _mark_refresh_jti_used(jti)
        if not fresh:
            await _revoke_all_user_tokens(db, user)
            await record_login_event(
                db,
                event_type="token_refresh_failed",
                username=user.username,
                user_id=user.id,
                failure_reason="refresh_token_replay",
            )
            logger.warning(
                "refresh_token_replay_detected user_id=%s jti=%s", user.id, jti
            )
            raise HTTPException(status_code=401, detail="Token revoked")

    await record_login_event(
        db,
        event_type="token_refresh",
        username=user.username,
        user_id=user.id,
    )

    tv = user.token_version or 0
    access = create_access_token(str(user.id), user.username, user.role, tv)
    new_refresh = create_refresh_token(str(user.id), tv)
    response.set_cookie(
        "access_token", access,
        httponly=True, samesite="strict", secure=settings.cookie_secure,
        max_age=_ACCESS_MAX_AGE, path="/",
    )
    response.set_cookie(
        "refresh_token", new_refresh,
        httponly=True, samesite="strict", secure=settings.cookie_secure,
        max_age=_REFRESH_MAX_AGE, path="/v1/auth",
    )

    idle_timeout = await _get_effective_idle_timeout(user, db)

    return {
        "status": "success",
        "data": {
            "user_id": str(user.id),
            "username": user.username,
            "role": user.role,
            "display_name": user.display_name,
            "timezone": user.timezone,
            "idle_timeout_minutes": idle_timeout,
            "iface_status_filter": user.iface_status_filter,
            "iface_traffic_unit": user.iface_traffic_unit,
            "iface_chart_metric": user.iface_chart_metric,
            "iface_time_range": user.iface_time_range,
            "default_page": user.default_page,
            "ui_preferences": user.ui_preferences or {},
        },
    }


@router.get("/me")
async def get_me(request: Request, db: AsyncSession = Depends(get_db)):
    """Return the currently authenticated user from the JWT cookie."""
    from sqlalchemy import select as sa_select
    from monctl_central.storage.models import UserTenant

    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload["sub"]
    role = payload["role"]

    # Load tenant info for the current user
    from sqlalchemy.orm import selectinload
    user = (await db.execute(
        sa_select(User).options(selectinload(User.assigned_role)).where(User.id == uuid.UUID(user_id))
    )).scalar_one_or_none()

    # token_version gate — `/me` has its own JWT decode path (doesn't route
    # through `_get_user_from_cookie`), so the check has to live here too.
    # Without this, a logged-out / role-changed user's access token would
    # keep `/me` returning data until natural exp (F-CEN-006).
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")
    if payload.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="Token revoked")

    all_tenants = getattr(user, "all_tenants", False)

    if role == "admin" or all_tenants:
        tenant_ids = None  # unrestricted
    else:
        rows = (await db.execute(
            sa_select(UserTenant.tenant_id).where(
                UserTenant.user_id == uuid.UUID(user_id)
            )
        )).scalars().all()
        tenant_ids = [str(t) for t in rows]

    # Load permissions for non-admin users
    permissions_list = None
    if role != "admin" and user and user.role_id:
        from monctl_central.dependencies import _load_user_permissions
        perms = await _load_user_permissions(db, user_id)
        permissions_list = list(perms)

    idle_timeout = await _get_effective_idle_timeout(user, db) if user else 60

    # Effective Superset BI tier — same derivation rule as the OAuth
    # userinfo helper so the frontend can hide the Superset sidebar entry
    # and render a friendly denial state without depending on a separate
    # call.
    from monctl_central.auth.oauth import _effective_superset_access
    superset_access = _effective_superset_access(user) if user else "viewer"

    return {
        "status": "success",
        "data": {
            "user_id": user_id,
            "username": payload["username"],
            "role": role,
            "role_id": str(user.role_id) if user and user.role_id else None,
            "role_name": user.assigned_role.name if user and user.assigned_role else None,
            "timezone": user.timezone if user else "UTC",
            "table_page_size": user.table_page_size if user else 50,
            "table_scroll_mode": user.table_scroll_mode if user else "paginated",
            "all_tenants": all_tenants,
            "tenant_ids": tenant_ids,
            "permissions": permissions_list,
            "idle_timeout_minutes": idle_timeout,
            "iface_status_filter": user.iface_status_filter if user else "all",
            "iface_traffic_unit": user.iface_traffic_unit if user else "auto",
            "iface_chart_metric": user.iface_chart_metric if user else "traffic",
            "iface_time_range": user.iface_time_range if user else "24h",
            "default_page": user.default_page if user else "/",
            "superset_access": superset_access,
            "ui_preferences": (user.ui_preferences if user else {}) or {},
        },
    }
