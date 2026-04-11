"""Legacy CH events query / acknowledge / clear endpoints.

After phase deprecation (see docs/event-policy-rework.md) the
EventPolicy CRUD endpoints and EventEngine are gone. This router
keeps the read/acknowledge/clear surface so the Events UI can still
query the append-only CH events table for historical observation.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from monctl_central.dependencies import get_clickhouse, require_permission
from monctl_central.storage.clickhouse import ClickHouseClient

router = APIRouter()


# ── Formatters ────────────────────────────────────────────


def _fmt_event(e: dict) -> dict:
    data = e.get("data", "{}")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            data = {}

    def _ts(v) -> str | None:
        if v is None:
            return None
        s = str(v)
        if s.startswith("1970") or s.startswith("0001"):
            return None
        return s

    return {
        "id": str(e.get("id", "")),
        "event_type": e.get("event_type", ""),
        "definition_id": str(e.get("definition_id", "")),
        "definition_name": e.get("definition_name", ""),
        "policy_id": str(e.get("policy_id", "")),
        "policy_name": e.get("policy_name", ""),
        "collector_id": str(e.get("collector_id", "")),
        "device_id": str(e.get("device_id", "")),
        "app_id": str(e.get("app_id", "")),
        "source": e.get("source", ""),
        "severity": e.get("severity", "info"),
        "message": e.get("message", ""),
        "data": data,
        "state": e.get("state", "active"),
        "occurred_at": _ts(e.get("occurred_at")),
        "received_at": _ts(e.get("received_at")),
        "acknowledged_at": _ts(e.get("acknowledged_at")),
        "acknowledged_by": e.get("acknowledged_by") or None,
        "cleared_at": _ts(e.get("cleared_at")),
        "cleared_by": e.get("cleared_by") or None,
        "collector_name": e.get("collector_name", ""),
        "device_name": e.get("device_name", ""),
        "app_name": e.get("app_name", ""),
    }


# ── Event queries ─────────────────────────────────────────


@router.get("")
async def list_events(
    state: str | None = Query(None),
    severity: str | None = Query(None),
    device_id: str | None = Query(None),
    message: str | None = Query(default=None),
    source: str | None = Query(default=None),
    sort_by: str = Query(default="occurred_at"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_permission("event", "view")),
):
    total = await asyncio.to_thread(
        ch.count_events, state=state, severity=severity,
        device_id=device_id, message=message, source=source,
    )
    rows = await asyncio.to_thread(
        ch.query_events, state=state, severity=severity,
        device_id=device_id, limit=limit, message=message, source=source,
        sort_by=sort_by, sort_dir=sort_dir, offset=offset,
    )
    return {
        "status": "success",
        "data": [_fmt_event(r) for r in rows],
        "meta": {"limit": limit, "offset": offset, "count": len(rows), "total": total},
    }


@router.get("/active")
async def list_active_events(
    severity: str | None = Query(None),
    device_id: str | None = Query(None),
    message: str | None = Query(default=None),
    source: str | None = Query(default=None),
    device_name: str | None = Query(default=None),
    policy_name: str | None = Query(default=None),
    definition_name: str | None = Query(default=None),
    sort_by: str = Query(default="occurred_at"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_permission("event", "view")),
):
    total = await asyncio.to_thread(
        ch.count_events, state="active", severity=severity,
        device_id=device_id, message=message, source=source,
        device_name=device_name, policy_name=policy_name,
        definition_name=definition_name,
    )
    rows = await asyncio.to_thread(
        ch.query_events, state="active", severity=severity,
        device_id=device_id, limit=limit, message=message, source=source,
        device_name=device_name, policy_name=policy_name,
        definition_name=definition_name,
        sort_by=sort_by, sort_dir=sort_dir, offset=offset,
    )
    return {
        "status": "success",
        "data": [_fmt_event(r) for r in rows],
        "meta": {"limit": limit, "offset": offset, "count": len(rows), "total": total},
    }


@router.get("/cleared")
async def list_cleared_events(
    severity: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    message: str | None = Query(default=None),
    source: str | None = Query(default=None),
    device_name: str | None = Query(default=None),
    policy_name: str | None = Query(default=None),
    definition_name: str | None = Query(default=None),
    sort_by: str = Query(default="occurred_at"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_permission("event", "view")),
):
    total = await asyncio.to_thread(
        ch.count_events, state="cleared", severity=severity,
        device_id=device_id, message=message, source=source,
        device_name=device_name, policy_name=policy_name,
        definition_name=definition_name,
    )
    rows = await asyncio.to_thread(
        ch.query_events, state="cleared", severity=severity,
        device_id=device_id, limit=limit, message=message, source=source,
        device_name=device_name, policy_name=policy_name,
        definition_name=definition_name,
        sort_by=sort_by, sort_dir=sort_dir, offset=offset,
    )
    return {
        "status": "success",
        "data": [_fmt_event(r) for r in rows],
        "meta": {"limit": limit, "offset": offset, "count": len(rows), "total": total},
    }


# ── Event actions ─────────────────────────────────────────


class BulkEventActionRequest(BaseModel):
    event_ids: list[str] = Field(min_length=1, max_length=500)


@router.post("/acknowledge")
async def acknowledge_events(
    req: BulkEventActionRequest,
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_permission("event", "manage")),
):
    actor = auth.get("username", "unknown")
    await asyncio.to_thread(ch.update_event_state, req.event_ids, "acknowledged", actor)
    return {"status": "success", "data": {"acknowledged": len(req.event_ids)}}


@router.post("/clear")
async def clear_events(
    req: BulkEventActionRequest,
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_permission("event", "manage")),
):
    actor = auth.get("username", "unknown")
    await asyncio.to_thread(ch.update_event_state, req.event_ids, "cleared", actor)
    return {"status": "success", "data": {"cleared": len(req.event_ids)}}


# EventPolicy CRUD was removed in the phase deprecation of the event
# policy rework. Rule configuration lives at /v1/incident-rules now.
# See docs/event-policy-rework.md.
