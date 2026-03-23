"""Scheduler tasks — runs on the leader-elected instance only.

Responsibilities:
- Health monitor: mark stale collectors as DOWN
- Alert engine: evaluate alert rules against ClickHouse data
- Interface data rollup: hourly and daily aggregation
- Data retention cleanup
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

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
        self._last_hourly_rollup: datetime | None = None
        self._last_daily_rollup: datetime | None = None
        self._last_os_check: datetime | None = None

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
                # Event policy evaluation (runs after alerts)
                await self._evaluate_event_policies()
                # Rollup + cleanup (checked every cycle, runs based on time)
                await self._run_rollups()
                # App cache TTL cleanup every 5 min (every 10th cycle)
                if cycle % 10 == 0:
                    await self._cleanup_app_cache()
                # OS update check (daily)
                await self._check_os_updates()
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
                logger.info("collector_marked_down collector_id=%s name=%s", str(c.id), c.name)
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
                logger.info("collector_health_check marked_down=%d", len(stale))

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_health_check", utc_now().isoformat()
            )

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
            return

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_evaluate_alerts", utc_now().isoformat()
            )

    async def _evaluate_event_policies(self) -> None:
        """Run event engine evaluation if ClickHouse is available."""
        if self._ch is None:
            return

        try:
            from monctl_central.events.engine import EventEngine

            engine = EventEngine(
                session_factory=self._session_factory,
                ch_client=self._ch,
            )
            await engine.evaluate_all()
        except Exception:
            logger.exception("event_policy_evaluation_error")

    async def _run_rollups(self) -> None:
        """Run hourly/daily rollups and retention cleanup when due."""
        if self._ch is None:
            return

        now = datetime.now(timezone.utc)

        # Hourly rollup — run after :05 of each hour, once per hour
        if now.minute >= 5 and (
            self._last_hourly_rollup is None
            or (now - self._last_hourly_rollup).total_seconds() >= 3600
        ):
            try:
                await self._hourly_rollup()
                await self._perf_hourly_rollup()
                self._last_hourly_rollup = now
            except Exception:
                logger.exception("hourly_rollup_error")

        # Daily rollup + cleanup — run after 00:15 UTC, once per day
        if now.hour == 0 and now.minute >= 15 and (
            self._last_daily_rollup is None
            or (now - self._last_daily_rollup).total_seconds() >= 86400
        ):
            try:
                await self._daily_rollup()
                await self._perf_daily_rollup()
                await self._retention_cleanup()
                # Alert history cleanup — reset old resolved instances to ok
                from monctl_central.alerting.cleanup import cleanup_resolved_instances
                async with self._session_factory() as session:
                    await cleanup_resolved_instances(session)
                    await session.commit()
                self._last_daily_rollup = now
            except Exception:
                logger.exception("daily_rollup_error")

    async def _hourly_rollup(self) -> None:
        """Aggregate raw interface data into interface_hourly."""
        sql = """
        INSERT INTO interface_hourly
        SELECT
            device_id, interface_id,
            toStartOfHour(executed_at) AS hour,
            min(in_rate_bps) AS in_rate_min,
            max(in_rate_bps) AS in_rate_max,
            avg(in_rate_bps) AS in_rate_avg,
            quantile(0.95)(in_rate_bps) AS in_rate_p95,
            min(out_rate_bps) AS out_rate_min,
            max(out_rate_bps) AS out_rate_max,
            avg(out_rate_bps) AS out_rate_avg,
            quantile(0.95)(out_rate_bps) AS out_rate_p95,
            max(in_utilization_pct) AS in_utilization_max,
            avg(in_utilization_pct) AS in_utilization_avg,
            max(out_utilization_pct) AS out_utilization_max,
            avg(out_utilization_pct) AS out_utilization_avg,
            if(max(in_octets) > min(in_octets), max(in_octets) - min(in_octets), 0) AS in_octets_total,
            if(max(out_octets) > min(out_octets), max(out_octets) - min(out_octets), 0) AS out_octets_total,
            sum(in_errors) AS in_errors_total,
            sum(out_errors) AS out_errors_total,
            sum(in_discards) AS in_discards_total,
            sum(out_discards) AS out_discards_total,
            (countIf(if_oper_status = 'up') / count()) * 100 AS availability_pct,
            toUInt16(count()) AS sample_count,
            max(if_speed_mbps) AS if_speed_mbps,
            any(device_name) AS device_name,
            any(if_name) AS if_name,
            any(tenant_id) AS tenant_id,
            any(tenant_name) AS tenant_name
        FROM interface
        WHERE executed_at >= toStartOfHour(now() - INTERVAL 1 HOUR)
          AND executed_at < toStartOfHour(now())
        GROUP BY device_id, interface_id, hour
        """
        self._ch.execute_rollup(sql)
        logger.info("hourly_rollup_complete")

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_hourly_rollup", utc_now().isoformat()
            )

    async def _perf_hourly_rollup(self) -> None:
        """Aggregate raw performance data into performance_hourly."""
        sql = """
        INSERT INTO performance_hourly
        SELECT
            device_id,
            app_id,
            component_type,
            component,
            mn AS metric_name,
            mt AS metric_type,
            toStartOfHour(executed_at) AS hour,
            min(mv) AS val_min,
            max(mv) AS val_max,
            avg(mv) AS val_avg,
            quantile(0.95)(mv) AS val_p95,
            toUInt16(count()) AS sample_count,
            any(device_name) AS device_name,
            any(app_name) AS app_name,
            any(tenant_id) AS tenant_id,
            any(tenant_name) AS tenant_name
        FROM (
            SELECT
                device_id, app_id, component_type, component,
                executed_at, device_name, app_name, tenant_id, tenant_name,
                mn, mv, mt
            FROM performance
            ARRAY JOIN
                metric_names AS mn,
                metric_values AS mv,
                arrayResize(metric_types, length(metric_names), 'gauge') AS mt
            WHERE executed_at >= toStartOfHour(now() - INTERVAL 1 HOUR)
              AND executed_at < toStartOfHour(now())
        )
        GROUP BY device_id, app_id, component_type, component, mn, mt, hour
        """
        self._ch.execute_rollup(sql)
        logger.info("perf_hourly_rollup_complete")

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_perf_hourly_rollup", utc_now().isoformat()
            )

    async def _daily_rollup(self) -> None:
        """Aggregate hourly data into interface_daily."""
        sql = """
        INSERT INTO interface_daily
        SELECT
            device_id, interface_id,
            toStartOfDay(hour) AS day,
            min(in_rate_min) AS in_rate_min,
            max(in_rate_max) AS in_rate_max,
            avg(in_rate_avg) AS in_rate_avg,
            quantile(0.95)(in_rate_p95) AS in_rate_p95,
            min(out_rate_min) AS out_rate_min,
            max(out_rate_max) AS out_rate_max,
            avg(out_rate_avg) AS out_rate_avg,
            quantile(0.95)(out_rate_p95) AS out_rate_p95,
            max(in_utilization_max) AS in_utilization_max,
            avg(in_utilization_avg) AS in_utilization_avg,
            max(out_utilization_max) AS out_utilization_max,
            avg(out_utilization_avg) AS out_utilization_avg,
            sum(in_octets_total) AS in_octets_total,
            sum(out_octets_total) AS out_octets_total,
            sum(in_errors_total) AS in_errors_total,
            sum(out_errors_total) AS out_errors_total,
            sum(in_discards_total) AS in_discards_total,
            sum(out_discards_total) AS out_discards_total,
            avg(availability_pct) AS availability_pct,
            toUInt16(sum(sample_count)) AS sample_count,
            max(if_speed_mbps) AS if_speed_mbps,
            any(device_name) AS device_name,
            any(if_name) AS if_name,
            any(tenant_id) AS tenant_id,
            any(tenant_name) AS tenant_name
        FROM interface_hourly
        WHERE hour >= toStartOfDay(now() - INTERVAL 1 DAY)
          AND hour < toStartOfDay(now())
        GROUP BY device_id, interface_id, day
        """
        self._ch.execute_rollup(sql)
        logger.info("daily_rollup_complete")

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_daily_rollup", utc_now().isoformat()
            )

    async def _perf_daily_rollup(self) -> None:
        """Aggregate hourly performance data into performance_daily."""
        sql = """
        INSERT INTO performance_daily
        SELECT
            device_id,
            app_id,
            component_type,
            component,
            metric_name,
            metric_type,
            toStartOfDay(hour) AS day,
            min(val_min) AS val_min,
            max(val_max) AS val_max,
            avg(val_avg) AS val_avg,
            quantile(0.95)(val_p95) AS val_p95,
            toUInt16(sum(sample_count)) AS sample_count,
            any(device_name) AS device_name,
            any(app_name) AS app_name,
            any(tenant_id) AS tenant_id,
            any(tenant_name) AS tenant_name
        FROM performance_hourly
        WHERE hour >= toStartOfDay(now() - INTERVAL 1 DAY)
          AND hour < toStartOfDay(now())
        GROUP BY device_id, app_id, component_type, component, metric_name, metric_type, day
        """
        self._ch.execute_rollup(sql)
        logger.info("perf_daily_rollup_complete")

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_perf_daily_rollup", utc_now().isoformat()
            )

    async def _retention_cleanup(self) -> None:
        """Delete data older than configured retention periods.

        Handles both global defaults and per-device overrides.
        Per-device overrides are applied first, then global defaults
        clean up remaining data (excluding overridden device+app combos).
        """
        from sqlalchemy import select
        from monctl_central.storage.models import DataRetentionOverride, SystemSetting

        # Load global retention settings
        raw_days = 7
        hourly_days = 90
        daily_days = 730
        config_days = 90
        perf_days = 90
        avail_days = 30
        perf_hourly_days = 90
        perf_daily_days = 730

        try:
            async with self._session_factory() as session:
                for key, default in [
                    ("interface_raw_retention_days", 7),
                    ("interface_hourly_retention_days", 90),
                    ("interface_daily_retention_days", 730),
                    ("config_retention_days", 90),
                    ("check_results_retention_days", 90),
                ]:
                    setting = await session.get(SystemSetting, key)
                    val = int(setting.value) if setting else default
                    if key == "interface_raw_retention_days":
                        raw_days = val
                    elif key == "interface_hourly_retention_days":
                        hourly_days = val
                    elif key == "interface_daily_retention_days":
                        daily_days = val
                    elif key == "config_retention_days":
                        config_days = val
                    elif key == "check_results_retention_days":
                        perf_days = val
                        avail_days = val

                # Load retention defaults from unified system
                for dt, fallback in [
                    ("config", config_days),
                    ("performance", perf_days),
                    ("availability_latency", avail_days),
                    ("interface", raw_days),
                ]:
                    rkey = f"retention_days_{dt}"
                    setting = await session.get(SystemSetting, rkey)
                    if setting:
                        val = int(setting.value)
                        if dt == "config":
                            config_days = val
                        elif dt == "performance":
                            perf_days = val
                        elif dt == "availability_latency":
                            avail_days = val
                        elif dt == "interface":
                            raw_days = val

                # Performance rollup retention
                for key, attr in [
                    ("perf_hourly_retention_days", None),
                    ("perf_daily_retention_days", None),
                ]:
                    setting = await session.get(SystemSetting, key)
                    if setting:
                        if key == "perf_hourly_retention_days":
                            perf_hourly_days = int(setting.value)
                        elif key == "perf_daily_retention_days":
                            perf_daily_days = int(setting.value)

                # Process per-device overrides
                overrides = (await session.execute(select(DataRetentionOverride))).scalars().all()

        except Exception:
            logger.debug("Could not load retention settings, using defaults")
            overrides = []

        # Apply per-device overrides first
        override_exclusions: dict[str, list[str]] = {
            "config": [], "performance": [],
            "availability_latency": [], "interface": [],
        }

        for override in overrides:
            table = override.data_type
            if table not in override_exclusions:
                continue
            ts_col = "hour" if table == "interface_hourly" else (
                "day" if table == "interface_daily" else "executed_at"
            )
            try:
                self._ch.execute_cleanup(
                    f"ALTER TABLE {table} DELETE WHERE "
                    f"device_id = '{override.device_id}' AND app_id = '{override.app_id}' "
                    f"AND {ts_col} < now() - INTERVAL {override.retention_days} DAY"
                )
            except Exception:
                logger.debug("Override cleanup failed: %s/%s", override.device_id, override.app_id)
            override_exclusions[table].append(
                f"(device_id = '{override.device_id}' AND app_id = '{override.app_id}')"
            )

        # Global cleanup — exclude overridden combos
        def _exclude_clause(table: str) -> str:
            conds = override_exclusions.get(table, [])
            return f" AND NOT ({' OR '.join(conds)})" if conds else ""

        cleanup_sqls = [
            f"ALTER TABLE interface DELETE WHERE executed_at < now() - INTERVAL {raw_days} DAY{_exclude_clause('interface')}",
            f"ALTER TABLE interface_hourly DELETE WHERE hour < now() - INTERVAL {hourly_days} DAY",
            f"ALTER TABLE interface_daily DELETE WHERE day < today() - INTERVAL {daily_days} DAY",
            f"ALTER TABLE config DELETE WHERE executed_at < now() - INTERVAL {config_days} DAY{_exclude_clause('config')}",
            f"ALTER TABLE performance DELETE WHERE executed_at < now() - INTERVAL {perf_days} DAY{_exclude_clause('performance')}",
            f"ALTER TABLE performance_hourly DELETE WHERE hour < now() - INTERVAL {perf_hourly_days} DAY",
            f"ALTER TABLE performance_daily DELETE WHERE day < today() - INTERVAL {perf_daily_days} DAY",
            f"ALTER TABLE availability_latency DELETE WHERE executed_at < now() - INTERVAL {avail_days} DAY{_exclude_clause('availability_latency')}",
        ]

        for sql in cleanup_sqls:
            try:
                self._ch.execute_cleanup(sql)
            except Exception:
                logger.debug("Cleanup query failed: %s", sql, exc_info=True)

        logger.info("retention_cleanup_complete raw_days=%s hourly_days=%s daily_days=%s config_days=%s perf_days=%s perf_hourly_days=%s perf_daily_days=%s avail_days=%s override_count=%s", raw_days, hourly_days, daily_days, config_days, perf_days, perf_hourly_days, perf_daily_days, avail_days, len(overrides))

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_retention_cleanup",
                utc_now().isoformat(),
            )

    async def _cleanup_app_cache(self) -> None:
        """Delete expired app_cache entries based on TTL."""
        from sqlalchemy import text as sa_text

        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    sa_text(
                        "DELETE FROM app_cache "
                        "WHERE ttl_seconds IS NOT NULL "
                        "AND updated_at + (ttl_seconds || ' seconds')::interval < now()"
                    )
                )
                await session.commit()
                if result.rowcount:
                    logger.info("app_cache_cleanup deleted=%d", result.rowcount)
        except Exception:
            logger.exception("app_cache_cleanup_error")

    async def _check_os_updates(self) -> None:
        """Check all nodes for OS updates via sidecars (runs daily)."""
        now = datetime.now(timezone.utc)
        if self._last_os_check is not None and (now - self._last_os_check).total_seconds() < 86400:
            return

        from sqlalchemy import delete, func, select
        from monctl_central.storage.models import OsAvailableUpdate, SystemSetting, SystemVersion

        try:
            async with self._session_factory() as session:
                # Check network_mode setting — skip if offline
                setting = await session.get(SystemSetting, "network_mode")
                if setting and setting.value == "offline":
                    logger.debug("os_update_check_skipped_offline")
                    self._last_os_check = now
                    return

                # Query all nodes
                result = await session.execute(select(SystemVersion))
                nodes = result.scalars().all()

                if not nodes:
                    self._last_os_check = now
                    return

                from monctl_central.upgrades.os_service import check_node_updates

                for node in nodes:
                    try:
                        updates = await check_node_updates(node.node_ip)
                    except Exception as exc:
                        logger.warning("os_update_check_node_failed node=%s error=%s", node.node_hostname, str(exc))
                        continue

                    # Delete old entries for this node
                    await session.execute(
                        delete(OsAvailableUpdate).where(
                            OsAvailableUpdate.node_hostname == node.node_hostname
                        )
                    )

                    # Insert new entries
                    for u in updates:
                        entry = OsAvailableUpdate(
                            node_hostname=node.node_hostname,
                            node_role=node.node_role,
                            package_name=u.get("package_name", u.get("package", "")),
                            current_version=u.get("current_version", ""),
                            new_version=u.get("new_version", u.get("version", "")),
                            severity=u.get("severity", "normal"),
                        )
                        session.add(entry)

                await session.commit()

                # Update Redis badge count
                from monctl_central.cache import _redis

                if _redis:
                    count_result = await session.execute(
                        select(func.count()).select_from(OsAvailableUpdate).where(
                            OsAvailableUpdate.is_installed == False  # noqa: E712
                        )
                    )
                    count = count_result.scalar() or 0
                    await _redis.set("monctl:os_updates:count", str(count))

                self._last_os_check = now
                logger.info("os_update_check_complete node_count=%d", len(nodes))

        except Exception:
            logger.exception("os_update_check_error")
