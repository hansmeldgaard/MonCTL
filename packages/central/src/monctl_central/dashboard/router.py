"""Dashboard aggregation endpoint — single call for all dashboard widgets."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, get_clickhouse, require_auth
from monctl_central.storage.models import (
    Device, Collector, AlertDefinition, AlertEntity,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Aggregated dashboard data — one call powers all widgets."""
    tenant_ids = auth.get("tenant_ids")

    # Run DB queries sequentially (async sessions can't be shared across gather),
    # but ClickHouse-only queries can run via asyncio.to_thread in parallel within each step.
    alert_summary = await _alert_summary(db, tenant_ids)
    device_health = await _device_health(db, tenant_ids)
    collector_status = await _collector_status(db)
    perf_top_n = await _performance_top_n(tenant_ids)

    return {
        "status": "success",
        "data": {
            "alert_summary": alert_summary,
            "device_health": device_health,
            "collector_status": collector_status,
            "performance_top_n": perf_top_n,
        },
    }


# ---------------------------------------------------------------------------
# Alert Summary
# ---------------------------------------------------------------------------

async def _alert_summary(db: AsyncSession, tenant_ids: list[str] | None) -> dict:
    """Count firing alerts + list top 10 most recent firing alerts."""

    # ── Total firing count ────────────────────────────────────────────────
    count_stmt = (
        select(func.count(AlertEntity.id))
        .where(AlertEntity.state == "firing")
    )
    if tenant_ids is not None:
        if len(tenant_ids) == 0:
            return {"total_firing": 0, "recent": []}
        count_stmt = count_stmt.join(
            Device, AlertEntity.device_id == Device.id
        ).where(Device.tenant_id.in_([uuid.UUID(t) for t in tenant_ids]))

    total_firing = (await db.execute(count_stmt)).scalar() or 0

    # ── Top 10 most recently fired alerts ─────────────────────────────────
    recent_stmt = (
        select(AlertEntity)
        .where(AlertEntity.state == "firing")
        .order_by(AlertEntity.started_firing_at.desc())
        .limit(10)
    )
    if tenant_ids is not None and len(tenant_ids) > 0:
        recent_stmt = recent_stmt.join(
            Device, AlertEntity.device_id == Device.id
        ).where(Device.tenant_id.in_([uuid.UUID(t) for t in tenant_ids]))

    recent_entities = (await db.execute(recent_stmt)).scalars().all()

    recent = []
    for entity in recent_entities:
        defn = await db.get(AlertDefinition, entity.definition_id)
        device = await db.get(Device, entity.device_id) if entity.device_id else None
        recent.append({
            "id": str(entity.id),
            "definition_name": defn.name if defn else "",
            "device_name": device.name if device else "",
            "device_id": str(entity.device_id) if entity.device_id else None,
            "entity_key": entity.entity_key,
            "current_value": entity.current_value,
            "fire_count": entity.fire_count,
            "started_at": entity.started_firing_at.isoformat() if entity.started_firing_at else None,
        })

    return {
        "total_firing": total_firing,
        "recent": recent,
    }


# ---------------------------------------------------------------------------
# Device Health
# ---------------------------------------------------------------------------

