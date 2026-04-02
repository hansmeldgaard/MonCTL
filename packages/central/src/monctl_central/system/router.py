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

from monctl_central.config import parse_node_list, settings
from monctl_central.dependencies import (
    get_clickhouse,
    get_engine,
    get_session_factory,
    require_admin,
)
from monctl_central.storage.models import (
    AlertEntity,
    AlertDefinition,
    Collector,
    CollectorGroup,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_TABLES = ["availability_latency", "performance", "interface", "config"]
_CHECK_TIMEOUT = 5.0  # seconds per subsystem check
_STARTED_AT = time.time()


def _safe_int(val) -> int | None:
    """Convert a value to int, returning None if not possible."""
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


async def _check_central() -> dict:
    """Process info for this central instance."""
    import resource
    from monctl_central.cache import _redis

    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = round(rss_kb / 1024, 1)  # Linux reports KB
    uptime_seconds = round(time.time() - _STARTED_AT, 1)

    # Scheduler leader check
    is_scheduler_leader = False
    scheduler_leader = None
    if _redis is not None:
        try:
            scheduler_leader = await _redis.get("monctl:scheduler:leader")
            is_scheduler_leader = scheduler_leader == settings.instance_id
        except Exception:
            pass

    hostname = os.environ.get("MONCTL_NODE_NAME", settings.instance_id)

    return {
        "status": "healthy",
        "latency_ms": None,
        "details": {
            "role": "central",
            "instance_id": settings.instance_id,
            "hostname": hostname,
            "python_version": platform.python_version(),
            "pid": os.getpid(),
            "uptime_seconds": uptime_seconds,
            "rss_mb": rss_mb,
            "debug": settings.debug,
            "is_scheduler_leader": is_scheduler_leader,
            "scheduler_leader": scheduler_leader,
        },
    }


async def _check_postgresql(db: AsyncSession) -> dict:
    """Comprehensive PostgreSQL health check."""
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

    # Active connections + max
    active_conns = (await db.execute(text(
        "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
    ))).scalar()
    total_conns = (await db.execute(text(
        "SELECT count(*) FROM pg_stat_activity"
    ))).scalar()
    max_conns = (await db.execute(text(
        "SELECT setting::int FROM pg_settings WHERE name = 'max_connections'"
    ))).scalar()

    # ── Replication ──
    replication = []
    try:
        rows = (await db.execute(text(
            "SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,"
            " (EXTRACT(EPOCH FROM replay_lag) * 1000)::bigint AS replay_lag_ms,"
            " (EXTRACT(EPOCH FROM write_lag) * 1000)::bigint AS write_lag_ms,"
            " pg_wal_lsn_diff(sent_lsn, replay_lsn) AS replay_lag_bytes"
            " FROM pg_stat_replication"
        ))).all()
        for r in rows:
            replication.append({
                "client_addr": str(r[0]) if r[0] else None,
                "state": r[1],
                "replay_lag_ms": int(r[6]) if r[6] is not None else None,
                "write_lag_ms": int(r[7]) if r[7] is not None else None,
                "replay_lag_bytes": int(r[8]) if r[8] is not None else None,
            })
    except Exception:
        pass

    # ── Cache hit ratio ──
    cache_hit = None
    index_hit = None
    try:
        row = (await db.execute(text(
            "SELECT"
            " CASE WHEN (blks_hit + blks_read) > 0"
            "   THEN round(100.0 * blks_hit / (blks_hit + blks_read), 2)"
            "   ELSE 100 END AS cache_hit_pct"
            " FROM pg_stat_database WHERE datname = current_database()"
        ))).one()
        cache_hit = float(row[0])
    except Exception:
        pass
    try:
        row = (await db.execute(text(
            "SELECT"
            " CASE WHEN (idx_blks_hit + idx_blks_read) > 0"
            "   THEN round(100.0 * idx_blks_hit / (idx_blks_hit + idx_blks_read), 2)"
            "   ELSE 100 END"
            " FROM pg_statio_all_tables"
            " WHERE (idx_blks_hit + idx_blks_read) > 0"
            " ORDER BY (idx_blks_hit + idx_blks_read) DESC LIMIT 1"
        ))).scalar_one_or_none()
        if row is not None:
            index_hit = float(row)
    except Exception:
        pass

    # ── Vacuum stats (top dead-tuple tables) ──
    vacuum_stats = []
    try:
        rows = (await db.execute(text(
            "SELECT schemaname || '.' || relname AS table_name,"
            " n_dead_tup, n_live_tup,"
            " last_autovacuum, last_autoanalyze"
            " FROM pg_stat_user_tables"
            " WHERE n_dead_tup > 0"
            " ORDER BY n_dead_tup DESC LIMIT 10"
        ))).all()
        for r in rows:
            vacuum_stats.append({
                "table": r[0],
                "dead_tuples": r[1],
                "live_tuples": r[2],
                "last_autovacuum": r[3].isoformat() if r[3] else None,
                "last_autoanalyze": r[4].isoformat() if r[4] else None,
            })
    except Exception:
        pass

    # ── XID age (transaction ID wraparound risk) ──
    xid_age = None
    try:
        xid_age = (await db.execute(text(
            "SELECT age(datfrozenxid) FROM pg_database WHERE datname = current_database()"
        ))).scalar()
    except Exception:
        pass

    # ── Long-running queries ──
    long_queries = []
    try:
        rows = (await db.execute(text(
            "SELECT pid, usename, state,"
            " EXTRACT(EPOCH FROM (now() - query_start))::int AS duration_s,"
            " left(query, 200) AS query_preview"
            " FROM pg_stat_activity"
            " WHERE state = 'active' AND query NOT LIKE '%pg_stat_activity%'"
            " AND backend_type NOT IN ('walsender', 'walreceiver')"
            " AND (now() - query_start) > interval '5 minutes'"
            " ORDER BY query_start ASC LIMIT 10"
        ))).all()
        for r in rows:
            long_queries.append({
                "pid": r[0], "user": r[1], "state": r[2],
                "duration_s": r[3], "query_preview": r[4],
            })
    except Exception:
        pass

    # ── Locks ──
    waiting_locks = 0
    try:
        waiting_locks = (await db.execute(text(
            "SELECT count(*) FROM pg_locks WHERE NOT granted"
        ))).scalar() or 0
    except Exception:
        pass

    # ── Deadlocks ──
    deadlocks = 0
    try:
        deadlocks = (await db.execute(text(
            "SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()"
        ))).scalar() or 0
    except Exception:
        pass

    # ── Temp files ──
    temp_bytes = 0
    try:
        temp_bytes = (await db.execute(text(
            "SELECT temp_bytes FROM pg_stat_database WHERE datname = current_database()"
        ))).scalar() or 0
    except Exception:
        pass

    # ── Table counts ──
    key_tables = [
        "devices", "collectors", "apps", "app_assignments",
        "alert_definitions", "alert_entities", "credentials", "tenants", "users",
    ]
    table_counts = {}
    for tbl in key_tables:
        try:
            cnt = (await db.execute(text(f"SELECT count(*) FROM {tbl}"))).scalar()  # noqa: S608
            table_counts[tbl] = cnt
        except Exception:
            table_counts[tbl] = None

    # ── Status determination ──
    status = "healthy"
    max_replay_lag_ms = max((r.get("replay_lag_ms") or 0 for r in replication), default=0)

    if (latency_ms > 500 or overflow > 5 or max_replay_lag_ms > 5000
            or (cache_hit is not None and cache_hit < 99)
            or waiting_locks > 5 or len(long_queries) > 0
            or (xid_age is not None and xid_age > 500_000_000)):
        status = "degraded"
    if (max_replay_lag_ms > 30000
            or (cache_hit is not None and cache_hit < 95)
            or (xid_age is not None and xid_age > 1_000_000_000)):
        status = "critical"

    return {
        "status": status,
        "latency_ms": latency_ms,
        "details": {
            "version": ver_row,
            "db_size_bytes": db_size_row,
            "connections": {
                "active": active_conns,
                "total": total_conns,
                "max": max_conns,
            },
            "pool_size": pool_size,
            "checked_out": checked_out,
            "overflow": overflow,
            "pool_status": pool_status,
            "replication": replication,
            "cache_hit_pct": cache_hit,
            "index_hit_pct": index_hit,
            "vacuum_stats": vacuum_stats,
            "xid_age": xid_age,
            "long_running_queries": long_queries,
            "waiting_locks": waiting_locks,
            "deadlocks_total": deadlocks,
            "temp_bytes_total": temp_bytes,
            "table_counts": table_counts,
        },
    }


async def _check_patroni() -> dict:
    """Check Patroni HA cluster status via REST API."""
    import httpx

    # Patroni REST API on central nodes
    patroni_nodes = parse_node_list(settings.patroni_nodes)
    if not patroni_nodes:
        return {"name": "Patroni", "status": "unconfigured", "message": "MONCTL_PATRONI_NODES not set"}
    t0 = time.monotonic()
    status = "healthy"
    members = []
    leader_name = None
    cluster_timeline = None
    history = []

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try each node until we get cluster info
            cluster_data = None
            for name, ip in patroni_nodes:
                try:
                    resp = await client.get(f"http://{ip}:8008/cluster")
                    if resp.status_code == 200:
                        cluster_data = resp.json()
                        break
                except Exception:
                    continue

            if cluster_data is None:
                return {
                    "status": "critical",
                    "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                    "details": {"error": "No Patroni node reachable"},
                }

            # Parse cluster members
            for m in cluster_data.get("members", []):
                member = {
                    "name": m.get("name"),
                    "role": m.get("role"),
                    "state": m.get("state"),
                    "host": m.get("host"),
                    "port": m.get("port"),
                    "timeline": m.get("timeline"),
                    "lag": _safe_int(m.get("lag")),
                    "pending_restart": m.get("tags", {}).get("pending_restart", False),
                }
                members.append(member)
                if m.get("role") == "leader":
                    leader_name = m.get("name")
                    cluster_timeline = m.get("timeline")

            # Fetch recent failover history from leader
            if leader_name:
                for name, ip in patroni_nodes:
                    try:
                        resp = await client.get(f"http://{ip}:8008/history")
                        if resp.status_code == 200:
                            raw = resp.json()
                            history = raw[-5:] if isinstance(raw, list) else []
                            break
                    except Exception:
                        continue

    except Exception as exc:
        return {
            "status": "critical",
            "latency_ms": round((time.monotonic() - t0) * 1000, 2),
            "details": {"error": str(exc)},
        }

    latency_ms = round((time.monotonic() - t0) * 1000, 2)

    # Status determination
    if not leader_name:
        status = "critical"
    else:
        replicas = [m for m in members if m["role"] in ("replica", "sync_standby")]
        if len(replicas) == 0:
            status = "degraded"
        for m in members:
            if m["state"] not in ("running", "streaming"):
                status = "degraded"
            if (m.get("lag") or 0) > 10_000_000:  # >10MB lag
                status = "degraded"
            if m.get("pending_restart"):
                status = "degraded" if status == "healthy" else status

    return {
        "status": status,
        "latency_ms": latency_ms,
        "details": {
            "leader": leader_name,
            "timeline": cluster_timeline,
            "members": members,
            "member_count": len(members),
            "replica_count": len([m for m in members if m["role"] in ("replica", "sync_standby")]),
            "failover_history": history,
        },
    }


async def _check_etcd() -> dict:
    """Check etcd cluster health."""
    import httpx

    etcd_nodes = parse_node_list(settings.etcd_nodes)
    if not etcd_nodes:
        return {"name": "etcd", "status": "unconfigured", "message": "MONCTL_ETCD_NODES not set"}
    t0 = time.monotonic()
    node_health = []
    leader_id = None
    leader_name = None
    member_count = 0
    db_size = None
    status = "healthy"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Check each node's health
            for name, ip in etcd_nodes:
                node = {"name": name, "host": ip, "healthy": False}
                try:
                    resp = await client.get(f"http://{ip}:2379/health")
                    if resp.status_code == 200:
                        data = resp.json()
                        node["healthy"] = data.get("health") == "true"
                except Exception as exc:
                    node["error"] = str(exc)
                node_health.append(node)

            # Get cluster status from first healthy node
            raft_index = None
            raft_term = None
            etcd_version = None
            for node in node_health:
                if not node["healthy"]:
                    continue
                try:
                    resp = await client.post(
                        f"http://{node['host']}:2379/v3/maintenance/status",
                        json={},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        leader_id = data.get("leader")
                        db_size = data.get("dbSize")
                        raft_index = data.get("raftIndex")
                        raft_term = data.get("raftTerm")
                        etcd_version = data.get("version")
                        break
                except Exception:
                    continue

            # Get member list
            member_details = []
            for node in node_health:
                if not node["healthy"]:
                    continue
                try:
                    resp = await client.post(
                        f"http://{node['host']}:2379/v3/cluster/member/list",
                        json={},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        members = data.get("members", [])
                        member_count = len(members)
                        for m in members:
                            mid = str(m.get("ID", ""))
                            mname = m.get("name", "")
                            if leader_id and mid == str(leader_id):
                                leader_name = mname
                            member_details.append({
                                "id": mid,
                                "name": mname,
                                "peer_urls": m.get("peerURLs", []),
                                "client_urls": m.get("clientURLs", []),
                                "is_leader": mid == str(leader_id) if leader_id else False,
                            })
                        break
                except Exception:
                    continue

            # Check for active alarms
            alarms = []
            for node in node_health:
                if not node["healthy"]:
                    continue
                try:
                    resp = await client.post(
                        f"http://{node['host']}:2379/v3/maintenance/alarm",
                        json={"action": "GET"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for a in data.get("alarms", []):
                            alarm_type = a.get("alarm", 0)
                            if alarm_type and alarm_type != 0:
                                alarms.append({
                                    "member_id": str(a.get("memberID", "")),
                                    "alarm": "NOSPACE" if alarm_type == 1 else "CORRUPT" if alarm_type == 2 else str(alarm_type),
                                })
                        break
                except Exception:
                    continue

    except Exception as exc:
        return {
            "status": "critical",
            "latency_ms": round((time.monotonic() - t0) * 1000, 2),
            "details": {"error": str(exc)},
        }

    latency_ms = round((time.monotonic() - t0) * 1000, 2)

    healthy_count = sum(1 for n in node_health if n["healthy"])
    if healthy_count == 0 or not leader_id:
        status = "critical"
    elif healthy_count < len(etcd_nodes):
        status = "degraded"
    elif member_count < 3:
        status = "degraded"

    # etcd db size warning (>2GB)
    if db_size is not None:
        db_size = int(db_size)
    if db_size and db_size > 2_000_000_000:
        status = "degraded" if status == "healthy" else status

    if alarms:
        status = "degraded" if status == "healthy" else status

    return {
        "status": status,
        "latency_ms": latency_ms,
        "details": {
            "nodes": node_health,
            "healthy_count": healthy_count,
            "total_nodes": len(etcd_nodes),
            "leader_id": str(leader_id) if leader_id else None,
            "leader_name": leader_name,
            "member_count": member_count,
            "db_size_bytes": db_size,
            "raft_index": raft_index,
            "raft_term": raft_term,
            "version": etcd_version,
            "alarms": alarms,
            "members": member_details,
        },
    }


def _query_node_resources(host: str, port: int, username: str, password: str, database: str) -> dict:
    """Query a single ClickHouse node for per-node metrics (server resources, replication, merges, errors)."""
    import clickhouse_connect

    result: dict = {"host": host, "reachable": False, "latency_ms": None}
    try:
        t0 = time.monotonic()
        client = clickhouse_connect.get_client(
            host=host, port=port, username=username, password=password,
            database=database, connect_timeout=5, send_receive_timeout=10,
        )
        client.query("SELECT 1")
        result["reachable"] = True
        result["latency_ms"] = round((time.monotonic() - t0) * 1000, 2)
    except Exception as exc:
        result["error"] = str(exc)
        return result

    # --- replication ---
    replication = []
    try:
        r = client.query(
            "SELECT table, is_readonly, is_session_expired,"
            " queue_size, total_replicas, active_replicas, absolute_delay"
            " FROM system.replicas WHERE database = currentDatabase()"
        )
        for row in r.named_results():
            replication.append({
                "table": row["table"],
                "is_readonly": row["is_readonly"],
                "is_session_expired": row["is_session_expired"],
                "queue_size": row["queue_size"],
                "total_replicas": row["total_replicas"],
                "active_replicas": row["active_replicas"],
                "absolute_delay": row["absolute_delay"],
            })
    except Exception:
        pass
    result["replication"] = replication

    # --- merges ---
    try:
        r = client.query(
            "SELECT count() AS cnt, max(elapsed) AS longest_seconds,"
            " sum(total_size_bytes_compressed) AS total_bytes FROM system.merges"
        )
        if r.result_rows:
            result["merges"] = {
                "active_count": r.first_row[0],
                "longest_seconds": round(r.first_row[1], 1) if r.first_row[1] else 0,
                "total_bytes_merging": r.first_row[2],
            }
    except Exception:
        pass

    # --- mutations ---
    try:
        r = client.query(
            "SELECT count() AS total, countIf(is_done = 0) AS pending,"
            " countIf(latest_fail_reason != '') AS failed"
            " FROM system.mutations WHERE database = currentDatabase()"
        )
        if r.result_rows:
            result["mutations"] = {"total": r.first_row[0], "pending": r.first_row[1], "failed": r.first_row[2]}
    except Exception:
        pass

    # --- server resources (disks, memory, CPU, load) ---
    disks = []
    try:
        r = client.query("SELECT name, path, free_space, total_space FROM system.disks")
        for row in r.named_results():
            total = row["total_space"]
            free = row["free_space"]
            disks.append({
                "name": row["name"],
                "free_bytes": free,
                "total_bytes": total,
                "used_pct": round(((total - free) / total) * 100, 1) if total > 0 else 0,
            })
    except Exception:
        pass

    async_metrics = {}
    try:
        r = client.query(
            "SELECT metric, value FROM system.asynchronous_metrics"
            " WHERE metric IN ("
            "'OSMemoryTotal', 'OSMemoryFreeWithoutCached',"
            " 'LoadAverage1', 'LoadAverage5', 'LoadAverage15')"
        )
        for row in r.named_results():
            async_metrics[row["metric"]] = row["value"]
    except Exception:
        pass

    # CH 24.3 has per-core metrics (OSUserTimeCPU0..N, OSSystemTimeCPU0..N) as 0-1 ratios.
    cpu_user_vals: list[float] = []
    cpu_sys_vals: list[float] = []
    cpu_iowait_vals: list[float] = []
    try:
        r = client.query(
            "SELECT metric, value FROM system.asynchronous_metrics"
            " WHERE metric LIKE 'OSUserTimeCPU%'"
            " OR metric LIKE 'OSSystemTimeCPU%'"
            " OR metric LIKE 'OSIOWaitTimeCPU%'"
        )
        for row in r.named_results():
            m = row["metric"]
            if m.startswith("OSUserTimeCPU"):
                cpu_user_vals.append(row["value"])
            elif m.startswith("OSSystemTimeCPU"):
                cpu_sys_vals.append(row["value"])
            elif m.startswith("OSIOWaitTimeCPU"):
                cpu_iowait_vals.append(row["value"])
    except Exception:
        pass

    avg_user = (sum(cpu_user_vals) / len(cpu_user_vals) * 100) if cpu_user_vals else 0
    avg_sys = (sum(cpu_sys_vals) / len(cpu_sys_vals) * 100) if cpu_sys_vals else 0
    avg_iowait = (sum(cpu_iowait_vals) / len(cpu_iowait_vals) * 100) if cpu_iowait_vals else 0

    os_mem_total = async_metrics.get("OSMemoryTotal", 0)
    os_mem_free = async_metrics.get("OSMemoryFreeWithoutCached", 0)
    result["server"] = {
        "disks": disks,
        "os_memory_total_bytes": os_mem_total,
        "os_memory_free_bytes": os_mem_free,
        "ch_memory_resident_bytes": 0,
        "cpu_user_pct": round(avg_user, 1),
        "cpu_system_pct": round(avg_sys, 1),
        "cpu_iowait_pct": round(avg_iowait, 1),
        "cpu_idle_pct": round(100 - avg_user - avg_sys - avg_iowait, 1),
        "load_average": [
            round(async_metrics.get("LoadAverage1", 0), 2),
            round(async_metrics.get("LoadAverage5", 0), 2),
            round(async_metrics.get("LoadAverage15", 0), 2),
        ],
        "tcp_connections": 0,
        "max_parts_per_partition": 0,
    }

    # --- recent errors ---
    recent_errors = []
    try:
        r = client.query(
            "SELECT name, value, last_error_time, last_error_message"
            " FROM system.errors ORDER BY last_error_time DESC LIMIT 10"
            " SETTINGS max_memory_usage = 500000000"
        )
        for row in r.named_results():
            recent_errors.append({
                "name": row["name"], "count": row["value"],
                "last_time": str(row["last_error_time"]),
                "message": row.get("last_error_message"),
            })
    except Exception:
        pass
    result["recent_errors"] = recent_errors

    try:
        client.close()
    except Exception:
        pass
    return result


async def _check_clickhouse() -> dict:
    """Check ClickHouse connectivity, row counts, data freshness, and per-node internals."""
    ch = get_clickhouse()

    def _run():  # noqa: C901
        import clickhouse_connect

        t0 = time.monotonic()
        client = clickhouse_connect.get_client(
            host=ch._hosts[0], port=ch._port,
            username=ch._username, password=ch._password,
            database=ch._database, connect_timeout=5, send_receive_timeout=10,
        )
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

        try:
            client.close()
        except Exception:
            pass

        return (
            latency_ms, tables, version, uptime_seconds,
            table_storage, total_bytes, total_rows_all, pk_memory_bytes,
            cluster_topology, keeper_ok, slow_queries,
        )

    (
        latency_ms, tables, version, uptime_seconds,
        table_storage, total_bytes, total_rows_all, pk_memory_bytes,
        cluster_topology, keeper_ok, slow_queries,
    ) = await asyncio.to_thread(_run)

    # --- Query each CH node independently for per-node metrics ---
    hosts = ch._hosts
    node_results = {}
    node_futures = []
    for host in hosts:
        node_futures.append(
            asyncio.to_thread(
                _query_node_resources,
                host, ch._port, ch._username, ch._password, ch._database,
            )
        )
    for nr in await asyncio.gather(*node_futures, return_exceptions=True):
        if isinstance(nr, Exception):
            continue
        node_results[nr["host"]] = nr

    # Build merged replication/merges/mutations from first reachable node
    replication: dict = {}
    merges: dict = {}
    mutations: dict = {}
    recent_errors: list = []
    for nr in node_results.values():
        if nr.get("reachable"):
            if not replication and nr.get("replication"):
                for rep in nr["replication"]:
                    replication[rep["table"]] = rep
            if not merges:
                merges = nr.get("merges", {})
            if not mutations:
                mutations = nr.get("mutations", {})
            if not recent_errors:
                recent_errors = nr.get("recent_errors", [])
            break

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

    # --- Disk usage (from per-node data) ---
    for nr in node_results.values():
        for dk in (nr.get("server") or {}).get("disks", []):
            total = dk.get("total_bytes", 0)
            free = dk.get("free_bytes", 0)
            if total > 0:
                used_pct = ((total - free) / total) * 100
                if used_pct > 95:
                    status = "critical"
                elif used_pct > 90 and status != "critical":
                    status = "degraded"

    # --- Build cluster object in the format the frontend expects ---
    cluster_obj = None
    if cluster_topology:
        shard_set = set()
        for node in cluster_topology:
            shard_set.add(node.get("host_name", ""))
        cluster_obj = {
            "cluster_name": ch._cluster_name or "monctl_cluster",
            "shard_count": 1,
            "replica_count": len(cluster_topology),
            "nodes": [
                {
                    "shard": 1,
                    "replica": i + 1,
                    "host": n.get("host_name", ""),
                    "address": n.get("host_name", ""),
                    "port": n.get("port", 9000),
                    "is_local": bool(n.get("is_local", False)),
                }
                for i, n in enumerate(cluster_topology)
            ],
        }

    # --- Build replication array (from merged dict) ---
    replication_list = [
        {
            "table": tbl,
            "is_leader": False,
            "is_readonly": rep.get("is_readonly", False),
            "queue_size": rep.get("queue_size", 0),
            "absolute_delay": rep.get("absolute_delay", 0),
            "active_replicas": rep.get("active_replicas", 0),
            "total_replicas": rep.get("total_replicas", 0),
            "is_session_expired": rep.get("is_session_expired", False),
            "log_lag": 0,
            "inserts_in_queue": 0,
            "merges_in_queue": 0,
        }
        for tbl, rep in replication.items()
    ]

    # --- Build keeper object ---
    keeper_obj = {"reachable": keeper_ok or False, "session_expired": False} if keeper_ok is not None else None

    # --- Use first reachable node's server data as legacy "server" field ---
    server_obj = None
    for nr in node_results.values():
        if nr.get("reachable") and nr.get("server"):
            server_obj = nr["server"]
            break

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
            "cluster": cluster_obj,
            "replication": replication_list,
            "merges": merges,
            "mutations": mutations,
            "keeper_ok": keeper_ok,
            "keeper": keeper_obj,
            "slow_queries_last_hour": slow_queries,
            "recent_errors": recent_errors,
            "server": server_obj,
            "nodes": node_results,
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
    """Check Redis connectivity, version, memory, replication, Sentinel, and key stats."""
    from monctl_central.cache import _redis
    import redis.asyncio as aioredis

    if _redis is None:
        return {
            "status": "critical",
            "latency_ms": None,
            "details": {"error": "Redis not connected"},
        }

    t0 = time.monotonic()
    try:
        await _redis.ping()
    except Exception as e:
        return {
            "status": "critical",
            "latency_ms": None,
            "details": {"error": f"Redis ping failed: {e}"},
        }
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
            "used_memory_human": info_mem.get("used_memory_human"),
            "used_memory_peak_human": info_mem.get("used_memory_peak_human"),
            "mem_fragmentation_ratio": info_mem.get("mem_fragmentation_ratio"),
        }
    except Exception:
        pass

    # Replication info
    replication = None
    try:
        info_repl = await _redis.info("replication")
        replication = {
            "role": info_repl.get("role"),
            "connected_slaves": info_repl.get("connected_slaves"),
        }
        if int(info_repl.get("connected_slaves", 0)) > 0:
            replicas = []
            for i in range(int(info_repl["connected_slaves"])):
                slave_key = f"slave{i}"
                if slave_key in info_repl:
                    replicas.append(info_repl[slave_key])
            replication["replicas"] = replicas
    except Exception:
        pass

    # Sentinel info
    sentinel_info = None
    sentinel_hosts_raw = settings.redis_sentinel_hosts
    sentinel_master_name = settings.redis_sentinel_master or "monctl-redis"
    try:
        if not sentinel_hosts_raw.strip():
            raise ValueError("MONCTL_REDIS_SENTINEL_HOSTS not configured")
        for entry in sentinel_hosts_raw.split(","):
            entry = entry.strip()
            if ":" in entry:
                host, port = entry.rsplit(":", 1)
            else:
                host, port = entry, "26379"
            try:
                s = aioredis.from_url(
                    f"redis://{host}:{port}", decode_responses=True,
                    socket_connect_timeout=3, socket_timeout=3,
                )
                master_info = await s.execute_command(
                    "SENTINEL", "master", sentinel_master_name
                )
                master_dict = dict(
                    zip(master_info[::2], master_info[1::2])
                )
                sentinel_info = {
                    "master_ip": master_dict.get("ip"),
                    "master_port": master_dict.get("port"),
                    "num_slaves": master_dict.get("num-slaves"),
                    "num_sentinels": int(master_dict.get("num-other-sentinels", 0)) + 1,
                    "quorum": master_dict.get("quorum"),
                    "flags": master_dict.get("flags"),
                }
                await s.close()
                break
            except Exception:
                continue
    except Exception:
        pass

    # Clients
    connected_clients = None
    try:
        info_clients = await _redis.info("clients")
        connected_clients = info_clients.get("connected_clients")
    except Exception:
        pass

    # Key stats by prefix (full scan if small, proportional for large)
    key_stats: dict[str, int] = {}
    total_keys = db_size or 0
    try:
        prefixes: dict[str, int] = {}
        scan_limit = total_keys if total_keys <= 10_000 else 5_000
        count = 0
        async for key in _redis.scan_iter(match="*", count=500):
            if isinstance(key, bytes):
                key = key.decode()
            parts = key.split(":")
            prefix = parts[0] if parts else key
            prefixes[prefix] = prefixes.get(prefix, 0) + 1
            count += 1
            if count >= scan_limit:
                break
        # Normalize proportionally if we sampled a subset
        if count > 0 and total_keys > count:
            scale = total_keys / count
            key_stats = {k: round(v * scale) for k, v in prefixes.items()}
        else:
            key_stats = prefixes
    except Exception:
        pass

    # Determine status
    status = "healthy"
    if replication:
        if replication.get("role") == "master" and replication.get("connected_slaves", 0) == 0:
            if settings.redis_sentinel_hosts:
                status = "degraded"  # No replicas connected in HA mode
    if sentinel_info and sentinel_info.get("flags") and "s_down" in sentinel_info["flags"]:
        status = "degraded"

    return {
        "status": status,
        "latency_ms": latency_ms,
        "details": {
            "version": version,
            "leader_instance": leader,
            "db_size": db_size,
            "connected_clients": connected_clients,
            "memory": memory_stats,
            "replication": replication,
            "sentinel": sentinel_info,
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

    # Build group name + weight snapshot lookup
    group_ids = {c.group_id for c in all_collectors if c.group_id}
    group_names: dict[str, str] = {}
    group_weights: dict[str, dict] = {}  # group_id -> {hostname: weight}
    if group_ids:
        groups = (
            await db.execute(
                select(CollectorGroup).where(CollectorGroup.id.in_(group_ids))
            )
        ).scalars().all()
        for g in groups:
            group_names[str(g.id)] = g.name
            if g.weight_snapshot:
                group_weights[str(g.id)] = g.weight_snapshot

    # Per-collector detail
    collector_list = []
    for c in all_collectors:
        peer_states = c.reported_peer_states or {}
        # Resolve weight for this collector from group snapshot
        weight = None
        if c.group_id and str(c.group_id) in group_weights:
            ws = group_weights[str(c.group_id)]
            weight = ws.get(c.hostname)
        system_resources = peer_states.get("_system_resources")

        # Compute capacity status based on CPU, memory, and deadline misses
        capacity_status = "ok"
        capacity_warnings: list[str] = []
        if system_resources:
            cpu_load = system_resources.get("cpu_load", [])
            cpu_count = system_resources.get("cpu_count", 1) or 1
            if cpu_load:
                # Use 1-minute load average
                cpu_pct = (cpu_load[0] / cpu_count) * 100
                if cpu_pct >= 95:
                    capacity_status = "critical"
                    capacity_warnings.append(f"CPU {cpu_pct:.0f}%")
                elif cpu_pct >= 80:
                    capacity_status = "warning"
                    capacity_warnings.append(f"CPU {cpu_pct:.0f}%")
            mem_total = system_resources.get("memory_total_mb", 0)
            mem_used = system_resources.get("memory_used_mb", 0)
            if mem_total > 0:
                mem_pct = (mem_used / mem_total) * 100
                if mem_pct >= 95:
                    capacity_status = "critical"
                    capacity_warnings.append(f"Memory {mem_pct:.0f}%")
                elif mem_pct >= 80:
                    if capacity_status != "critical":
                        capacity_status = "warning"
                    capacity_warnings.append(f"Memory {mem_pct:.0f}%")
        if c.deadline_miss_rate > 0.10:
            capacity_status = "critical"
            capacity_warnings.append(f"Miss rate {c.deadline_miss_rate:.1%}")
        elif c.deadline_miss_rate > 0.05:
            if capacity_status != "critical":
                capacity_status = "warning"
            capacity_warnings.append(f"Miss rate {c.deadline_miss_rate:.1%}")

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
            "system_resources": system_resources,
            "capacity_status": capacity_status,
            "capacity_warnings": capacity_warnings if capacity_warnings else None,
            "weight": weight,
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
        await db.execute(select(func.count(AlertDefinition.id)))
    ).scalar() or 0
    enabled_rules = (
        await db.execute(
            select(func.count(AlertDefinition.id)).where(AlertDefinition.enabled.is_(True))
        )
    ).scalar() or 0

    # Count total firing entities
    total_firing = (
        await db.execute(
            select(func.count(AlertEntity.id))
            .where(AlertEntity.state == "firing")
        )
    ).scalar() or 0

    # Firing by severity
    firing_by_severity: dict[str, int] = {}
    try:
        sev_rows = (
            await db.execute(
                select(AlertDefinition.severity, func.count(AlertEntity.id))
                .join(AlertDefinition, AlertEntity.definition_id == AlertDefinition.id)
                .where(AlertEntity.state == "firing")
                .group_by(AlertDefinition.severity)
            )
        ).all()
        for sev, cnt in sev_rows:
            firing_by_severity[sev] = cnt
    except Exception:
        pass

    if total_firing > 0:
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
                sidecar_hosts.append({"label": parts[0], "base_url": f"http://{parts[1]}:{parts[2]}"})

    t0 = time.monotonic()

    # Central tier: query sidecars (20s timeout — docker stats API is slow)
    async def _fetch(client: httpx.AsyncClient, host: dict) -> dict:
        base_url = host["base_url"]

        async def _get(path: str, timeout: float = 20.0):
            try:
                resp = await client.get(f"{base_url}{path}", timeout=timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception:
                return None

        stats_data, system_data = await asyncio.gather(
            _get("/stats"), _get("/system", timeout=5.0)
        )

        if stats_data is None:
            return {"label": host["label"], "status": "unreachable", "source": "sidecar", "data": None, "error": "Failed to fetch /stats"}

        # Inject host system summary into the stats data
        if system_data:
            host_info = system_data.get("host", {})
            stats_data["host"]["load_avg"] = host_info.get("load_avg")
            stats_data["host"]["mem_total_bytes"] = host_info.get("mem_total_bytes")
            stats_data["host"]["mem_available_bytes"] = host_info.get("mem_available_bytes")
            stats_data["host"]["uptime_seconds"] = host_info.get("uptime_seconds")
            stats_data["docker_version"] = system_data.get("docker", {}).get("version")

        return {"label": host["label"], "status": "ok", "source": "sidecar", "data": stats_data}

    sidecar_results: list[dict] = []
    if sidecar_hosts:
        async with httpx.AsyncClient() as client:
            sidecar_results = list(await asyncio.gather(
                *[_fetch(client, h) for h in sidecar_hosts]
            ))

    # Worker tier: prefer Redis push data, fall back to ClickHouse
    from monctl_central.cache import get_docker_push, get_pushed_docker_hosts

    sidecar_labels = {h["label"] for h in sidecar_hosts}
    pushed_hosts = await get_pushed_docker_hosts()
    pushed_labels = set()
    worker_results: list[dict] = []
    for meta in pushed_hosts:
        label = meta["host_label"]
        # Skip hosts already covered by sidecar queries
        if label in sidecar_labels:
            continue
        pushed_labels.add(label)
        stats = await get_docker_push(label, "stats")
        system = await get_docker_push(label, "system")
        if stats:
            # Inject host system summary (same as central tier)
            if system:
                host_info = system.get("host", {})
                stats.setdefault("host", {})
                stats["host"]["load_avg"] = host_info.get("load_avg")
                stats["host"]["mem_total_bytes"] = host_info.get("mem_total_bytes")
                stats["host"]["mem_available_bytes"] = host_info.get("mem_available_bytes")
                stats["host"]["uptime_seconds"] = host_info.get("uptime_seconds")
                stats["docker_version"] = system.get("docker", {}).get("version")
            worker_results.append({
                "label": label, "status": "ok", "source": "push", "data": stats,
            })
        else:
            worker_results.append({
                "label": label, "status": "stale", "source": "push", "data": None,
                "error": "No recent data",
            })

    # ClickHouse fallback for workers not using push mode
    collector_results = await asyncio.to_thread(_fetch_collector_docker_stats_from_ch)
    for cr in collector_results:
        if cr["label"] not in pushed_labels and cr["label"] not in sidecar_labels:
            worker_results.append(cr)

    latency_ms = round((time.monotonic() - t0) * 1000, 2)

    all_hosts = sidecar_results + worker_results

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
        _run_check("patroni", _check_patroni()),
        _run_check("etcd", _check_etcd()),
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

    # Overall status = worst of all (exclude alerts — they reflect monitored
    # devices, not infrastructure health)
    _INFRA_SUBSYSTEMS = {
        "central", "postgresql", "patroni", "etcd", "clickhouse",
        "redis", "collectors", "scheduler", "ingestion", "docker",
    }
    priority = {"critical": 2, "degraded": 1, "healthy": 0, "unknown": -1}
    worst = max(
        (
            s.get("status", "unknown")
            for name, s in subsystems.items()
            if name in _INFRA_SUBSYSTEMS
        ),
        key=lambda s: priority.get(s, -1),
        default="unknown",
    )

    from monctl_common.utils import utc_now

    checked_at = utc_now().isoformat()

    # Resolve human-readable node name from central subsystem
    central_details = subsystems.get("central", {}).get("details", {})
    node_hostname = central_details.get("hostname", settings.instance_id)

    # Cache for lightweight status endpoint
    global _last_health_status
    _last_health_status = {"overall_status": worst, "checked_at": checked_at}

    return {
        "status": "success",
        "data": {
            "overall_status": worst,
            "instance_id": settings.instance_id,
            "hostname": node_hostname,
            "version": "0.1.0",
            "checked_at": checked_at,
            "subsystems": subsystems,
        },
    }


_last_health_status: dict = {"overall_status": "unknown", "checked_at": None}


@router.get("/health/status")
async def system_health_status(
    auth: dict = Depends(require_admin),
):
    """Lightweight endpoint returning only overall status (for top-bar indicator)."""
    return {"status": "success", "data": _last_health_status}


@router.get("/collector-errors/{collector_name}")
async def get_collector_errors(
    collector_name: str,
    hours: int = 1,
    ch=Depends(get_clickhouse),
    auth: dict = Depends(require_admin),
):
    """Error analytics for a single collector: top errors + per-app breakdown."""
    from monctl_common.utils import utc_now
    from datetime import timedelta

    cutoff = (utc_now() - timedelta(hours=min(hours, 24))).strftime("%Y-%m-%d %H:%M:%S")
    tables = ["availability_latency", "performance", "config"]
    # Top errors (across all tables)
    top_errors: dict[str, int] = {}
    # Per-app error counts
    app_errors: dict[str, int] = {}
    app_totals: dict[str, int] = {}

    for table in tables:
        # Top error messages
        try:
            rows = ch.query(
                f"SELECT error_message, count() AS cnt"
                f" FROM {table}"
                f" WHERE collector_name = %(cn)s"
                f"   AND executed_at >= '{cutoff}'"
                f"   AND error_message != ''"
                f" GROUP BY error_message"
                f" ORDER BY cnt DESC"
                f" LIMIT 20",
                {"cn": collector_name},
            )
            for r in rows.result_rows:
                msg = r[0][:200]
                top_errors[msg] = top_errors.get(msg, 0) + r[1]
        except Exception:
            pass

        # Per-app error/total counts
        try:
            rows = ch.query(
                f"SELECT app_name,"
                f"   countIf(error_message != '') AS errors,"
                f"   count() AS total"
                f" FROM {table}"
                f" WHERE collector_name = %(cn)s"
                f"   AND executed_at >= '{cutoff}'"
                f" GROUP BY app_name",
                {"cn": collector_name},
            )
            for r in rows.result_rows:
                name = r[0] or "unknown"
                app_errors[name] = app_errors.get(name, 0) + r[1]
                app_totals[name] = app_totals.get(name, 0) + r[2]
        except Exception:
            pass

    # Sort and limit
    sorted_errors = sorted(top_errors.items(), key=lambda x: -x[1])[:15]
    sorted_apps = sorted(
        [
            {"app": k, "errors": app_errors[k], "total": app_totals[k]}
            for k in app_errors
        ],
        key=lambda x: -x["errors"],
    )

    return {
        "status": "success",
        "data": {
            "collector_name": collector_name,
            "hours": hours,
            "top_errors": [{"message": m, "count": c} for m, c in sorted_errors],
            "app_errors": sorted_apps,
        },
    }


@router.post("/patroni/switchover")
async def patroni_switchover(
    body: dict,
    auth: dict = Depends(require_admin),
):
    """Initiate a planned Patroni switchover to a target replica."""
    import httpx

    leader = body.get("leader")
    candidate = body.get("candidate")
    if not leader or not candidate:
        return {"status": "error", "message": "Both 'leader' and 'candidate' are required."}

    # Resolve leader IP from Patroni cluster
    patroni_nodes = parse_node_list(settings.patroni_nodes)
    if not patroni_nodes:
        return {"status": "error", "message": "MONCTL_PATRONI_NODES not configured"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Find the leader node's Patroni API
            leader_ip = None
            for name, ip in patroni_nodes:
                try:
                    resp = await client.get(f"http://{ip}:8008/cluster")
                    if resp.status_code == 200:
                        cluster = resp.json()
                        for m in cluster.get("members", []):
                            if m.get("role") == "leader":
                                leader_ip = m.get("host")
                                break
                        if leader_ip:
                            break
                except Exception:
                    continue

            if not leader_ip:
                return {"status": "error", "message": "Could not find Patroni leader."}

            # Execute switchover via Patroni REST API
            resp = await client.post(
                f"http://{leader_ip}:8008/switchover",
                json={"leader": leader, "candidate": candidate},
            )
            if resp.status_code == 200:
                return {"status": "success", "data": {"message": f"Switchover initiated: {leader} → {candidate}"}}
            else:
                return {"status": "error", "message": f"Patroni returned {resp.status_code}: {resp.text}"}
    except Exception as exc:
        logger.exception("patroni_switchover_failed")
        return {"status": "error", "message": str(exc)}
