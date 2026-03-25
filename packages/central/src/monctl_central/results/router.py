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
from monctl_central.storage.models import Device, InterfaceMetadata

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
    """Format a ClickHouse row dict into the API response format.

    Handles columns from all result tables (availability_latency, performance, config).
    """
    state = r.get("state", 3)
    rtt = r.get("rtt_ms") or None
    resp_time = r.get("response_time_ms") or None
    status_code = r.get("status_code") or None
    exec_time = r.get("execution_time") or None

    out: dict = {
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

    # Config table fields
    if "config_key" in r:
        out["config_key"] = r.get("config_key")
        out["config_value"] = r.get("config_value")
        out["config_hash"] = r.get("config_hash")

    # Performance table fields
    if "component" in r:
        out["component"] = r.get("component")
        out["component_type"] = r.get("component_type")
    if "metric_names" in r:
        out["metric_names"] = r.get("metric_names")
        out["metric_values"] = r.get("metric_values")

    return out


# Tables for general history queries (interface has its own dedicated tab/endpoints)
HISTORY_TABLES = {"availability_latency", "performance", "config"}
# All tables (used by explicit table= queries and /latest)
VALID_TABLES = {"availability_latency", "performance", "interface", "config"}


@router.get("")
async def list_results(
    table: Optional[str] = Query(default=None, description="ClickHouse table to query (omit to search all tables)"),
    collector_id: Optional[str] = Query(default=None, description="Filter by collector UUID"),
    app_id: Optional[str] = Query(default=None, description="Filter by app UUID"),
    device_id: Optional[str] = Query(default=None, description="Filter by device UUID"),
    state: Optional[int] = Query(default=None, description="Filter by state: 0=OK 1=WARN 2=CRIT 3=UNKNOWN"),
    role: Optional[str] = Query(default=None, description="Filter by assignment role (comma-separated: availability,latency,interface)"),
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
        tables = list(HISTORY_TABLES)

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

    # Role filter — allows frontend to request only availability/latency results
    if role:
        _VALID_ROLES = {"availability", "latency", "interface", ""}
        allowed_roles = {r.strip() for r in role.split(",")}
        invalid = allowed_roles - _VALID_ROLES
        if invalid:
            raise HTTPException(
                status_code=422, detail=f"Invalid role values: {invalid}"
            )
        all_rows = [r for r in all_rows if r.get("role", "") in allowed_roles]

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
        "interface_id": str(r.get("interface_id", "")),
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


_VALID_TIERS = {"raw", "hourly", "daily"}
_TIER_TABLE = {"raw": "interface", "hourly": "interface_hourly", "daily": "interface_daily"}
_TIER_TIME_COL = {"raw": "executed_at", "hourly": "hour", "daily": "day"}


async def _auto_select_tier(
    from_ts_str: str | None, db: AsyncSession, device_id: str | None = None,
) -> str:
    """Auto-select interface data tier based on age of query vs configured retention."""
    if not from_ts_str:
        return "raw"
    from monctl_central.storage.models import SystemSetting
    from_dt = datetime.fromisoformat(from_ts_str.replace("Z", "+00:00"))
    age = datetime.now(tz=from_dt.tzinfo or None) - from_dt

    raw_days = 7
    hourly_days = 90

    # Check per-device override first
    if device_id:
        try:
            device = await db.get(Device, uuid.UUID(device_id))
            if device and device.retention_overrides:
                overrides = device.retention_overrides
                if "interface_raw_retention_days" in overrides:
                    raw_days = int(overrides["interface_raw_retention_days"])
                if "interface_hourly_retention_days" in overrides:
                    hourly_days = int(overrides["interface_hourly_retention_days"])
                if age.days <= raw_days:
                    return "raw"
                elif age.days <= hourly_days:
                    return "hourly"
                return "daily"
        except Exception:
            pass

    try:
        setting = await db.get(SystemSetting, "interface_raw_retention_days")
        if setting:
            raw_days = int(setting.value)
        setting = await db.get(SystemSetting, "interface_hourly_retention_days")
        if setting:
            hourly_days = int(setting.value)
    except Exception:
        pass

    if age.days <= raw_days:
        return "raw"
    elif age.days <= hourly_days:
        return "hourly"
    return "daily"


@router.get("/interfaces/{device_id}")
async def device_interfaces(
    device_id: str,
    from_ts: Optional[str] = Query(default=None, description="ISO datetime — return only results at or after this time"),
    to_ts: Optional[str] = Query(default=None, description="ISO datetime — return only results at or before this time"),
    if_index: Optional[int] = Query(default=None, description="Filter by interface index"),
    interface_id: Optional[str] = Query(default=None, description="Filter by stable interface UUID (preferred over if_index)"),
    tier: Optional[str] = Query(default=None, description="Data tier: raw, hourly, daily (omit for auto)"),
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

    # Resolve tier
    if tier and tier in _VALID_TIERS:
        selected_tier = tier
    else:
        selected_tier = await _auto_select_tier(from_ts, db, device_id=device_id)

    table = _TIER_TABLE[selected_tier]
    time_col = _TIER_TIME_COL[selected_tier]

    ch = get_clickhouse()
    try:
        sql = f"SELECT * FROM {table} WHERE device_id = {{device_id:UUID}}"
        params: dict = {"device_id": device_id}

        if from_ts:
            sql += f" AND {time_col} >= {{from_ts:DateTime64}}"
            from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
            params["from_ts"] = from_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if to_ts:
            sql += f" AND {time_col} <= {{to_ts:DateTime64}}"
            to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
            params["to_ts"] = to_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # Prefer interface_id over if_index when both provided
        if interface_id is not None:
            sql += " AND interface_id = {interface_id:UUID}"
            params["interface_id"] = interface_id
        elif if_index is not None and selected_tier == "raw":
            sql += " AND if_index = {if_index:UInt32}"
            params["if_index"] = if_index

        sql += f" ORDER BY interface_id, {time_col} DESC LIMIT {{limit:UInt32}}"
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
        "meta": {"limit": limit, "count": len(data), "tier": selected_tier},
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

    # Get valid interface_ids from metadata to filter out orphaned ClickHouse rows.
    # Orphans occur when metadata is recreated (new UUID) but old ClickHouse rows
    # still reference the previous interface_id.
    from sqlalchemy import select
    valid_ids_result = await db.execute(
        select(InterfaceMetadata.id).where(
            InterfaceMetadata.device_id == uuid.UUID(device_id),
        )
    )
    valid_ids = {str(row[0]) for row in valid_ids_result.all()}

    ch = get_clickhouse()
    try:
        rows = ch.query_latest(table="interface", device_id=device_id)
    except Exception as exc:
        if ch._is_table_missing_error(exc):
            rows = []
        else:
            raise

    data = [_format_interface_row(r) for r in rows
            if str(r.get("interface_id", "")) in valid_ids]
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
            "device_category": device.device_category,
            "tenant_id": str(device.tenant_id) if device.tenant_id else None,
            "up": all_reachable,
            "checks": checks,
        },
    }


# ── Performance data endpoints ────────────────────────────────────────────────


def _format_performance_row(r: dict) -> dict:
    """Format a ClickHouse performance table row."""
    metric_names = r.get("metric_names", [])
    metric_values = r.get("metric_values", [])
    metric_types = r.get("metric_types", [])
    metrics = dict(zip(metric_names, metric_values)) if metric_names else {}
    return {
        "assignment_id": str(r.get("assignment_id", "")),
        "app_id": str(r.get("app_id", "")),
        "app_name": r.get("app_name", ""),
        "device_id": str(r.get("device_id", "")),
        "component": r.get("component", ""),
        "component_type": r.get("component_type", ""),
        "state": r.get("state", 0),
        "metrics": metrics,
        "metric_names": list(metric_names),
        "metric_values": list(metric_values),
        "metric_types": list(metric_types),
        "executed_at": _ensure_utc_iso(r.get("executed_at")) or "",
        "collector_name": r.get("collector_name", "") or None,
    }


@router.get("/performance/{device_id}/summary")
async def device_performance_summary(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return available apps, component_types, and components for a device."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    ch = get_clickhouse()

    sql = """
        SELECT DISTINCT
            app_name, app_id, assignment_id,
            component_type, component, metric_names
        FROM performance_latest FINAL
        WHERE device_id = {device_id:UUID}
          AND component_type != ''
          AND component != ''
        ORDER BY app_name, component_type, component
    """
    params = {"device_id": device_id}

    try:
        client = ch._get_client()
        result = client.query(sql, parameters=params)
        rows = list(result.named_results())
    except Exception as exc:
        if ch._is_table_missing_error(exc):
            rows = []
        else:
            raise

    apps: dict = {}
    for r in rows:
        app_key = str(r.get("app_id", ""))
        if app_key not in apps:
            apps[app_key] = {
                "app_id": app_key,
                "app_name": r.get("app_name", ""),
                "assignment_id": str(r.get("assignment_id", "")),
                "component_types": {},
            }
        ct = r.get("component_type", "")
        if ct not in apps[app_key]["component_types"]:
            apps[app_key]["component_types"][ct] = {
                "components": [],
                "metric_names": [],
            }
        component_name = r.get("component", "")
        entry = apps[app_key]["component_types"][ct]
        if component_name and component_name not in entry["components"]:
            entry["components"].append(component_name)
        for m in (r.get("metric_names", []) or []):
            if m not in entry["metric_names"]:
                entry["metric_names"].append(m)

    return {"status": "success", "data": list(apps.values())}


_PERF_TIER_TABLE = {"raw": "performance", "hourly": "performance_hourly", "daily": "performance_daily"}
_PERF_TIER_TIME_COL = {"raw": "executed_at", "hourly": "hour", "daily": "day"}


async def _auto_select_perf_tier(
    from_ts_str: str | None, db: AsyncSession, device_id: str | None = None,
) -> str:
    """Auto-select performance data tier based on age of query vs configured retention."""
    if not from_ts_str:
        return "raw"
    from monctl_central.storage.models import SystemSetting
    from_dt = datetime.fromisoformat(from_ts_str.replace("Z", "+00:00"))
    age = datetime.now(tz=from_dt.tzinfo or None) - from_dt

    raw_days = 7
    hourly_days = 90

    # Check per-device override first
    if device_id:
        try:
            device = await db.get(Device, uuid.UUID(device_id))
            if device and device.retention_overrides:
                overrides = device.retention_overrides
                if "perf_raw_retention_days" in overrides:
                    raw_days = int(overrides["perf_raw_retention_days"])
                if "perf_hourly_retention_days" in overrides:
                    hourly_days = int(overrides["perf_hourly_retention_days"])
                if age.days <= raw_days:
                    return "raw"
                elif age.days <= hourly_days:
                    return "hourly"
                return "daily"
        except Exception:
            pass

    try:
        setting = await db.get(SystemSetting, "perf_raw_retention_days")
        if setting:
            raw_days = int(setting.value)
        setting = await db.get(SystemSetting, "perf_hourly_retention_days")
        if setting:
            hourly_days = int(setting.value)
    except Exception:
        pass

    if age.days <= raw_days:
        return "raw"
    elif age.days <= hourly_days:
        return "hourly"
    return "daily"


@router.get("/performance/{device_id}")
async def device_performance(
    device_id: str,
    from_ts: Optional[str] = Query(default=None),
    to_ts: Optional[str] = Query(default=None),
    component_type: Optional[str] = Query(default=None),
    component: Optional[str] = Query(default=None),
    app_id: Optional[str] = Query(default=None),
    tier: Optional[str] = Query(default=None, description="Data tier: raw, hourly, daily (omit for auto)"),
    limit: int = Query(default=5000, le=20000),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return performance metrics history for a device."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Resolve tier
    if tier and tier in _PERF_TIER_TABLE:
        selected_tier = tier
    else:
        selected_tier = await _auto_select_perf_tier(from_ts, db, device_id=device_id)

    ch = get_clickhouse()
    table = _PERF_TIER_TABLE[selected_tier]
    time_col = _PERF_TIER_TIME_COL[selected_tier]

    if selected_tier == "raw":
        # Raw tier — query performance table with array columns
        sql = f"SELECT * FROM {table} WHERE device_id = {{device_id:UUID}}"
        params: dict = {"device_id": device_id}

        if from_ts:
            sql += f" AND {time_col} >= {{from_ts:DateTime64}}"
            params["from_ts"] = from_ts.replace("Z", "").replace("+00:00", "").split("+")[0]
        if to_ts:
            sql += f" AND {time_col} <= {{to_ts:DateTime64}}"
            params["to_ts"] = to_ts.replace("Z", "").replace("+00:00", "").split("+")[0]
        if component_type:
            sql += " AND component_type = {component_type:String}"
            params["component_type"] = component_type
        if component:
            components = [c.strip() for c in component.split(",")]
            sql += " AND component IN ({components:Array(String)})"
            params["components"] = components
        if app_id:
            sql += " AND app_id = {app_id:UUID}"
            params["app_id"] = app_id

        sql += f" ORDER BY component_type, component, {time_col} DESC"
        sql += " LIMIT {limit:UInt32}"
        params["limit"] = limit

        try:
            client = ch._get_client()
            result = client.query(sql, parameters=params)
            rows = list(result.named_results())
        except Exception as exc:
            if ch._is_table_missing_error(exc):
                rows = []
            else:
                raise

        data = [_format_performance_row(r) for r in rows]
    else:
        # Rollup tier — individual metric rows, re-group into array format
        sql = (
            f"SELECT device_id, app_id, component_type, component, metric_name, metric_type,"
            f" {time_col}, val_avg, val_min, val_max, val_p95, sample_count,"
            f" device_name, app_name, tenant_id, tenant_name"
            f" FROM {table} WHERE device_id = {{device_id:UUID}}"
        )
        params = {"device_id": device_id}

        if from_ts:
            sql += f" AND {time_col} >= {{from_ts:DateTime64}}"
            params["from_ts"] = from_ts.replace("Z", "").replace("+00:00", "").split("+")[0]
        if to_ts:
            sql += f" AND {time_col} <= {{to_ts:DateTime64}}"
            params["to_ts"] = to_ts.replace("Z", "").replace("+00:00", "").split("+")[0]
        if component_type:
            sql += " AND component_type = {component_type:String}"
            params["component_type"] = component_type
        if component:
            components = [c.strip() for c in component.split(",")]
            sql += " AND component IN ({components:Array(String)})"
            params["components"] = components
        if app_id:
            sql += " AND app_id = {app_id:UUID}"
            params["app_id"] = app_id

        sql += f" ORDER BY component_type, component, {time_col} DESC"
        sql += " LIMIT {limit:UInt32}"
        params["limit"] = limit

        try:
            client = ch._get_client()
            result = client.query(sql, parameters=params)
            raw_rows = list(result.named_results())
        except Exception as exc:
            if ch._is_table_missing_error(exc):
                raw_rows = []
            else:
                raise

        # Re-group per-metric rows into array format
        grouped: dict[tuple, dict] = {}
        for row in raw_rows:
            key = (row.get("component_type", ""), row.get("component", ""), str(row.get(time_col, "")))
            if key not in grouped:
                grouped[key] = {
                    "assignment_id": "",
                    "app_id": str(row.get("app_id", "")),
                    "app_name": row.get("app_name", ""),
                    "device_id": str(row.get("device_id", "")),
                    "component_type": row.get("component_type", ""),
                    "component": row.get("component", ""),
                    "state": 0,
                    "metrics": {},
                    "metric_names": [],
                    "metric_values": [],
                    "metric_types": [],
                    "executed_at": _ensure_utc_iso(row.get(time_col)) or "",
                    "collector_name": None,
                    "sample_count": 0,
                }
            entry = grouped[key]
            mn = row.get("metric_name", "")
            entry["metric_names"].append(mn)
            entry["metric_values"].append(row.get("val_avg", 0))
            entry["metric_types"].append(row.get("metric_type", "gauge"))
            entry["metrics"][mn] = row.get("val_avg", 0)
            entry["sample_count"] = max(entry["sample_count"], row.get("sample_count", 0))

        data = list(grouped.values())

    return {
        "status": "success",
        "data": data,
        "tier": selected_tier,
        "meta": {"limit": limit, "count": len(data)},
    }
