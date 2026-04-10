"""IncidentEngine — phase 1 (shadow mode).

Runs after the scheduler's AlertEngine + EventEngine each cycle. Reads
AlertEntities and IncidentRules from PG and upserts rows in the
incidents table. Does NOT:

- write ClickHouse events
- send notifications
- trigger automations
- apply correlation groups, severity ladders, dependencies, scope filters,
  or flap guard windows (columns exist but are reserved for phase 2)

The feature flag `settings.incident_engine` controls whether
`evaluate_all()` does any work at all:
- "off"   → no-op (early return)
- "shadow" → runs the full loop (default)

See docs/event-policy-rework.md.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.alerting.engine import _fmt_number, _SafeFormatDict
from monctl_central.config import settings
from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import (
    AlertDefinition,
    AlertEntity,
    EventPolicy,
    Incident,
    IncidentRule,
)

logger = logging.getLogger(__name__)


class IncidentEngine:
    """Phase 1 incident engine — observation only."""

    def __init__(self, session_factory, ch_client: ClickHouseClient | None = None) -> None:
        self._session_factory = session_factory
        self._ch = ch_client  # unused in phase 1, reserved for phase 2

    async def evaluate_all(self) -> None:
        if settings.incident_engine == "off":
            return

        async with self._session_factory() as session:
            rules = (
                await session.execute(
                    select(IncidentRule)
                    .where(IncidentRule.enabled == True)  # noqa: E712
                    .options(selectinload(IncidentRule.definition))
                )
            ).scalars().all()

            opened = 0
            updated = 0
            cleared = 0

            for rule in rules:
                try:
                    o, u, c = await self._evaluate_rule(session, rule)
                    opened += o
                    updated += u
                    cleared += c
                except Exception:
                    logger.exception(
                        "incident_rule_error rule_id=%s name=%s",
                        str(rule.id), rule.name,
                    )

            await session.commit()

            if opened or updated or cleared:
                logger.info(
                    "incident_cycle opened=%d updated=%d cleared=%d rules=%d",
                    opened, updated, cleared, len(rules),
                )

    async def _evaluate_rule(
        self, session: AsyncSession, rule: IncidentRule
    ) -> tuple[int, int, int]:
        """Evaluate one rule. Returns (opened, updated, cleared) counts."""
        defn = rule.definition
        if not defn or not defn.enabled:
            return 0, 0, 0

        entities = (
            await session.execute(
                select(AlertEntity).where(
                    AlertEntity.definition_id == defn.id,
                    AlertEntity.enabled == True,  # noqa: E712
                )
            )
        ).scalars().all()

        # Load currently-open incidents for this rule.
        open_incidents = (
            await session.execute(
                select(Incident).where(
                    Incident.rule_id == rule.id,
                    Incident.state == "open",
                )
            )
        ).scalars().all()
        open_by_key = {inc.entity_key: inc for inc in open_incidents}

        now = datetime.now(timezone.utc)
        opened = updated = cleared = 0

        for inst in entities:
            entity_key = f"{inst.assignment_id}|{inst.entity_key}"
            incident = open_by_key.get(entity_key)

            if inst.state == "firing":
                if incident is None:
                    # Threshold check mirrors the EventEngine's consecutive/cumulative logic.
                    if not self._meets_threshold(rule, inst):
                        continue
                    new_inc = Incident(
                        rule_id=rule.id,
                        entity_key=entity_key,
                        assignment_id=inst.assignment_id,
                        device_id=inst.device_id,
                        state="open",
                        severity=rule.severity,
                        message=self._render_message(rule, defn, inst),
                        labels=inst.entity_labels or {},
                        fire_count=1,
                        opened_at=now,
                        last_fired_at=now,
                    )
                    session.add(new_inc)
                    opened += 1
                    logger.info(
                        "incident_opened rule=%s entity=%s device=%s",
                        rule.name, inst.entity_key or "-",
                        (inst.entity_labels or {}).get("device_name", "-"),
                    )
                else:
                    incident.last_fired_at = now
                    incident.fire_count += 1
                    incident.message = self._render_message(rule, defn, inst)
                    # Refresh labels in case entity_labels grew new keys since open.
                    if inst.entity_labels:
                        incident.labels = inst.entity_labels
                    updated += 1

            elif inst.state == "resolved" and incident is not None:
                if rule.auto_clear_on_resolve:
                    incident.state = "cleared"
                    incident.cleared_at = now
                    incident.cleared_reason = "auto"
                    cleared += 1
                    logger.info(
                        "incident_cleared rule=%s entity=%s reason=auto",
                        rule.name, inst.entity_key or "-",
                    )

        return opened, updated, cleared

    @staticmethod
    def _meets_threshold(rule: IncidentRule, inst: AlertEntity) -> bool:
        """Same consecutive/cumulative semantics as EventEngine._check_criteria."""
        if rule.mode == "consecutive":
            return (inst.fire_count or 0) >= rule.fire_count_threshold
        if rule.mode == "cumulative":
            history = inst.fire_history or []
            window = history[-rule.window_size :] if rule.window_size else history
            fires_in_window = sum(1 for x in window if x)
            return fires_in_window >= rule.fire_count_threshold
        return False

    @staticmethod
    def _render_message(
        rule: IncidentRule, defn: AlertDefinition, inst: AlertEntity
    ) -> str:
        """Same template priority as EventEngine: rule.message_template → defn.message_template → fallback."""
        labels = inst.entity_labels or {}
        metrics = getattr(inst, "metric_values", None) or {}
        thresholds = getattr(inst, "threshold_values", None) or {}
        value = inst.current_value

        for template in [rule.message_template, defn.message_template]:
            if not template:
                continue
            context: dict[str, str] = {}
            for k, v in labels.items():
                context[k] = str(v)
            context["value"] = _fmt_number(value)
            context["alert_name"] = defn.name
            context["rule_name"] = defn.name
            context["fire_count"] = str(inst.fire_count)
            context["entity_key"] = inst.entity_key or ""
            for k, v in metrics.items():
                context[k] = _fmt_number(v)
            for k, v in thresholds.items():
                context[f"${k}"] = _fmt_number(v)
            try:
                return template.format_map(_SafeFormatDict(context))
            except (ValueError, TypeError):
                continue

        device = labels.get("device_name", "unknown")
        entity = labels.get("if_name") or labels.get("component") or inst.entity_key or ""
        val_str = f" = {round(value, 2)}" if value is not None else ""
        return f"{defn.name}{val_str} on {device} {entity} [{inst.fire_count}x]".strip()


async def sync_incident_rules_from_event_policies(session_factory) -> tuple[int, int, int]:
    """Upsert a mirror IncidentRule for every EventPolicy.

    - Adds new rules for policies that don't have a mirror yet.
    - Updates mutable fields (name, thresholds, severity, enabled, ...) on
      existing mirrors.
    - Disables mirrors whose source EventPolicy has been deleted (source_policy_id
      is set to NULL by the FK ON DELETE SET NULL and this task marks them
      `enabled = False` so the engine skips them).

    Returns (added, updated, disabled).
    """
    added = updated = disabled = 0
    async with session_factory() as session:
        policies = (await session.execute(select(EventPolicy))).scalars().all()
        mirrors = (
            await session.execute(
                select(IncidentRule).where(IncidentRule.source == "mirror")
            )
        ).scalars().all()
        mirror_by_policy_id = {
            m.source_policy_id: m for m in mirrors if m.source_policy_id is not None
        }
        orphan_mirrors = [m for m in mirrors if m.source_policy_id is None]

        for policy in policies:
            mirror = mirror_by_policy_id.get(policy.id)
            if mirror is None:
                session.add(
                    IncidentRule(
                        name=policy.name,
                        description=policy.description,
                        definition_id=policy.definition_id,
                        mode=policy.mode,
                        fire_count_threshold=policy.fire_count_threshold,
                        window_size=policy.window_size,
                        severity=policy.event_severity,
                        message_template=policy.message_template,
                        auto_clear_on_resolve=policy.auto_clear_on_resolve,
                        enabled=policy.enabled,
                        source="mirror",
                        source_policy_id=policy.id,
                    )
                )
                added += 1
                continue

            dirty = False
            if mirror.name != policy.name:
                mirror.name = policy.name
                dirty = True
            if mirror.description != policy.description:
                mirror.description = policy.description
                dirty = True
            if mirror.definition_id != policy.definition_id:
                mirror.definition_id = policy.definition_id
                dirty = True
            if mirror.mode != policy.mode:
                mirror.mode = policy.mode
                dirty = True
            if mirror.fire_count_threshold != policy.fire_count_threshold:
                mirror.fire_count_threshold = policy.fire_count_threshold
                dirty = True
            if mirror.window_size != policy.window_size:
                mirror.window_size = policy.window_size
                dirty = True
            if mirror.severity != policy.event_severity:
                mirror.severity = policy.event_severity
                dirty = True
            if mirror.message_template != policy.message_template:
                mirror.message_template = policy.message_template
                dirty = True
            if mirror.auto_clear_on_resolve != policy.auto_clear_on_resolve:
                mirror.auto_clear_on_resolve = policy.auto_clear_on_resolve
                dirty = True
            if mirror.enabled != policy.enabled:
                mirror.enabled = policy.enabled
                dirty = True
            if dirty:
                mirror.updated_at = datetime.now(timezone.utc)
                updated += 1

        # Orphan mirrors — policy was deleted, FK cleared source_policy_id.
        for orphan in orphan_mirrors:
            if orphan.enabled:
                orphan.enabled = False
                orphan.updated_at = datetime.now(timezone.utc)
                disabled += 1

        await session.commit()

    if added or updated or disabled:
        logger.info(
            "incident_rules_synced added=%d updated=%d disabled=%d",
            added, updated, disabled,
        )
    return added, updated, disabled
