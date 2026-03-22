"""Events and event policies — query, acknowledge, clear, policy CRUD."""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from monctl_common.validators import validate_uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_clickhouse, get_db, require_auth
from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import AlertDefinition, EventPolicy
from monctl_common.utils import utc_now

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


def _fmt_policy(p: EventPolicy) -> dict:
    defn_name = ""
    if p.definition:
        defn_name = p.definition.name
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "definition_id": str(p.definition_id),
        "definition_name": defn_name,
        "mode": p.mode,
        "fire_count_threshold": p.fire_count_threshold,
        "window_size": p.window_size,
        "event_severity": p.event_severity,
        "message_template": p.message_template,
        "auto_clear_on_resolve": p.auto_clear_on_resolve,
        "enabled": p.enabled,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
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
    auth: dict = Depends(require_auth),
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
    sort_by: str = Query(default="occurred_at"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_auth),
):
    total = await asyncio.to_thread(
        ch.count_events, state="active", severity=severity,
        device_id=device_id, message=message, source=source,
    )
    rows = await asyncio.to_thread(
        ch.query_events, state="active", severity=severity,
        device_id=device_id, limit=limit, message=message, source=source,
        sort_by=sort_by, sort_dir=sort_dir, offset=offset,
    )
    return {
        "status": "success",
        "data": [_fmt_event(r) for r in rows],
        "meta": {"limit": limit, "offset": offset, "count": len(rows), "total": total},
    }


@router.get("/cleared")
async def list_cleared_events(
    message: str | None = Query(default=None),
    source: str | None = Query(default=None),
    sort_by: str = Query(default="occurred_at"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_auth),
):
    total = await asyncio.to_thread(
        ch.count_events, state="cleared", message=message, source=source,
    )
    rows = await asyncio.to_thread(
        ch.query_events, state="cleared", limit=limit, message=message, source=source,
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
    auth: dict = Depends(require_auth),
):
    actor = auth.get("username", "unknown")
    await asyncio.to_thread(ch.update_event_state, req.event_ids, "acknowledged", actor)
    return {"status": "success", "data": {"acknowledged": len(req.event_ids)}}


@router.post("/clear")
async def clear_events(
    req: BulkEventActionRequest,
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_auth),
):
    actor = auth.get("username", "unknown")
    await asyncio.to_thread(ch.update_event_state, req.event_ids, "cleared", actor)
    return {"status": "success", "data": {"cleared": len(req.event_ids)}}


# ── Event Policies CRUD ──────────────────────────────────


class CreateEventPolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    definition_id: str
    mode: str = Field(default="consecutive")
    fire_count_threshold: int = Field(default=1, ge=1)
    window_size: int = Field(default=5, ge=1)
    event_severity: str = Field(default="warning", max_length=20)
    message_template: str | None = Field(default=None, max_length=2000)
    auto_clear_on_resolve: bool = True
    enabled: bool = True

    @field_validator("definition_id")
    @classmethod
    def check_definition_id(cls, v: str) -> str:
        validate_uuid(v, "definition_id")
        return v

    @field_validator("event_severity")
    @classmethod
    def check_severity(cls, v: str) -> str:
        if v not in {"info", "warning", "critical", "emergency", "recovery"}:
            raise ValueError("event_severity must be one of: info, warning, critical, emergency, recovery")
        return v

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v not in {"consecutive", "sliding_window"}:
            raise ValueError("mode must be 'consecutive' or 'sliding_window'")
        return v


class UpdateEventPolicyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    mode: str | None = None
    fire_count_threshold: int | None = None
    window_size: int | None = None
    event_severity: str | None = Field(default=None, max_length=20)
    message_template: str | None = Field(default=None, max_length=2000)
    auto_clear_on_resolve: bool | None = None
    enabled: bool | None = None

    @field_validator("event_severity")
    @classmethod
    def check_severity(cls, v: str | None) -> str | None:
        if v is not None and v not in {"info", "warning", "critical", "emergency", "recovery"}:
            raise ValueError("event_severity must be one of: info, warning, critical, emergency, recovery")
        return v

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in {"consecutive", "sliding_window"}:
            raise ValueError("mode must be 'consecutive' or 'sliding_window'")
        return v


@router.get("/policies")
async def list_event_policies(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    rows = (
        await db.execute(
            select(EventPolicy)
            .options(selectinload(EventPolicy.definition))
            .order_by(EventPolicy.name)
        )
    ).scalars().all()
    return {"status": "success", "data": [_fmt_policy(p) for p in rows]}


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_event_policy(
    req: CreateEventPolicyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    defn = await db.get(AlertDefinition, uuid.UUID(req.definition_id))
    if not defn:
        raise HTTPException(status_code=404, detail="Alert definition not found")

    if req.mode not in ("consecutive", "cumulative"):
        raise HTTPException(status_code=400, detail="Mode must be 'consecutive' or 'cumulative'")

    policy = EventPolicy(
        name=req.name,
        description=req.description,
        definition_id=uuid.UUID(req.definition_id),
        mode=req.mode,
        fire_count_threshold=req.fire_count_threshold,
        window_size=req.window_size,
        event_severity=req.event_severity,
        message_template=req.message_template,
        auto_clear_on_resolve=req.auto_clear_on_resolve,
        enabled=req.enabled,
    )
    db.add(policy)
    await db.flush()
    # Reload with relationship
    await db.refresh(policy, ["definition"])
    return {"status": "success", "data": _fmt_policy(policy)}


@router.put("/policies/{policy_id}")
async def update_event_policy(
    policy_id: str,
    req: UpdateEventPolicyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    policy = await db.get(EventPolicy, uuid.UUID(policy_id))
    if not policy:
        raise HTTPException(status_code=404, detail="Not found")

    if req.name is not None:
        policy.name = req.name
    if req.description is not None:
        policy.description = req.description
    if req.mode is not None:
        if req.mode not in ("consecutive", "cumulative"):
            raise HTTPException(status_code=400, detail="Mode must be 'consecutive' or 'cumulative'")
        policy.mode = req.mode
    if req.fire_count_threshold is not None:
        policy.fire_count_threshold = req.fire_count_threshold
    if req.window_size is not None:
        policy.window_size = req.window_size
    if req.event_severity is not None:
        policy.event_severity = req.event_severity
    if req.message_template is not None:
        policy.message_template = req.message_template
    if req.auto_clear_on_resolve is not None:
        policy.auto_clear_on_resolve = req.auto_clear_on_resolve
    if req.enabled is not None:
        policy.enabled = req.enabled

    policy.updated_at = utc_now()
    await db.refresh(policy, ["definition"])
    return {"status": "success", "data": _fmt_policy(policy)}


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_policy(
    policy_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    policy = await db.get(EventPolicy, uuid.UUID(policy_id))
    if not policy:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(policy)
