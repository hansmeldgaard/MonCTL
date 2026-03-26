"""Analytics SQL explorer — read-only ClickHouse proxy and schema browser."""

from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from monctl_central.dependencies import get_clickhouse, require_auth

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# SQL safety
# ---------------------------------------------------------------------------

_ALLOWED_PREFIXES = re.compile(
    r"^\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b",
    re.IGNORECASE,
)

_BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|RENAME|ATTACH|DETACH"
    r"|GRANT|REVOKE|KILL|OPTIMIZE|SYSTEM|SET)\b",
    re.IGNORECASE,
)

_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)

DEFAULT_LIMIT = 1000
MAX_LIMIT = 10000


def _validate_sql(sql: str) -> str:
    """Ensure SQL is read-only and inject LIMIT if missing."""
    stripped = sql.strip().rstrip(";")

    if not _ALLOWED_PREFIXES.match(stripped):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only SELECT, WITH, SHOW, DESCRIBE, and EXPLAIN queries are allowed.",
        )

    if _BLOCKED_KEYWORDS.search(stripped):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query contains a disallowed mutating keyword.",
        )

    # Inject LIMIT if not present
    if not _LIMIT_RE.search(stripped):
        stripped = f"{stripped}\nLIMIT {DEFAULT_LIMIT}"

    return stripped


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=50000)
    limit: int | None = Field(default=None, ge=1, le=MAX_LIMIT)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/query")
async def run_query(
    body: QueryRequest,
    auth: dict = Depends(require_auth),
):
    """Execute a read-only SQL query against ClickHouse."""
    sql = _validate_sql(body.sql)

    # Override default limit if caller specified one
    if body.limit is not None:
        if _LIMIT_RE.search(sql):
            sql = _LIMIT_RE.sub(f"LIMIT {body.limit}", sql)
        else:
            sql = f"{sql}\nLIMIT {body.limit}"

    import time as _time

    ch = get_clickhouse()
    client = ch._get_client()

    query_settings = {
        "readonly": 1,
        "max_execution_time": 30,
    }

    t0 = _time.monotonic()
    try:
        result = await asyncio.to_thread(
            client.query, sql, settings=query_settings,
        )
    except Exception as exc:
        msg = str(exc)
        # Categorise common ClickHouse errors
        if "SYNTAX_ERROR" in msg or "Syntax error" in msg:
            raise HTTPException(status_code=400, detail=f"SQL syntax error: {msg}")
        if "UNKNOWN_TABLE" in msg or "Table" in msg and "doesn't exist" in msg:
            raise HTTPException(status_code=400, detail=f"Unknown table: {msg}")
        if "TIMEOUT_EXCEEDED" in msg or "timeout" in msg.lower():
            raise HTTPException(status_code=408, detail=f"Query timed out: {msg}")
        logger.exception("ClickHouse query failed")
        raise HTTPException(status_code=400, detail=f"Query error: {msg}")

    columns = [
        {"name": name, "type": getattr(col_type, "name", None) or str(col_type)}
        for name, col_type in zip(result.column_names, result.column_types)
    ]

    elapsed_ms = round((_time.monotonic() - t0) * 1000, 1)

    # Convert rows to serialisable lists
    rows = []
    for row in result.result_rows:
        rows.append([_serialise(v) for v in row])

    limit = body.limit or 1000
    return {
        "status": "success",
        "data": {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": len(rows) >= limit,
            "execution_time_ms": elapsed_ms,
            "query": body.sql,
        },
    }


def _serialise(value):
    """Make ClickHouse values JSON-serialisable."""
    import datetime
    import decimal
    import uuid as _uuid

    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, _uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [_serialise(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialise(v) for k, v in value.items()}
    return str(value)


@router.get("/tables")
async def list_tables(
    auth: dict = Depends(require_auth),
):
    """Browse ClickHouse schema — tables and columns for the monctl database."""
    ch = get_clickhouse()
    client = ch._get_client()

    query_settings = {"readonly": 1, "max_execution_time": 10}

    try:
        tables_result = await asyncio.to_thread(
            client.query,
            "SELECT name, engine, total_rows, total_bytes "
            "FROM system.tables "
            "WHERE database = {db:String} "
            "ORDER BY name",
            parameters={"db": ch._database},
            settings=query_settings,
        )

        columns_result = await asyncio.to_thread(
            client.query,
            "SELECT table, name, type, position "
            "FROM system.columns "
            "WHERE database = {db:String} "
            "ORDER BY table, position",
            parameters={"db": ch._database},
            settings=query_settings,
        )
    except Exception as exc:
        logger.exception("Failed to query ClickHouse schema")
        raise HTTPException(status_code=500, detail=f"Schema query failed: {exc}")

    # Index columns by table
    columns_by_table: dict[str, list[dict]] = {}
    for row in columns_result.named_results():
        tbl = row["table"]
        columns_by_table.setdefault(tbl, []).append({
            "name": row["name"],
            "type": row["type"],
            "position": row["position"],
        })

    tables = []
    for row in tables_result.named_results():
        tables.append({
            "name": row["name"],
            "engine": row["engine"],
            "total_rows": row["total_rows"],
            "total_bytes": row["total_bytes"],
            "columns": columns_by_table.get(row["name"], []),
        })

    return {"status": "success", "data": tables}
