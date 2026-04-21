"""Audit query API — /v1/audit/*.

Exposes login events (from PostgreSQL) and mutation audit (from ClickHouse)
to the frontend and management API. All endpoints require the 'audit:view'
permission; admins and management API keys bypass as usual.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_clickhouse, get_db, require_permission
from monctl_central.storage.models import AuditLoginEvent

router = APIRouter()

_AUDIT_VIEW = require_permission("audit", "view")


def _row_to_login_dict(row: AuditLoginEvent) -> dict:
    return {
        "id": str(row.id),
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "event_type": row.event_type,
        "user_id": str(row.user_id) if row.user_id else None,
        "username": row.username,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "auth_type": row.auth_type,
        "failure_reason": row.failure_reason,
        "request_id": row.request_id,
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
    }


@router.get("/logins")
async def list_login_events(
    user_id: str | None = None,
    username: str | None = None,
    event_type: str | None = None,
    ip_address: str | None = None,
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(_AUDIT_VIEW),
):
    """List authentication audit events (login/logout/refresh)."""
    stmt = select(AuditLoginEvent)
    count_stmt = select(func.count()).select_from(AuditLoginEvent)

    if user_id:
        stmt = stmt.where(AuditLoginEvent.user_id == user_id)
        count_stmt = count_stmt.where(AuditLoginEvent.user_id == user_id)
    if username:
        stmt = stmt.where(AuditLoginEvent.username == username)
        count_stmt = count_stmt.where(AuditLoginEvent.username == username)
    if event_type:
        stmt = stmt.where(AuditLoginEvent.event_type == event_type)
        count_stmt = count_stmt.where(AuditLoginEvent.event_type == event_type)
    if ip_address:
        stmt = stmt.where(AuditLoginEvent.ip_address == ip_address)
        count_stmt = count_stmt.where(AuditLoginEvent.ip_address == ip_address)
    if from_ts:
        stmt = stmt.where(AuditLoginEvent.timestamp >= from_ts)
        count_stmt = count_stmt.where(AuditLoginEvent.timestamp >= from_ts)
    if to_ts:
        stmt = stmt.where(AuditLoginEvent.timestamp <= to_ts)
        count_stmt = count_stmt.where(AuditLoginEvent.timestamp <= to_ts)

    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(desc(AuditLoginEvent.timestamp)).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "status": "success",
        "data": [_row_to_login_dict(r) for r in rows],
        "meta": {"limit": limit, "offset": offset, "count": len(rows), "total": total},
    }


@router.get("/mutations")
async def list_mutations(
    user_id: str | None = None,
    username: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    ip_address: str | None = None,
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(_AUDIT_VIEW),
):
    """Query mutation audit events from ClickHouse."""
    ch = get_clickhouse()
    rows, total = await asyncio.to_thread(
        ch.query_audit_mutations,
        user_id=user_id,
        username=username,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        ip_address=ip_address,
        from_ts=from_ts.strftime("%Y-%m-%d %H:%M:%S") if from_ts else None,
        to_ts=to_ts.strftime("%Y-%m-%d %H:%M:%S") if to_ts else None,
        limit=limit,
        offset=offset,
    )

    # Normalize datetimes to ISO strings for JSON
    for r in rows:
        ts = r.get("timestamp")
        if hasattr(ts, "isoformat"):
            r["timestamp"] = ts.isoformat()

    return {
        "status": "success",
        "data": rows,
        "meta": {"limit": limit, "offset": offset, "count": len(rows), "total": total},
    }


@router.get("/latest")
async def latest_mutations_by_resource(
    resource_type: str,
    resource_ids: str = Query(
        ..., description="comma-separated resource ids (max 500)"
    ),
    auth: dict = Depends(_AUDIT_VIEW),
):
    """Latest audit mutation per resource_id — batch lookup for list pages."""
    ids = [s.strip() for s in resource_ids.split(",") if s.strip()]
    if not ids:
        return {"status": "success", "data": []}
    if len(ids) > 500:
        raise HTTPException(400, "too many resource_ids (max 500)")
    ch = get_clickhouse()
    rows = await asyncio.to_thread(
        ch.query_latest_mutation_per_resource,
        resource_type=resource_type,
        resource_ids=ids,
    )
    for r in rows:
        ts = r.pop("last_ts", None)
        if hasattr(ts, "isoformat"):
            r["timestamp"] = ts.isoformat()
        elif ts is not None:
            r["timestamp"] = str(ts)
    return {"status": "success", "data": rows}


@router.get("/resources/{resource_type}/{resource_id}/history")
async def resource_history(
    resource_type: str,
    resource_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(_AUDIT_VIEW),
):
    """All mutations on a specific resource, newest first."""
    ch = get_clickhouse()
    rows, total = await asyncio.to_thread(
        ch.query_audit_mutations,
        resource_type=resource_type,
        resource_id=resource_id,
        limit=limit,
        offset=offset,
    )
    for r in rows:
        ts = r.get("timestamp")
        if hasattr(ts, "isoformat"):
            r["timestamp"] = ts.isoformat()
    return {
        "status": "success",
        "data": rows,
        "meta": {"limit": limit, "offset": offset, "count": len(rows), "total": total},
    }


@router.get("/users/{user_id}/activity")
async def user_activity(
    user_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(_AUDIT_VIEW),
):
    """Combined view: recent logins + mutations for one user."""
    # Logins
    login_stmt = (
        select(AuditLoginEvent)
        .where(AuditLoginEvent.user_id == user_id)
        .order_by(desc(AuditLoginEvent.timestamp))
        .limit(limit)
    )
    login_rows = (await db.execute(login_stmt)).scalars().all()

    # Mutations
    ch = get_clickhouse()
    mut_rows, _ = await asyncio.to_thread(
        ch.query_audit_mutations, user_id=user_id, limit=limit
    )
    for r in mut_rows:
        ts = r.get("timestamp")
        if hasattr(ts, "isoformat"):
            r["timestamp"] = ts.isoformat()

    return {
        "status": "success",
        "data": {
            "logins": [_row_to_login_dict(r) for r in login_rows],
            "mutations": mut_rows,
        },
    }
