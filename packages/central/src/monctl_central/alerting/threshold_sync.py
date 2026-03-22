"""Auto-sync threshold variables from alert definition expressions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.alerting.dsl import validate_expression
from monctl_central.storage.models import AlertDefinition, ThresholdVariable


async def sync_threshold_variables(
    db: AsyncSession, app_id: uuid.UUID, definition: AlertDefinition, target_table: str
) -> None:
    """Ensure threshold variables exist for all extracted params from a definition."""
    validation = validate_expression(definition.expression, target_table)
    if not validation.valid:
        return

    existing_vars = {
        v.name: v for v in (
            await db.execute(
                select(ThresholdVariable).where(ThresholdVariable.app_id == app_id)
            )
        ).scalars().all()
    }

    for param in validation.threshold_params:
        existing = existing_vars.get(param.name)
        if existing is None:
            var = ThresholdVariable(
                app_id=app_id,
                name=param.name,
                display_name=_auto_display_name(param.name),
                default_value=param.default_value,
                unit=_auto_detect_unit(param.name),
            )
            db.add(var)
        else:
            if existing.default_value != param.default_value:
                existing.default_value = param.default_value
                existing.updated_at = datetime.now(timezone.utc)


def _auto_display_name(param_name: str) -> str:
    name = param_name
    if name.endswith("_threshold"):
        name = name[:-len("_threshold")]
    return name.replace("_", " ").title()


def _auto_detect_unit(param_name: str) -> str | None:
    name = param_name.lower()
    if "_pct" in name or "_percent" in name or "utilization" in name:
        return "percent"
    if "_ms" in name or "latency" in name or "rtt" in name:
        return "ms"
    if "_bytes" in name or "_octets" in name:
        return "bytes"
    if "_count" in name or "_errors" in name or "_pkts" in name:
        return "count"
    return None
