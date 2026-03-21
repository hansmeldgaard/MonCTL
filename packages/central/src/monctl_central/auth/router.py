"""Authentication endpoints for web UI login."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from monctl_central.config import settings
from monctl_central.dependencies import get_db
from monctl_central.storage.models import User

router = APIRouter()

_ACCESS_MAX_AGE = settings.jwt_access_token_expire_minutes * 60
_REFRESH_MAX_AGE = settings.jwt_refresh_token_expire_days * 86400


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=128)


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

    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
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
        },
    }


@router.post("/logout")
async def logout(response: Response):
    """Clear authentication cookies."""
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
        raise HTTPException(status_code=401, detail="No refresh token")

    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload["sub"]
    stmt = select(User).where(User.id == uuid.UUID(user_id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")

    access = create_access_token(str(user.id), user.username, user.role)
    response.set_cookie(
        "access_token", access,
        httponly=True, samesite="lax", secure=False,
        max_age=_ACCESS_MAX_AGE, path="/",
    )

    return {
        "status": "success",
        "data": {
            "user_id": str(user.id),
            "username": user.username,
            "role": user.role,
            "display_name": user.display_name,
            "timezone": user.timezone,
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
        },
    }
