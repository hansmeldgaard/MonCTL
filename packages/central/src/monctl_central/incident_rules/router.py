"""IncidentRule CRUD at `/v1/incident-rules`.

After phase deprecation of the event policy rework, every rule is
native (operator-managed). The legacy `source='mirror'` concept —
auto-synced from `EventPolicy` via a now-retired scheduler task — has
been flipped to `source='native'` in alembic revision zq7r8s9t0u1v;
the `source_policy_id` FK and the mirror-sync job are gone.

New rules default to `source='native'`. Any pre-existing row with
`source='mirror'` (theoretical — the migration flipped them all) is
treated as fully editable just like native rules.

JSONB validation is delegated to the engine's validator helpers so the
API and engine enforce identical semantics — one place to maintain
error messages.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.common.filters import ilike_filter
from monctl_central.dependencies import get_db, require_permission
from monctl_central.incidents.engine import (
    _validate_companion_ids,
    _validate_depends_on,
    _validate_ladder,
    _validate_scope_filter,
)
from monctl_central.storage.models import AlertDefinition, IncidentRule
from monctl_common.utils import utc_now
from monctl_common.validators import validate_uuid

router = APIRouter()


_VALID_SEVERITIES = {"info", "warning", "critical", "emergency"}
_VALID_MODES = {"consecutive", "cumulative"}
_VALID_COMPANION_MODES = {"any", "all"}


# ── Formatter ────────────────────────────────────────────────


def _fmt_rule(r: IncidentRule) -> dict:
    defn_name = r.definition.name if r.definition else None
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "definition_id": str(r.definition_id),
        "definition_name": defn_name,
        "mode": r.mode,
        "fire_count_threshold": r.fire_count_threshold,
        "window_size": r.window_size,
        "severity": r.severity,
        "message_template": r.message_template,
        "auto_clear_on_resolve": r.auto_clear_on_resolve,
        # Phase-2 feature fields — may be None on phase-1-era rules.
        "severity_ladder": r.severity_ladder,
        "scope_filter": r.scope_filter,
        "depends_on": r.depends_on,
        "flap_guard_seconds": r.flap_guard_seconds,
        "clear_on_companion_ids": r.clear_on_companion_ids,
        "clear_companion_mode": r.clear_companion_mode,
        "enabled": r.enabled,
        "source": r.source,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ── Shared field validators ─────────────────────────────────


def _reject_if_ladder_invalid(raw) -> None:
    """Run `_validate_ladder` and raise 400 with the same shape it would
    log. Lets API callers see immediately what went wrong instead of
    silently storing a malformed ladder that the engine then skips."""
    if raw is None:
        return
    if _validate_ladder(raw) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid severity_ladder. Must be a non-empty list of "
                "{after_seconds, severity} with first after_seconds=0, "
                "strictly ascending after_seconds, and non-decreasing "
                "severity priority (info < warning < critical < emergency)."
            ),
        )


def _reject_if_scope_invalid(raw) -> None:
    if raw is None:
        return
    # _validate_scope_filter returns None for both "missing/empty" and
    # "malformed". To distinguish, we explicitly check the input shape
    # here so empty dict is accepted (= no filter) but malformed dicts
    # are rejected.
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=400,
            detail="scope_filter must be a flat object of string → string.",
        )
    if not raw:
        return  # empty dict is valid = no filter
    if _validate_scope_filter(raw) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid scope_filter. Must be a flat object of string → "
                "string where empty-string values act as a wildcard."
            ),
        )


def _reject_if_depends_on_invalid(raw) -> None:
    if raw is None:
        return
    if _validate_depends_on(raw) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid depends_on. Must be {rule_ids: [uuid-string, ...], "
                "match_on: [label-key, ...]} with a non-empty rule_ids list."
            ),
        )


def _reject_if_companion_ids_invalid(raw) -> None:
    """Accept None or empty list (feature disabled). Reject malformed shape."""
    if raw is None:
        return
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=400,
            detail="clear_on_companion_ids must be a list of UUID strings.",
        )
    if not raw:
        return
    if _validate_companion_ids(raw) is None:
        raise HTTPException(
            status_code=400,
            detail="clear_on_companion_ids must be a list of UUID strings.",
        )


# ── Request schemas ─────────────────────────────────────────


class CreateIncidentRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    definition_id: str
    mode: str = Field(default="consecutive")
    fire_count_threshold: int = Field(default=1, ge=1)
    window_size: int = Field(default=5, ge=1)
    severity: str = Field(default="warning", max_length=20)
    message_template: str | None = Field(default=None, max_length=2000)
    auto_clear_on_resolve: bool = True
    severity_ladder: list | None = None
    scope_filter: dict | None = None
    depends_on: dict | None = None
    flap_guard_seconds: int | None = Field(default=None, ge=0)
    clear_on_companion_ids: list[str] | None = None
    clear_companion_mode: str = Field(default="any")
    enabled: bool = True

    @field_validator("definition_id")
    @classmethod
    def check_definition_id(cls, v: str) -> str:
        validate_uuid(v, "definition_id")
        return v

    @field_validator("severity")
    @classmethod
    def check_severity(cls, v: str) -> str:
        if v not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity must be one of: {', '.join(sorted(_VALID_SEVERITIES))}"
            )
        return v

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v not in _VALID_MODES:
            raise ValueError("mode must be 'consecutive' or 'cumulative'")
        return v

    @field_validator("clear_companion_mode")
    @classmethod
    def check_companion_mode(cls, v: str) -> str:
        if v not in _VALID_COMPANION_MODES:
            raise ValueError("clear_companion_mode must be 'any' or 'all'")
        return v


class UpdateIncidentRuleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    mode: str | None = None
    fire_count_threshold: int | None = Field(default=None, ge=1)
    window_size: int | None = Field(default=None, ge=1)
    severity: str | None = Field(default=None, max_length=20)
    message_template: str | None = Field(default=None, max_length=2000)
    auto_clear_on_resolve: bool | None = None
    severity_ladder: list | None = None
    scope_filter: dict | None = None
    depends_on: dict | None = None
    flap_guard_seconds: int | None = Field(default=None, ge=0)
    clear_on_companion_ids: list[str] | None = None
    clear_companion_mode: str | None = None
    enabled: bool | None = None

    @field_validator("severity")
    @classmethod
    def check_severity(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity must be one of: {', '.join(sorted(_VALID_SEVERITIES))}"
            )
        return v

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_MODES:
            raise ValueError("mode must be 'consecutive' or 'cumulative'")
        return v

    @field_validator("clear_companion_mode")
    @classmethod
    def check_companion_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_COMPANION_MODES:
            raise ValueError("clear_companion_mode must be 'any' or 'all'")
        return v


# ── Endpoints ───────────────────────────────────────────────


@router.get("")
async def list_incident_rules(
    name: str | None = Query(default=None, description="Filter by name (ilike)"),
    definition_name: str | None = Query(
        default=None, description="Filter by alert definition name (ilike)"
    ),
    severity: str | None = Query(default=None, description="Filter by severity"),
    source: str | None = Query(
        default=None, description="Filter by source (mirror/native)"
    ),
    enabled: str | None = Query(
        default=None, description="Filter by enabled (true/false)"
    ),
    search: str | None = Query(
        default=None, description="Search name or definition name"
    ),
    sort_by: str = Query(default="name", description="Sort field"),
    sort_dir: str = Query(default="asc", description="Sort direction"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("event", "view")),
):
    stmt = select(IncidentRule).options(selectinload(IncidentRule.definition))

    if name:
        if (c := ilike_filter(IncidentRule.name, name)) is not None:
            stmt = stmt.where(c)
    if definition_name:
        stmt = stmt.join(
            AlertDefinition, IncidentRule.definition_id == AlertDefinition.id
        )
        if (c := ilike_filter(AlertDefinition.name, definition_name)) is not None:
            stmt = stmt.where(c)
    if severity:
        stmt = stmt.where(IncidentRule.severity == severity)
    if source:
        stmt = stmt.where(IncidentRule.source == source)
    if enabled is not None and enabled != "":
        stmt = stmt.where(IncidentRule.enabled == (enabled.lower() == "true"))
    if search:
        stmt = stmt.outerjoin(
            AlertDefinition, IncidentRule.definition_id == AlertDefinition.id
        )
        negate = search.startswith("!")
        s = search[1:] if negate else (search[1:] if search.startswith("\\!") else search)
        if s:
            pattern = f"%{s}%"
            disj = sa.or_(
                IncidentRule.name.ilike(pattern),
                AlertDefinition.name.ilike(pattern),
            )
            stmt = stmt.where(sa.not_(disj) if negate else disj)

    count_stmt = select(sa.func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    sort_column = {
        "name": IncidentRule.name,
        "severity": IncidentRule.severity,
        "mode": IncidentRule.mode,
        "enabled": IncidentRule.enabled,
        "source": IncidentRule.source,
        "created_at": IncidentRule.created_at,
    }.get(sort_by, IncidentRule.name)

    if sort_dir == "desc":
        stmt = stmt.order_by(sa.desc(sort_column))
    else:
        stmt = stmt.order_by(sa.asc(sort_column))

    stmt = stmt.offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().unique().all()
    return {
        "status": "success",
        "data": [_fmt_rule(r) for r in rows],
        "meta": {
            "limit": limit,
            "offset": offset,
            "count": len(rows),
            "total": total,
        },
    }


@router.get("/{rule_id}")
async def get_incident_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("event", "view")),
):
    try:
        rid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule_id")
    rule = (
        await db.execute(
            select(IncidentRule)
            .where(IncidentRule.id == rid)
            .options(selectinload(IncidentRule.definition))
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "success", "data": _fmt_rule(rule)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_incident_rule(
    req: CreateIncidentRuleRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("event", "manage")),
):
    defn = await db.get(AlertDefinition, uuid.UUID(req.definition_id))
    if not defn:
        raise HTTPException(status_code=404, detail="Alert definition not found")

    _reject_if_ladder_invalid(req.severity_ladder)
    _reject_if_scope_invalid(req.scope_filter)
    _reject_if_depends_on_invalid(req.depends_on)
    _reject_if_companion_ids_invalid(req.clear_on_companion_ids)

    rule = IncidentRule(
        name=req.name,
        description=req.description,
        definition_id=uuid.UUID(req.definition_id),
        mode=req.mode,
        fire_count_threshold=req.fire_count_threshold,
        window_size=req.window_size,
        severity=req.severity,
        message_template=req.message_template,
        auto_clear_on_resolve=req.auto_clear_on_resolve,
        severity_ladder=req.severity_ladder,
        scope_filter=req.scope_filter,
        depends_on=req.depends_on,
        flap_guard_seconds=req.flap_guard_seconds,
        clear_on_companion_ids=req.clear_on_companion_ids,
        clear_companion_mode=req.clear_companion_mode,
        enabled=req.enabled,
        source="native",
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule, ["definition"])
    return {"status": "success", "data": _fmt_rule(rule)}


@router.patch("/{rule_id}")
async def update_incident_rule(
    rule_id: str,
    req: UpdateIncidentRuleRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("event", "manage")),
):
    try:
        rid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule_id")

    rule = (
        await db.execute(
            select(IncidentRule)
            .where(IncidentRule.id == rid)
            .options(selectinload(IncidentRule.definition))
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Not found")

    # Collect fields the caller is trying to change (explicitly set in the
    # request, not just left at default None). Every field is editable —
    # the legacy mirror-rule restriction is gone (see phase deprecation).
    updates = req.model_dump(exclude_unset=True)

    # Validate JSONB shapes before mutating anything.
    if "severity_ladder" in updates:
        _reject_if_ladder_invalid(updates["severity_ladder"])
    if "scope_filter" in updates:
        _reject_if_scope_invalid(updates["scope_filter"])
    if "depends_on" in updates:
        _reject_if_depends_on_invalid(updates["depends_on"])
    if "clear_on_companion_ids" in updates:
        _reject_if_companion_ids_invalid(updates["clear_on_companion_ids"])

    for field, value in updates.items():
        setattr(rule, field, value)

    rule.updated_at = utc_now()
    await db.flush()
    await db.refresh(rule, ["definition"])
    return {"status": "success", "data": _fmt_rule(rule)}


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_incident_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("event", "manage")),
):
    try:
        rid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule_id")

    rule = await db.get(IncidentRule, rid)
    if rule is None:
        raise HTTPException(status_code=404, detail="Not found")

    await db.delete(rule)
    return None
