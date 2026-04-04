"""Authentication endpoints for web UI login."""

from __future__ import annotations

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

router = APIRouter()

_ACCESS_MAX_AGE = settings.jwt_access_token_expire_minutes * 60
_REFRESH_MAX_AGE = settings.jwt_refresh_token_expire_days * 86400


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=128)


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
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with username + password. Sets HTTP-only cookies."""
    stmt = select(User).where(User.username == request.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        await record_login_event(
            db,
            event_type="login_failed",
            username=request.username,
            failure_reason="user_not_found",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not verify_password(request.password, user.password_hash):
        await record_login_event(
            db,
            event_type="login_failed",
            username=request.username,
            user_id=user.id,
            failure_reason="invalid_password",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not user.is_active:
        await record_login_event(
            db,
            event_type="login_failed",
            username=request.username,
            user_id=user.id,
            failure_reason="user_inactive",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    await record_login_event(
        db,
        event_type="login_success",
        username=user.username,
        user_id=user.id,
    )

    access = create_access_token(str(user.id), user.username, user.role)
    refresh = create_refresh_token(str(user.id))

    response.set_cookie(
        "access_token", access,
        httponly=True, samesite="lax", secure=False,
        max_age=_ACCESS_MAX_AGE, path="/",
    )
    response.set_cookie(
        "refresh_token", refresh,
        httponly=True, samesite="lax", secure=False,
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
        },
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Clear authentication cookies."""
    # Best-effort: identify the user from the existing access_token cookie
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
    """Use the refresh token cookie to issue a new access token."""
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

    await record_login_event(
        db,
        event_type="token_refresh",
        username=user.username,
        user_id=user.id,
    )

    access = create_access_token(str(user.id), user.username, user.role)
    response.set_cookie(
        "access_token", access,
        httponly=True, samesite="lax", secure=False,
        max_age=_ACCESS_MAX_AGE, path="/",
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
    all_tenants = getattr(user, "all_tenants", False) if user else False

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
        },
    }
