"""System settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import SystemSetting
from monctl_common.utils import utc_now

router = APIRouter()

_DEFAULTS = {
    "job_status_retention_days": "7",
    "check_results_retention_days": "90",
    "interface_poll_interval_seconds": "300",
    "interface_metadata_refresh_seconds": "3600",
    "interface_raw_retention_days": "7",
    "interface_hourly_retention_days": "90",
    "interface_daily_retention_days": "730",
    "pypi_network_mode": "direct",
    "pypi_proxy_url": "",
}


@router.get("")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get all system settings as a dict."""
    result = await db.execute(select(SystemSetting))
    rows = result.scalars().all()
    data = dict(_DEFAULTS)
    for row in rows:
        data[row.key] = row.value
    return {"status": "success", "data": data}


class UpdateSettingsRequest(BaseModel):
    settings: dict[str, str]


@router.put("")
async def update_settings(
    request: UpdateSettingsRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Partial update system settings."""
    for key, value in request.settings.items():
        existing = await db.get(SystemSetting, key)
        if existing:
            existing.value = value
            existing.updated_at = utc_now()
        else:
            db.add(SystemSetting(key=key, value=value))
    await db.flush()
    # Return updated settings
    result = await db.execute(select(SystemSetting))
    rows = result.scalars().all()
    data = dict(_DEFAULTS)
    for row in rows:
        data[row.key] = row.value
    return {"status": "success", "data": data}
