"""System health check endpoint — concurrent subsystem checks."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.config import settings
from monctl_central.dependencies import get_clickhouse, get_engine, get_session_factory, require_admin
from monctl_central.storage.models import Collector

logger = logging.getLogger(__name__)

router = APIRouter()

_TABLES = ["availability_latency", "performance", "interface", "config"]
_CHECK_TIMEOUT = 5.0  # seconds per subsystem check


async def _check_postgresql(db: AsyncSession) -> dict:
    """Check PostgreSQL connectivity and pool status."""
    t0 = time.monotonic()
    await db.execute(text("SELECT 1"))
    latency_ms = round((time.monotonic() - t0) * 1000, 2)

    engine = get_engine()
    pool = engine.pool
    pool_status = pool.status()
    pool_size = pool.size()
    checked_out = pool.checkedout()
    overflow = pool.overflow()

    if latency_ms > 500 or overflow > 5:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "latency_ms": latency_ms,
        "details": {
            "pool_size": pool_size,
            "checked_out": checked_out,
            "overflow": overflow,
            "pool_status": pool_status,
        },
    }


async def _check_clickhouse() -> dict:
    """Check ClickHouse connectivity, row counts, and data freshness."""
    ch = get_clickhouse()

    def _run():
        t0 = time.monotonic()
        client = ch._get_client()
        client.query("SELECT 1")
        latency_ms = round((time.monotonic() - t0) * 1000, 2)

        tables = {}
        for table in _TABLES:
            try:
                count_result = client.query(f"SELECT count() FROM {table}")
                row_count = count_result.first_row[0] if count_result.result_rows else 0
                latest_result = client.query(
                    f"SELECT max(received_at) FROM {table}"
                )
                latest_val = latest_result.first_row[0] if latest_result.result_rows else None
                tables[table] = {
                    "rows": row_count,
                    "latest_received_at": latest_val.isoformat() if latest_val else None,
                }
            except Exception:
                tables[table] = {"rows": 0, "latest_received_at": None}

        return latency_ms, tables

    latency_ms, tables = await asyncio.to_thread(_run)

    # Check data freshness — if any table with data hasn't received in >10 min → degraded
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    status = "healthy"
    for info in tables.values():
        if info["rows"] > 0 and info["latest_received_at"]:
            try:
                from datetime import datetime as dt
                latest = dt.fromisoformat(info["latest_received_at"])
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=timezone.utc)
                age = now - latest
                if age > timedelta(minutes=10):
                    status = "degraded"
                elif age > timedelta(minutes=5) and status == "healthy":
                    pass  # still healthy, just informational
            except Exception:
                pass

    return {
        "status": status,
        "latency_ms": latency_ms,
        "details": {"tables": tables},
    }


async def _check_redis() -> dict:
    """Check Redis connectivity and read scheduler leader key."""
    from monctl_central.cache import _redis

    if _redis is None:
        return {
            "status": "critical",
            "latency_ms": None,
            "details": {"error": "Redis not connected"},
        }

    t0 = time.monotonic()
    await _redis.ping()
    latency_ms = round((time.monotonic() - t0) * 1000, 2)

    db_size = await _redis.dbsize()
    leader = await _redis.get("monctl:scheduler:leader")

    return {
        "status": "healthy",
        "latency_ms": latency_ms,
        "details": {
            "leader_instance": leader,
            "db_size": db_size,
        },
    }


async def _check_collectors(db: AsyncSession) -> dict:
    """Check collector status distribution and load metrics."""
    rows = (
        await db.execute(
            select(Collector.status, func.count(Collector.id)).group_by(Collector.status)
        )
    ).all()

    by_status = {row[0]: row[1] for row in rows}
    total = sum(by_status.values())

    # Load metrics for ACTIVE collectors
    active_collectors = (
        await db.execute(
            select(Collector).where(Collector.status == "ACTIVE")
        )
    ).scalars().all()

    total_jobs = sum(c.total_jobs for c in active_collectors)
    avg_load = (
        round(sum(c.effective_load for c in active_collectors) / len(active_collectors), 3)
        if active_collectors
        else 0
    )
    avg_miss_rate = (
        round(sum(c.deadline_miss_rate for c in active_collectors) / len(active_collectors), 3)
        if active_collectors
        else 0
    )

    active_count = by_status.get("ACTIVE", 0)
    if total == 0:
        status = "critical"
    elif active_count == 0:
        status = "critical"
    elif active_count < total:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "latency_ms": None,
        "details": {
            "by_status": by_status,
            "total_jobs": total_jobs,
            "avg_load": avg_load,
            "avg_deadline_miss_rate": avg_miss_rate,
        },
    }


async def _check_scheduler() -> dict:
    """Check scheduler leader election status."""
    from monctl_central.cache import _redis

    if _redis is None:
        return {
            "status": "critical",
            "latency_ms": None,
            "details": {"error": "Redis not connected"},
        }

    leader = await _redis.get("monctl:scheduler:leader")
    ttl = await _redis.ttl("monctl:scheduler:leader")

    if leader is None:
        status = "critical"
    elif ttl < 10:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "latency_ms": None,
        "details": {
            "current_leader": leader,
            "is_this_instance": leader == settings.instance_id if leader else False,
            "leader_key_ttl": ttl,
        },
    }


async def _run_check(name: str, coro) -> tuple[str, dict]:
    """Run a single subsystem check with timeout."""
    try:
        result = await asyncio.wait_for(coro, timeout=_CHECK_TIMEOUT)
        return name, result
    except asyncio.TimeoutError:
        return name, {
            "status": "critical",
            "latency_ms": None,
            "details": {"error": "Check timed out"},
        }
    except Exception as exc:
        logger.exception("health_check_failed subsystem=%s", name)
        return name, {
            "status": "critical",
            "latency_ms": None,
            "details": {"error": str(exc)},
        }


async def _check_collectors_standalone() -> dict:
    """Run collectors check with its own DB session."""
    factory = get_session_factory()
    async with factory() as db:
        return await _check_collectors(db)


async def _check_postgresql_standalone() -> dict:
    """Run PostgreSQL check with its own DB session."""
    factory = get_session_factory()
    async with factory() as db:
        return await _check_postgresql(db)


@router.get("/health")
async def system_health(
    auth: dict = Depends(require_admin),
):
    """Comprehensive system health check across all subsystems."""
    results = await asyncio.gather(
        _run_check("postgresql", _check_postgresql_standalone()),
        _run_check("clickhouse", _check_clickhouse()),
        _run_check("redis", _check_redis()),
        _run_check("collectors", _check_collectors_standalone()),
        _run_check("scheduler", _check_scheduler()),
        return_exceptions=True,
    )

    subsystems = {}
    for item in results:
        if isinstance(item, Exception):
            continue
        name, data = item
        subsystems[name] = data

    # Overall status = worst of all
    priority = {"critical": 2, "degraded": 1, "healthy": 0, "unknown": -1}
    worst = max(
        (s.get("status", "unknown") for s in subsystems.values()),
        key=lambda s: priority.get(s, -1),
        default="unknown",
    )

    from monctl_common.utils import utc_now

    return {
        "status": "success",
        "data": {
            "overall_status": worst,
            "instance_id": settings.instance_id,
            "version": "0.1.0",
            "checked_at": utc_now().isoformat(),
            "subsystems": subsystems,
        },
    }
