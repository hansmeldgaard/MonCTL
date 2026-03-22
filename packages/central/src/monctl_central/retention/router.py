"""Unified data retention management — global defaults and per-device overrides."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import (
    App, AppAssignment, DataRetentionOverride, SystemSetting,
)

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_DATA_TYPES = {"config", "performance", "availability_latency", "interface"}
DEFAULT_RETENTION = {
    "config": 365,
    "performance": 90,
    "availability_latency": 30,
    "interface": 90,
}

# Fallback key names from existing settings page
_LEGACY_KEYS = {
    "config": "config_retention_days",
    "performance": "check_results_retention_days",
    "availability_latency": "check_results_retention_days",
    "interface": "interface_raw_retention_days",
}


async def _get_effective_default(db: AsyncSession, data_type: str) -> int:
    """Get effective retention for a data type, checking unified key then legacy key."""
    fallback = DEFAULT_RETENTION.get(data_type, 90)
    # Check unified key first
    key = f"retention_days_{data_type}"
    setting = await db.get(SystemSetting, key)
    if setting:
        return int(setting.value)
    # Fall back to legacy key
    legacy_key = _LEGACY_KEYS.get(data_type)
    if legacy_key:
        setting = await db.get(SystemSetting, legacy_key)
        if setting:
            return int(setting.value)
    return fallback


@router.get("/retention/defaults")
async def get_retention_defaults(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return global retention defaults for all data types."""
    defaults = {}
    for data_type in DEFAULT_RETENTION:
        defaults[data_type] = await _get_effective_default(db, data_type)

    return {"status": "success", "data": defaults}


class UpdateRetentionDefaultRequest(BaseModel):
    data_type: str
    retention_days: int


@router.put("/retention/defaults")
async def set_retention_default(
    req: UpdateRetentionDefaultRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Set the global retention default for a specific data type."""
    if req.data_type not in VALID_DATA_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid data_type. Must be one of: {VALID_DATA_TYPES}")
    if req.retention_days < 1:
        raise HTTPException(status_code=400, detail="retention_days must be a positive integer")

    key = f"retention_days_{req.data_type}"
    setting = await db.get(SystemSetting, key)
    if setting:
        setting.value = str(req.retention_days)
    else:
        db.add(SystemSetting(key=key, value=str(req.retention_days)))
    await db.commit()

    return {"status": "success", "data": {"data_type": req.data_type, "retention_days": req.retention_days}}


@router.get("/devices/{device_id}/retention")
async def get_device_retention(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return effective retention for all apps assigned to a device."""
    defaults = {}
    for data_type in DEFAULT_RETENTION:
        defaults[data_type] = await _get_effective_default(db, data_type)

    stmt = (
        select(AppAssignment)
        .join(App, AppAssignment.app_id == App.id)
        .where(AppAssignment.device_id == uuid.UUID(device_id))
        .options(selectinload(AppAssignment.app))
    )
    assignments = (await db.execute(stmt)).scalars().all()

    stmt = select(DataRetentionOverride).where(
        DataRetentionOverride.device_id == uuid.UUID(device_id)
    )
    overrides = (await db.execute(stmt)).scalars().all()
    override_map = {(str(o.app_id), o.data_type): o for o in overrides}

    entries = []
    for assignment in assignments:
        app = assignment.app
        if not app:
            continue
        data_type = app.target_table or "availability_latency"
        override = override_map.get((str(app.id), data_type))

        entries.append({
            "app_id": str(app.id),
            "app_name": app.name,
            "data_type": data_type,
            "retention_days": override.retention_days if override else defaults.get(data_type, 90),
            "source": "device_override" if override else "global_default",
            "override_id": str(override.id) if override else None,
        })

    entries.sort(key=lambda e: (e["data_type"], e["app_name"]))
    return {"status": "success", "data": entries}


class SetDeviceRetentionRequest(BaseModel):
    app_id: str
    data_type: str
    retention_days: int


@router.put("/devices/{device_id}/retention")
async def set_device_retention(
    device_id: str,
    req: SetDeviceRetentionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create or update a per-device retention override."""
    if req.data_type not in VALID_DATA_TYPES:
        raise HTTPException(status_code=400, detail="Invalid data_type")
    if req.retention_days < 1:
        raise HTTPException(status_code=400, detail="retention_days must be positive")

    stmt = select(DataRetentionOverride).where(
        DataRetentionOverride.device_id == uuid.UUID(device_id),
        DataRetentionOverride.app_id == uuid.UUID(req.app_id),
        DataRetentionOverride.data_type == req.data_type,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        existing.retention_days = req.retention_days
        existing.updated_at = datetime.now(timezone.utc)
        override = existing
    else:
        override = DataRetentionOverride(
            device_id=uuid.UUID(device_id),
            app_id=uuid.UUID(req.app_id),
            data_type=req.data_type,
            retention_days=req.retention_days,
        )
        db.add(override)

    await db.flush()
    await db.commit()

    return {"status": "success", "data": {
        "id": str(override.id),
        "app_id": req.app_id,
        "data_type": req.data_type,
        "retention_days": req.retention_days,
        "source": "device_override",
    }}


@router.delete("/devices/{device_id}/retention/{override_id}")
async def delete_device_retention(
    device_id: str,
    override_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a per-device retention override (reverts to global default)."""
    override = await db.get(DataRetentionOverride, uuid.UUID(override_id))
    if not override or str(override.device_id) != device_id:
        raise HTTPException(status_code=404, detail="Override not found")
    await db.delete(override)
    await db.commit()
    return {"status": "success"}
