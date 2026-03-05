"""Alerting management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import AlertRule, AlertState

router = APIRouter()


class CreateAlertRuleRequest(BaseModel):
    name: str
    description: str | None = None
    rule_type: str = Field(description="'threshold', 'absence', or 'state_change'")
    condition: dict
    severity: str = Field(description="'warning' or 'critical'")
    notification_channels: list[dict] = Field(default_factory=list)


@router.get("/rules")
async def list_alert_rules(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all alert rules."""
    stmt = select(AlertRule)
    result = await db.execute(stmt)
    rules = result.scalars().all()
    return {
        "status": "success",
        "data": [
            {
                "id": str(r.id),
                "name": r.name,
                "rule_type": r.rule_type,
                "severity": r.severity,
                "enabled": r.enabled,
            }
            for r in rules
        ],
    }


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    request: CreateAlertRuleRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new alert rule."""
    rule = AlertRule(
        name=request.name,
        description=request.description,
        rule_type=request.rule_type,
        condition=request.condition,
        severity=request.severity,
        notification_channels=request.notification_channels,
    )
    db.add(rule)
    await db.flush()
    return {
        "status": "success",
        "data": {"id": str(rule.id), "name": rule.name},
    }


@router.get("/active")
async def list_active_alerts(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List currently firing alerts."""
    stmt = select(AlertState).where(AlertState.state == "firing")
    result = await db.execute(stmt)
    states = result.scalars().all()
    return {
        "status": "success",
        "data": [
            {
                "id": str(s.id),
                "rule_id": str(s.rule_id),
                "state": s.state,
                "labels": s.labels,
                "started_at": s.started_at.isoformat(),
            }
            for s in states
        ],
    }
