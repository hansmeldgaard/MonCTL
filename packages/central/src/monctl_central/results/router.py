"""Check results query API."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import apply_tenant_filter, check_tenant_access, get_db, require_auth
from monctl_central.storage.models import AppAssignment, CheckResultRecord, Device

router = APIRouter()

STATE_NAMES = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}


@router.get("")
async def list_results(
    collector_id: Optional[str] = Query(default=None, description="Filter by collector UUID"),
    app_id: Optional[str] = Query(default=None, description="Filter by app UUID"),
    device_id: Optional[str] = Query(default=None, description="Filter by device UUID (joins through app_assignments)"),
    state: Optional[int] = Query(default=None, description="Filter by state: 0=OK 1=WARN 2=CRIT 3=UNKNOWN"),
    from_ts: Optional[str] = Query(default=None, description="ISO datetime (e.g. 2026-01-01T00:00:00Z) — return only results at or after this time"),
    to_ts: Optional[str] = Query(default=None, description="ISO datetime — return only results at or before this time"),
    limit: int = Query(default=50, le=5000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List recent check results, newest first. Includes device and app info."""
    from datetime import datetime
    from monctl_central.storage.models import App

    stmt = (
        select(CheckResultRecord, AppAssignment, App)
        .join(AppAssignment, CheckResultRecord.assignment_id == AppAssignment.id)
        .join(App, AppAssignment.app_id == App.id)
        .order_by(desc(CheckResultRecord.executed_at))
    )

    if collector_id:
        stmt = stmt.where(CheckResultRecord.collector_id == uuid.UUID(collector_id))
    if app_id:
        stmt = stmt.where(CheckResultRecord.app_id == uuid.UUID(app_id))
    if state is not None:
        stmt = stmt.where(CheckResultRecord.state == state)
    if device_id:
        stmt = stmt.where(AppAssignment.device_id == uuid.UUID(device_id))
    if from_ts:
        ts = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        stmt = stmt.where(CheckResultRecord.executed_at >= ts)
    if to_ts:
        ts = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        stmt = stmt.where(CheckResultRecord.executed_at <= ts)

    # Apply tenant filtering through device join
    tenant_ids = auth.get("tenant_ids")
    if tenant_ids is not None:
        stmt = stmt.outerjoin(Device, AppAssignment.device_id == Device.id)
        if len(tenant_ids) == 0:
            import sqlalchemy as sa
            stmt = stmt.where(sa.false())
        else:
            import sqlalchemy as sa
            uuids = [uuid.UUID(t) for t in tenant_ids]
            stmt = stmt.where(Device.tenant_id.in_(uuids))

    stmt = stmt.offset(offset).limit(limit)
    rows = (await db.execute(stmt)).all()

    # Batch-load devices
    device_ids = {a.device_id for _, a, _ in rows if a.device_id}
    devices_map: dict[uuid.UUID, object] = {}
    if device_ids:
        device_rows = (await db.execute(
            select(Device).where(Device.id.in_(device_ids))
        )).scalars().all()
        devices_map = {d.id: d for d in device_rows}

    data = []
    for result, assignment, app in rows:
        perf = result.performance_data or {}
        device = devices_map.get(assignment.device_id) if assignment.device_id else None
        data.append({
            "id": result.id,
            "assignment_id": str(result.assignment_id),
            "collector_id": str(result.collector_id),
            "app_id": str(result.app_id),
            "app_name": app.name,
            "device_id": str(assignment.device_id) if assignment.device_id else None,
            "device_name": device.name if device else None,
            "state": result.state,
            "state_name": STATE_NAMES.get(result.state, "UNKNOWN"),
            "output": result.output,
            "reachable": perf.get("reachable") == 1.0,
            "rtt_ms": perf.get("rtt_ms"),
            "response_time_ms": perf.get("response_time_ms"),
            "status_code": int(perf.get("status_code", 0)) or None,
            "performance_data": perf,
            "executed_at": result.executed_at.isoformat() if result.executed_at else None,
            "received_at": result.received_at.isoformat() if result.received_at else None,
            "role": assignment.role,
            "execution_time_ms": round(result.execution_time * 1000, 2) if result.execution_time else None,
        })

    return {
        "status": "success",
        "data": data,
        "meta": {"limit": limit, "offset": offset, "count": len(data)},
    }


