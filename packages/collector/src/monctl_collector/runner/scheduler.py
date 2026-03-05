"""App scheduler — reads assignments from config and runs them via AppExecutor."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from monctl_collector.buffer.service import ResultBuffer
from monctl_collector.runner.executor import AppExecutor
from monctl_common.schemas.config import AppAssignmentConfig, CollectorConfig
from monctl_common.schemas.metrics import AppResult

logger = structlog.get_logger()


class AppScheduler:
    """Schedules monitoring apps based on assignments from central config.

    When the config changes (via ConfigSyncService), call apply_config() to
    add/remove APScheduler jobs so the set of running checks matches the
    assignments provided by central.
    """

    def __init__(
        self,
        buffer: ResultBuffer,
        collector_id: str,
        apps_dir: str = "/opt/monctl/apps",
        max_concurrent: int = 50,
    ):
        self.buffer = buffer
        self.collector_id = collector_id
        self.apps_dir = apps_dir
        self.executor = AppExecutor(max_concurrent=max_concurrent)
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._known_assignment_ids: set[str] = set()

    def start(self) -> None:
        """Start the underlying APScheduler."""
        self._scheduler.start()
        logger.info("app_scheduler_started")

    def shutdown(self) -> None:
        """Gracefully stop the scheduler."""
        self._scheduler.shutdown(wait=False)
        logger.info("app_scheduler_stopped")

    async def apply_config(self, config: CollectorConfig) -> None:
        """Sync running jobs to match the given config assignments.

        - New assignments → add APScheduler job
        - Removed assignments → remove job
        - Existing assignments → no change (APScheduler keeps them running)
        """
        incoming_ids = {a.assignment_id for a in config.assignments}

        # Remove jobs for dropped assignments
        for removed_id in self._known_assignment_ids - incoming_ids:
            if self._scheduler.get_job(removed_id):
                self._scheduler.remove_job(removed_id)
                logger.info("job_removed", assignment_id=removed_id)

        # Add jobs for new assignments
        for assignment in config.assignments:
            if assignment.assignment_id not in self._known_assignment_ids:
                self._schedule_assignment(assignment)

        self._known_assignment_ids = incoming_ids

    def _schedule_assignment(self, assignment: AppAssignmentConfig) -> None:
        """Add a single APScheduler job for an assignment."""
        schedule = assignment.schedule

        if schedule.type == "interval":
            try:
                interval_seconds = int(schedule.value)
            except ValueError:
                logger.error(
                    "invalid_interval",
                    assignment_id=assignment.assignment_id,
                    value=schedule.value,
                )
                return
            self._scheduler.add_job(
                self._run_assignment,
                trigger="interval",
                seconds=interval_seconds,
                id=assignment.assignment_id,
                args=[assignment],
                next_run_time=datetime.now(tz=timezone.utc),  # run immediately first time
                max_instances=1,  # never overlap executions of the same check
                misfire_grace_time=interval_seconds,
            )
        elif schedule.type == "cron":
            self._scheduler.add_job(
                self._run_assignment,
                trigger="cron",
                id=assignment.assignment_id,
                args=[assignment],
                **self._parse_cron(schedule.value),
                max_instances=1,
                misfire_grace_time=60,
            )
        else:
            logger.warning(
                "unknown_schedule_type",
                assignment_id=assignment.assignment_id,
                schedule_type=schedule.type,
            )
            return

        logger.info(
            "job_scheduled",
            assignment_id=assignment.assignment_id,
            app_name=assignment.app_name,
            schedule_type=schedule.type,
            schedule_value=schedule.value,
        )

    async def _run_assignment(self, assignment: AppAssignmentConfig) -> None:
        """Execute one check and enqueue the result into the buffer."""
        log = logger.bind(
            assignment_id=assignment.assignment_id,
            app_name=assignment.app_name,
        )
        try:
            check_result = await self._execute(assignment)

            app_result = AppResult(
                assignment_id=assignment.assignment_id,
                app_id=assignment.app_id,
                check_result=check_result,
                executed_at=datetime.now(tz=timezone.utc),
            )

            from monctl_common.utils import utc_now
            payload = {
                "collector_id": self.collector_id,
                "timestamp": utc_now().isoformat(),
                "sequence": 0,
                "app_results": [app_result.model_dump(mode="json")],
                "events": [],
            }
            await self.buffer.enqueue(payload)

            log.info(
                "app_executed",
                state=check_result.state.name,
                output=check_result.output[:120],
                execution_time=check_result.execution_time,
            )
        except Exception as e:
            log.error("app_execution_failed", error=str(e))

    async def _execute(self, assignment: AppAssignmentConfig):
        """Determine app type and delegate to executor."""
        limits = assignment.resource_limits
        app_name = assignment.app_name  # e.g., "ping_check"

        # Try script path first: <apps_dir>/<app_name>.py
        script_path = os.path.join(self.apps_dir, f"{app_name}.py")
        if os.path.isfile(script_path):
            return await self.executor.run_script_app(
                script_path=script_path,
                config=assignment.config,
                timeout_seconds=limits.timeout_seconds,
                memory_mb=limits.memory_mb,
            )

        # Fallback: try bare app name (for SDK apps registered by name)
        # SDK apps would be dynamically imported here in a future implementation
        from monctl_common.constants import CheckState
        from monctl_common.schemas.metrics import CheckResult
        return CheckResult(
            state=CheckState.UNKNOWN,
            output=f"App not found: {app_name} (looked for {script_path})",
        )

    @staticmethod
    def _parse_cron(cron_expr: str) -> dict:
        """Parse '* * * * *' (min hr dom mon dow) into APScheduler kwargs."""
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr!r}")
        keys = ["minute", "hour", "day", "month", "day_of_week"]
        return dict(zip(keys, parts))
