"""Device type CRUD endpoints — manage sysObjectID → DeviceCategory mappings."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import Device, DeviceCategory, DeviceType

router = APIRouter()


class CreateDeviceTypeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sys_object_id_pattern: str = Field(
        min_length=3, max_length=256,
        description="sysObjectID prefix, e.g. '1.3.6.1.4.1.9.1.2571'",
    )
    device_category_id: str = Field(description="UUID of the target device category")
    vendor: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=255)
    os_family: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    priority: int = Field(default=0, ge=0, le=1000)
    auto_assign_packs: list[str] | None = None

    @field_validator("sys_object_id_pattern")
    @classmethod
    def validate_oid_pattern(cls, v: str) -> str:
        v = v.strip()
        if v.startswith("."):
            v = v[1:]
        parts = v.split(".")
        if not all(p.isdigit() for p in parts):
            raise ValueError("sysObjectID pattern must contain only digits separated by dots")
        if len(parts) < 3:
            raise ValueError("sysObjectID pattern must have at least 3 components")
        return v


class UpdateDeviceTypeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sys_object_id_pattern: str | None = Field(default=None, min_length=3, max_length=256)
    device_category_id: str | None = None
    vendor: str | None = None
    model: str | None = None
    os_family: str | None = None
    description: str | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    auto_assign_packs: list[str] | None = None

    @field_validator("sys_object_id_pattern")
    @classmethod
    def validate_oid_pattern(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v.startswith("."):
            v = v[1:]
        parts = v.split(".")
        if not all(p.isdigit() for p in parts):
            raise ValueError("sysObjectID pattern must contain only digits separated by dots")
        return v


def _fmt(rule: DeviceType) -> dict:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "sys_object_id_pattern": rule.sys_object_id_pattern,
        "device_category_id": str(rule.device_category_id),
        "device_category_name": rule.device_category.name if rule.device_category else None,
        "vendor": rule.vendor,
        "model": rule.model,
        "os_family": rule.os_family,
        "description": rule.description,
        "priority": rule.priority,
        "auto_assign_packs": rule.auto_assign_packs or [],
        "pack_id": str(rule.pack_id) if rule.pack_id else None,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


@router.get("")
async def list_device_types(
    name: str | None = Query(default=None, description="Filter by name (ilike)"),
    search: str | None = Query(default=None, description="Search by name, vendor, OID pattern"),
    device_category_id: str | None = Query(default=None),
    vendor: str | None = Query(default=None),
    sort_by: str = Query(default="name", description="Column to sort by"),
    sort_dir: str = Query(default="asc", description="asc or desc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List device types with search, filtering, sorting, and pagination."""
    stmt = select(DeviceType).options(selectinload(DeviceType.device_category))

    if name:
        stmt = stmt.where(DeviceType.name.ilike(f"%{name}%"))
    if search:
        search_filter = f"%{search}%"
        stmt = stmt.where(
            sa.or_(
                DeviceType.name.ilike(search_filter),
                DeviceType.vendor.ilike(search_filter),
                DeviceType.sys_object_id_pattern.ilike(search_filter),
                DeviceType.model.ilike(search_filter),
            )
        )
    if device_category_id:
        stmt = stmt.where(DeviceType.device_category_id == uuid.UUID(device_category_id))
    if vendor:
        stmt = stmt.where(DeviceType.vendor.ilike(f"%{vendor}%"))

    # Count
    count_stmt = select(sa.func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Sorting
    sort_columns = {
        "name": DeviceType.name,
        "vendor": DeviceType.vendor,
        "sys_object_id_pattern": DeviceType.sys_object_id_pattern,
        "priority": DeviceType.priority,
        "created_at": DeviceType.created_at,
    }
    sort_col = sort_columns.get(sort_by, DeviceType.name)
    if sort_dir == "desc":
        stmt = stmt.order_by(sa.desc(sort_col))
    else:
        stmt = stmt.order_by(sa.asc(sort_col))

    stmt = stmt.offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    # Count devices per device type
    type_ids = [r.id for r in rows]
    dev_count_map: dict[uuid.UUID, int] = {}
    if type_ids:
        dev_count_stmt = (
            select(Device.device_type_id, sa.func.count().label("cnt"))
            .where(Device.device_type_id.in_(type_ids))
            .group_by(Device.device_type_id)
        )
        dev_count_rows = (await db.execute(dev_count_stmt)).all()
        dev_count_map = {row[0]: row[1] for row in dev_count_rows}

    def _fmt_with_count(r: DeviceType) -> dict:
        d = _fmt(r)
        d["device_count"] = dev_count_map.get(r.id, 0)
        return d

    return {
        "status": "success",
        "data": [_fmt_with_count(r) for r in rows],
        "meta": {"total": total, "limit": limit, "offset": offset, "count": len(rows)},
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_device_type(
    request: CreateDeviceTypeRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new device type."""
    dt = await db.get(DeviceCategory, uuid.UUID(request.device_category_id))
    if not dt:
        raise HTTPException(status_code=404, detail="Device category not found")

    existing = (await db.execute(
        select(DeviceType).where(
            DeviceType.sys_object_id_pattern == request.sys_object_id_pattern
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A device type with pattern '{request.sys_object_id_pattern}' already exists",
        )

    rule = DeviceType(
        name=request.name,
        sys_object_id_pattern=request.sys_object_id_pattern,
        device_category_id=dt.id,
        vendor=request.vendor,
        model=request.model,
        os_family=request.os_family,
        description=request.description,
        priority=request.priority,
        auto_assign_packs=request.auto_assign_packs,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule, ["device_category"])
    return {"status": "success", "data": _fmt(rule)}


@router.get("/{rule_id}")
async def get_device_type(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get a single device type."""
    rule = (await db.execute(
        select(DeviceType)
        .options(selectinload(DeviceType.device_category))
        .where(DeviceType.id == uuid.UUID(rule_id))
    )).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Device type not found")
    return {"status": "success", "data": _fmt(rule)}


@router.put("/{rule_id}")
async def update_device_type(
    rule_id: str,
    request: UpdateDeviceTypeRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a device type."""
    rule = await db.get(DeviceType, uuid.UUID(rule_id))
    if not rule:
        raise HTTPException(status_code=404, detail="Device type not found")

    if request.name is not None:
        rule.name = request.name
    if request.sys_object_id_pattern is not None:
        if request.sys_object_id_pattern != rule.sys_object_id_pattern:
            existing = (await db.execute(
                select(DeviceType).where(
                    DeviceType.sys_object_id_pattern == request.sys_object_id_pattern,
                    DeviceType.id != rule.id,
                )
            )).scalar_one_or_none()
            if existing:
                raise HTTPException(status_code=409, detail="Pattern already exists")
        rule.sys_object_id_pattern = request.sys_object_id_pattern
    if request.device_category_id is not None:
        dt = await db.get(DeviceCategory, uuid.UUID(request.device_category_id))
        if not dt:
            raise HTTPException(status_code=404, detail="Device category not found")
        rule.device_category_id = dt.id
    if request.vendor is not None:
        rule.vendor = request.vendor
    if request.model is not None:
        rule.model = request.model
    if request.os_family is not None:
        rule.os_family = request.os_family
    if request.description is not None:
        rule.description = request.description
    if request.priority is not None:
        rule.priority = request.priority
    if request.auto_assign_packs is not None:
        rule.auto_assign_packs = request.auto_assign_packs or None

    await db.flush()
    await db.refresh(rule, ["device_category"])
    return {"status": "success", "data": _fmt(rule)}


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_type(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a device type."""
    rule = await db.get(DeviceType, uuid.UUID(rule_id))
    if not rule:
        raise HTTPException(status_code=404, detail="Device type not found")
    await db.delete(rule)
