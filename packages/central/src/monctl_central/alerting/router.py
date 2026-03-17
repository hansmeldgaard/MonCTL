"""App-level alert definitions, instances, and threshold overrides."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.alerting.dsl import invert_expression, validate_expression
from monctl_central.alerting.instance_sync import sync_instances_for_definition
from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import (
    AlertInstance,
    App,
    AppAlertDefinition,
    AppAssignment,
    ThresholdOverride,
)
from monctl_common.utils import utc_now

router = APIRouter()


# ── Formatters ───────────────────────────────────────────

def _fmt_definition(d: AppAlertDefinition, instance_counts: dict | None = None) -> dict:
    result = {
        "id": str(d.id),
        "app_id": str(d.app_id),
        "app_version_id": str(d.app_version_id),
        "name": d.name,
        "description": d.description,
        "expression": d.expression,
        "window": d.window,
        "severity": d.severity,
        "enabled": d.enabled,
        "message_template": d.message_template,
        "notification_channels": d.notification_channels,
        "pack_origin": d.pack_origin,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }
    if instance_counts:
        result["instance_count"] = instance_counts.get(d.id, {}).get("total", 0)
        result["firing_count"] = instance_counts.get(d.id, {}).get("firing", 0)
    return result


def _fmt_instance(i: AlertInstance) -> dict:
    return {
        "id": str(i.id),
        "definition_id": str(i.definition_id),
        "assignment_id": str(i.assignment_id),
        "device_id": str(i.device_id) if i.device_id else None,
        "enabled": i.enabled,
        "state": i.state,
        "current_value": i.current_value,
        "fire_count": i.fire_count,
        "fire_history": i.fire_history,
        "last_evaluated_at": i.last_evaluated_at.isoformat() if i.last_evaluated_at else None,
        "started_at": i.started_at.isoformat() if i.started_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "event_created": i.event_created,
        "entity_key": i.entity_key,
        "entity_labels": i.entity_labels,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


def _fmt_override(o: ThresholdOverride) -> dict:
    return {
        "id": str(o.id),
        "definition_id": str(o.definition_id),
        "device_id": str(o.device_id),
        "entity_key": o.entity_key,
        "overrides": o.overrides,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


# ── Request models ───────────────────────────────────────

class CreateAlertDefinitionRequest(BaseModel):
    app_id: str
    app_version_id: str
    name: str
    description: str | None = None
    expression: str
    window: str = "5m"
    severity: str = Field(default="warning", description="info, warning, critical, emergency")
    enabled: bool = True
    message_template: str | None = None
    notification_channels: list[dict] = Field(default_factory=list)


class UpdateAlertDefinitionRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    expression: str | None = None
    window: str | None = None
    severity: str | None = None
    enabled: bool | None = None
    message_template: str | None = None


class ValidateExpressionRequest(BaseModel):
    expression: str
    target_table: str


class CreateThresholdOverrideRequest(BaseModel):
    definition_id: str
    device_id: str
    entity_key: str = ""
    overrides: dict


class UpdateThresholdOverrideRequest(BaseModel):
    overrides: dict


# ── Alert Definitions ────────────────────────────────────

_VALID_SEVERITIES = {"info", "warning", "critical", "emergency", "recovery"}


@router.get("/definitions")
async def list_alert_definitions(
    app_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all alert definitions, optionally filtered by app_id."""
    stmt = select(AppAlertDefinition)
    if app_id:
        stmt = stmt.where(AppAlertDefinition.app_id == uuid.UUID(app_id))
    stmt = stmt.order_by(AppAlertDefinition.name)

    definitions = (await db.execute(stmt)).scalars().all()

    # Get instance counts per definition
    count_stmt = (
        select(
            AlertInstance.definition_id,
            func.count().label("total"),
            func.count().filter(AlertInstance.state == "firing").label("firing"),
        )
        .group_by(AlertInstance.definition_id)
    )
    count_rows = (await db.execute(count_stmt)).all()
    counts = {
        row.definition_id: {"total": row.total, "firing": row.firing}
        for row in count_rows
    }

    return {
        "status": "success",
        "data": [_fmt_definition(d, counts) for d in definitions],
    }


