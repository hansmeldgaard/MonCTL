"""Check results query API — reads from ClickHouse.

All three endpoints query ClickHouse directly using denormalized data.
No cross-DB JOINs to PostgreSQL needed (device_name, app_name, role,
tenant_id are stored in each ClickHouse row).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import check_tenant_access, get_clickhouse, get_db, require_auth
from monctl_central.storage.models import Device

router = APIRouter()

STATE_NAMES = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}


def _format_ch_row(r: dict) -> dict:
    """Format a ClickHouse row dict into the API response format."""
    state = r.get("state", 3)
    rtt = r.get("rtt_ms") or None
    resp_time = r.get("response_time_ms") or None
    status_code = r.get("status_code") or None
    exec_time = r.get("execution_time") or None

    return {
        "assignment_id": str(r.get("assignment_id", "")),
        "collector_id": str(r.get("collector_id", "")),
        "app_id": str(r.get("app_id", "")),
        "app_name": r.get("app_name", ""),
        "device_id": str(r.get("device_id", "")),
        "device_name": r.get("device_name", ""),
        "state": state,
        "state_name": STATE_NAMES.get(state, "UNKNOWN"),
        "output": r.get("output", ""),
        "reachable": bool(r.get("reachable", 1)),
        "rtt_ms": rtt if rtt and rtt > 0 else None,
        "response_time_ms": resp_time if resp_time and resp_time > 0 else None,
        "status_code": int(status_code) if status_code and status_code > 0 else None,
        "role": r.get("role", ""),
        "error_message": r.get("error_message", "") or None,
        "executed_at": r["executed_at"].isoformat() if isinstance(r.get("executed_at"), datetime) else str(r.get("executed_at", "")),
        "received_at": r["received_at"].isoformat() if isinstance(r.get("received_at"), datetime) else str(r.get("received_at", "")),
        "execution_time_ms": round(exec_time * 1000, 2) if exec_time and exec_time > 0 else None,
        "started_at": r["started_at"].isoformat() if isinstance(r.get("started_at"), datetime) else (str(r["started_at"]) if r.get("started_at") else None),
        "collector_name": r.get("collector_name", "") or None,
    }


@router.get("")
async def list_results(
    collector_id: Optional[str] = Query(default=None, description="Filter by collector UUID"),
    app_id: Optional[str] = Query(default=None, description="Filter by app UUID"),
    device_id: Optional[str] = Query(default=None, description="Filter by device UUID"),
    state: Optional[int] = Query(default=None, description="Filter by state: 0=OK 1=WARN 2=CRIT 3=UNKNOWN"),
    from_ts: Optional[str] = Query(default=None, description="ISO datetime — return only results at or after this time"),
    to_ts: Optional[str] = Query(default=None, description="ISO datetime — return only results at or before this time"),
    limit: int = Query(default=50, le=5000),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_auth),
):
    """List recent check results, newest first. Reads from ClickHouse."""
    ch = get_clickhouse()

    # Parse tenant filter
    tenant_ids = auth.get("tenant_ids")
    tenant_id = None
    if tenant_ids is not None:
        if len(tenant_ids) == 0:
            return {"status": "success", "data": [], "meta": {"limit": limit, "offset": offset, "count": 0}}
        if len(tenant_ids) == 1:
            tenant_id = tenant_ids[0]

    from_dt = None
    to_dt = None
    if from_ts:
        from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
    if to_ts:
        to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))

    rows = ch.query_history(
        device_id=device_id,
        collector_id=collector_id,
        app_id=app_id,
        state=state,
        tenant_id=tenant_id,
        from_ts=from_dt,
        to_ts=to_dt,
        limit=limit,
        offset=offset,
    )

    # Multi-tenant filter for users with multiple tenant assignments
    if tenant_ids is not None and len(tenant_ids) > 1:
        tid_set = set(tenant_ids)
        rows = [r for r in rows if str(r.get("tenant_id", "")) in tid_set]

    data = [_format_ch_row(r) for r in rows]
    return {
        "status": "success",
        "data": data,
        "meta": {"limit": limit, "offset": offset, "count": len(data)},
    }


@router.get("/latest")
async def latest_results(
    collector_id: Optional[str] = Query(default=None, description="Filter by collector UUID"),
    device_id: Optional[str] = Query(default=None, description="Filter by device UUID"),
    auth: dict = Depends(require_auth),
):
    """Return the most recent result per assignment_id (status dashboard).

    Uses ClickHouse ReplacingMergeTree materialized view with FINAL
    for instant deduplication — no GROUP BY subquery needed.
    """
    ch = get_clickhouse()

    tenant_ids = auth.get("tenant_ids")
    tenant_id = None
    if tenant_ids is not None:
        if len(tenant_ids) == 0:
            return {"status": "success", "data": [], "meta": {"count": 0}}
        if len(tenant_ids) == 1:
            tenant_id = tenant_ids[0]

    rows = ch.query_latest(
        tenant_id=tenant_id,
        device_id=device_id,
        collector_id=collector_id,
    )

    if tenant_ids is not None and len(tenant_ids) > 1:
        tid_set = set(tenant_ids)
        rows = [r for r in rows if str(r.get("tenant_id", "")) in tid_set]

    data = [_format_ch_row(r) for r in rows]
    return {
        "status": "success",
        "data": data,
        "meta": {"count": len(data)},
    }


@router.get("/by-device/{device_id}")
async def device_status(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return the latest result for every assignment linked to a device.

    Primary endpoint for a device status dashboard.
    Device info is loaded from PostgreSQL, results from ClickHouse.
    """
    # Verify device exists in PostgreSQL
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    ch = get_clickhouse()
    rows = ch.query_by_device(device_id)

    checks = []
    for r in rows:
        formatted = _format_ch_row(r)
        checks.append({
            "assignment_id": formatted["assignment_id"],
            "collector_id": formatted["collector_id"],
            "app_name": formatted["app_name"],
            "role": formatted["role"],
            "state": formatted["state"],
            "state_name": formatted["state_name"],
            "output": formatted["output"],
            "reachable": formatted["reachable"],
            "rtt_ms": formatted["rtt_ms"],
            "response_time_ms": formatted["response_time_ms"],
            "status_code": formatted["status_code"],
            "executed_at": formatted["executed_at"],
            "execution_time_ms": formatted["execution_time_ms"],
        })

    availability_checks = [c for c in checks if c.get("role") == "availability"]
    relevant = availability_checks if availability_checks else checks
    all_reachable = all(c["reachable"] for c in relevant) if relevant else None

    return {
        "status": "success",
        "data": {
            "device_id": device_id,
            "device_name": device.name,
            "device_address": device.address,
            "device_type": device.device_type,
            "tenant_id": str(device.tenant_id) if device.tenant_id else None,
            "up": all_reachable,
            "checks": checks,
        },
    }
