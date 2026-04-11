"""Read-only API over the `incidents` PG table — phase 3d of the event policy rework.

Incidents are the IncidentEngine's primary output: persistent rows that
track an alert-definition-level condition over time. Each row carries
rule metadata, the firing state, the incident lifecycle state
(open/cleared), and a `parent_incident_id` link for suppression under a
parent.

This endpoint is the UI-side read channel for the incidents tree view
shipped in phase 3d. No mutation endpoints — the engine owns the write
path entirely.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_db, require_permission
from monctl_central.storage.models import Incident, IncidentRule

router = APIRouter()


def _fmt_incident(i: Incident) -> dict:
    rule_name = i.rule.name if i.rule else None
    rule_source = i.rule.source if i.rule else None
    return {
        "id": str(i.id),
        "rule_id": str(i.rule_id),
        "rule_name": rule_name,
        "rule_source": rule_source,
        "entity_key": i.entity_key,
        "assignment_id": str(i.assignment_id),
        "device_id": str(i.device_id) if i.device_id else None,
        "state": i.state,
        "severity": i.severity,
        "message": i.message,
        "labels": i.labels or {},
        "fire_count": i.fire_count,
        "opened_at": i.opened_at.isoformat() if i.opened_at else None,
        "last_fired_at": i.last_fired_at.isoformat() if i.last_fired_at else None,
        "cleared_at": i.cleared_at.isoformat() if i.cleared_at else None,
        "cleared_reason": i.cleared_reason,
        "correlation_key": i.correlation_key,
        "parent_incident_id": (
            str(i.parent_incident_id) if i.parent_incident_id else None
        ),
        "severity_reached_at": (
            i.severity_reached_at.isoformat() if i.severity_reached_at else None
        ),
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
    }


@router.get("")
async def list_incidents(
    state: str | None = Query(
        default=None, description="Filter by lifecycle state (open / cleared)"
    ),
    severity: str | None = Query(default=None, description="Filter by severity"),
    rule_id: str | None = Query(default=None, description="Filter by rule_id"),
    rule_name: str | None = Query(
        default=None, description="Filter by rule name (ilike)"
    ),
    device_name: str | None = Query(
        default=None, description="Filter by device_name label (ilike)"
    ),
    search: str | None = Query(
        default=None, description="Search rule name / message / device"
    ),
    sort_by: str = Query(default="opened_at", description="Sort field"),
    sort_dir: str = Query(default="desc", description="Sort direction"),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("event", "view")),
):
    stmt = select(Incident).options(selectinload(Incident.rule))

    if state is not None and state != "":
        if state not in ("open", "cleared"):
            raise HTTPException(
                status_code=400, detail="state must be 'open' or 'cleared'"
            )
        stmt = stmt.where(Incident.state == state)
    if severity:
        stmt = stmt.where(Incident.severity == severity)
    if rule_id:
        try:
            stmt = stmt.where(Incident.rule_id == uuid.UUID(rule_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid rule_id")
    if rule_name:
        stmt = stmt.join(IncidentRule, Incident.rule_id == IncidentRule.id)
        stmt = stmt.where(IncidentRule.name.ilike(f"%{rule_name}%"))
    if device_name:
        # labels is JSONB; filter by device_name text search.
        stmt = stmt.where(
            Incident.labels["device_name"].as_string().ilike(f"%{device_name}%")
        )
    if search:
        stmt = stmt.outerjoin(IncidentRule, Incident.rule_id == IncidentRule.id)
        stmt = stmt.where(
            sa.or_(
                IncidentRule.name.ilike(f"%{search}%"),
                Incident.message.ilike(f"%{search}%"),
                Incident.labels["device_name"].as_string().ilike(f"%{search}%"),
            )
        )

    count_stmt = select(sa.func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Sort. Primary incidents (parent_incident_id IS NULL) come first when
    # sorting by opened_at so the tree view renders primaries together.
    sort_column = {
        "opened_at": Incident.opened_at,
        "last_fired_at": Incident.last_fired_at,
        "severity": Incident.severity,
        "state": Incident.state,
        "fire_count": Incident.fire_count,
    }.get(sort_by, Incident.opened_at)

    if sort_dir == "asc":
        stmt = stmt.order_by(sa.asc(sort_column))
    else:
        stmt = stmt.order_by(sa.desc(sort_column))

    stmt = stmt.offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().unique().all()
    return {
        "status": "success",
        "data": [_fmt_incident(i) for i in rows],
        "meta": {
            "limit": limit,
            "offset": offset,
            "count": len(rows),
            "total": total,
        },
    }


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("event", "view")),
):
    try:
        iid = uuid.UUID(incident_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid incident_id")
    incident = (
        await db.execute(
            select(Incident)
            .where(Incident.id == iid)
            .options(selectinload(Incident.rule))
        )
    ).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "success", "data": _fmt_incident(incident)}