@router.post("/definitions", status_code=status.HTTP_201_CREATED)
async def create_alert_definition(
    request: CreateAlertDefinitionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new alert definition on an app version."""
    app = await db.get(App, uuid.UUID(request.app_id))
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    validation = validate_expression(request.expression, app.target_table)
    if not validation.valid:
        raise HTTPException(
            status_code=400, detail=f"Invalid expression: {validation.error}"
        )

    if request.severity not in _VALID_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Severity must be one of: {', '.join(sorted(_VALID_SEVERITIES))}",
        )

    defn = AppAlertDefinition(
        app_id=uuid.UUID(request.app_id),
        app_version_id=uuid.UUID(request.app_version_id),
        name=request.name,
        description=request.description,
        expression=request.expression,
        window=request.window,
        severity=request.severity,
        enabled=request.enabled,
        message_template=request.message_template,
        notification_channels=request.notification_channels,
    )
    db.add(defn)
    await db.flush()

    # Auto-create instances for all existing assignments
    await sync_instances_for_definition(db, defn)
    await db.flush()

    return {"status": "success", "data": _fmt_definition(defn)}


@router.get("/definitions/{definition_id}")
async def get_alert_definition(
    definition_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get a single alert definition with its instances."""
    defn = await db.get(
        AppAlertDefinition,
        uuid.UUID(definition_id),
        options=[selectinload(AppAlertDefinition.instances)],
    )
    if not defn:
        raise HTTPException(status_code=404, detail="Not found")

    data = _fmt_definition(defn)
    data["instances"] = [_fmt_instance(i) for i in defn.instances]
    return {"status": "success", "data": data}


@router.put("/definitions/{definition_id}")
async def update_alert_definition(
    definition_id: str,
    request: UpdateAlertDefinitionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update an alert definition."""
    defn = await db.get(AppAlertDefinition, uuid.UUID(definition_id))
    if not defn:
        raise HTTPException(status_code=404, detail="Not found")

    if request.expression is not None:
        app = await db.get(App, defn.app_id)
        validation = validate_expression(request.expression, app.target_table if app else "availability_latency")
        if not validation.valid:
            raise HTTPException(
                status_code=400, detail=f"Invalid expression: {validation.error}"
            )
        defn.expression = request.expression

    if request.severity is not None:
        if request.severity not in _VALID_SEVERITIES:
            raise HTTPException(
                status_code=400,
                detail=f"Severity must be one of: {', '.join(sorted(_VALID_SEVERITIES))}",
            )
        defn.severity = request.severity

    if request.name is not None:
        defn.name = request.name
    if request.description is not None:
        defn.description = request.description
    if request.window is not None:
        defn.window = request.window
    if request.enabled is not None:
        defn.enabled = request.enabled
    if request.message_template is not None:
        defn.message_template = request.message_template

    defn.updated_at = utc_now()
    return {"status": "success", "data": _fmt_definition(defn)}


@router.delete("/definitions/{definition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_definition(
    definition_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete an alert definition (CASCADE deletes instances)."""
    defn = await db.get(AppAlertDefinition, uuid.UUID(definition_id))
    if not defn:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(defn)


@router.post("/definitions/{definition_id}/invert")
async def invert_alert_definition(
    definition_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Generate inverted expression for a recovery alert."""
    defn = await db.get(AppAlertDefinition, uuid.UUID(definition_id))
    if defn is None:
        raise HTTPException(status_code=404, detail="Definition not found")

    try:
        inverted = invert_expression(defn.expression)
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=f"Cannot invert expression: {e}")

    return {
        "status": "success",
        "data": {
            "suggested_name": f"{defn.name} — Recovery",
            "inverted_expression": inverted,
            "original_expression": defn.expression,
            "window": defn.window,
            "severity": "recovery",
            "app_id": str(defn.app_id),
            "app_version_id": str(defn.app_version_id),
        },
    }


# ── Alert Instances ──────────────────────────────────────

@router.get("/instances")
async def list_alert_instances(
    state: str | None = Query(None),
    device_id: str | None = Query(None),
    definition_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List alert instances with optional filters."""
    stmt = (
        select(AlertInstance)
        .join(AppAlertDefinition, AlertInstance.definition_id == AppAlertDefinition.id)
        .join(App, AppAlertDefinition.app_id == App.id)
    )
    if state:
        stmt = stmt.where(AlertInstance.state == state)
    if device_id:
        stmt = stmt.where(AlertInstance.device_id == uuid.UUID(device_id))
    if definition_id:
        stmt = stmt.where(AlertInstance.definition_id == uuid.UUID(definition_id))

    instances = (await db.execute(stmt)).scalars().all()

    # Enrich with definition and app info
    result = []
    for inst in instances:
        data = _fmt_instance(inst)
        # Load definition for enrichment
        defn = await db.get(AppAlertDefinition, inst.definition_id)
        if defn:
            data["definition_name"] = defn.name
            data["definition_severity"] = defn.severity
            data["definition_expression"] = defn.expression
            app = await db.get(App, defn.app_id)
            data["app_name"] = app.name if app else ""
        # Load device name from assignment
        assignment = await db.get(AppAssignment, inst.assignment_id)
        if assignment and assignment.device_id:
            from monctl_central.storage.models import Device
            device = await db.get(Device, assignment.device_id)
            data["device_name"] = device.name if device else ""
        result.append(data)

    return {"status": "success", "data": result}


@router.get("/instances/active")
async def list_active_instances(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all currently firing alert instances."""
    stmt = select(AlertInstance).where(AlertInstance.state == "firing")
    instances = (await db.execute(stmt)).scalars().all()

    result = []
    for inst in instances:
        data = _fmt_instance(inst)
        defn = await db.get(AppAlertDefinition, inst.definition_id)
        if defn:
            data["definition_name"] = defn.name
            data["definition_severity"] = defn.severity
            data["definition_expression"] = defn.expression
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
    severity: str | None = Query(None),
    device_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List recently resolved alert instances within retention window."""
    from datetime import datetime, timedelta, timezone
    from monctl_central.storage.models import Device, SystemSetting

    setting = await db.get(SystemSetting, "alert_history_retention_days")
    retention_days = int(setting.value) if setting else 7
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    stmt = (
        select(AlertInstance)
        .where(
            AlertInstance.state == "resolved",
            AlertInstance.resolved_at >= cutoff,
        )
        .order_by(AlertInstance.resolved_at.desc())
        .limit(limit)
    )
    if device_id:
        stmt = stmt.where(AlertInstance.device_id == uuid.UUID(device_id))

    instances = (await db.execute(stmt)).scalars().all()

    result = []
    for inst in instances:
        data = _fmt_instance(inst)
        defn = await db.get(AppAlertDefinition, inst.definition_id)
        if defn:
            data["definition_name"] = defn.name
            data["definition_severity"] = defn.severity
            data["definition_expression"] = defn.expression
            if severity and defn.severity != severity:
                continue
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


class UpdateAlertInstanceRequest(BaseModel):
    enabled: bool


@router.put("/instances/{instance_id}")
async def update_alert_instance(
    instance_id: str,
    request: UpdateAlertInstanceRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Enable or disable an alert instance."""
    instance = await db.get(AlertInstance, uuid.UUID(instance_id))
    if not instance:
        raise HTTPException(status_code=404, detail="Not found")
    instance.enabled = request.enabled
    return {"status": "success", "data": _fmt_instance(instance)}


# ── Expression Validation ────────────────────────────────

@router.post("/validate-expression")
async def validate_expression_endpoint(
    request: ValidateExpressionRequest,
    auth: dict = Depends(require_auth),
):
    """Validate a DSL expression for live UI feedback."""
    result = validate_expression(request.expression, request.target_table)
    return {
        "status": "success",
        "data": {
            "valid": result.valid,
            "error": result.error,
            "referenced_metrics": result.referenced_metrics,
            "threshold_params": [
                {"name": tp.name, "default_value": tp.default_value}
                for tp in result.threshold_params
            ],
            "has_aggregation": result.has_aggregation,
        },
    }


# ── Threshold Overrides ──────────────────────────────────

@router.get("/overrides")
async def list_threshold_overrides(
    device_id: str | None = Query(None),
    definition_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List threshold overrides."""
    stmt = select(ThresholdOverride)
    if device_id:
        stmt = stmt.where(ThresholdOverride.device_id == uuid.UUID(device_id))
    if definition_id:
        stmt = stmt.where(ThresholdOverride.definition_id == uuid.UUID(definition_id))

    overrides = (await db.execute(stmt)).scalars().all()
    return {"status": "success", "data": [_fmt_override(o) for o in overrides]}


@router.post("/overrides", status_code=status.HTTP_201_CREATED)
async def create_threshold_override(
    request: CreateThresholdOverrideRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a threshold override for a device."""
    override = ThresholdOverride(
        definition_id=uuid.UUID(request.definition_id),
        device_id=uuid.UUID(request.device_id),
        entity_key=request.entity_key,
        overrides=request.overrides,
    )
    db.add(override)
    await db.flush()
    return {"status": "success", "data": _fmt_override(override)}


@router.put("/overrides/{override_id}")
async def update_threshold_override(
    override_id: str,
    request: UpdateThresholdOverrideRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a threshold override."""
    override = await db.get(ThresholdOverride, uuid.UUID(override_id))
    if not override:
        raise HTTPException(status_code=404, detail="Not found")
    override.overrides = request.overrides
    override.updated_at = utc_now()
    return {"status": "success", "data": _fmt_override(override)}


@router.delete("/overrides/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_threshold_override(
    override_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a threshold override."""
    override = await db.get(ThresholdOverride, uuid.UUID(override_id))
    if not override:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(override)
