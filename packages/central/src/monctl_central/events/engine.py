"""Event engine — promotes alerts to events based on event policies.

Runs after AlertEngine in the scheduler loop.  Evaluates all enabled
EventPolicies against AlertEntity fire_count / fire_history and inserts
new events into ClickHouse.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import (
    ActiveEvent,
    AlertEntity,
    AlertDefinition,
    EventPolicy,
)

logger = logging.getLogger(__name__)

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


class EventEngine:
    def __init__(self, session_factory, ch_client: ClickHouseClient):
        self._session_factory = session_factory
        self._ch = ch_client

    async def evaluate_all(self) -> None:
        async with self._session_factory() as session:
            policies = (
                await session.execute(
                    select(EventPolicy)
                    .where(EventPolicy.enabled == True)  # noqa: E712
                    .options(selectinload(EventPolicy.definition))
                )
            ).scalars().all()

            events_to_insert: list[dict] = []

            for policy in policies:
                try:
                    new_events = await self._evaluate_policy(session, policy)
                    events_to_insert.extend(new_events)
                except Exception:
                    logger.exception(
                        "event_policy_error policy_id=%s name=%s",
                        str(policy.id), policy.name,
                    )

            await session.commit()

            if events_to_insert:
                try:
                    await asyncio.to_thread(self._ch.insert_events, events_to_insert)
                    logger.info("events_inserted count=%d", len(events_to_insert))
                except Exception:
                    logger.exception("events_insert_error")

    async def _evaluate_policy(
        self, session: AsyncSession, policy: EventPolicy
    ) -> list[dict]:
        defn = policy.definition
        if not defn or not defn.enabled:
            return []

        entities = (
            await session.execute(
                select(AlertEntity).where(
                    AlertEntity.definition_id == defn.id,
                    AlertEntity.enabled == True,  # noqa: E712
                )
            )
        ).scalars().all()

        # Load existing active events for this policy
        active_events = (
            await session.execute(
                select(ActiveEvent).where(ActiveEvent.policy_id == policy.id)
            )
        ).scalars().all()
        active_by_key = {ae.entity_key: ae for ae in active_events}

        now = datetime.now(timezone.utc)
        new_events: list[dict] = []

        for inst in entities:
            entity_key = f"{inst.assignment_id}|{inst.entity_key}"
            has_active = entity_key in active_by_key

            if inst.state == "firing" and not has_active:
                if self._check_criteria(policy, inst):
                    event_row = self._build_event(policy, defn, inst, now)
                    new_events.append(event_row)
                    # Track in active_events table
                    ae = ActiveEvent(
                        policy_id=policy.id,
                        entity_key=entity_key,
                        clickhouse_event_id=str(uuid.uuid4()),
                    )
                    session.add(ae)
                    logger.info(
                        "event_promoted policy=%s defn=%s entity=%s fire_count=%d",
                        policy.name, defn.name, inst.entity_key, inst.fire_count,
                    )

            elif inst.state == "resolved" and has_active:
                if policy.auto_clear_on_resolve:
                    resolve_event = self._build_resolve_event(policy, defn, inst, now)
                    new_events.append(resolve_event)
                await session.delete(active_by_key[entity_key])

        return new_events

    def _check_criteria(self, policy: EventPolicy, inst: AlertEntity) -> bool:
        if policy.mode == "consecutive":
            return (inst.fire_count or 0) >= policy.fire_count_threshold

        if policy.mode == "cumulative":
            history = inst.fire_history or []
            window = history[-policy.window_size:] if policy.window_size else history
            fires_in_window = sum(1 for x in window if x)
            return fires_in_window >= policy.fire_count_threshold

        return False

    def _build_message(
        self, policy: EventPolicy, defn: AlertDefinition, inst: AlertEntity
    ) -> str:
        """Build event message. Priority: policy template > definition template > default."""
        from monctl_central.alerting.engine import _fmt_number, _SafeFormatDict

        labels = inst.entity_labels or {}
        metrics = getattr(inst, "metric_values", None) or {}
        thresholds = getattr(inst, "threshold_values", None) or {}
        value = inst.current_value

        # Try policy template, then definition template
        for template in [policy.message_template, defn.message_template]:
            if not template:
                continue
            context: dict[str, str] = {}
            for k, v in labels.items():
                context[k] = str(v)
            context["value"] = _fmt_number(value)
            context["alert_name"] = defn.name
            context["rule_name"] = defn.name  # backward compat
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

    def _build_event(
        self,
        policy: EventPolicy,
        defn: AlertDefinition,
        inst: AlertEntity,
        now: datetime,
    ) -> dict:
        labels = inst.entity_labels or {}
        return {
            "event_type": "alert",
            "definition_id": str(defn.id),
            "definition_name": defn.name,
            "policy_id": str(policy.id),
            "policy_name": policy.name,
            "collector_id": labels.get("collector_id", _ZERO_UUID),
            "device_id": str(inst.device_id) if inst.device_id else _ZERO_UUID,
            "app_id": str(defn.app_id),
            "assignment_id": str(inst.assignment_id),
            "tenant_id": labels.get("tenant_id", _ZERO_UUID),
            "source": f"policy:{policy.name.lower().replace(' ', '_')}",
            "severity": policy.event_severity,
            "message": self._build_message(policy, defn, inst),
            "data": json.dumps({
                "value": inst.current_value,
                "fire_count": inst.fire_count,
                "mode": policy.mode,
                "labels": labels,
            }),
            "state": "active",
            "occurred_at": now,
            "collector_name": labels.get("collector_name", ""),
            "device_name": labels.get("device_name", ""),
            "app_name": labels.get("app_name", defn.name),
        }

    def _build_resolve_event(
        self,
        policy: EventPolicy,
        defn: AlertDefinition,
        inst: AlertEntity,
        now: datetime,
    ) -> dict:
        labels = inst.entity_labels or {}
        device = labels.get("device_name", "unknown")
        return {
            "event_type": "alert_resolved",
            "definition_id": str(defn.id),
            "definition_name": defn.name,
            "policy_id": str(policy.id),
            "policy_name": policy.name,
            "collector_id": labels.get("collector_id", _ZERO_UUID),
            "device_id": str(inst.device_id) if inst.device_id else _ZERO_UUID,
            "app_id": str(defn.app_id),
            "assignment_id": str(inst.assignment_id),
            "tenant_id": labels.get("tenant_id", _ZERO_UUID),
            "source": f"policy:{policy.name.lower().replace(' ', '_')}",
            "severity": "info",
            "message": f"Resolved: {defn.name} on {device}",
            "data": json.dumps({"labels": labels, "auto_cleared": True}),
            "state": "cleared",
            "occurred_at": now,
            "collector_name": labels.get("collector_name", ""),
            "device_name": labels.get("device_name", ""),
            "app_name": labels.get("app_name", defn.name),
        }
