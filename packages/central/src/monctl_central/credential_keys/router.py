"""Credential key management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import CredentialKey

router = APIRouter()


class CreateCredentialKeyRequest(BaseModel):
    name: str = Field(description="Unique key name, e.g. 'username', 'password'")
    description: str | None = None
    is_secret: bool = Field(default=False, description="If true, values are treated as secrets")


class UpdateCredentialKeyRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_secret: bool | None = None


def _fmt(k: CredentialKey) -> dict:
    return {
        "id": str(k.id),
        "name": k.name,
        "description": k.description,
        "is_secret": k.is_secret,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


@router.get("")
async def list_credential_keys(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all credential keys."""
    rows = (await db.execute(select(CredentialKey).order_by(CredentialKey.name))).scalars().all()
    return {"status": "success", "data": [_fmt(k) for k in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_credential_key(
    request: CreateCredentialKeyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new credential key definition."""
    existing = (
        await db.execute(select(CredentialKey).where(CredentialKey.name == request.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Credential key '{request.name}' already exists",
        )
    key = CredentialKey(name=request.name, description=request.description, is_secret=request.is_secret)
    db.add(key)
    await db.flush()
    return {"status": "success", "data": _fmt(key)}


@router.put("/{key_id}")
async def update_credential_key(
    key_id: str,
    request: UpdateCredentialKeyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a credential key."""
    key = await db.get(CredentialKey, uuid.UUID(key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential key not found")
    if request.name is not None:
        key.name = request.name
    if request.description is not None:
        key.description = request.description
    if request.is_secret is not None:
        key.is_secret = request.is_secret
    return {"status": "success", "data": _fmt(key)}


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a credential key."""
    key = await db.get(CredentialKey, uuid.UUID(key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential key not found")
    await db.delete(key)