async def _device_health(db: AsyncSession, tenant_ids: list[str] | None) -> dict:
    """Device up/down/degraded counts + worst 10 performers."""

    # ── Total device count ────────────────────────────────────────────────
    device_stmt = select(func.count(Device.id))
    if tenant_ids is not None:
        if len(tenant_ids) == 0:
            return {"total": 0, "up": 0, "down": 0, "degraded": 0, "worst": []}
        device_stmt = device_stmt.where(
            Device.tenant_id.in_([uuid.UUID(t) for t in tenant_ids])
        )
    total_devices = (await db.execute(device_stmt)).scalar() or 0

    # ── Get reachability from ClickHouse latest view ──────────────────────
    ch = get_clickhouse()
    try:
        reachability_rows = await asyncio.to_thread(
            ch.query_latest, table="availability_latency", tenant_id=None
        )
    except Exception:
        logger.exception("Failed to query availability_latency_latest for dashboard")
        reachability_rows = []

    # Filter by tenant if needed
    if tenant_ids is not None and len(tenant_ids) > 0:
        tid_set = set(tenant_ids)
        reachability_rows = [
            r for r in reachability_rows
            if str(r.get("tenant_id", "")) in tid_set
        ]

    # Group by device_id
    device_checks: dict[str, list[bool]] = {}
    for r in reachability_rows:
        did = str(r.get("device_id", ""))
        if did and did != "00000000-0000-0000-0000-000000000000":
            device_checks.setdefault(did, []).append(bool(r.get("reachable", 1)))

    up = 0
    down = 0
    degraded = 0
    device_scores: list[dict] = []

    for did, checks in device_checks.items():
        all_up = all(checks)
        all_down = not any(checks)
        if all_up:
            up += 1
        elif all_down:
            down += 1
            device_scores.append({"device_id": did, "reason": "down", "score": 100})
        else:
            degraded += 1
            fail_pct = round((1 - sum(checks) / len(checks)) * 100)
            device_scores.append({"device_id": did, "reason": "degraded", "score": fail_pct})

    # Devices with no checks count as up
    no_check_count = total_devices - len(device_checks)
    up += no_check_count

    # ── Worst 10 devices ──────────────────────────────────────────────────
    device_scores.sort(key=lambda x: x["score"], reverse=True)
    worst_ids = [d["device_id"] for d in device_scores[:10]]

    worst = []
    if worst_ids:
        devices_by_id = {}
        for did in worst_ids:
            try:
                device = await db.get(Device, uuid.UUID(did))
                if device:
                    devices_by_id[did] = device
            except Exception:
                pass

        # Count firing alerts per device
        alert_count_stmt = (
            select(AlertEntity.device_id, func.count(AlertEntity.id))
            .where(
                AlertEntity.state == "firing",
                AlertEntity.device_id.in_([uuid.UUID(d) for d in worst_ids]),
            )
            .group_by(AlertEntity.device_id)
        )
        alert_counts = dict(
            (str(row[0]), row[1])
            for row in (await db.execute(alert_count_stmt)).all()
        )

        for score_entry in device_scores[:10]:
            did = score_entry["device_id"]
            device = devices_by_id.get(did)
            if device:
                worst.append({
                    "device_id": did,
                    "device_name": device.name,
                    "device_address": device.address,
                    "reason": score_entry["reason"],
                    "firing_alerts": alert_counts.get(did, 0),
                })

    return {
        "total": total_devices,
        "up": up,
        "down": down,
        "degraded": degraded,
        "worst": worst,
    }


# ---------------------------------------------------------------------------
# Collector Fleet Status
# ---------------------------------------------------------------------------

async def _collector_status(db: AsyncSession) -> dict:
    """Collector fleet overview: online/offline/pending counts, stale collectors."""

    collectors = (await db.execute(select(Collector))).scalars().all()

    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(minutes=5)

    online = 0
    offline = 0
    pending = 0
    stale: list[dict] = []

    for c in collectors:
        if c.status == "PENDING":
            pending += 1
        elif c.status == "ACTIVE":
            if c.last_seen_at and c.last_seen_at < stale_threshold:
                offline += 1
                stale.append({
                    "collector_id": str(c.id),
                    "name": c.name,
                    "last_seen": c.last_seen_at.isoformat() if c.last_seen_at else None,
                    "stale_seconds": int((now - c.last_seen_at).total_seconds()),
                })
            else:
                online += 1
        else:
            offline += 1

    stale.sort(key=lambda x: x.get("stale_seconds", 0) or 0, reverse=True)

    return {
        "total": len(collectors),
        "online": online,
        "offline": offline,
        "pending": pending,
        "stale": stale[:10],
    }


