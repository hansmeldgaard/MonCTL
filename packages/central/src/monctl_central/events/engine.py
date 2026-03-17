"""Event engine — promotes alerts to events based on event policies.

Runs after AlertEngine in the scheduler loop.  Evaluates all enabled
EventPolicies against AlertInstance fire_count / fire_history and inserts
new events into ClickHouse.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import (
    AlertInstance,
    AppAlertDefinition,
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

        instances = (
            await session.execute(
                select(AlertInstance).where(
                    AlertInstance.definition_id == defn.id,
                    AlertInstance.enabled == True,  # noqa: E712
                )
            )
        ).scalars().all()

        now = datetime.now(timezone.utc)
        new_events: list[dict] = []

        for inst in instances:
            if inst.state == "firing" and not inst.event_created:
                if self._check_criteria(policy, inst):
                    event_row = self._build_event(policy, defn, inst, now)
                    new_events.append(event_row)
                    inst.event_created = True
                    logger.info(
                        "event_promoted policy=%s defn=%s entity=%s fire_count=%d",
                        policy.name, defn.name, inst.entity_key, inst.fire_count,
                    )

            elif inst.state == "resolved" and inst.event_created:
                if policy.auto_clear_on_resolve:
                    resolve_event = self._build_resolve_event(policy, defn, inst, now)
                    new_events.append(resolve_event)
                inst.event_created = False

        return new_events

    def _check_criteria(self, policy: EventPolicy, inst: AlertInstance) -> bool:
        if policy.mode == "consecutive":
            return (inst.fire_count or 0) >= policy.fire_count_threshold

        if policy.mode == "cumulative":
            history = inst.fire_history or []
            window = history[-policy.window_size:] if policy.window_size else history
            fires_in_window = sum(1 for x in window if x)
            return fires_in_window >= policy.fire_count_threshold

        return False

    def _build_message(
        self, policy: EventPolicy, defn: AppAlertDefinition, inst: AlertInstance
    ) -> str:
        template = policy.message_template or defn.message_template
        labels = inst.entity_labels or {}
        value = inst.current_value

        if template:
            try:
                return template.format(
                    value=round(value, 2) if value is not None else "N/A",
                    rule_name=defn.name,
                    fire_count=inst.fire_count,
                    **labels,
                )
            except (KeyError, IndexError, TypeError):
                pass

        device = labels.get("device_name", "unknown")
        entity = labels.get("if_name") or labels.get("component") or inst.entity_key or ""
        val_str = f" = {round(value, 2)}" if value is not None else ""
        return f"{defn.name}{val_str} on {device} {entity} [{inst.fire_count}x]".strip()

    def _build_event(
        self,
        policy: EventPolicy,
        defn: AppAlertDefinition,
        inst: AlertInstance,
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
        defn: AppAlertDefinition,
        inst: AlertInstance,
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
