"""Receive docker-stats push data from worker sidecars.

Workers push consolidated docker-stats payloads to central because central
cannot reach workers (network is one-way: workers → central VIP only).
Data is stored in Redis with a short TTL and served via the docker_infra router.
Logs are also written to ClickHouse for centralized log collection.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from monctl_central.cache import (
    append_docker_push_events,
    append_docker_push_logs,
    store_docker_push,
)
from monctl_central.dependencies import get_clickhouse, require_collector_auth as require_auth

router = APIRouter()
logger = structlog.get_logger()

_LEVEL_KEYWORDS = {
    "CRITICAL": ("CRITICAL", "FATAL"),
    "ERROR": ("ERROR", "ERR "),
    "WARNING": ("WARNING", "WARN "),
    "DEBUG": ("DEBUG",),
}


def _detect_level(message: str) -> str:
    upper = message.upper()[:100]
    for level, keywords in _LEVEL_KEYWORDS.items():
        if any(kw in upper for kw in keywords):
            return level
    return "INFO"


def _infer_host_role(label: str) -> str:
    """Classify a host_label into central / worker / other for filtering.

    Labels follow the hostname convention (central1-4, worker1-4) — we
    stay lenient here so a future rename doesn't silently drop everything
    into 'other'.
    """
    """Classify a host_label into central / worker / other."""
    lower = label.lower()
    if "central" in lower:
        return "central"
    if "worker" in lower or "collector" in lower:
        return "worker"
    return "other"


def _as_int(val) -> int:
    try:
        return max(int(val), 0) if val is not None else 0
    except (TypeError, ValueError):
        return 0


def _as_float(val) -> float:
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _host_metrics_row(label: str, payload: DockerStatsPush) -> dict:
    """Flatten the sidecar's system payload into host_metrics_history columns."""
    sys = payload.system or {}
    host = sys.get("host") or {}
    containers = sys.get("containers") or {}
    load = host.get("load_avg") or {}

    mem_total = _as_int(host.get("mem_total_bytes"))
    mem_available = _as_int(host.get("mem_available_bytes"))
    mem_used = max(mem_total - mem_available, 0) if mem_total else 0
    swap_total = _as_int(host.get("swap_total_bytes"))
    swap_free = _as_int(host.get("swap_free_bytes"))
    swap_used = max(swap_total - swap_free, 0) if swap_total else 0

    ts = datetime.fromtimestamp(payload.timestamp, tz=timezone.utc).replace(
        microsecond=0, tzinfo=None,
    )

    return {
        "timestamp": ts,
        "host_label": label,
        "host_role": _infer_host_role(label),
        "cpu_count": _as_int(host.get("cpu_count")),
        "load_1m": _as_float(load.get("1m")),
        "load_5m": _as_float(load.get("5m")),
        "load_15m": _as_float(load.get("15m")),
        "mem_total_bytes": mem_total,
        "mem_used_bytes": mem_used,
        "mem_available_bytes": mem_available,
        "swap_total_bytes": swap_total,
        "swap_used_bytes": swap_used,
        "disk_total_bytes": _as_int(host.get("disk_total_bytes")),
        "disk_used_bytes": _as_int(host.get("disk_used_bytes")),
        "disk_free_bytes": _as_int(host.get("disk_free_bytes")),
        "uptime_seconds": _as_int(host.get("uptime_seconds")),
        "containers_running": _as_int(containers.get("running")),
        "containers_total": _as_int(containers.get("total")),
    }
