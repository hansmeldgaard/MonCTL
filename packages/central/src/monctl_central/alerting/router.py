"""App-level alert definitions, instances, and threshold overrides."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from monctl_common.validators import validate_alert_window, validate_uuid
import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.alerting.dsl import invert_expression, validate_expression
from monctl_central.alerting.instance_sync import sync_instances_for_definition
from monctl_central.alerting.threshold_sync import sync_threshold_variables
from monctl_central.common.filters import ilike_filter
from monctl_central.dependencies import get_clickhouse, get_db, require_permission
from monctl_central.storage.models import (
    AlertEntity,
    App,
    AlertDefinition,
    AppAssignment,
    ThresholdOverride,
    ThresholdVariable,
)
from monctl_common.utils import utc_now

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────


def _ensure_utc(rows: list[dict]) -> list[dict]:
    """Ensure datetime values from ClickHouse carry a UTC marker.

    ClickHouse returns naive Python datetimes (no tzinfo). FastAPI
    serialises them as `"2026-04-11T08:30:10"` without a `Z` suffix.
    JavaScript's `new Date("...")` then parses that as *browser-local
    time* rather than UTC, producing a timezone-dependent shift.

    This helper walks each dict, finds `datetime` values, and replaces
    them with UTC-aware equivalents so FastAPI emits `"...+00:00"`.
    Runs in O(rows × columns); the overhead is negligible for the
    typical ≤1000 rows returned by alert log / entity queries.
    """
    for row in rows:
        for key, val in row.items():
            if isinstance(val, datetime) and val.tzinfo is None:
                row[key] = val.replace(tzinfo=timezone.utc)
    return rows


# ── Formatters ───────────────────────────────────────────

def _fmt_definition(d: AlertDefinition, instance_counts: dict | None = None) -> dict:
    result = {
        "id": str(d.id),
        "app_id": str(d.app_id),
        "app_name": d.app.name if d.app else None,
        "name": d.name,
        "description": d.description,
        "severity_tiers": d.severity_tiers or [],
        "window": d.window,
        "enabled": d.enabled,
        "pack_origin": d.pack_origin,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }
    if instance_counts:
        result["instance_count"] = instance_counts.get(d.id, {}).get("total", 0)
        result["firing_count"] = instance_counts.get(d.id, {}).get("firing", 0)
    return result


def _display_state(internal_state: str) -> str | None:
    if internal_state == "firing":
        return "active"
    if internal_state == "resolved":
        return "cleared"
    return None


def _fmt_entity(i: AlertEntity) -> dict:
    return {
        "id": str(i.id),
        "definition_id": str(i.definition_id),
        "assignment_id": str(i.assignment_id),
        "device_id": str(i.device_id) if i.device_id else None,
        "enabled": i.enabled,
        "state": i.state,
        "severity": i.severity,
        "display_state": _display_state(i.state),
        "current_value": i.current_value,
        "fire_count": i.fire_count,
        "fire_history": i.fire_history,
        "last_evaluated_at": i.last_evaluated_at.isoformat() if i.last_evaluated_at else None,
        "started_firing_at": i.started_firing_at.isoformat() if i.started_firing_at else None,
        "current_state_since": i.current_state_since.isoformat() if i.current_state_since else None,
        "last_triggered_at": i.last_triggered_at.isoformat() if i.last_triggered_at else None,
        "last_cleared_at": i.last_cleared_at.isoformat() if i.last_cleared_at else None,
        "entity_key": i.entity_key,
        "entity_labels": i.entity_labels,
        "metric_values": i.metric_values or {},
        "threshold_values": i.threshold_values or {},
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


def _fmt_override(o: ThresholdOverride) -> dict:
    return {
        "id": str(o.id),
        "variable_id": str(o.variable_id),
        "device_id": str(o.device_id),
        "entity_key": o.entity_key,
        "value": o.value,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


# ── Request models ───────────────────────────────────────

class SeverityTier(BaseModel):
    severity: str = Field(min_length=1, max_length=20)
    # Healthy tiers use expression=None; non-healthy tiers require a
    # DSL expression. See _validate_tier_list.
    expression: str | None = Field(default=None, max_length=2000)
    message_template: str = Field(min_length=1, max_length=2000)

    @field_validator("severity")
    @classmethod
    def check_severity(cls, v: str) -> str:
        allowed = ("info", "warning", "critical", "emergency", "healthy")
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v


def _validate_tier_list(tiers: list[SeverityTier]) -> None:
    """Cross-tier invariants: at most one healthy tier, non-healthy tiers
    must have an expression, severities unique.

    The healthy tier may OPTIONALLY carry an expression — when set, it
    acts as a POSITIVE CLEAR signal (engine only clears an active alert
    when this expression matches). When omitted, the engine falls back
    to the legacy auto-clear on any non-matching cycle.
    """
    seen: set[str] = set()
    healthy_count = 0
    for i, t in enumerate(tiers):
        if t.severity in seen:
            raise ValueError(f"duplicate severity '{t.severity}' at severity_tiers[{i}]")
        seen.add(t.severity)
        if t.severity == "healthy":
            healthy_count += 1
        else:
            if not t.expression:
                raise ValueError(f"severity_tiers[{i}] requires an expression")
    if healthy_count > 1:
        raise ValueError("at most one healthy tier is allowed")


class CreateAlertDefinitionRequest(BaseModel):
    app_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    severity_tiers: list[SeverityTier] = Field(min_length=1)
    window: str = Field(default="5m", max_length=10)
    enabled: bool = True

    @field_validator("app_id")
    @classmethod
    def check_app_id(cls, v: str) -> str:
        validate_uuid(v, "app_id")
        return v

    @field_validator("window")
    @classmethod
    def check_window(cls, v: str) -> str:
        return validate_alert_window(v)

    @field_validator("severity_tiers")
    @classmethod
    def check_tiers(cls, v: list[SeverityTier]) -> list[SeverityTier]:
        _validate_tier_list(v)
        return v


class UpdateAlertDefinitionRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    severity_tiers: list[SeverityTier] | None = Field(default=None, min_length=1)
    window: str | None = Field(default=None, max_length=10)
    enabled: bool | None = None

    @field_validator("window")
    @classmethod
    def check_window(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_alert_window(v)
        return v

    @field_validator("severity_tiers")
    @classmethod
    def check_tiers(cls, v: list[SeverityTier] | None) -> list[SeverityTier] | None:
        if v is not None:
            _validate_tier_list(v)
        return v


class ValidateExpressionRequest(BaseModel):
    expression: str = Field(min_length=1, max_length=2000)
    target_table: str = Field(min_length=1, max_length=64)


class CreateThresholdOverrideRequest(BaseModel):
    variable_id: str
    device_id: str
    entity_key: str = ""
    value: float

    @field_validator("variable_id")
    @classmethod
    def check_variable_id(cls, v: str) -> str:
        validate_uuid(v, "variable_id")
        return v

    @field_validator("device_id")
    @classmethod
    def check_device_id(cls, v: str) -> str:
        validate_uuid(v, "device_id")
        return v


class UpdateThresholdOverrideRequest(BaseModel):
    value: float


# ── Alert Definitions ────────────────────────────────────

@router.get("/definitions")
async def list_alert_definitions(
    app_id: str | None = Query(None),
    name: str | None = Query(default=None),
    expression: str | None = Query(default=None),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    """List all alert definitions, optionally filtered by app_id."""
    # Build filters
    filters = []
    if app_id:
        filters.append(AlertDefinition.app_id == uuid.UUID(app_id))
    if name:
        c = ilike_filter(AlertDefinition.name, name)
        if c is not None:
            filters.append(c)
    if expression:
        # severity_tiers is JSONB; cast to text for a substring search
        # across all tier expressions at once.
        c = ilike_filter(sa.cast(AlertDefinition.severity_tiers, sa.Text), expression)
        if c is not None:
            filters.append(c)

    # Count total
    count_stmt = select(sa.func.count()).select_from(AlertDefinition)
    for f in filters:
        count_stmt = count_stmt.where(f)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Main query
    stmt = select(AlertDefinition).options(selectinload(AlertDefinition.app))
    for f in filters:
        stmt = stmt.where(f)

    SORT_MAP = {
        "name": AlertDefinition.name,
        "enabled": AlertDefinition.enabled,
        "created_at": AlertDefinition.created_at,
    }
    sort_col = SORT_MAP.get(sort_by, AlertDefinition.name)
    stmt = stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())
    stmt = stmt.limit(limit).offset(offset)

    definitions = (await db.execute(stmt)).scalars().all()

    # Get instance counts per definition
    count_stmt = (
        select(
            AlertEntity.definition_id,
            func.count().label("total"),
            func.count().filter(AlertEntity.state == "firing").label("firing"),
        )
        .group_by(AlertEntity.definition_id)
    )
    count_rows = (await db.execute(count_stmt)).all()
    counts = {
        row.definition_id: {"total": row.total, "firing": row.firing}
        for row in count_rows
    }

    return {
        "status": "success",
        "data": [_fmt_definition(d, counts) for d in definitions],
        "meta": {"limit": limit, "offset": offset, "count": len(definitions), "total": total},
    }


@router.post("/definitions", status_code=status.HTTP_201_CREATED)
async def create_alert_definition(
    request: CreateAlertDefinitionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "create")),
):
    """Create a new alert definition on an app version."""
    app = await db.get(App, uuid.UUID(request.app_id))
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    tiers_payload = [t.model_dump() for t in request.severity_tiers]
    for i, tier in enumerate(tiers_payload):
        # Only non-healthy tiers carry an expression to validate.
        expr = tier.get("expression")
        if not expr:
            continue
        validation = validate_expression(expr, app.target_table)
        if not validation.valid:
            raise HTTPException(
                status_code=400,
                detail=f"severity_tiers[{i}] invalid expression: {validation.error}",
            )

    defn = AlertDefinition(
        app_id=uuid.UUID(request.app_id),
        name=request.name,
        description=request.description,
        severity_tiers=tiers_payload,
        window=request.window,
        enabled=request.enabled,
    )
    db.add(defn)
    await db.flush()

    # Auto-sync threshold variables across every tier's expression.
    await sync_threshold_variables(db, uuid.UUID(request.app_id), defn, app.target_table)

    # Auto-create instances for all existing assignments
    await sync_instances_for_definition(db, defn)
    await db.flush()

    return {"status": "success", "data": _fmt_definition(defn)}


@router.get("/definitions/{definition_id}")
async def get_alert_definition(
    definition_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    """Get a single alert definition with its instances."""
    defn = await db.get(
        AlertDefinition,
        uuid.UUID(definition_id),
        options=[
            selectinload(AlertDefinition.entities),
            selectinload(AlertDefinition.app),
        ],
    )
    if not defn:
        raise HTTPException(status_code=404, detail="Not found")

    data = _fmt_definition(defn)
    data["entities"] = [_fmt_entity(i) for i in defn.entities]
    return {"status": "success", "data": data}


@router.put("/definitions/{definition_id}")
async def update_alert_definition(
    definition_id: str,
    request: UpdateAlertDefinitionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    """Update an alert definition."""
    defn = await db.get(AlertDefinition, uuid.UUID(definition_id))
    if not defn:
        raise HTTPException(status_code=404, detail="Not found")

    if request.severity_tiers is not None:
        app = await db.get(App, defn.app_id)
        target_table = app.target_table if app else "availability_latency"
        tiers_payload = [t.model_dump() for t in request.severity_tiers]
        for i, tier in enumerate(tiers_payload):
            expr = tier.get("expression")
            if not expr:
                continue
            validation = validate_expression(expr, target_table)
            if not validation.valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"severity_tiers[{i}] invalid expression: {validation.error}",
                )
        defn.severity_tiers = tiers_payload
        await sync_threshold_variables(db, defn.app_id, defn, target_table)

    if request.name is not None:
        defn.name = request.name
    if request.description is not None:
        defn.description = request.description
    if request.window is not None:
        defn.window = request.window
    if request.enabled is not None:
        defn.enabled = request.enabled

    defn.updated_at = utc_now()
    return {"status": "success", "data": _fmt_definition(defn)}


@router.delete("/definitions/{definition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_definition(
    definition_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "delete")),
):
    """Delete an alert definition (CASCADE deletes instances)."""
    defn = await db.get(AlertDefinition, uuid.UUID(definition_id))
    if not defn:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(defn)


@router.post("/definitions/{definition_id}/invert")
async def invert_alert_definition(
    definition_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    """Generate inverted expression for a recovery alert."""
    defn = await db.get(AlertDefinition, uuid.UUID(definition_id))
    if defn is None:
        raise HTTPException(status_code=404, detail="Definition not found")

    # For a multi-tier def we invert the highest-severity tier's
    # expression (the "most problematic" threshold) — that's what a
    # recovery alert should target.
    tiers = defn.severity_tiers or []
    if not tiers:
        raise HTTPException(status_code=400, detail="Definition has no severity_tiers")
    top_expr = tiers[-1].get("expression", "")
    try:
        inverted = invert_expression(top_expr)
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=f"Cannot invert expression: {e}")

    return {
        "status": "success",
        "data": {
            "suggested_name": f"{defn.name} — Recovery",
            "inverted_expression": inverted,
            "original_expression": top_expr,
            "window": defn.window,
            "app_id": str(defn.app_id),
        },
    }


# ── Alert Instances ──────────────────────────────────────

@router.get("/instances")
async def list_alert_instances(
    state: str | None = Query(None),
    device_id: str | None = Query(None),
    definition_id: str | None = Query(None),
    sort_by: str = Query(default="state"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    definition_name: str | None = Query(default=None),
    app_name: str | None = Query(default=None),
    device_name: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    """List alert instances with optional filters, sort, and pagination."""
    from monctl_central.storage.models import Device

    stmt = (
        select(AlertEntity)
        .join(AlertDefinition, AlertEntity.definition_id == AlertDefinition.id)
        .join(App, AlertDefinition.app_id == App.id)
        .outerjoin(Device, AlertEntity.device_id == Device.id)
    )
    if state:
        stmt = stmt.where(AlertEntity.state == state)
    if device_id:
        stmt = stmt.where(AlertEntity.device_id == uuid.UUID(device_id))
    if definition_id:
        stmt = stmt.where(AlertEntity.definition_id == uuid.UUID(definition_id))
    if definition_name:
        if (c := ilike_filter(AlertDefinition.name, definition_name)) is not None:
            stmt = stmt.where(c)
    if app_name:
        if (c := ilike_filter(App.name, app_name)) is not None:
            stmt = stmt.where(c)
    if device_name:
        if (c := ilike_filter(Device.name, device_name)) is not None:
            stmt = stmt.where(c)
    if entity_key:
        if (c := ilike_filter(AlertEntity.entity_key, entity_key)) is not None:
            stmt = stmt.where(c)

    # Count before pagination
    count_stmt = select(sa.func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Sort
    _SORT_MAP = {
        "state": AlertEntity.state,
        "definition_name": AlertDefinition.name,
        "app_name": App.name,
        "device_name": Device.name,
        "entity_key": AlertEntity.entity_key,
        "current_value": AlertEntity.current_value,
        "fire_count": AlertEntity.fire_count,
        "started_firing_at": AlertEntity.started_firing_at,
        "current_state_since": AlertEntity.current_state_since,
        "last_triggered_at": AlertEntity.last_triggered_at,
    }
    sort_col = _SORT_MAP.get(sort_by, AlertEntity.state)
    stmt = stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())
    stmt = stmt.limit(limit).offset(offset)

    instances = (await db.execute(stmt)).scalars().all()

    # Enrich with definition and app info
    result = []
    for inst in instances:
        data = _fmt_entity(inst)
        defn = await db.get(AlertDefinition, inst.definition_id)
        if defn:
            data["definition_name"] = defn.name
            data["definition_severity_tiers"] = defn.severity_tiers or []
            app = await db.get(App, defn.app_id)
            data["app_name"] = app.name if app else ""
        assignment = await db.get(AppAssignment, inst.assignment_id)
        if assignment and assignment.device_id:
            from monctl_central.storage.models import Device
            device = await db.get(Device, assignment.device_id)
            data["device_name"] = device.name if device else ""
        result.append(data)

    return {
        "status": "success",
        "data": result,
        "meta": {"limit": limit, "offset": offset, "count": len(result), "total": total},
    }


@router.get("/instances/active")
async def list_active_instances(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    """List all currently firing alert instances."""
    stmt = select(AlertEntity).where(AlertEntity.state == "firing")
    instances = (await db.execute(stmt)).scalars().all()

    result = []
    for inst in instances:
        data = _fmt_entity(inst)
        defn = await db.get(AlertDefinition, inst.definition_id)
        if defn:
            data["definition_name"] = defn.name
            data["definition_severity_tiers"] = defn.severity_tiers or []
            app = await db.get(App, defn.app_id)
            data["app_name"] = app.name if app else ""
        assignment = await db.get(AppAssignment, inst.assignment_id)
        if assignment and assignment.device_id:
            from monctl_central.storage.models import Device
            device = await db.get(Device, assignment.device_id)
            data["device_name"] = device.name if device else ""
        result.append(data)

    return {"status": "success", "data": result}


@router.get("/instances/resolved")
async def list_resolved_instances(
    limit: int = Query(200, le=500),
    device_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    """List recently resolved alert instances within retention window."""
    from datetime import datetime, timedelta, timezone
    from monctl_central.storage.models import Device, SystemSetting

    setting = await db.get(SystemSetting, "alert_history_retention_days")
    retention_days = int(setting.value) if setting else 7
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    stmt = (
        select(AlertEntity)
        .where(
            AlertEntity.state == "resolved",
            AlertEntity.last_cleared_at >= cutoff,
        )
        .order_by(AlertEntity.last_cleared_at.desc())
        .limit(limit)
    )
    if device_id:
        stmt = stmt.where(AlertEntity.device_id == uuid.UUID(device_id))

    instances = (await db.execute(stmt)).scalars().all()

    result = []
    for inst in instances:
        data = _fmt_entity(inst)
        defn = await db.get(AlertDefinition, inst.definition_id)
        if defn:
            data["definition_name"] = defn.name
            data["definition_severity_tiers"] = defn.severity_tiers or []
            app = await db.get(App, defn.app_id)
            data["app_name"] = app.name if app else ""
        assignment = await db.get(AppAssignment, inst.assignment_id)
        if assignment and assignment.device_id:
            device = await db.get(Device, assignment.device_id)
            data["device_name"] = device.name if device else ""
        result.append(data)

    return {
        "status": "success",
        "data": result,
        "meta": {"retention_days": retention_days},
    }


class UpdateAlertEntityRequest(BaseModel):
    enabled: bool


@router.put("/instances/{instance_id}")
async def update_alert_instance(
    instance_id: str,
    request: UpdateAlertEntityRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    """Enable or disable an alert instance."""
    instance = await db.get(AlertEntity, uuid.UUID(instance_id))
    if not instance:
        raise HTTPException(status_code=404, detail="Not found")
    instance.enabled = request.enabled
    return {"status": "success", "data": _fmt_entity(instance)}


# ── Expression Validation ────────────────────────────────

@router.post("/validate-expression")
async def validate_expression_endpoint(
    request: ValidateExpressionRequest,
    auth: dict = Depends(require_permission("alert", "view")),
):
    """Validate a DSL expression for live UI feedback."""
    result = validate_expression(request.expression, request.target_table)
    return {
        "status": "success",
        "data": {
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "error": result.error,  # backward compat
            "referenced_metrics": result.referenced_metrics,
            "threshold_params": [
                {"name": tp.name, "default_value": tp.default_value, "param_key": tp.param_key}
                for tp in result.threshold_params
            ],
            "threshold_refs": [
                {"name": ref.name, "is_named": ref.is_named, "inline_value": ref.inline_value}
                for ref in result.threshold_refs
            ],
            "has_aggregation": result.has_aggregation,
            "has_arithmetic": result.has_arithmetic,
            "has_division": result.has_division,
        },
    }


# ── Threshold Overrides ──────────────────────────────────

@router.get("/overrides")
async def list_threshold_overrides(
    device_id: str | None = Query(None),
    variable_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    """List threshold overrides."""
    stmt = select(ThresholdOverride)
    if device_id:
        stmt = stmt.where(ThresholdOverride.device_id == uuid.UUID(device_id))
    if variable_id:
        stmt = stmt.where(ThresholdOverride.variable_id == uuid.UUID(variable_id))

    overrides = (await db.execute(stmt)).scalars().all()
    return {"status": "success", "data": [_fmt_override(o) for o in overrides]}


@router.post("/overrides", status_code=status.HTTP_201_CREATED)
async def create_threshold_override(
    request: CreateThresholdOverrideRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    """Create a threshold override for a device."""
    # Verify the variable exists
    variable = await db.get(ThresholdVariable, uuid.UUID(request.variable_id))
    if not variable:
        raise HTTPException(status_code=404, detail="Threshold variable not found")

    override = ThresholdOverride(
        variable_id=uuid.UUID(request.variable_id),
        device_id=uuid.UUID(request.device_id),
        entity_key=request.entity_key,
        value=request.value,
    )
    db.add(override)
    await db.flush()
    return {"status": "success", "data": _fmt_override(override)}


@router.put("/overrides/{override_id}")
async def update_threshold_override(
    override_id: str,
    request: UpdateThresholdOverrideRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    """Update a threshold override."""
    override = await db.get(ThresholdOverride, uuid.UUID(override_id))
    if not override:
        raise HTTPException(status_code=404, detail="Not found")
    override.value = request.value
    override.updated_at = utc_now()
    return {"status": "success", "data": _fmt_override(override)}


@router.delete("/overrides/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_threshold_override(
    override_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    """Delete a threshold override."""
    override = await db.get(ThresholdOverride, uuid.UUID(override_id))
    if not override:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(override)


# ── Alert Log (ClickHouse history) ──────────────────────

@router.get("/log")
async def query_alert_log(
    definition_id: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    definition_name: str | None = Query(default=None),
    device_name: str | None = Query(default=None),
    message: str | None = Query(default=None),
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    sort_by: str = Query(default="occurred_at"),
    sort_dir: str = Query(default="DESC"),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_permission("alert", "view")),
    ch=Depends(get_clickhouse),
):
    """Query the alert fire/clear log from ClickHouse."""
    tenant_id = auth.get("tenant_id")
    rows_raw, total = await asyncio.gather(
        asyncio.to_thread(
            ch.query_alert_log,
            definition_id=definition_id,
            entity_key=entity_key,
            device_id=device_id,
            action=action,
            definition_name=definition_name,
            device_name=device_name,
            message=message,
            tenant_id=tenant_id,
            from_ts=from_ts,
            to_ts=to_ts,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
            offset=offset,
        ),
        asyncio.to_thread(
            ch.count_alert_log,
            definition_id=definition_id,
            entity_key=entity_key,
            device_id=device_id,
            action=action,
            definition_name=definition_name,
            device_name=device_name,
            message=message,
            tenant_id=tenant_id,
            from_ts=from_ts,
            to_ts=to_ts,
        ),
    )
    rows = _ensure_utc(rows_raw)
    return {
        "status": "success",
        "data": rows,
        "meta": {
            "limit": limit,
            "offset": offset,
            "count": len(rows),
            "total": total,
        },
    }


# ── Orphan Threshold Cleanup ────────────────────────────

@router.post("/cleanup-orphan-thresholds")
async def cleanup_orphan_threshold_variables(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    """Remove threshold variables not referenced by any alert definition and with no overrides."""
    all_vars = (await db.execute(select(ThresholdVariable))).scalars().all()
    removed = 0

    for var in all_vars:
        defs = (await db.execute(
            select(AlertDefinition).where(AlertDefinition.app_id == var.app_id)
        )).scalars().all()

        referenced = False
        for d in defs:
            # Post PR #38 alert defs carry severity_tiers instead of a flat
            # expression. Check every tier's expression for the variable.
            for tier in (d.severity_tiers or []):
                expr = tier.get("expression") if isinstance(tier, dict) else None
                if not expr:
                    continue
                validation = validate_expression(expr, "")
                for ref in validation.threshold_refs:
                    if ref.name == var.name:
                        referenced = True
                        break
                if not referenced:
                    for tp in validation.threshold_params:
                        if tp.name == var.name:
                            referenced = True
                            break
                if referenced:
                    break
            if referenced:
                break

        if not referenced:
            override_count = (await db.execute(
                select(func.count()).select_from(ThresholdOverride)
                .where(ThresholdOverride.variable_id == var.id)
            )).scalar()
            if override_count == 0:
                await db.delete(var)
                removed += 1

    return {"status": "success", "data": {"removed": removed}}
