"""Scheduler tasks — runs on the leader-elected instance only.

Responsibilities:
- Health monitor: mark stale collectors as DOWN
- Alert engine: evaluate alert rules against ClickHouse data
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from monctl_central.scheduler.leader import LeaderElection

logger = logging.getLogger(__name__)


class SchedulerRunner:
    """Runs periodic tasks only when this instance is the elected leader."""

    def __init__(
        self,
        leader: LeaderElection,
        session_factory,
        clickhouse_client=None,
    ):
        self._leader = leader
        self._session_factory = session_factory
        self._ch = clickhouse_client
        self._task: asyncio.Task | None = None

    async def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        cycle = 0
        while True:
            await asyncio.sleep(30)
            cycle += 1
            if not self._leader.is_leader:
                continue
            try:
                # Health monitor runs every 60s (every 2nd cycle)
                if cycle % 2 == 0:
                    await self._health_check()
                # Alert evaluation runs every 30s
                await self._evaluate_alerts()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler_task_error")

    async def _health_check(self) -> None:
        """Mark stale collectors as DOWN and bump surviving group members."""
        from sqlalchemy import select, update
        from monctl_central.storage.models import Collector
        from monctl_common.utils import utc_now

        stale_seconds = 90
        cutoff = utc_now() - timedelta(seconds=stale_seconds)

        async with self._session_factory() as session:
            stale = (
                await session.execute(
                    select(Collector).where(
                        Collector.status == "ACTIVE",
                        Collector.last_seen_at < cutoff,
                    )
                )
            ).scalars().all()

            for c in stale:
                c.status = "DOWN"
                c.updated_at = utc_now()
                logger.info(
                    "collector_marked_down",
                    collector_id=str(c.id),
                    name=c.name,
                )
                if c.group_id:
                    await session.execute(
                        update(Collector)
                        .where(
                            Collector.group_id == c.group_id,
                            Collector.id != c.id,
                            Collector.status == "ACTIVE",
                        )
                        .values(
                            config_version=Collector.config_version + 1,
                            updated_at=utc_now(),
                        )
                    )

            if stale:
                await session.commit()
                logger.info("collector_health_check", marked_down=len(stale))

    async def _evaluate_alerts(self) -> None:
        """Run alert engine evaluation if ClickHouse is available."""
        if self._ch is None:
            return

        try:
            from monctl_central.alerting.engine import AlertEngine

            engine = AlertEngine(
                session_factory=self._session_factory,
                ch_client=self._ch,
            )
            await engine.evaluate_all()
        except Exception:
            logger.exception("alert_evaluation_error")
