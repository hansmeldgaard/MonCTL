"""REST API for Actions, Automations, and Run History."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from monctl_central.dependencies import get_db, get_clickhouse, get_session_factory, require_permission
from monctl_central.storage.models import Action, Automation, AutomationStep

logger = structlog.get_logger()
router = APIRouter()


# ── Request Models ────────────────────────────────────────────────────────

class CreateActionRequest(BaseModel):
    name: str = Field(..., max_length=200)
    description: str | None = None
    target: str = Field(default="collector")
    source_code: str = ""
    credential_type: str | None = None
    credential_id: str | None = None
    timeout_seconds: int = Field(default=60, ge=5, le=300)
    enabled: bool = True


class UpdateActionRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    target: str | None = None
    source_code: str | None = None
    credential_type: str | None = None
    credential_id: str | None = None
    clear_credential_id: bool = False
    timeout_seconds: int | None = Field(default=None, ge=5, le=300)
    enabled: bool | None = None


class StepInput(BaseModel):
    action_id: str
    step_order: int = Field(ge=1)
    credential_type_override: str | None = None
    timeout_override: int | None = Field(default=None, ge=5, le=300)


class CreateAutomationRequest(BaseModel):
    name: str = Field(..., max_length=200)
    description: str | None = None
    trigger_type: str
    event_severity_filter: str | None = None
    event_policy_ids: list[str] | None = None
    event_label_filter: dict | None = None
    cron_expression: str | None = None
    cron_device_label_filter: dict | None = None
    cron_device_ids: list[str] | None = None
    device_ids: list[str] | None = None
    device_label_filter: dict | None = None
    cooldown_seconds: int = Field(default=300, ge=0)
    enabled: bool = True
    steps: list[StepInput] = Field(default_factory=list)


class UpdateAutomationRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    event_severity_filter: str | None = None
    event_policy_ids: list[str] | None = None
    event_label_filter: dict | None = None
    cron_expression: str | None = None
    cron_device_label_filter: dict | None = None
    cron_device_ids: list[str] | None = None
    device_ids: list[str] | None = None
    device_label_filter: dict | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    steps: list[StepInput] | None = None


class ManualTriggerRequest(BaseModel):
    device_ids: list[str] = Field(..., min_length=1)


# ── Helpers ───────────────────────────────────────────────────────────────

def _fmt_action(a: Action) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "description": a.description,
        "target": a.target,
        "source_code": a.source_code,
        "credential_type": a.credential_type,
        "credential_id": str(a.credential_id) if a.credential_id else None,
        "timeout_seconds": a.timeout_seconds,
        "enabled": a.enabled,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _fmt_automation(a: Automation) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "description": a.description,
        "trigger_type": a.trigger_type,
        "event_severity_filter": a.event_severity_filter,
        "event_policy_ids": a.event_policy_ids,
        "event_label_filter": a.event_label_filter,
        "cron_expression": a.cron_expression,
        "cron_device_label_filter": a.cron_device_label_filter,
        "cron_device_ids": a.cron_device_ids,
        "device_ids": a.device_ids,
        "device_label_filter": a.device_label_filter,
        "cooldown_seconds": a.cooldown_seconds,
        "enabled": a.enabled,
        "steps": [
            {
                "id": str(s.id),
                "action_id": str(s.action_id),
                "action_name": s.action.name if s.action else "",
                "action_target": s.action.target if s.action else "",
                "step_order": s.step_order,
                "credential_type_override": s.credential_type_override,
                "timeout_override": s.timeout_override,
            }
            for s in sorted(a.steps, key=lambda s: s.step_order)
        ],
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


# ── Action CRUD ───────────────────────────────────────────────────────────

@router.get("/actions")
async def list_actions(
    search: str | None = Query(default=None),
    target: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc"),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    stmt = select(Action)
    count_stmt = select(func.count(Action.id))

    if search:
        stmt = stmt.where(Action.name.ilike(f"%{search}%"))
        count_stmt = count_stmt.where(Action.name.ilike(f"%{search}%"))
    if target:
        stmt = stmt.where(Action.target == target)
        count_stmt = count_stmt.where(Action.target == target)

    sort_col = getattr(Action, sort_by, Action.name)
    stmt = stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(stmt)).scalars().all()
    return {
        "data": [_fmt_action(a) for a in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/actions/{action_id}")
async def get_action(
    action_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    action = await db.get(Action, uuid.UUID(action_id))
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return {"data": _fmt_action(action)}


@router.post("/actions", status_code=201)
async def create_action(
    request: CreateActionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "create")),
):
    if request.target not in ("collector", "central"):
        raise HTTPException(400, detail="target must be 'collector' or 'central'")

    action = Action(
        name=request.name,
        description=request.description,
        target=request.target,
        source_code=request.source_code,
        credential_type=request.credential_type,
        credential_id=uuid.UUID(request.credential_id) if request.credential_id else None,
        timeout_seconds=request.timeout_seconds,
        enabled=request.enabled,
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return {"data": _fmt_action(action)}


@router.put("/actions/{action_id}")
async def update_action(
    action_id: str,
    request: UpdateActionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    action = await db.get(Action, uuid.UUID(action_id))
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if request.name is not None:
        action.name = request.name
    if request.description is not None:
        action.description = request.description
    if request.target is not None:
        if request.target not in ("collector", "central"):
            raise HTTPException(400, detail="target must be 'collector' or 'central'")
        action.target = request.target
    if request.source_code is not None:
        action.source_code = request.source_code
    if request.credential_type is not None:
        action.credential_type = request.credential_type
    if request.clear_credential_id:
        action.credential_id = None
    elif request.credential_id is not None:
        action.credential_id = uuid.UUID(request.credential_id)
    if request.timeout_seconds is not None:
        action.timeout_seconds = request.timeout_seconds
    if request.enabled is not None:
        action.enabled = request.enabled

    await db.commit()
    await db.refresh(action)
    return {"data": _fmt_action(action)}


@router.delete("/actions/{action_id}", status_code=204)
async def delete_action(
    action_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "delete")),
):
    action = await db.get(Action, uuid.UUID(action_id))
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    step_count = (
        await db.execute(
            select(func.count(AutomationStep.id))
            .where(AutomationStep.action_id == action.id)
        )
    ).scalar() or 0
    if step_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Action is referenced by {step_count} automation step(s). Remove from automations first.",
        )

    await db.delete(action)
    await db.commit()


# ── Automation CRUD ───────────────────────────────────────────────────────

@router.get("/automations")
async def list_automations(
    search: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc"),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    stmt = select(Automation).options(
        joinedload(Automation.steps).joinedload(AutomationStep.action)
    )
    count_stmt = select(func.count(Automation.id))

    if search:
        stmt = stmt.where(Automation.name.ilike(f"%{search}%"))
        count_stmt = count_stmt.where(Automation.name.ilike(f"%{search}%"))
    if trigger_type:
        stmt = stmt.where(Automation.trigger_type == trigger_type)
        count_stmt = count_stmt.where(Automation.trigger_type == trigger_type)

    sort_col = getattr(Automation, sort_by, Automation.name)
    stmt = stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(stmt)).unique().scalars().all()
    return {
        "data": [_fmt_automation(a) for a in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/automations/{automation_id}")
async def get_automation(
    automation_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "view")),
):
    automation = (
        await db.execute(
            select(Automation)
            .where(Automation.id == uuid.UUID(automation_id))
            .options(joinedload(Automation.steps).joinedload(AutomationStep.action))
        )
    ).unique().scalar_one_or_none()
    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"data": _fmt_automation(automation)}


@router.post("/automations", status_code=201)
async def create_automation(
    request: CreateAutomationRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "create")),
):
    if request.trigger_type not in ("event", "cron"):
        raise HTTPException(400, detail="trigger_type must be 'event' or 'cron'")

    if request.trigger_type == "cron":
        if not request.cron_expression:
            raise HTTPException(400, detail="cron_expression required for cron trigger")
        try:
            from croniter import croniter
            croniter(request.cron_expression)
        except (ValueError, KeyError) as e:
            raise HTTPException(400, detail=f"Invalid cron expression: {e}")

    automation = Automation(
        name=request.name,
        description=request.description,
        trigger_type=request.trigger_type,
        event_severity_filter=request.event_severity_filter,
        event_policy_ids=request.event_policy_ids,
        event_label_filter=request.event_label_filter,
        cron_expression=request.cron_expression,
        cron_device_label_filter=request.cron_device_label_filter,
        cron_device_ids=request.cron_device_ids,
        device_ids=request.device_ids,
        device_label_filter=request.device_label_filter,
        cooldown_seconds=request.cooldown_seconds,
        enabled=request.enabled,
    )
    db.add(automation)
    await db.flush()

    for step_input in request.steps:
        action = await db.get(Action, uuid.UUID(step_input.action_id))
        if not action:
            raise HTTPException(400, detail=f"Action {step_input.action_id} not found")
        step = AutomationStep(
            automation_id=automation.id,
            action_id=action.id,
            step_order=step_input.step_order,
            credential_type_override=step_input.credential_type_override,
            timeout_override=step_input.timeout_override,
        )
        db.add(step)

    await db.commit()

    automation = (
        await db.execute(
            select(Automation)
            .where(Automation.id == automation.id)
            .options(joinedload(Automation.steps).joinedload(AutomationStep.action))
        )
    ).unique().scalar_one()
    return {"data": _fmt_automation(automation)}


@router.put("/automations/{automation_id}")
async def update_automation(
    automation_id: str,
    request: UpdateAutomationRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    automation = (
        await db.execute(
            select(Automation)
            .where(Automation.id == uuid.UUID(automation_id))
            .options(joinedload(Automation.steps))
        )
    ).unique().scalar_one_or_none()
    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")

    if request.name is not None:
        automation.name = request.name
    if request.description is not None:
        automation.description = request.description
    if request.event_severity_filter is not None:
        automation.event_severity_filter = request.event_severity_filter
    if request.event_policy_ids is not None:
        automation.event_policy_ids = request.event_policy_ids
    if request.event_label_filter is not None:
        automation.event_label_filter = request.event_label_filter
    if request.cron_expression is not None:
        try:
            from croniter import croniter
            croniter(request.cron_expression)
        except (ValueError, KeyError) as e:
            raise HTTPException(400, detail=f"Invalid cron expression: {e}")
        automation.cron_expression = request.cron_expression
    if request.cron_device_label_filter is not None:
        automation.cron_device_label_filter = request.cron_device_label_filter
    if request.cron_device_ids is not None:
        automation.cron_device_ids = request.cron_device_ids
    if request.device_ids is not None:
        automation.device_ids = request.device_ids
    if request.device_label_filter is not None:
        automation.device_label_filter = request.device_label_filter
    if request.cooldown_seconds is not None:
        automation.cooldown_seconds = request.cooldown_seconds
    if request.enabled is not None:
        automation.enabled = request.enabled

    if request.steps is not None:
        for existing_step in list(automation.steps):
            await db.delete(existing_step)
        await db.flush()

        for step_input in request.steps:
            action = await db.get(Action, uuid.UUID(step_input.action_id))
            if not action:
                raise HTTPException(400, detail=f"Action {step_input.action_id} not found")
            step = AutomationStep(
                automation_id=automation.id,
                action_id=action.id,
                step_order=step_input.step_order,
                credential_type_override=step_input.credential_type_override,
                timeout_override=step_input.timeout_override,
            )
            db.add(step)

    await db.commit()

    automation = (
        await db.execute(
            select(Automation)
            .where(Automation.id == automation.id)
            .options(joinedload(Automation.steps).joinedload(AutomationStep.action))
        )
    ).unique().scalar_one()
    return {"data": _fmt_automation(automation)}


@router.delete("/automations/{automation_id}", status_code=204)
async def delete_automation(
    automation_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("alert", "delete")),
):
    automation = await db.get(Automation, uuid.UUID(automation_id))
    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")
    await db.delete(automation)
    await db.commit()


# ── Manual Trigger ────────────────────────────────────────────────────────

@router.post("/automations/{automation_id}/trigger")
async def trigger_automation(
    automation_id: str,
    request: ManualTriggerRequest,
    ch=Depends(get_clickhouse),
    auth: dict = Depends(require_permission("alert", "edit")),
):
    """Manually trigger an automation for specific devices."""
    from monctl_central.automations.engine import AutomationEngine
    engine = AutomationEngine(
        session_factory=get_session_factory(),
        ch_client=ch,
    )

    triggered_by = auth.get("username", "unknown")
    try:
        run_ids = await engine.trigger_manual(
            automation_id=automation_id,
            device_ids=request.device_ids,
            triggered_by=triggered_by,
        )
        return {"data": {"run_ids": run_ids, "count": len(run_ids)}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Run History ───────────────────────────────────────────────────────────

@router.get("/runs")
async def list_runs(
    automation_id: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    event_id: str | None = Query(default=None),
    run_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    ch=Depends(get_clickhouse),
    auth: dict = Depends(require_permission("alert", "view")),
):
    """List automation run history from ClickHouse."""
    import json
    rows, total = await asyncio.to_thread(
        ch.query_rba_runs,
        automation_id=automation_id,
        device_id=device_id,
        event_id=event_id,
        status=run_status,
        limit=page_size,
        offset=(page - 1) * page_size,
    )

    for row in rows:
        if isinstance(row.get("step_results"), str):
            try:
                row["step_results"] = json.loads(row["step_results"])
            except json.JSONDecodeError:
                row["step_results"] = []
        if isinstance(row.get("shared_data"), str):
            try:
                row["shared_data"] = json.loads(row["shared_data"])
            except json.JSONDecodeError:
                row["shared_data"] = {}
        for key in ("run_id", "automation_id", "device_id", "collector_id"):
            if key in row and hasattr(row[key], "hex"):
                row[key] = str(row[key])
        for key in ("started_at", "finished_at"):
            if key in row and hasattr(row[key], "isoformat"):
                row[key] = row[key].isoformat()

    return {
        "data": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    ch=Depends(get_clickhouse),
    auth: dict = Depends(require_permission("alert", "view")),
):
    """Get a single run's details including step results."""
    import json
    sql = """
        SELECT *
        FROM rba_runs
        WHERE run_id = {run_id:UUID}
        LIMIT 1
    """
    result = await asyncio.to_thread(
        lambda: ch._client.query(sql, parameters={"run_id": run_id})
    )
    if not result.result_rows:
        raise HTTPException(status_code=404, detail="Run not found")

    row = dict(zip(result.column_names, result.result_rows[0]))
    for field in ("step_results", "shared_data"):
        if isinstance(row.get(field), str):
            try:
                row[field] = json.loads(row[field])
            except json.JSONDecodeError:
                row[field] = [] if field == "step_results" else {}
    for key in ("run_id", "automation_id", "device_id", "collector_id"):
        if key in row and hasattr(row[key], "hex"):
            row[key] = str(row[key])
    for key in ("started_at", "finished_at"):
        if key in row and hasattr(row[key], "isoformat"):
            row[key] = row[key].isoformat()

    return {"data": row}
