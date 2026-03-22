"""Auto-sync threshold variables from alert definition expressions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.alerting.dsl import validate_expression
from monctl_central.storage.models import AlertDefinition, ThresholdVariable

logger = logging.getLogger(__name__)


async def sync_threshold_variables(
    db: AsyncSession,
    app_id: uuid.UUID,
    definition: AlertDefinition,
    target_table: str,
    pack_hints: list[dict] | None = None,
) -> list[str]:
    """Ensure threshold variables exist for all extracted params from a definition.

    Args:
        pack_hints: Optional list of threshold_defaults from pack JSON.
                    Each dict has: param_key, default_value, display_name, unit, description.
                    When provided, these override the heuristic auto-detection.

    Returns:
        List of warning messages (e.g. missing $variable references).
    """
    warnings: list[str] = []

    validation = validate_expression(definition.expression, target_table)
    if not validation.valid:
        return warnings

    # Build hint lookup: param_key → hint dict
    hints: dict[str, dict] = {}
    if pack_hints:
        for h in pack_hints:
            if h.get("param_key"):
                hints[h["param_key"]] = h

    existing_vars = {
        v.name: v for v in (
            await db.execute(
                select(ThresholdVariable).where(ThresholdVariable.app_id == app_id)
            )
        ).scalars().all()
    }

    # Check explicit $variable references — warn if not pre-created
    variable_ref_names = set(validation.variable_refs)
    for vname in variable_ref_names:
        if vname not in existing_vars:
            warnings.append(
                f"Expression references ${{${vname}}} but no ThresholdVariable "
                f"'{vname}' exists on this app. Create it first for proper defaults."
            )
            logger.warning(
                "threshold_variable_missing variable=%s app_id=%s definition=%s",
                vname, str(app_id), definition.name,
            )

    # Auto-create ThresholdVariables for implicit threshold params
    # ONLY if the expression has NO $variable references — if user uses $variable
    # syntax, they've opted into explicit mode and we don't create implicit variables
    if not variable_ref_names:
        for param in validation.threshold_params:
            hint = hints.get(param.name, {})
            existing = existing_vars.get(param.name)
            if existing is None:
                var = ThresholdVariable(
                    app_id=app_id,
                    name=param.name,
                    display_name=hint.get("display_name") or _auto_display_name(param.name),
                    default_value=param.default_value,
                    unit=hint.get("unit") or _auto_detect_unit(param.name),
                    description=hint.get("description"),
                )
                db.add(var)
            else:
                if existing.default_value != param.default_value:
                    existing.default_value = param.default_value
                    existing.updated_at = datetime.now(timezone.utc)
                if hint.get("display_name") and existing.display_name == _auto_display_name(param.name):
                    existing.display_name = hint["display_name"]
                if hint.get("unit") and existing.unit == _auto_detect_unit(param.name):
                    existing.unit = hint["unit"]
                if hint.get("description") and not existing.description:
                    existing.description = hint["description"]

    return warnings


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
