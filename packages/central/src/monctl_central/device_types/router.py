"""Device type catalogue endpoints — define what types of devices exist."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import DeviceType

router = APIRouter()


class CreateDeviceTypeRequest(BaseModel):
    name: str = Field(description="Unique type name, e.g. 'host', 'network', 'api'")
    description: str | None = Field(default=None, description="Optional description")


class UpdateDeviceTypeRequest(BaseModel):
    name: str | None = None
    description: str | None = None


def _fmt(dt: DeviceType) -> dict:
    return {
        "id": str(dt.id),
        "name": dt.name,
        "description": dt.description,
        "created_at": dt.created_at.isoformat() if dt.created_at else None,
    }


@router.get("")
async def list_device_types(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all defined device types."""
    rows = (await db.execute(select(DeviceType).order_by(DeviceType.name))).scalars().all()
    return {"status": "success", "data": [_fmt(dt) for dt in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_device_type(
    request: CreateDeviceTypeRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new device type."""
    # Check for duplicate name
    existing = (
        await db.execute(select(DeviceType).where(DeviceType.name == request.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Device type '{request.name}' already exists",
        )
    dt = DeviceType(name=request.name, description=request.description)
    db.add(dt)
    await db.flush()
    return {"status": "success", "data": _fmt(dt)}


@router.put("/{type_id}")
async def update_device_type(
    type_id: str,
    request: UpdateDeviceTypeRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a device type name or description."""
    dt = await db.get(DeviceType, uuid.UUID(type_id))
    if dt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device type not found")
    if request.name is not None:
        dt.name = request.name
    if request.description is not None:
        dt.description = request.description
    return {"status": "success", "data": _fmt(dt)}


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_type(
    type_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a device type."""
    dt = await db.get(DeviceType, uuid.UUID(type_id))
    if dt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device type not found")
    await db.delete(dt)
