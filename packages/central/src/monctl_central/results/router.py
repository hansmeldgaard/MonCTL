"""Check results query API — reads from ClickHouse.

All three endpoints query ClickHouse directly using denormalized data.
No cross-DB JOINs to PostgreSQL needed (device_name, app_name, role,
tenant_id are stored in each ClickHouse row).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import check_tenant_access, get_clickhouse, get_db, require_auth
from monctl_central.storage.models import Device

logger = logging.getLogger(__name__)

router = APIRouter()

STATE_NAMES = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}


def _ensure_utc_iso(dt) -> str | None:
    """Format datetime as ISO 8601 with explicit UTC offset."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.isoformat() + "+00:00"
        return dt.isoformat()
    return str(dt) if dt else None


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
        "executed_at": _ensure_utc_iso(r.get("executed_at")) or "",
        "received_at": _ensure_utc_iso(r.get("received_at")) or "",
        "execution_time_ms": round(exec_time * 1000, 2) if exec_time and exec_time > 0 else None,
        "started_at": _ensure_utc_iso(r.get("started_at")),
        "collector_name": r.get("collector_name", "") or None,
    }


VALID_TABLES = {"availability_latency", "performance", "interface", "config"}


@router.get("")
async def list_results(
    table: Optional[str] = Query(default=None, description="ClickHouse table to query (omit to search all tables)"),
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
    # Determine which tables to query
    if table and table in VALID_TABLES:
        tables = [table]
    else:
        tables = list(VALID_TABLES)

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

    all_rows: list[dict] = []
    for t in tables:
        try:
            rows = ch.query_history(
                table=t,
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
            all_rows.extend(rows)
        except Exception as exc:
            if ch._is_table_missing_error(exc):
                logger.debug("Table %s does not exist yet, skipping", t)
            else:
                logger.error("ClickHouse query failed for table %s: %s", t, exc)
                raise

    # Multi-tenant filter for users with multiple tenant assignments
    if tenant_ids is not None and len(tenant_ids) > 1:
        tid_set = set(tenant_ids)
        all_rows = [r for r in all_rows if str(r.get("tenant_id", "")) in tid_set]

    # Sort merged results by executed_at descending and apply limit
    all_rows.sort(key=lambda r: r.get("executed_at", ""), reverse=True)
    all_rows = all_rows[:limit]

    data = [_format_ch_row(r) for r in all_rows]
    return {
        "status": "success",
        "data": data,
        "meta": {"limit": limit, "offset": offset, "count": len(data)},
    }


@router.get("/latest")
async def latest_results(
    table: Optional[str] = Query(default=None, description="ClickHouse table to query (omit to search all tables)"),
    collector_id: Optional[str] = Query(default=None, description="Filter by collector UUID"),
    device_id: Optional[str] = Query(default=None, description="Filter by device UUID"),
    auth: dict = Depends(require_auth),
):
    """Return the most recent result per key (status dashboard).

    Uses ClickHouse ReplacingMergeTree materialized view with FINAL
    for instant deduplication — no GROUP BY subquery needed.
    """
    if table and table in VALID_TABLES:
        tables = [table]
    else:
        tables = list(VALID_TABLES)

    ch = get_clickhouse()

    tenant_ids = auth.get("tenant_ids")
    tenant_id = None
    if tenant_ids is not None:
        if len(tenant_ids) == 0:
            return {"status": "success", "data": [], "meta": {"count": 0}}
        if len(tenant_ids) == 1:
            tenant_id = tenant_ids[0]

    all_rows: list[dict] = []
    for t in tables:
        try:
            rows = ch.query_latest(
                table=t,
                tenant_id=tenant_id,
                device_id=device_id,
                collector_id=collector_id,
            )
            all_rows.extend(rows)
        except Exception as exc:
            if ch._is_table_missing_error(exc):
                logger.debug("Table %s_latest does not exist yet, skipping", t)
            else:
                logger.error("ClickHouse query failed for table %s: %s", t, exc)
                raise

    if tenant_ids is not None and len(tenant_ids) > 1:
        tid_set = set(tenant_ids)
        all_rows = [r for r in all_rows if str(r.get("tenant_id", "")) in tid_set]

    data = [_format_ch_row(r) for r in all_rows]
    return {
        "status": "success",
        "data": data,
        "meta": {"count": len(data)},
    }


def _format_interface_row(r: dict) -> dict:
    """Format a ClickHouse interface table row into the API response format."""
    return {
        "assignment_id": str(r.get("assignment_id", "")),
        "collector_id": str(r.get("collector_id", "")),
        "app_id": str(r.get("app_id", "")),
        "app_name": r.get("app_name", ""),
        "device_id": str(r.get("device_id", "")),
        "device_name": r.get("device_name", ""),
        "if_index": r.get("if_index", 0),
        "if_name": r.get("if_name", ""),
        "if_alias": r.get("if_alias", ""),
        "if_speed_mbps": r.get("if_speed_mbps", 0),
        "if_admin_status": r.get("if_admin_status", ""),
        "if_oper_status": r.get("if_oper_status", ""),
        "in_octets": r.get("in_octets", 0),
        "out_octets": r.get("out_octets", 0),
        "in_errors": r.get("in_errors", 0),
        "out_errors": r.get("out_errors", 0),
        "in_discards": r.get("in_discards", 0),
        "out_discards": r.get("out_discards", 0),
        "in_unicast_pkts": r.get("in_unicast_pkts", 0),
        "out_unicast_pkts": r.get("out_unicast_pkts", 0),
        "in_rate_bps": r.get("in_rate_bps", 0),
        "out_rate_bps": r.get("out_rate_bps", 0),
        "in_utilization_pct": r.get("in_utilization_pct", 0),
        "out_utilization_pct": r.get("out_utilization_pct", 0),
        "poll_interval_sec": r.get("poll_interval_sec", 0),
        "state": r.get("state", 0),
        "executed_at": _ensure_utc_iso(r.get("executed_at")) or "",
        "received_at": _ensure_utc_iso(r.get("received_at")) or "",
        "tenant_id": str(r.get("tenant_id", "")),
        "collector_name": r.get("collector_name", "") or None,
    }


@router.get("/interfaces/{device_id}")
async def device_interfaces(
    device_id: str,
    from_ts: Optional[str] = Query(default=None, description="ISO datetime — return only results at or after this time"),
    to_ts: Optional[str] = Query(default=None, description="ISO datetime — return only results at or before this time"),
    if_index: Optional[int] = Query(default=None, description="Filter by interface index"),
    limit: int = Query(default=2000, le=10000),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return interface history for a device, optionally filtered by interface and time range."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    ch = get_clickhouse()
    try:
        sql = "SELECT * FROM interface WHERE device_id = {device_id:UUID}"
        params: dict = {"device_id": device_id}

        if from_ts:
            sql += " AND executed_at >= {from_ts:DateTime64}"
            params["from_ts"] = from_ts.replace("Z", "+00:00")
        if to_ts:
            sql += " AND executed_at <= {to_ts:DateTime64}"
            params["to_ts"] = to_ts.replace("Z", "+00:00")
        if if_index is not None:
            sql += " AND if_index = {if_index:UInt32}"
            params["if_index"] = if_index

        sql += " ORDER BY if_index, executed_at DESC LIMIT {limit:UInt32}"
        params["limit"] = limit

        client = ch._get_client()
        result = client.query(sql, parameters=params)
        rows = list(result.named_results())
    except Exception as exc:
        if ch._is_table_missing_error(exc):
            rows = []
        else:
            raise

    data = [_format_interface_row(r) for r in rows]
    return {
        "status": "success",
        "data": data,
        "meta": {"limit": limit, "count": len(data)},
    }


@router.get("/interfaces/{device_id}/latest")
async def device_interfaces_latest(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return the latest interface data per interface for a device."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    ch = get_clickhouse()
    try:
        rows = ch.query_latest(table="interface", device_id=device_id)
    except Exception as exc:
        if ch._is_table_missing_error(exc):
            rows = []
        else:
            raise

    data = [_format_interface_row(r) for r in rows]
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
    try:
        rows = ch.query_by_device(device_id)
    except Exception:
        logger.exception("query_by_device failed for device %s", device_id)
        rows = []

    if not rows:
        logger.warning("device_status: 0 checks returned from ClickHouse for device %s", device_id)

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