# ---------------------------------------------------------------------------
# Performance Top-N
# ---------------------------------------------------------------------------

async def _performance_top_n(tenant_ids: list[str] | None) -> dict:
    """Top 10 devices by CPU, memory, and interface bandwidth from ClickHouse."""
    ch = get_clickhouse()
    result: dict[str, list] = {"cpu": [], "memory": [], "bandwidth": []}

    tenant_filter = ""
    if tenant_ids and len(tenant_ids) == 1:
        tid = tenant_ids[0].replace("'", "")
        tenant_filter = f" AND tenant_id = toUUID('{tid}')"

    # ── Top CPU utilization ───────────────────────────────────────────────
    try:
        cpu_sql = f"""
            SELECT
                device_id,
                device_name,
                component,
                metric_values[indexOf(metric_names, 'utilization_pct')] AS cpu_pct,
                executed_at
            FROM performance_latest FINAL
            WHERE component_type = 'cpu'
              AND has(metric_names, 'utilization_pct')
              AND device_id != toUUID('00000000-0000-0000-0000-000000000000')
              {tenant_filter}
            ORDER BY cpu_pct DESC
            LIMIT 20
        """
        cpu_rows = await asyncio.to_thread(lambda: ch._get_client().query(cpu_sql))

        seen_devices: set[str] = set()
        for row in cpu_rows.result_set:
            did = str(row[0])
            if did not in seen_devices:
                seen_devices.add(did)
                result["cpu"].append({
                    "device_id": did,
                    "device_name": row[1],
                    "component": row[2],
                    "value": round(float(row[3]), 1),
                    "unit": "%",
                    "executed_at": row[4].isoformat() if row[4] else None,
                })
            if len(result["cpu"]) >= 10:
                break
    except Exception:
        logger.exception("Failed to query CPU top-n for dashboard")

    # ── Top memory utilization ────────────────────────────────────────────
    try:
        mem_sql = f"""
            SELECT
                device_id,
                device_name,
                metric_values[indexOf(metric_names, 'utilization_pct')] AS mem_pct,
                executed_at
            FROM performance_latest FINAL
            WHERE component_type = 'memory'
              AND has(metric_names, 'utilization_pct')
              AND device_id != toUUID('00000000-0000-0000-0000-000000000000')
              {tenant_filter}
            ORDER BY mem_pct DESC
            LIMIT 10
        """
        mem_rows = await asyncio.to_thread(lambda: ch._get_client().query(mem_sql))
        for row in mem_rows.result_set:
            result["memory"].append({
                "device_id": str(row[0]),
                "device_name": row[1],
                "value": round(float(row[2]), 1),
                "unit": "%",
                "executed_at": row[3].isoformat() if row[3] else None,
            })
    except Exception:
        logger.exception("Failed to query memory top-n for dashboard")

    # ── Top bandwidth utilization ─────────────────────────────────────────
    try:
        bw_sql = f"""
            SELECT
                device_id,
                device_name,
                if_name,
                greatest(in_utilization_pct, out_utilization_pct) AS max_util,
                in_rate_bps,
                out_rate_bps,
                if_speed_mbps,
                executed_at
            FROM interface_latest FINAL
            WHERE device_id != toUUID('00000000-0000-0000-0000-000000000000')
              AND if_speed_mbps > 0
              {tenant_filter}
            ORDER BY max_util DESC
            LIMIT 10
        """
        bw_rows = await asyncio.to_thread(lambda: ch._get_client().query(bw_sql))
        for row in bw_rows.result_set:
            result["bandwidth"].append({
                "device_id": str(row[0]),
                "device_name": row[1],
                "interface": row[2],
                "value": round(float(row[3]), 1),
                "unit": "%",
                "in_rate_bps": row[4],
                "out_rate_bps": row[5],
                "speed_mbps": row[6],
                "executed_at": row[7].isoformat() if row[7] else None,
            })
    except Exception:
        logger.exception("Failed to query bandwidth top-n for dashboard")

    return result
