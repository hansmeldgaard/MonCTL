"""Label key registry endpoints."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import apply_tenant_filter, get_db, require_auth
from monctl_central.storage.models import Device, LabelKey

router = APIRouter()

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,62}[a-z0-9]$")


class CreateLabelKeyRequest(BaseModel):
    key: str = Field(description="Label key name (lowercase, a-z0-9, hyphens, underscores)")
    description: str | None = None
    color: str | None = Field(default=None, description="Hex color for UI badges, e.g. '#3B82F6'")
    show_description: bool = Field(default=False)
    predefined_values: list[str] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        v = v.strip().lower()
        if not _KEY_PATTERN.match(v):
            raise ValueError(
                "Key must be 2-64 chars, lowercase, start with letter, "
                "contain only a-z, 0-9, hyphens, underscores"
            )
        return v


class UpdateLabelKeyRequest(BaseModel):
    description: str | None = None
    color: str | None = None
    show_description: bool | None = None
    predefined_values: list[str] | None = None


def _fmt(k: LabelKey) -> dict:
    return {
        "id": str(k.id),
        "key": k.key,
        "description": k.description,
        "color": k.color,
        "show_description": k.show_description,
        "predefined_values": k.predefined_values or [],
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


@router.get("")
async def list_label_keys(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all registered label keys."""
    rows = (await db.execute(select(LabelKey).order_by(LabelKey.key))).scalars().all()
    return {"status": "success", "data": [_fmt(k) for k in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_label_key(
    request: CreateLabelKeyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new label key."""
    existing = (
        await db.execute(select(LabelKey).where(LabelKey.key == request.key))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Label key '{request.key}' already exists",
        )

    lk = LabelKey(
        key=request.key,
        description=request.description,
        color=request.color,
        show_description=request.show_description,
        predefined_values=request.predefined_values or [],
    )
    db.add(lk)
    await db.flush()
    return {"status": "success", "data": _fmt(lk)}


@router.put("/{key_id}")
async def update_label_key(
    key_id: str,
    request: UpdateLabelKeyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a label key."""
    lk = (
        await db.execute(select(LabelKey).where(LabelKey.id == uuid.UUID(key_id)))
    ).scalar_one_or_none()
    if not lk:
        raise HTTPException(status_code=404, detail="Label key not found")

    if request.description is not None:
        lk.description = request.description
    if request.color is not None:
        lk.color = request.color
    if request.show_description is not None:
        lk.show_description = request.show_description
    if request.predefined_values is not None:
        lk.predefined_values = request.predefined_values

    await db.flush()
    return {"status": "success", "data": _fmt(lk)}


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a label key from the registry."""
    lk = (
        await db.execute(select(LabelKey).where(LabelKey.id == uuid.UUID(key_id)))
    ).scalar_one_or_none()
    if not lk:
        raise HTTPException(status_code=404, detail="Label key not found")
    await db.delete(lk)


@router.get("/values/{key_name}")
async def list_label_values(
    key_name: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get all unique values used for a given label key across all devices."""
    # Get predefined values from registry
    lk = (
        await db.execute(select(LabelKey).where(LabelKey.key == key_name))
    ).scalar_one_or_none()
    predefined = set(lk.predefined_values) if lk and lk.predefined_values else set()

    # Get actually-used values from devices
    stmt = select(
        func.distinct(Device.labels[key_name].as_string())
    ).where(
        Device.labels[key_name].isnot(None)
    )
    stmt = apply_tenant_filter(stmt, auth, Device.tenant_id)
    rows = (await db.execute(stmt)).scalars().all()
    used = {v for v in rows if v}

    all_values = sorted(predefined | used)
    return {
        "status": "success",
        "data": all_values,
        "meta": {"predefined_count": len(predefined), "used_count": len(used)},
    }