def _container_metric_rows(label: str, payload: "DockerStatsPush") -> list[dict]:
    """Flatten payload.stats.containers[] into container_metrics_history rows.

    Only rows for running containers with valid mem_usage are emitted —
    the sidecar leaves cpu_pct/mem_usage None for stopped containers and
    we don't want to persist NULL noise.
    """
    stats = payload.stats or {}
    containers = stats.get("containers") or []
    role = _infer_host_role(label)
    ts = datetime.fromtimestamp(payload.timestamp, tz=timezone.utc).replace(
        microsecond=0, tzinfo=None,
    )
    rows: list[dict] = []
    for c in containers:
        if c.get("mem_usage_bytes") is None:
            continue
        rows.append({
            "timestamp": ts,
            "host_label": label,
            "host_role": role,
            "container_name": str(c.get("name") or ""),
            "image": str(c.get("image") or ""),
            "status": str(c.get("status") or ""),
            "cpu_pct": _as_float(c.get("cpu_pct")),
            "mem_usage_bytes": _as_int(c.get("mem_usage_bytes")),
            "mem_limit_bytes": _as_int(c.get("mem_limit_bytes")),
            "mem_pct": _as_float(c.get("mem_pct")),
            "net_rx_bytes": _as_int(c.get("net_rx_bytes")),
            "net_tx_bytes": _as_int(c.get("net_tx_bytes")),
            "block_read_bytes": _as_int(c.get("block_read_bytes")),
            "block_write_bytes": _as_int(c.get("block_write_bytes")),
            "pids": _as_int(c.get("pids")),
            "restart_count": _as_int(c.get("restart_count")),
        })
    return rows


class DockerStatsPush(BaseModel):
    host_label: str
    timestamp: float
    stats: dict | None = None
    system: dict | None = None
    logs: dict[str, list] | None = None
    events: list[dict] | None = None
    images: dict | None = None


@router.post("/docker-stats/push")
async def push_docker_stats(
    payload: DockerStatsPush,
    auth: dict = Depends(require_auth),
):
    """Receive consolidated docker-stats data from a worker sidecar."""
    label = payload.host_label

    # Store _meta for host discovery
    await store_docker_push(label, "_meta", {
        "host_label": label,
        "last_push": payload.timestamp,
        "received_at": time.time(),
    })

    if payload.stats:
        await store_docker_push(label, "stats", payload.stats)
        # Persist per-container metrics so we can trace leaks / load
        # after-the-fact (e.g. forwarder RSS over 24h). One row per
        # running container per push.
        try:
            rows = _container_metric_rows(label, payload)
            if rows:
                ch = get_clickhouse()
                ch.insert_container_metrics(rows)
        except Exception:
            logger.debug("docker_push_container_metrics_ch_failed", label=label)

    if payload.system:
        await store_docker_push(label, "system", payload.system)
        # Persist a historical sample for capacity planning / post-hoc
        # "was this node saturated at T?" queries. One row per push.
        try:
            ch = get_clickhouse()
            ch.insert_host_metrics([_host_metrics_row(label, payload)])
        except Exception:
            logger.debug("docker_push_host_metrics_ch_failed", label=label)

    if payload.logs:
        await append_docker_push_logs(label, payload.logs)
        # Also write to ClickHouse for centralized log collection
        try:
            ch = get_clickhouse()
            now = datetime.now(timezone.utc).isoformat()
            rows = []
            for container_name, lines in payload.logs.items():
                for line in lines:
                    # Lines can be plain strings or dicts with timestamp/message
                    if isinstance(line, dict):
                        msg = line.get("message", "")
                        ts = line.get("timestamp", now)
                    else:
                        msg = str(line)
                        ts = now
                    rows.append({
                        "timestamp": ts,
                        "collector_id": "00000000-0000-0000-0000-000000000000",
                        "collector_name": label,
                        "host_label": label,
                        "source_type": "docker",
                        "container_name": container_name,
                        "image_name": "",
                        "level": _detect_level(msg),
                        "stream": line.get("stream", "stdout") if isinstance(line, dict) else "stdout",
                        "message": msg,
                    })
            if rows:
                ch.insert("logs", rows, column_names=[
                    "timestamp", "collector_id", "collector_name", "host_label",
                    "source_type", "container_name", "image_name",
                    "level", "stream", "message",
                ])
        except Exception:
            logger.debug("docker_push_logs_ch_failed", label=label)

    if payload.events:
        await append_docker_push_events(label, payload.events)

    if payload.images is not None:
        await store_docker_push(label, "images", payload.images)

    return {"status": "ok"}
