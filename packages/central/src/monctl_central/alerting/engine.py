"""Alert engine — evaluates alert rules against ClickHouse data.

Runs periodically on the leader-elected scheduler instance.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.alerting.evaluators import (
    AbsenceEvaluator,
    StateChangeEvaluator,
    ThresholdEvaluator,
)
from monctl_central.alerting.notifier import send_notifications
from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import AlertRule, AlertState

logger = logging.getLogger(__name__)


_EVALUATORS = {
    "threshold": ThresholdEvaluator(),
    "state_change": StateChangeEvaluator(),
    "absence": AbsenceEvaluator(),
}


class AlertEngine:
    """Evaluates enabled alert rules against ClickHouse check_results data."""

    def __init__(self, session_factory, ch_client: ClickHouseClient):
        self._session_factory = session_factory
        self._ch = ch_client

    async def evaluate_all(self) -> None:
        """Load all enabled rules from PG, evaluate each, update states, notify."""
        async with self._session_factory() as session:
            rules = (
                await session.execute(
                    select(AlertRule).where(AlertRule.enabled == True)  # noqa: E712
                )
            ).scalars().all()

            for rule in rules:
                try:
                    await self._evaluate_rule(session, rule)
                except Exception:
                    logger.exception("alert_rule_error", rule_id=str(rule.id), name=rule.name)

            await session.commit()

    async def _evaluate_rule(self, session: AsyncSession, rule: AlertRule) -> None:
        evaluator = _EVALUATORS.get(rule.rule_type)
        if evaluator is None:
            logger.warning("unknown_rule_type", rule_type=rule.rule_type, rule_id=str(rule.id))
            return

        # Evaluate: returns set of assignment_ids that are currently firing
        firing_assignments = evaluator.evaluate(rule, self._ch)

        # Load existing alert states for this rule
        existing_states = (
            await session.execute(
                select(AlertState).where(AlertState.rule_id == rule.id)
            )
        ).scalars().all()
        states_by_assignment: dict[str, AlertState] = {}
        for s in existing_states:
            assignment_key = s.labels.get("assignment_id", "")
            states_by_assignment[assignment_key] = s

        now = datetime.now(timezone.utc)

        # Process firing assignments
        for assignment_id in firing_assignments:
            existing = states_by_assignment.get(assignment_id)
            if existing and existing.state == "firing":
                # Already firing — check repeat_interval for re-notification
                continue
            elif existing and existing.state == "resolved":
                # Re-fire
                existing.state = "firing"
                existing.started_at = now
                existing.resolved_at = None
                await send_notifications(rule, assignment_id, "firing")
            else:
                # New alert
                new_state = AlertState(
                    rule_id=rule.id,
                    state="firing",
                    labels={"assignment_id": assignment_id},
                    started_at=now,
                    last_notified_at=now,
                )
                session.add(new_state)
                await send_notifications(rule, assignment_id, "firing")

        # Resolve alerts that are no longer firing
        for assignment_id, state in states_by_assignment.items():
            if state.state == "firing" and assignment_id not in firing_assignments:
                state.state = "resolved"
                state.resolved_at = now
                await send_notifications(rule, assignment_id, "resolved")
