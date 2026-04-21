"""Config change history API — reads from ClickHouse config table.

Provides changelog, snapshot, diff, and change-timestamp endpoints
for tracking configuration changes per device.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import check_tenant_access, get_clickhouse, get_db, require_permission
from monctl_central.storage.models import Device

logger = logging.getLogger(__name__)

router = APIRouter()


def _ensure_utc_iso(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.isoformat() + "+00:00"
        return dt.isoformat()
    return str(dt) if dt else None


def _fmt_config_row(r: dict) -> dict:
    return {
        "device_id": str(r.get("device_id", "")),
        "device_name": r.get("device_name", ""),
        "app_id": str(r.get("app_id", "")),
        "app_name": r.get("app_name", ""),
        "component_type": r.get("component_type", ""),
        "component": r.get("component", ""),
        "config_key": r.get("config_key", ""),
        "config_value": r.get("config_value", ""),
        "config_hash": r.get("config_hash", ""),
        "executed_at": _ensure_utc_iso(r.get("executed_at")) or "",
    }


async def _get_device_with_access(
    device_id: str, db: AsyncSession, auth: dict
) -> Device:
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return device


@router.get("/devices/{device_id}/config/changelog")
async def config_changelog(
    device_id: str,
    app_id: Optional[str] = Query(default=None),
    config_key: Optional[str] = Query(default=None),
    component: Optional[str] = Query(default=None),
    value: Optional[str] = Query(default=None),
    from_ts: Optional[str] = Query(default=None),
    to_ts: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=5000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Return config change history for a device, newest first."""
    await _get_device_with_access(device_id, db, auth)
    ch = get_clickhouse()

    from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00")) if from_ts else None
    to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00")) if to_ts else None

    rows, total = await asyncio.gather(
        asyncio.to_thread(
            ch.query_config_changelog,
            device_id,
            app_id=app_id,
            config_key=config_key,
            component=component,
            value=value,
            from_ts=from_dt,
            to_ts=to_dt,
            limit=limit,
            offset=offset,
        ),
        asyncio.to_thread(
            ch.count_config_changelog,
            device_id,
            app_id=app_id,
            config_key=config_key,
            component=component,
            value=value,
            from_ts=from_dt,
            to_ts=to_dt,
        ),
    )

    data = [_fmt_config_row(r) for r in rows]
    return {
        "status": "success",
        "data": data,
        "meta": {"limit": limit, "offset": offset, "count": len(data), "total": total},
    }


@router.get("/devices/{device_id}/config/snapshot")
async def config_snapshot(
    device_id: str,
    app_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Return the current config snapshot (latest value per key)."""
    await _get_device_with_access(device_id, db, auth)
    ch = get_clickhouse()

    rows = await asyncio.to_thread(ch.query_config_snapshot, device_id, app_id=app_id)
    data = [_fmt_config_row(r) for r in rows]
    return {
        "status": "success",
        "data": data,
        "meta": {"count": len(data)},
    }


@router.get("/devices/{device_id}/config/diff")
async def config_diff(
    device_id: str,
    config_key: str = Query(..., description="Config key to show diff history for"),
    app_id: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=200),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Return value history for a specific config key, for building diffs.

    Returns rows ordered by time descending — consecutive rows with
    different config_hash represent actual value changes.
    """
    await _get_device_with_access(device_id, db, auth)
    ch = get_clickhouse()

    rows = await asyncio.to_thread(
        ch.query_config_diff, device_id, config_key, app_id=app_id, limit=limit
    )
    data = [_fmt_config_row(r) for r in rows]
    return {
        "status": "success",
        "data": data,
        "meta": {"count": len(data)},
    }


@router.get("/devices/{device_id}/config/snapshot-at")
async def config_snapshot_at_time(
    device_id: str,
    at_time: str = Query(..., description="ISO timestamp to snapshot at"),
    app_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Return the config state at a specific point in time."""
    await _get_device_with_access(device_id, db, auth)
    ch = get_clickhouse()

    rows = await asyncio.to_thread(
        ch.query_config_snapshot_at_time, device_id, at_time, app_id=app_id
    )
    data = [_fmt_config_row(r) for r in rows]
    return {
        "status": "success",
        "data": data,
        "meta": {"count": len(data)},
    }


@router.get("/devices/{device_id}/config/compare")
async def config_compare(
    device_id: str,
    time_a: str = Query(..., description="Earlier ISO timestamp"),
    time_b: str = Query(..., description="Later ISO timestamp"),
    app_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Compare config state between two points in time.

    Returns only keys that differ between snapshot A and snapshot B.
    """
    await _get_device_with_access(device_id, db, auth)
    ch = get_clickhouse()

    # Strip timezone offset — ClickHouse DateTime64(3) params don't accept +00:00
    from datetime import datetime as _dt
    def _normalize_ts(ts: str) -> str:
        try:
            parsed = _dt.fromisoformat(ts)
            return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        except Exception:
            return ts

    snapshot_a, snapshot_b = await asyncio.gather(
        asyncio.to_thread(
            ch.query_config_snapshot_at_time, device_id, _normalize_ts(time_a), app_id=app_id
        ),
        asyncio.to_thread(
            ch.query_config_snapshot_at_time, device_id, _normalize_ts(time_b), app_id=app_id
        ),
    )

    map_a = {
        (r.get("component_type", ""), r.get("component", ""), r.get("config_key", "")): r.get("config_value", "")
        for r in snapshot_a
    }
    map_b = {
        (r.get("component_type", ""), r.get("component", ""), r.get("config_key", "")): r.get("config_value", "")
        for r in snapshot_b
    }

    all_keys = sorted(set(map_a.keys()) | set(map_b.keys()))
    changes = []
    unchanged = []
    for key in all_keys:
        val_a = map_a.get(key)
        val_b = map_b.get(key)
        entry = {
            "component_type": key[0],
            "component": key[1],
            "config_key": key[2],
            "value_a": val_a,
            "value_b": val_b,
        }
        if val_a == val_b:
            entry["change_type"] = "unchanged"
            unchanged.append(entry)
        elif val_a is None:
            entry["change_type"] = "added"
            changes.append(entry)
        elif val_b is None:
            entry["change_type"] = "removed"
            changes.append(entry)
        else:
            entry["change_type"] = "modified"
            changes.append(entry)

    return {
        "status": "success",
        "data": {
            "time_a": time_a,
            "time_b": time_b,
            "changes": changes,
            "unchanged": unchanged,
            "total_keys_a": len(map_a),
            "total_keys_b": len(map_b),
        },
    }


@router.get("/devices/{device_id}/config/change-timestamps")
async def config_change_timestamps(
    device_id: str,
    app_id: Optional[str] = Query(default=None),
    from_ts: Optional[str] = Query(default=None),
    to_ts: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Return a timeline of config change events (minute-level buckets)."""
    await _get_device_with_access(device_id, db, auth)
    ch = get_clickhouse()

    from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00")) if from_ts else None
    to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00")) if to_ts else None

    rows = await asyncio.to_thread(
        ch.query_config_change_timestamps,
        device_id, app_id=app_id, from_ts=from_dt, to_ts=to_dt,
    )
    data = [
        {
            "change_time": _ensure_utc_iso(r.get("change_time")) or "",
            "change_count": r.get("change_count", 0),
            "changed_keys": list(r.get("changed_keys", [])),
        }
        for r in rows
    ]
    return {
        "status": "success",
        "data": data,
        "meta": {"count": len(data)},
    }
