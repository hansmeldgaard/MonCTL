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
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.common.filters import ilike_filter
from monctl_central.dependencies import get_db, require_permission
from monctl_central.storage.models import AlertEntity, Incident, IncidentRule

router = APIRouter()


def _fmt_incident(
    i: Incident,
    live_by_key: dict[tuple[uuid.UUID, uuid.UUID, str], tuple[str | None, float | None]] | None = None,
) -> dict:
    rule_name = i.rule.name if i.rule else None
    rule_source = i.rule.source if i.rule else None

    # Live alert view: peak severity frozen on `i.severity` (watermark);
    # the current alert tier may differ when the underlying value has
    # moved back down. Exposed so the UI can show "peaked critical, now
    # warning". Cleared incidents get null (nothing live to compare to).
    live_severity: str | None = None
    live_current_value: float | None = None
    if live_by_key is not None and i.state == "open" and i.rule is not None:
        # Incident.entity_key is `"{assignment_id}|{suffix}"`; strip prefix.
        suffix = i.entity_key.split("|", 1)[1] if "|" in i.entity_key else ""
        key = (i.rule.definition_id, i.assignment_id, suffix)
        hit = live_by_key.get(key)
        if hit is not None:
            live_severity, live_current_value = hit

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
        "live_severity": live_severity,
        "live_current_value": live_current_value,
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


async def _load_live_by_key(
    db: AsyncSession, incidents: list[Incident]
) -> dict[tuple[uuid.UUID, uuid.UUID, str], tuple[str | None, float | None]]:
    """Batch-load live AlertEntity (severity, current_value) for open
    incidents so the list endpoint can expose peak-vs-current in one
    round-trip. Cleared incidents are skipped (no meaningful live view).
    """
    open_ones = [
        i for i in incidents if i.state == "open" and i.rule is not None
    ]
    if not open_ones:
        return {}
    def_ids = {i.rule.definition_id for i in open_ones}
    asg_ids = {i.assignment_id for i in open_ones}
    rows = (
        await db.execute(
            select(
                AlertEntity.definition_id,
                AlertEntity.assignment_id,
                AlertEntity.entity_key,
                AlertEntity.severity,
                AlertEntity.current_value,
            ).where(
                AlertEntity.definition_id.in_(def_ids),
                AlertEntity.assignment_id.in_(asg_ids),
            )
        )
    ).all()
    return {
        (def_id, asg_id, ekey or ""): (sev, cv)
        for def_id, asg_id, ekey, sev, cv in rows
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
    device_id: str | None = Query(
        default=None, description="Filter by device_id"
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
        if (c := ilike_filter(IncidentRule.name, rule_name)) is not None:
            stmt = stmt.where(c)
    if device_id:
        try:
            stmt = stmt.where(Incident.device_id == uuid.UUID(device_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid device_id")
    if device_name:
        # labels is JSONB; filter by device_name text search.
        if (
            c := ilike_filter(
                Incident.labels["device_name"].as_string(), device_name
            )
        ) is not None:
            stmt = stmt.where(c)
    if search:
        stmt = stmt.outerjoin(IncidentRule, Incident.rule_id == IncidentRule.id)
        negate = search.startswith("!")
        s = search[1:] if negate else (search[1:] if search.startswith("\\!") else search)
        if s:
            pattern = f"%{s}%"
            disj = sa.or_(
                IncidentRule.name.ilike(pattern),
                Incident.message.ilike(pattern),
                Incident.labels["device_name"].as_string().ilike(pattern),
            )
            stmt = stmt.where(sa.not_(disj) if negate else disj)

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
    live_by_key = await _load_live_by_key(db, rows)
    return {
        "status": "success",
        "data": [_fmt_incident(i, live_by_key) for i in rows],
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
    live_by_key = await _load_live_by_key(db, [incident])
    return {"status": "success", "data": _fmt_incident(incident, live_by_key)}


class BulkClearRequest(BaseModel):
    incident_ids: list[str] = Field(min_length=1, max_length=500)


@router.post("/clear")
async def clear_incidents(
    req: BulkClearRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("event", "manage")),
):
    """Manually clear one or more open incidents.

    Sets `state='cleared'`, `cleared_at=now`, `cleared_reason='manual'`
    on every open incident whose id is in the request. Already-cleared
    incidents are silently ignored. The engine will not re-open them
    automatically while the underlying alert remains firing — the next
    firing cycle treats the entity as a new incident.
    """
    try:
        ids = [uuid.UUID(i) for i in req.incident_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid incident_id")

    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Incident)
        .where(Incident.id.in_(ids), Incident.state == "open")
        .values(state="cleared", cleared_at=now, cleared_reason="manual")
    )
    return {
        "status": "success",
        "data": {"cleared": int(result.rowcount or 0)},
    }
