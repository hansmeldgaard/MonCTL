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


class DockerStatsPush(BaseModel):
    host_label: str
    timestamp: float
    stats: dict | None = None
    system: dict | None = None
    logs: dict[str, list[str]] | None = None
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

    if payload.system:
        await store_docker_push(label, "system", payload.system)

    if payload.logs:
        await append_docker_push_logs(label, payload.logs)
        # Also write to ClickHouse for centralized log collection
        try:
            ch = get_clickhouse()
            now = datetime.now(timezone.utc).isoformat()
            rows = []
            for container_name, lines in payload.logs.items():
                for line in lines:
                    rows.append({
                        "timestamp": now,
                        "collector_id": "00000000-0000-0000-0000-000000000000",
                        "collector_name": label,
                        "host_label": label,
                        "source_type": "docker",
                        "container_name": container_name,
                        "image_name": "",
                        "level": _detect_level(line),
                        "stream": "stdout",
                        "message": line,
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
