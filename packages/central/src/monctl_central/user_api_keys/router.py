"""User API key management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth, require_permission
from monctl_central.storage.models import ApiKey
from monctl_common.utils import generate_api_key, hash_api_key, key_prefix_display
from monctl_common.constants import USER_KEY_PREFIX

router = APIRouter()


def _fmt(k: ApiKey) -> dict:
    return {
        "id": str(k.id),
        "name": k.name,
        "key_prefix": k.key_prefix,
        "scopes": k.scopes,
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
    }


class CreateUserApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None


def _require_cookie_user(auth: dict) -> str:
    """Ensure auth is from JWT cookie (not API key). Returns user_id."""
    if auth.get("auth_type") != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only available for logged-in users (not via API key)",
        )
    return auth["user_id"]


@router.get("")
async def list_my_api_keys(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("api_key", "view")),
):
    """List API keys for the current user."""
    user_id = _require_cookie_user(auth)
    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == uuid.UUID(user_id), ApiKey.key_type == "user")
        .order_by(ApiKey.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {"status": "success", "data": [_fmt(k) for k in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user_api_key(
    req: CreateUserApiKeyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("api_key", "create")),
):
    """Create a new API key for the current user.

    The raw key is returned ONCE in this response.
    The key inherits the user's RBAC role and tenant assignments.
    """
    user_id = _require_cookie_user(auth)

    count_stmt = select(ApiKey).where(
        ApiKey.user_id == uuid.UUID(user_id),
        ApiKey.key_type == "user",
    )
    existing = (await db.execute(count_stmt)).scalars().all()
    if len(existing) >= 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10 API keys per user",
        )

    raw_key = generate_api_key(USER_KEY_PREFIX)
    api_key = ApiKey(
        key_hash=hash_api_key(raw_key),
        key_prefix=key_prefix_display(raw_key),
        key_type="user",
        user_id=uuid.UUID(user_id),
        name=req.name,
        scopes=["*"],
        expires_at=req.expires_at,
    )
    db.add(api_key)
    await db.flush()

    return {
        "status": "success",
        "data": {
            **_fmt(api_key),
            "raw_key": raw_key,
        },
    }


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("api_key", "delete")),
):
    """Revoke/delete an API key. Only the owning user can delete their keys."""
    user_id = _require_cookie_user(auth)

    api_key = await db.get(ApiKey, uuid.UUID(key_id))
    if not api_key or api_key.user_id != uuid.UUID(user_id):
        raise HTTPException(status_code=404, detail="API key not found")

    from monctl_central.cache import delete_cached_api_key
    await delete_cached_api_key(api_key.key_hash)

    await db.delete(api_key)
