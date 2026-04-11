"""Automation engine: evaluates triggers and orchestrates action execution."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone

import structlog
from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from monctl_central.storage.models import (
    Action, Automation, AutomationStep, Collector, Credential, Device,
)
from monctl_central.automations.executor import execute_action_locally

logger = structlog.get_logger()


@dataclass
class ActionContext:
    """Context passed to an action script at runtime."""
    device_id: str = ""
    device_name: str = ""
    device_ip: str = ""
    collector_id: str = ""
    collector_name: str = ""
    credential: dict = field(default_factory=dict)
    trigger_type: str = ""
    event_id: str = ""
    event_severity: str = ""
    event_message: str = ""
    shared_data: dict = field(default_factory=dict)
    step_number: int = 0
    action_name: str = ""


class AutomationEngine:
    """Evaluates automation triggers and orchestrates action execution."""

    def __init__(self, session_factory, ch_client):
        self._session_factory = session_factory
        self._ch = ch_client

    # ── Incident-triggered automations ───────────────────────────────────
    #
    # The only event-producing hook after cut-over step 2 (see
    # docs/event-policy-rework.md). The IncidentEngine calls
    # `on_incident_transition` on opened / escalated / cleared state
    # changes. Automations match via `trigger_type='incident'` plus
    # `incident_rule_ids` and `incident_state_trigger`. The legacy
    # `on_new_events` hook was retired in step 2 (alembic revision
    # zp6q7r8s9t0u); EventEngine still writes CH events for historical
    # queries but no longer fires automations.

    async def on_incident_transition(
        self,
        incident_id: str,
        rule_id: str,
        transition: str,
        device_id: str,
        severity: str,
        message: str,
        labels: dict,
    ) -> None:
        """Called by the IncidentEngine on an incident state transition.

        `transition` is one of `"opened"`, `"escalated"`, or `"cleared"`.
        Matches against enabled `trigger_type="incident"` automations
        whose `incident_rule_ids` contains the rule and whose
        `incident_state_trigger` covers the transition. Respects
        per-device cooldown the same way `on_new_events` does.
        """
        async with self._session_factory() as session:
            automations = (
                await session.execute(
                    select(Automation)
                    .where(
                        Automation.trigger_type == "incident",
                        Automation.enabled == True,  # noqa: E712
                    )
                    .options(joinedload(Automation.steps).joinedload(AutomationStep.action))
                )
            ).unique().scalars().all()

            if not automations:
                return

            for automation in automations:
                if not self._incident_matches(
                    automation, rule_id, transition, device_id, labels
                ):
                    continue

                # Per-device cooldown — same semantics as on_new_events.
                if device_id and automation.cooldown_seconds > 0:
                    last_run = await asyncio.to_thread(
                        self._ch.get_last_rba_run_time,
                        str(automation.id),
                        device_id,
                    )
                    if last_run:
                        # ClickHouse returns naive datetimes — coerce to UTC
                        # so the subtraction against tz-aware `now()` works.
                        if last_run.tzinfo is None:
                            last_run = last_run.replace(tzinfo=timezone.utc)
                        elapsed = (
                            datetime.now(timezone.utc) - last_run
                        ).total_seconds()
                        if elapsed < automation.cooldown_seconds:
                            logger.debug(
                                "automation_cooldown_skip",
                                automation=automation.name,
                                device_id=device_id,
                                elapsed=elapsed,
                                cooldown=automation.cooldown_seconds,
                            )
                            continue

                # Reuse the existing `_execute_automation` path. Its
                # `event_data` dict isn't actually coupled to the events
                # table — it's just passed through to ActionContext
                # (`event_id`, `event_severity`, `event_message`) and to
                # the run log. Fill it with incident-equivalent fields so
                # action scripts see a consistent envelope.
                synthetic_event = {
                    "id": incident_id,
                    "severity": severity,
                    "message": message,
                    "device_id": device_id,
                    "data": {"labels": labels or {}},
                    # Extra fields specific to incident triggers, available
                    # to action scripts that want them.
                    "incident_id": incident_id,
                    "incident_rule_id": rule_id,
                    "incident_transition": transition,
                }
                asyncio.create_task(
                    self._execute_automation(
                        session_factory=self._session_factory,
                        automation=automation,
                        device_id=device_id,
                        trigger_type="incident",
                        event_data=synthetic_event,
                        triggered_by=f"system:incident:{transition}",
                    ),
                    name=f"rba_incident_{automation.id}_{device_id}",
                )

    def _incident_matches(
        self,
        automation: Automation,
        rule_id: str,
        transition: str,
        device_id: str,
        labels: dict,
    ) -> bool:
        """Check if an incident transition matches an automation's filters."""
        if automation.incident_rule_ids:
            if rule_id not in automation.incident_rule_ids:
                return False

        # `incident_state_trigger` is one of "opened", "escalated",
        # "cleared", or "any". NULL also means "any".
        want = automation.incident_state_trigger
        if want and want != "any" and want != transition:
            return False

        # Reuse the shared device filters that `_event_matches` honors.
        device_ids = automation.device_ids or automation.cron_device_ids
        if device_ids and device_id and device_id not in device_ids:
            return False

        device_label_filter = (
            automation.device_label_filter or automation.cron_device_label_filter
        )
        if device_label_filter:
            for key, value in device_label_filter.items():
                if (labels or {}).get(key) != value:
                    return False

        return True

    # ── Cron-triggered automations ───────────────────────────────────────

    async def evaluate_cron_triggers(self) -> None:
        """Called every 30s by the scheduler. Checks cron automations."""
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            automations = (
                await session.execute(
                    select(Automation)
                    .where(
                        Automation.trigger_type == "cron",
                        Automation.enabled == True,  # noqa: E712
                    )
                    .options(joinedload(Automation.steps).joinedload(AutomationStep.action))
                )
            ).unique().scalars().all()

            for automation in automations:
                if not automation.cron_expression:
                    continue

                cron = croniter(automation.cron_expression, now)
                prev_fire = cron.get_prev(datetime)
                if (now - prev_fire).total_seconds() > 30:
                    continue

                devices = await self._resolve_cron_devices(session, automation)
                for device in devices:
                    if automation.cooldown_seconds > 0:
                        last_run = await asyncio.to_thread(
                            self._ch.get_last_rba_run_time,
                            str(automation.id),
                            str(device.id),
                        )
                        if last_run:
                            elapsed = (now - last_run).total_seconds()
                            if elapsed < automation.cooldown_seconds:
                                continue

                    asyncio.create_task(
                        self._execute_automation(
                            session_factory=self._session_factory,
                            automation=automation,
                            device_id=str(device.id),
                            trigger_type="cron",
                            event_data={},
                            triggered_by="system:cron",
                        ),
                        name=f"rba_cron_{automation.id}_{device.id}",
                    )

    async def _resolve_cron_devices(
        self, session: AsyncSession, automation: Automation
    ) -> list[Device]:
        """Resolve which devices a cron automation targets."""
        # Prefer unified fields, fallback to cron-specific fields
        device_ids = automation.device_ids or automation.cron_device_ids
        label_filter = automation.device_label_filter or automation.cron_device_label_filter

        if device_ids:
            device_uuids = [uuid.UUID(d) for d in device_ids]
            result = await session.execute(
                select(Device).where(Device.id.in_(device_uuids))
            )
            return list(result.scalars().all())

        if label_filter:
            from sqlalchemy import text as sa_text
            label_json = json.dumps(label_filter)
            result = await session.execute(
                select(Device).where(
                    Device.labels.op("@>")(sa_text(f"'{label_json}'::jsonb"))
                )
            )
            return list(result.scalars().all())

        return []

    # ── Manual trigger ───────────────────────────────────────────────────

    async def trigger_manual(
        self,
        automation_id: str,
        device_ids: list[str],
        triggered_by: str,
    ) -> list[str]:
        """Manually trigger an automation for specific devices."""
        async with self._session_factory() as session:
            automation = (
                await session.execute(
                    select(Automation)
                    .where(Automation.id == uuid.UUID(automation_id))
                    .options(joinedload(Automation.steps).joinedload(AutomationStep.action))
                )
            ).unique().scalar_one_or_none()

            if not automation:
                raise ValueError(f"Automation {automation_id} not found")

            run_ids = []
            for device_id in device_ids:
                run_id = str(uuid.uuid4())
                asyncio.create_task(
                    self._execute_automation(
                        session_factory=self._session_factory,
                        automation=automation,
                        device_id=device_id,
                        trigger_type="manual",
                        event_data={},
                        triggered_by=triggered_by,
                        run_id=run_id,
                    ),
                    name=f"rba_manual_{automation.id}_{device_id}",
                )
                run_ids.append(run_id)
            return run_ids

    # ── Core execution ───────────────────────────────────────────────────

    async def _execute_automation(
        self,
        session_factory,
        automation: Automation,
        device_id: str,
        trigger_type: str,
        event_data: dict,
        triggered_by: str,
        run_id: str | None = None,
    ) -> None:
        """Execute all steps of an automation sequentially (fail-fast)."""
        run_id = run_id or str(uuid.uuid4())
        start_time = time.time()
        started_at = datetime.now(timezone.utc)

        # Resolve device and collector info
        async with session_factory() as session:
            device = await session.get(Device, uuid.UUID(device_id)) if device_id else None

            device_name = device.name if device else ""
            device_ip = device.address if device else ""
            collector_id = ""
            collector_name = ""

            if device and device.collector_group_id:
                from monctl_common.utils import utc_now
                stale_cutoff = utc_now() - timedelta(seconds=90)
                collector_result = await session.execute(
                    select(Collector)
                    .where(
                        Collector.group_id == device.collector_group_id,
                        Collector.status == "ACTIVE",
                        Collector.last_seen_at >= stale_cutoff,
                    )
                    .limit(1)
                )
                collector = collector_result.scalar_one_or_none()
                if collector:
                    collector_id = str(collector.id)
                    collector_name = collector.name or ""

        shared_data: dict = {}
        step_results: list[dict] = []
        final_status = "success"
        failed_step = 0

        steps = sorted(automation.steps, key=lambda s: s.step_order)

        for step in steps:
            action = step.action
            if not action or not action.enabled:
                step_results.append({
                    "step": step.step_order,
                    "action_id": str(step.action_id),
                    "action_name": action.name if action else "unknown",
                    "target": action.target if action else "unknown",
                    "status": "skipped",
                    "stdout": "",
                    "stderr": "Action disabled or not found",
                    "exit_code": -1,
                    "duration_ms": 0,
                    "output_data": {},
                })
                continue

            # Resolve credential for this step
            # Priority: direct credential_id on action → credential_type (device-resolved)
            credential_data = {}
            if action.credential_id:
                # Direct credential reference (e.g. central actions contacting external systems)
                async with session_factory() as session:
                    cred = await session.get(Credential, action.credential_id)
                    if cred:
                        from monctl_central.credentials.crypto import decrypt_credential
                        credential_data = decrypt_credential(cred.secret_data)
            else:
                cred_type = step.credential_type_override or action.credential_type
                if cred_type and device_id:
                    async with session_factory() as session:
                        device_fresh = await session.get(Device, uuid.UUID(device_id))
                        if device_fresh and device_fresh.credentials:
                            cred_id_str = device_fresh.credentials.get(cred_type)
                            if cred_id_str:
                                cred = await session.get(Credential, uuid.UUID(cred_id_str))
                                if cred:
                                    from monctl_central.credentials.crypto import decrypt_credential
                                    credential_data = decrypt_credential(cred.secret_data)

            # Build context
            timeout = step.timeout_override or action.timeout_seconds
            ctx = ActionContext(
                device_id=device_id,
                device_name=device_name,
                device_ip=device_ip,
                collector_id=collector_id,
                collector_name=collector_name,
                credential=credential_data,
                trigger_type=trigger_type,
                event_id=event_data.get("id", ""),
                event_severity=event_data.get("severity", ""),
                event_message=event_data.get("message", ""),
                shared_data=shared_data,
                step_number=step.step_order,
                action_name=action.name,
            )
            ctx_dict = asdict(ctx)

            # Execute based on target
            if action.target == "central":
                result = await execute_action_locally(
                    source_code=action.source_code,
                    context_data=ctx_dict,
                    timeout=timeout,
                )
            elif action.target == "collector":
                if not collector_id:
                    result = {
                        "status": "failed",
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": "No active collector found for device's collector group",
                        "output_data": {},
                        "duration_ms": 0,
                    }
                else:
                    try:
                        from monctl_central.ws.connection_manager import ConnectionManager
                        # Get the global manager instance
                        from monctl_central.ws.router import manager as ws_manager
                        ws_result = await ws_manager.send_command(
                            uuid.UUID(collector_id),
                            "run_action",
                            {
                                "source_code": action.source_code,
                                "context": ctx_dict,
                                "timeout": timeout,
                            },
                            timeout=float(timeout + 10),
                        )
                        result = ws_result
                    except KeyError:
                        result = {
                            "status": "failed",
                            "exit_code": -1,
                            "stdout": "",
                            "stderr": f"Collector {collector_id} is not connected via WebSocket",
                            "output_data": {},
                            "duration_ms": 0,
                        }
                    except asyncio.TimeoutError:
                        result = {
                            "status": "timeout",
                            "exit_code": -1,
                            "stdout": "",
                            "stderr": f"Collector did not respond within {timeout + 10}s",
                            "output_data": {},
                            "duration_ms": timeout * 1000,
                        }
            else:
                result = {
                    "status": "failed",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Unknown action target: {action.target}",
                    "output_data": {},
                    "duration_ms": 0,
                }

            step_result = {
                "step": step.step_order,
                "action_id": str(action.id),
                "action_name": action.name,
                "target": action.target,
                "status": result.get("status", "failed"),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "exit_code": result.get("exit_code", -1),
                "duration_ms": result.get("duration_ms", 0),
                "output_data": result.get("output_data", {}),
            }
            step_results.append(step_result)

            namespace = f"step_{step.step_order}"
            shared_data[namespace] = result.get("output_data", {})

            if result.get("status") != "success":
                final_status = "failed"
                failed_step = step.step_order
                logger.warning(
                    "automation_step_failed",
                    automation=automation.name,
                    step=step.step_order,
                    action=action.name,
                    status=result.get("status"),
                    stderr=result.get("stderr", "")[:500],
                )
                break

        duration_ms = int((time.time() - start_time) * 1000)
        finished_at = datetime.now(timezone.utc)

        run_record = {
            "run_id": run_id,
            "automation_id": str(automation.id),
            "automation_name": automation.name,
            "trigger_type": trigger_type,
            "event_id": event_data.get("id", ""),
            "event_severity": event_data.get("severity", ""),
            "event_message": event_data.get("message", "")[:1000],
            "device_id": device_id or "00000000-0000-0000-0000-000000000000",
            "device_name": device_name,
            "device_ip": device_ip,
            "collector_id": collector_id or "00000000-0000-0000-0000-000000000000",
            "collector_name": collector_name,
            "status": final_status,
            "total_steps": len(steps),
            "completed_steps": len([s for s in step_results if s["status"] == "success"]),
            "failed_step": failed_step,
            "step_results": json.dumps(step_results),
            "shared_data": json.dumps(shared_data),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "triggered_by": triggered_by,
        }

        try:
            await asyncio.to_thread(self._ch.insert_rba_run, run_record)
        except Exception:
            logger.exception("rba_run_insert_error", run_id=run_id)

        logger.info(
            "automation_run_complete",
            automation=automation.name,
            run_id=run_id,
            status=final_status,
            steps=len(steps),
            duration_ms=duration_ms,
        )