@router.get("/latest")
async def latest_results(
    collector_id: Optional[str] = Query(default=None, description="Filter by collector UUID"),
    device_id: Optional[str] = Query(default=None, description="Filter by device UUID"),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return the most recent result per assignment_id (good for a status dashboard).

    Includes device and app info for dashboard display.
    """
    from monctl_central.storage.models import App, Device

    # Subquery: max executed_at per assignment
    subq = (
        select(
            CheckResultRecord.assignment_id,
            func.max(CheckResultRecord.executed_at).label("max_ts"),
        )
        .group_by(CheckResultRecord.assignment_id)
        .subquery()
    )

    stmt = (
        select(CheckResultRecord, AppAssignment, App)
        .join(
            subq,
            (CheckResultRecord.assignment_id == subq.c.assignment_id)
            & (CheckResultRecord.executed_at == subq.c.max_ts),
        )
        .join(AppAssignment, CheckResultRecord.assignment_id == AppAssignment.id)
        .join(App, AppAssignment.app_id == App.id)
        .join(Device, AppAssignment.device_id == Device.id)
        .order_by(desc(CheckResultRecord.executed_at))
    )

    if collector_id:
        stmt = stmt.where(CheckResultRecord.collector_id == uuid.UUID(collector_id))

    if device_id:
        stmt = stmt.where(AppAssignment.device_id == uuid.UUID(device_id))

    stmt = apply_tenant_filter(stmt, auth, Device.tenant_id)

    rows = (await db.execute(stmt)).all()

    # Collect device IDs to batch-load
    device_ids = {a.device_id for _, a, _ in rows if a.device_id}
    devices_map: dict[uuid.UUID, object] = {}
    if device_ids:
        device_rows = (await db.execute(
            select(Device).where(Device.id.in_(device_ids))
        )).scalars().all()
        devices_map = {d.id: d for d in device_rows}

    data = []
    for result, assignment, app in rows:
        perf = result.performance_data or {}
        device = devices_map.get(assignment.device_id) if assignment.device_id else None
        data.append({
            "id": result.id,
            "assignment_id": str(result.assignment_id),
            "collector_id": str(result.collector_id),
            "app_id": str(result.app_id),
            "app_name": app.name,
            "device_id": str(assignment.device_id) if assignment.device_id else None,
            "device_name": device.name if device else None,
            "state": result.state,
            "state_name": STATE_NAMES.get(result.state, "UNKNOWN"),
            "output": result.output,
            "reachable": perf.get("reachable") == 1.0,
            "rtt_ms": perf.get("rtt_ms"),
            "response_time_ms": perf.get("response_time_ms"),
            "status_code": int(perf.get("status_code", 0)) or None,
            "performance_data": perf,
            "role": assignment.role,
            "executed_at": result.executed_at.isoformat() if result.executed_at else None,
            "received_at": result.received_at.isoformat() if result.received_at else None,
            "execution_time_ms": round(result.execution_time * 1000, 2) if result.execution_time else None,
        })

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

    This is the primary endpoint for a device status dashboard.
    Returns up/down state and key performance metrics per check (rtt_ms, response_time_ms, etc.)
    """
    from monctl_central.storage.models import App

    # Verify the device exists
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    # Tenant access check
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Subquery: latest result per assignment for this device
    subq = (
        select(
            CheckResultRecord.assignment_id,
            func.max(CheckResultRecord.executed_at).label("max_ts"),
        )
        .join(AppAssignment, CheckResultRecord.assignment_id == AppAssignment.id)
        .where(AppAssignment.device_id == uuid.UUID(device_id))
        .group_by(CheckResultRecord.assignment_id)
        .subquery()
    )

    stmt = (
        select(CheckResultRecord, AppAssignment, App)
        .join(
            subq,
            (CheckResultRecord.assignment_id == subq.c.assignment_id)
            & (CheckResultRecord.executed_at == subq.c.max_ts),
        )
        .join(AppAssignment, CheckResultRecord.assignment_id == AppAssignment.id)
        .join(App, AppAssignment.app_id == App.id)
        .order_by(desc(CheckResultRecord.executed_at))
    )

    rows = (await db.execute(stmt)).all()

    checks = []
    for result, assignment, app in rows:
        perf = result.performance_data or {}
        checks.append({
            "assignment_id": str(result.assignment_id),
            "collector_id": str(result.collector_id) if result.collector_id else None,
            "app_name": app.name,
            "role": assignment.role,
            "state": result.state,
            "state_name": STATE_NAMES.get(result.state, "UNKNOWN"),
            "output": result.output,
            "reachable": perf.get("reachable") == 1.0,
            # App-specific performance fields (present when the app reports them)
            "rtt_ms": perf.get("rtt_ms"),                           # ping checks
            "response_time_ms": perf.get("response_time_ms"),       # HTTP checks
            "status_code": int(perf.get("status_code", 0)) or None, # HTTP checks
            "performance_data": perf,
            "executed_at": result.executed_at.isoformat() if result.executed_at else None,
            "execution_time_ms": round(result.execution_time * 1000, 2) if result.execution_time else None,
        })

    # Overall device up = availability-role checks are reachable.
    # If no availability check is assigned, fall back to all checks.
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


def _format_result(r: CheckResultRecord) -> dict:
    perf = r.performance_data or {}
    return {
        "id": r.id,
        "assignment_id": str(r.assignment_id),
        "collector_id": str(r.collector_id),
        "app_id": str(r.app_id),
        "state": r.state,
        "state_name": STATE_NAMES.get(r.state, "UNKNOWN"),
        "output": r.output,
        "reachable": perf.get("reachable") == 1.0,
        # Common performance fields surfaced for quick access
        "rtt_ms": perf.get("rtt_ms"),
        "response_time_ms": perf.get("response_time_ms"),
        "status_code": int(perf.get("status_code", 0)) or None,
        "performance_data": perf,
        "executed_at": r.executed_at.isoformat() if r.executed_at else None,
        "received_at": r.received_at.isoformat() if r.received_at else None,
        "execution_time_ms": round(r.execution_time * 1000, 2) if r.execution_time else None,
    }
