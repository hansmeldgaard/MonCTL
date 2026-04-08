"""Log ingestion and query endpoints."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from monctl_central.dependencies import require_permission, require_collector_auth, get_clickhouse

logger = structlog.get_logger()
router = APIRouter(prefix="/logs", tags=["logs"])


# ── Ingest ────────────────────────────────────────────────────────────────────

class LogEntry(BaseModel):
    timestamp: str
    source_type: str = "docker"
    container_name: str = ""
    image_name: str = ""
    level: str = "INFO"
    stream: str = "stdout"
    message: str


class LogIngestRequest(BaseModel):
    collector_id: str
    collector_name: str
    host_label: str = ""
    entries: list[LogEntry] = Field(max_length=5000)


@router.post("/ingest", tags=["collector-api"])
async def ingest_logs(
    request: LogIngestRequest,
    auth: dict = Depends(require_collector_auth),
):
    """Receive a batch of log entries from a collector."""
    if not request.entries:
        return {"status": "success", "data": {"ok": True, "ingested": 0}}

    ch = get_clickhouse()

    rows = []
    for entry in request.entries:
        rows.append({
            "timestamp": entry.timestamp,
            "collector_id": request.collector_id,
            "collector_name": request.collector_name,
            "host_label": request.host_label,
            "source_type": entry.source_type,
            "container_name": entry.container_name,
            "image_name": entry.image_name,
            "level": entry.level,
            "stream": entry.stream,
            "message": entry.message,
        })

    try:
        ch.insert("logs", rows, column_names=[
            "timestamp", "collector_id", "collector_name", "host_label",
            "source_type", "container_name", "image_name",
            "level", "stream", "message",
        ])
    except Exception as exc:
        logger.error("log_ingest_error", error=str(exc), count=len(rows))
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "success", "data": {"ok": True, "ingested": len(rows)}}


# ── Query ─────────────────────────────────────────────────────────────────────

LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


@router.get("")
async def query_logs(
    collector_name: str | None = Query(None),
    container_name: str | None = Query(None),
    host_label: str | None = Query(None),
    level: str | None = Query(None),
    source_type: str | None = Query(None),
    search: str | None = Query(None),
    from_ts: str | None = Query(None),
    to_ts: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=10, le=1000),
    sort_field: str = Query("timestamp"),
    sort_dir: str = Query("desc"),
    auth: dict = Depends(require_permission("result", "view")),
):
    """Query log entries with filtering, search, and pagination."""
    ch = get_clickhouse()

    conditions = []
    params = {}

    if collector_name:
        conditions.append("collector_name = %(collector_name)s")
        params["collector_name"] = collector_name
    if container_name:
        conditions.append("container_name = %(container_name)s")
        params["container_name"] = container_name
    if host_label:
        conditions.append("host_label = %(host_label)s")
        params["host_label"] = host_label
    if source_type:
        conditions.append("source_type = %(source_type)s")
        params["source_type"] = source_type
    if level and level in LEVEL_ORDER:
        allowed_levels = [k for k, v in LEVEL_ORDER.items() if v >= LEVEL_ORDER[level]]
        placeholders = ", ".join(f"'{lv}'" for lv in allowed_levels)
        conditions.append(f"level IN ({placeholders})")
    if search:
        conditions.append("message ILIKE %(search)s")
        params["search"] = f"%{search}%"
    if from_ts:
        conditions.append("timestamp >= %(from_ts)s")
        params["from_ts"] = from_ts
    if to_ts:
        conditions.append("timestamp <= %(to_ts)s")
        params["to_ts"] = to_ts

    where = " AND ".join(conditions) if conditions else "1=1"

    allowed_sort = {"timestamp", "collector_name", "container_name", "level", "source_type"}
    if sort_field not in allowed_sort:
        sort_field = "timestamp"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    count_sql = f"SELECT count() FROM logs WHERE {where}"
    count_result = ch.query(count_sql, parameters=params)
    total = count_result.result_rows[0][0] if count_result.result_rows else 0

    offset = (page - 1) * page_size
    data_sql = f"""
        SELECT timestamp, collector_id, collector_name, host_label,
               source_type, container_name, image_name,
               level, stream, message
        FROM logs
        WHERE {where}
        ORDER BY {sort_field} {sort_dir}
        LIMIT %(limit)s OFFSET %(offset)s
    """
    params["limit"] = page_size
    params["offset"] = offset

    result = ch.query(data_sql, parameters=params)

    entries = []
    for row in result.result_rows:
        entries.append({
            "timestamp": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
            "collector_id": str(row[1]),
            "collector_name": row[2],
            "host_label": row[3],
            "source_type": row[4],
            "container_name": row[5],
            "image_name": row[6],
            "level": row[7],
            "stream": row[8],
            "message": row[9],
        })

    return {
        "status": "success",
        "data": {
            "data": entries,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total > 0 else 0,
        },
    }


@router.get("/filters")
async def get_log_filters(
    auth: dict = Depends(require_permission("result", "view")),
):
    """Return distinct values for filter dropdowns."""
    ch = get_clickhouse()

    collectors = ch.query(
        "SELECT DISTINCT collector_name FROM logs WHERE collector_name != '' "
        "ORDER BY collector_name"
    )
    containers = ch.query(
        "SELECT DISTINCT container_name FROM logs WHERE container_name != '' "
        "ORDER BY container_name"
    )
    hosts = ch.query(
        "SELECT DISTINCT host_label FROM logs WHERE host_label != '' "
        "ORDER BY host_label"
    )

    return {
        "status": "success",
        "data": {
            "collectors": [r[0] for r in collectors.result_rows],
            "containers": [r[0] for r in containers.result_rows],
            "hosts": [r[0] for r in hosts.result_rows],
            "levels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            "source_types": ["docker", "application"],
        },
    }
