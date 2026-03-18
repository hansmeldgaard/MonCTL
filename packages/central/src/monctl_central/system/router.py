"""System health check endpoint — concurrent subsystem checks."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import sys
import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.config import settings
from monctl_central.dependencies import (
    get_clickhouse,
    get_engine,
    get_session_factory,
    require_admin,
)
from monctl_central.storage.models import (
    AlertInstance,
    AppAlertDefinition,
    Collector,
    CollectorGroup,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_TABLES = ["availability_latency", "performance", "interface", "config"]
_CHECK_TIMEOUT = 5.0  # seconds per subsystem check
_STARTED_AT = time.time()


async def _check_central() -> dict:
    """Process info for this central instance."""
    import resource

    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = round(rss_kb / 1024, 1)  # Linux reports KB
    uptime_seconds = round(time.time() - _STARTED_AT, 1)

    return {
        "status": "healthy",
        "latency_ms": None,
        "details": {
            "role": "central",
            "instance_id": settings.instance_id,
            "python_version": platform.python_version(),
            "pid": os.getpid(),
            "uptime_seconds": uptime_seconds,
            "rss_mb": rss_mb,
            "debug": settings.debug,
        },
    }


async def _check_postgresql(db: AsyncSession) -> dict:
    """Check PostgreSQL connectivity, pool status, version, and table counts."""
    t0 = time.monotonic()
    await db.execute(text("SELECT 1"))
    latency_ms = round((time.monotonic() - t0) * 1000, 2)

    engine = get_engine()
    pool = engine.pool
    pool_status = pool.status()
    pool_size = pool.size()
    checked_out = pool.checkedout()
    overflow = pool.overflow()

    # Version
    ver_row = (await db.execute(text("SELECT version()"))).scalar()

    # Database size
    db_size_row = (
        await db.execute(text("SELECT pg_database_size(current_database())"))
    ).scalar()

    # Active connections
    active_conns = (
        await db.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE state = 'active'"
            )
        )
    ).scalar()

    # Table counts for key tables
    key_tables = [
        "devices", "collectors", "apps", "app_assignments",
        "app_alert_definitions", "alert_instances", "credentials", "tenants", "users",
    ]
    table_counts = {}
    for tbl in key_tables:
        try:
            cnt = (
                await db.execute(text(f"SELECT count(*) FROM {tbl}"))  # noqa: S608
            ).scalar()
            table_counts[tbl] = cnt
        except Exception:
            table_counts[tbl] = None

    if latency_ms > 500 or overflow > 5:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "latency_ms": latency_ms,
        "details": {
            "version": ver_row,
            "db_size_bytes": db_size_row,
            "active_connections": active_conns,
            "pool_size": pool_size,
            "checked_out": checked_out,
            "overflow": overflow,
            "pool_status": pool_status,
            "table_counts": table_counts,
        },
    }


async def _check_clickhouse() -> dict:
    """Check ClickHouse connectivity, row counts, data freshness, and internals."""
    ch = get_clickhouse()

    def _run():  # noqa: C901
        t0 = time.monotonic()
        client = ch._get_client()
        client.query("SELECT 1")
        latency_ms = round((time.monotonic() - t0) * 1000, 2)

        # --- basic table stats ---
        tables = {}
        for table in _TABLES:
            try:
                count_result = client.query(f"SELECT count() FROM {table}")
                row_count = (
                    count_result.first_row[0] if count_result.result_rows else 0
                )
                latest_result = client.query(
                    f"SELECT max(received_at) FROM {table}"
                )
                latest_val = (
                    latest_result.first_row[0]
                    if latest_result.result_rows
                    else None
                )
                # Empty tables return epoch (1970-01-01) for max() — treat as None
                if row_count == 0:
                    latest_val = None
                tables[table] = {
                    "rows": row_count,
                    "bytes": 0,
                    "parts": 0,
                    "latest_received_at": (
                        latest_val.isoformat() if latest_val else None
                    ),
                }
            except Exception:
                tables[table] = {"rows": 0, "bytes": 0, "parts": 0, "latest_received_at": None}

        # --- version & uptime ---
        version = None
        uptime_seconds = None
        try:
            r = client.query("SELECT version()")
            version = r.first_row[0] if r.result_rows else None
        except Exception:
            pass
        try:
            r = client.query("SELECT uptime()")
            uptime_seconds = r.first_row[0] if r.result_rows else None
        except Exception:
            pass

        # --- per-table bytes + parts from system.parts ---
        table_storage = {}
        total_bytes = 0
        total_rows_all = 0
        try:
            r = client.query(
                "SELECT table, sum(bytes_on_disk) AS bytes,"
                " sum(rows) AS rows, count() AS parts"
                " FROM system.parts"
                " WHERE active AND database = currentDatabase()"
                " GROUP BY table"
                " SETTINGS max_memory_usage = 500000000"
            )
            for row in r.named_results():
                table_storage[row["table"]] = {
                    "bytes": row["bytes"],
                    "rows": row["rows"],
                    "parts": row["parts"],
                }
                total_bytes += row["bytes"]
                total_rows_all += row["rows"]
        except Exception:
            pass

        # Merge bytes/parts into the tables dict
        for tbl_name, storage in table_storage.items():
            if tbl_name in tables:
                tables[tbl_name]["bytes"] = storage.get("bytes", 0)
                tables[tbl_name]["parts"] = storage.get("parts", 0)

        # --- pk_memory_bytes ---
        pk_memory_bytes = 0
        try:
            r = client.query(
                "SELECT sum(primary_key_bytes_in_memory) AS pk_mem"
                " FROM system.parts WHERE active AND database = currentDatabase()"
            )
            pk_memory_bytes = r.first_row[0] if r.result_rows else 0
        except Exception:
            pass

        # --- cluster topology ---
        cluster_topology = []
        cluster_name = ch._cluster_name
        try:
            r = client.query(
                "SELECT host_name, port, is_local"
                " FROM system.clusters WHERE cluster = {cluster:String}",
                parameters={"cluster": cluster_name},
            )
            for row in r.named_results():
                cluster_topology.append({
                    "host_name": row["host_name"],
                    "port": row["port"],
                    "is_local": row["is_local"],
                })
        except Exception:
            pass

        # --- replication status ---
        replication = {}
        try:
            r = client.query(
                "SELECT database, table, is_readonly, is_session_expired,"
                " future_parts, parts_to_check, inserts_in_queue,"
                " merges_in_queue, queue_size, log_pointer,"
                " total_replicas, active_replicas,"
                " absolute_delay"
                " FROM system.replicas"
                " WHERE database = currentDatabase()"
            )
            for row in r.named_results():
                replication[row["table"]] = {
                    "is_readonly": row["is_readonly"],
                    "is_session_expired": row["is_session_expired"],
                    "queue_size": row["queue_size"],
                    "total_replicas": row["total_replicas"],
                    "active_replicas": row["active_replicas"],
                    "absolute_delay": row["absolute_delay"],
                }
        except Exception:
            pass

        # --- merge activity ---
        merges = {}
        try:
            r = client.query(
                "SELECT count() AS cnt,"
                " max(elapsed) AS longest_seconds,"
                " sum(total_size_bytes_compressed) AS total_bytes"
                " FROM system.merges"
            )
            if r.result_rows:
                merges = {
                    "active_count": r.first_row[0],
                    "longest_seconds": round(r.first_row[1], 1) if r.first_row[1] else 0,
                    "total_bytes_merging": r.first_row[2],
                }
        except Exception:
            pass

        # --- mutations ---
        mutations = {}
        try:
            r = client.query(
                "SELECT count() AS total,"
                " countIf(is_done = 0) AS pending,"
                " countIf(latest_fail_reason != '') AS failed"
                " FROM system.mutations"
                " WHERE database = currentDatabase()"
            )
            if r.result_rows:
                mutations = {
                    "total": r.first_row[0],
                    "pending": r.first_row[1],
                    "failed": r.first_row[2],
                }
        except Exception:
            pass

        # --- Keeper health ---
        keeper_ok = None
        try:
            r = client.query(
                "SELECT count() FROM system.zookeeper WHERE path = '/'"
            )
            keeper_ok = True
        except Exception:
            keeper_ok = False

        # --- slow queries (last hour, > 5s) ---
        slow_queries = 0
        try:
            r = client.query(
                "SELECT count() FROM system.query_log"
                " WHERE event_time > now() - INTERVAL 1 HOUR"
                " AND query_duration_ms > 5000"
                " AND type = 'QueryFinish'"
                " SETTINGS max_memory_usage = 500000000"
            )
            slow_queries = r.first_row[0] if r.result_rows else 0
        except Exception:
            pass

        # --- recent errors ---
        recent_errors = []
        try:
            r = client.query(
                "SELECT name, value, last_error_time, last_error_message"
                " FROM system.errors"
                " ORDER BY last_error_time DESC LIMIT 10"
                " SETTINGS max_memory_usage = 500000000"
            )
            for row in r.named_results():
                recent_errors.append({
                    "name": row["name"],
                    "count": row["value"],
                    "last_time": str(row["last_error_time"]),
                    "message": row.get("last_error_message"),
                })
        except Exception:
            pass

        # --- server resources ---
        disks = []
        try:
            r = client.query(
                "SELECT name, path, free_space, total_space"
                " FROM system.disks"
            )
            for row in r.named_results():
                disks.append({
                    "name": row["name"],
                    "path": row["path"],
                    "free_space": row["free_space"],
                    "total_space": row["total_space"],
                })
        except Exception:
            pass

        async_metrics = {}
        try:
            r = client.query(
                "SELECT metric, value FROM system.asynchronous_metrics"
                " WHERE metric IN ("
                "'OSMemoryTotal', 'OSMemoryFreeWithoutCached',"
                " 'LoadAverage1', 'LoadAverage5', 'LoadAverage15',"
                " 'OSCPUUser', 'OSCPUSystem')"
            )
            for row in r.named_results():
                async_metrics[row["metric"]] = row["value"]
        except Exception:
            pass

        return (
            latency_ms, tables, version, uptime_seconds,
            table_storage, total_bytes, total_rows_all, pk_memory_bytes,
            cluster_topology, replication, merges, mutations,
            keeper_ok, slow_queries, recent_errors, disks, async_metrics,
        )

    (
        latency_ms, tables, version, uptime_seconds,
        table_storage, total_bytes, total_rows_all, pk_memory_bytes,
        cluster_topology, replication, merges, mutations,
        keeper_ok, slow_queries, recent_errors, disks, async_metrics,
    ) = await asyncio.to_thread(_run)

    # --- Data freshness check (existing logic) ---
    from datetime import datetime, timedelta, timezone as tz

    now = datetime.now(tz.utc)
    status = "healthy"
    for info in tables.values():
        if info["rows"] > 0 and info["latest_received_at"]:
            try:
                latest = datetime.fromisoformat(info["latest_received_at"])
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=tz.utc)
                age = now - latest
                if age > timedelta(minutes=10):
                    status = "degraded"
            except Exception:
                pass

    # --- Replication status checks ---
    for tbl, rep in replication.items():
        if rep.get("is_readonly") or rep.get("is_session_expired"):
            status = "critical"
            break
        if rep.get("active_replicas", 0) < rep.get("total_replicas", 0):
            if status != "critical":
                status = "degraded"
        if rep.get("queue_size", 0) > 100:
            if status != "critical":
                status = "degraded"
        if rep.get("absolute_delay", 0) > 300:
            if status != "critical":
                status = "degraded"

    # --- Failed mutations ---
    if mutations.get("failed", 0) > 0 and status != "critical":
        status = "degraded"

    # --- Disk usage ---
    for d in disks:
        total = d.get("total_space", 0)
        free = d.get("free_space", 0)
        if total > 0:
            used_pct = ((total - free) / total) * 100
            if used_pct > 95:
                status = "critical"
            elif used_pct > 90 and status != "critical":
                status = "degraded"

    return {
        "status": status,
        "latency_ms": latency_ms,
        "details": {
            "version": version,
            "uptime_seconds": uptime_seconds,
            "tables": tables,
            "table_storage": table_storage,
            "total_bytes": total_bytes,
            "total_rows": total_rows_all,
            "pk_memory_bytes": pk_memory_bytes,
            "cluster_topology": cluster_topology,
            "replication": replication,
            "merges": merges,
            "mutations": mutations,
            "keeper_ok": keeper_ok,
            "slow_queries_last_hour": slow_queries,
            "recent_errors": recent_errors,
            "disks": disks,
            "async_metrics": async_metrics,
        },
    }


async def _check_ingestion() -> dict:
    """Query ClickHouse for rows received in the last 5 minutes per table."""
    ch = get_clickhouse()

    def _run():
        client = ch._get_client()
        per_table = {}
        total_rows = 0
        for table in _TABLES:
            try:
                r = client.query(
                    f"SELECT count() FROM {table}"
                    " WHERE received_at >= now() - INTERVAL 5 MINUTE"
                )
                cnt = r.first_row[0] if r.result_rows else 0
                per_table[table] = {
                    "rows_5min": cnt,
                    "rows_per_sec": round(cnt / 300, 2),
                }
                total_rows += cnt
            except Exception:
                per_table[table] = {"rows_5min": 0, "rows_per_sec": 0}
        return per_table, total_rows

    per_table, total_rows = await asyncio.to_thread(_run)

    # Status: 0 rows in 5 min is degraded (will be refined in post-processing)
    if total_rows == 0:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "latency_ms": None,
        "details": {
            "tables": per_table,
            "total_rows_5min": total_rows,
            "total_rows_per_sec": round(total_rows / 300, 2),
        },
    }


async def _check_redis() -> dict:
    """Check Redis connectivity, version, memory, clients, and key stats."""
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

    # Version
    version = None
    try:
        info_server = await _redis.info("server")
        version = info_server.get("redis_version")
    except Exception:
        pass

    # Memory
    memory_stats = {}
    try:
        info_mem = await _redis.info("memory")
        memory_stats = {
            "used_memory": info_mem.get("used_memory"),
            "used_memory_human": info_mem.get("used_memory_human"),
            "used_memory_peak": info_mem.get("used_memory_peak"),
            "used_memory_peak_human": info_mem.get("used_memory_peak_human"),
            "mem_fragmentation_ratio": info_mem.get("mem_fragmentation_ratio"),
        }
    except Exception:
        pass

    # Clients
    connected_clients = None
    try:
        info_clients = await _redis.info("clients")
        connected_clients = info_clients.get("connected_clients")
    except Exception:
        pass

    # Key stats by prefix (sampled)
    key_stats = {}
    try:
        prefixes: dict[str, int] = {}
        count = 0
        async for key in _redis.scan_iter(match="monctl:*", count=500):
            if isinstance(key, bytes):
                key = key.decode()
            parts = key.split(":")
            prefix = ":".join(parts[:2]) if len(parts) >= 2 else key
            prefixes[prefix] = prefixes.get(prefix, 0) + 1
            count += 1
            if count >= 2000:
                break
        key_stats = prefixes
    except Exception:
        pass

    return {
        "status": "healthy",
        "latency_ms": latency_ms,
        "details": {
            "version": version,
            "leader_instance": leader,
            "db_size": db_size,
            "connected_clients": connected_clients,
            "memory": memory_stats,
            "key_stats": key_stats,
        },
    }


async def _check_collectors(db: AsyncSession) -> dict:
    """Check collector status distribution and per-collector detail."""
    rows = (
        await db.execute(
            select(Collector.status, func.count(Collector.id)).group_by(
                Collector.status
            )
        )
    ).all()

    by_status = {row[0]: row[1] for row in rows}
    total = sum(by_status.values())

    # Load all collectors with group info
    all_collectors = (
        await db.execute(select(Collector))
    ).scalars().all()

    # Build group name lookup
    group_ids = {c.group_id for c in all_collectors if c.group_id}
    group_names: dict[str, str] = {}
    if group_ids:
        groups = (
            await db.execute(
                select(CollectorGroup).where(CollectorGroup.id.in_(group_ids))
            )
        ).scalars().all()
        group_names = {str(g.id): g.name for g in groups}

    # Per-collector detail
    collector_list = []
    for c in all_collectors:
        peer_states = c.reported_peer_states or {}
        entry = {
            "id": str(c.id),
            "name": c.name,
            "hostname": c.hostname,
            "status": c.status,
            "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
            "total_jobs": c.total_jobs,
            "worker_count": c.worker_count,
            "load_score": c.load_score,
            "effective_load": c.effective_load,
            "deadline_miss_rate": c.deadline_miss_rate,
            "group_name": (
                group_names.get(str(c.group_id)) if c.group_id else None
            ),
            "ip_addresses": c.ip_addresses,
            "labels": c.labels,
            "container_states": peer_states.get("_container_states"),
            "queue_stats": peer_states.get("_queue_stats"),
        }
        collector_list.append(entry)

    active_collectors = [c for c in all_collectors if c.status == "ACTIVE"]
    total_jobs = sum(c.total_jobs for c in active_collectors)
    avg_load = (
        round(
            sum(c.effective_load for c in active_collectors)
            / len(active_collectors),
            3,
        )
        if active_collectors
        else 0
    )
    avg_miss_rate = (
        round(
            sum(c.deadline_miss_rate for c in active_collectors)
            / len(active_collectors),
            3,
        )
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
            "collectors": collector_list,
        },
    }


async def _check_scheduler() -> dict:
    """Check scheduler leader election status and last-run timestamps."""
    from monctl_central.cache import _redis

    if _redis is None:
        return {
            "status": "critical",
            "latency_ms": None,
            "details": {"error": "Redis not connected"},
        }

    leader = await _redis.get("monctl:scheduler:leader")
    ttl = await _redis.ttl("monctl:scheduler:leader")

    # Read last-run timestamps for each task
    task_keys = {
        "health_check": "monctl:scheduler:last_health_check",
        "evaluate_alerts": "monctl:scheduler:last_evaluate_alerts",
        "hourly_rollup": "monctl:scheduler:last_hourly_rollup",
        "daily_rollup": "monctl:scheduler:last_daily_rollup",
        "retention_cleanup": "monctl:scheduler:last_retention_cleanup",
    }
    last_runs: dict[str, str | None] = {}
    for name, key in task_keys.items():
        val = await _redis.get(key)
        last_runs[name] = val if val else None

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
            "is_this_instance": (
                leader == settings.instance_id if leader else False
            ),
            "leader_key_ttl": ttl,
            "last_runs": last_runs,
        },
    }


async def _check_alerts(db: AsyncSession) -> dict:
    """Count firing alerts by severity and rule stats."""
    # Total / enabled definitions
    total_rules = (
        await db.execute(select(func.count(AppAlertDefinition.id)))
    ).scalar() or 0
    enabled_rules = (
        await db.execute(
            select(func.count(AppAlertDefinition.id)).where(AppAlertDefinition.enabled.is_(True))
        )
    ).scalar() or 0

    # Firing instances grouped by severity
    firing_rows = (
        await db.execute(
            select(AppAlertDefinition.severity, func.count(AlertInstance.id))
            .join(AlertInstance, AlertInstance.definition_id == AppAlertDefinition.id)
            .where(AlertInstance.state == "firing")
            .group_by(AppAlertDefinition.severity)
        )
    ).all()
    firing_by_severity = {row[0]: row[1] for row in firing_rows}
    total_firing = sum(firing_by_severity.values())

    if total_firing > 0:
        if firing_by_severity.get("critical", 0) > 0:
            status = "critical"
        else:
            status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "latency_ms": None,
        "details": {
            "total_rules": total_rules,
            "enabled_rules": enabled_rules,
            "total_firing": total_firing,
            "firing_by_severity": firing_by_severity,
        },
    }


def _fetch_collector_docker_stats_from_ch() -> list[dict]:
    """Read latest Docker container stats from ClickHouse performance table."""
    from collections import defaultdict

    ch = get_clickhouse()
    try:
        client = ch._get_client()
        r = client.query(
            "SELECT collector_name, component, metric_names, metric_values"
            " FROM performance_latest FINAL"
            " WHERE component_type = 'docker_container'"
            " ORDER BY collector_name, component"
            " SETTINGS max_memory_usage = 500000000"
        )
    except Exception:
        logger.warning("docker_ch_query_failed", exc_info=True)
        return []

    by_collector: dict[str, list[dict]] = defaultdict(list)
    for row in r.named_results():
        collector = row["collector_name"] or "unknown"
        names = row.get("metric_names", [])
        values = row.get("metric_values", [])
        md = dict(zip(names, values)) if names and values else {}
        by_collector[collector].append({
            "name": row["component"],
            "status": "running" if md.get("running", 0) == 1.0 else "stopped",
            "health": "healthy" if md.get("health", -1) == 1.0 else "unhealthy" if md.get("health", -1) == 0.0 else None,
            "cpu_pct": md.get("cpu_pct"),
            "mem_usage_bytes": int(md["mem_usage_bytes"]) if "mem_usage_bytes" in md else None,
            "mem_limit_bytes": int(md["mem_limit_bytes"]) if "mem_limit_bytes" in md else None,
            "mem_pct": md.get("mem_pct"),
            "net_rx_bytes": int(md["net_rx_bytes"]) if "net_rx_bytes" in md else None,
            "net_tx_bytes": int(md["net_tx_bytes"]) if "net_tx_bytes" in md else None,
            "restart_count": int(md.get("restart_count", 0)),
        })

    results = []
    for cname, containers in by_collector.items():
        results.append({
            "label": cname,
            "status": "ok",
            "source": "collector",
            "data": {
                "hostname": cname,
                "container_count": len([c for c in containers if c["status"] == "running"]),
                "total_containers": len(containers),
                "host": None,
                "containers": containers,
            },
        })
    return results


async def _check_docker_infrastructure() -> dict:
    """Query central sidecars + read collector data from ClickHouse."""
    import httpx

    raw = settings.docker_stats_hosts
    sidecar_hosts = []
    if raw:
        for entry in raw.split(","):
            parts = entry.strip().split(":")
            if len(parts) == 3:
                sidecar_hosts.append({"label": parts[0], "url": f"http://{parts[1]}:{parts[2]}/stats"})

    t0 = time.monotonic()

    # Central tier: query sidecars (20s timeout — docker stats API is slow)
    async def _fetch(client: httpx.AsyncClient, host: dict) -> dict:
        try:
            resp = await client.get(host["url"], timeout=20.0)
            resp.raise_for_status()
            return {"label": host["label"], "status": "ok", "source": "sidecar", "data": resp.json()}
        except Exception as exc:
            return {"label": host["label"], "status": "unreachable", "source": "sidecar", "data": None, "error": str(exc)}

    sidecar_results: list[dict] = []
    if sidecar_hosts:
        async with httpx.AsyncClient() as client:
            sidecar_results = list(await asyncio.gather(
                *[_fetch(client, h) for h in sidecar_hosts]
            ))

    # Worker tier: read from ClickHouse
    collector_results = await asyncio.to_thread(_fetch_collector_docker_stats_from_ch)

    latency_ms = round((time.monotonic() - t0) * 1000, 2)

    all_hosts = sidecar_results + collector_results

    if not all_hosts:
        return {
            "status": "healthy",
            "latency_ms": None,
            "details": {"configured": False, "hosts": []},
        }

    reachable = sum(1 for r in all_hosts if r["status"] == "ok")
    total = len(all_hosts)

    status = "healthy"
    if reachable < total:
        status = "degraded" if reachable > 0 else "critical"

    for host in all_hosts:
        if host.get("data"):
            for c in host["data"].get("containers", []):
                if c.get("health") == "unhealthy" and status == "healthy":
                    status = "degraded"
                if c.get("status") == "restarting" and status == "healthy":
                    status = "degraded"

    return {
        "status": status,
        "latency_ms": latency_ms,
        "details": {
            "configured": True,
            "reachable_hosts": reachable,
            "total_hosts": total,
            "hosts": all_hosts,
        },
    }


_DOCKER_CHECK_TIMEOUT = 30.0  # Docker stats API is slow (2s per container)


async def _run_check(name: str, coro, timeout: float | None = None) -> tuple[str, dict]:
    """Run a single subsystem check with timeout."""
    try:
        result = await asyncio.wait_for(coro, timeout=timeout or _CHECK_TIMEOUT)
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


async def _check_alerts_standalone() -> dict:
    """Run alerts check with its own DB session."""
    factory = get_session_factory()
    async with factory() as db:
        return await _check_alerts(db)


@router.get("/health")
async def system_health(
    auth: dict = Depends(require_admin),
):
    """Comprehensive system health check across all subsystems."""
    results = await asyncio.gather(
        _run_check("central", _check_central()),
        _run_check("postgresql", _check_postgresql_standalone()),
        _run_check("clickhouse", _check_clickhouse()),
        _run_check("redis", _check_redis()),
        _run_check("collectors", _check_collectors_standalone()),
        _run_check("scheduler", _check_scheduler()),
        _run_check("ingestion", _check_ingestion()),
        _run_check("alerts", _check_alerts_standalone()),
        _run_check("docker", _check_docker_infrastructure(), timeout=_DOCKER_CHECK_TIMEOUT),
        return_exceptions=True,
    )

    subsystems = {}
    for item in results:
        if isinstance(item, Exception):
            continue
        name, data = item
        subsystems[name] = data

    # Post-processing: if 0 ingestion rows but 0 active collectors → healthy
    ingestion = subsystems.get("ingestion", {})
    collectors = subsystems.get("collectors", {})
    if (
        ingestion.get("status") == "degraded"
        and ingestion.get("details", {}).get("total_rows_5min", 0) == 0
        and collectors.get("details", {}).get("by_status", {}).get("ACTIVE", 0)
        == 0
    ):
        ingestion["status"] = "healthy"

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
