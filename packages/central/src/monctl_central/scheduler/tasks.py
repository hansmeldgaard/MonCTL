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

from monctl_central.config import parse_node_list, settings
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
        self._last_eligibility_scan: datetime | None = None

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
                    await self._evaluate_system_health()
                # Alert evaluation runs every 30s
                await self._evaluate_alerts()
                # Event policy evaluation (runs after alerts)
                await self._evaluate_event_policies()
                # Cron automation evaluation (runs after events)
                await self._evaluate_cron_automations()
                # Rollup + cleanup (checked every cycle, runs based on time)
                await self._run_rollups()
                # Alert instance sync every 5 min (every 10th cycle)
                if cycle % 10 == 0:
                    await self._sync_alert_instances()
                # App cache TTL cleanup every 5 min (every 10th cycle, offset)
                if cycle % 10 == 2:
                    await self._cleanup_app_cache()
                # Cost-aware job rebalancing every 5 min (every 10th cycle)
                if cycle % 10 == 5:
                    await self._rebalance_collector_groups()
                # OS update check (daily) — fire-and-forget to avoid blocking alerts
                asyncio.create_task(self._check_os_updates())
                # Nightly eligibility scan (daily, configurable time)
                await self._run_eligibility_scan()
                # Finalize completed eligibility runs (every cycle)
                await self._finalize_eligibility_runs()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler_task_error")

    async def _health_check(self) -> None:
        """Mark stale collectors as DOWN and bump surviving group members."""
        from sqlalchemy import select, update
        from monctl_central.storage.models import Collector, CollectorGroup
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
                    # Invalidate weight snapshot — topology changed
                    group = await session.get(CollectorGroup, c.group_id)
                    if group:
                        group.weight_snapshot = None

            if stale:
                await session.commit()
                logger.info("collector_health_check marked_down=%d", len(stale))

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_health_check", utc_now().isoformat()
            )

    async def _evaluate_system_health(self) -> None:
        """Evaluate system health thresholds and write alerts to alert_log."""
        if self._ch is None:
            return

        import json
        import uuid
        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now
        from sqlalchemy import text

        SYSTEM_APP_ID = "00000000-0000-0000-0000-000000000001"
        SYSTEM_DEVICE_ID = "00000000-0000-0000-0000-000000000000"
        ZERO_UUID = "00000000-0000-0000-0000-000000000000"

        def _check_def(name: str, entity: str, current_val, threshold, severity="warning",
                       comparison="gt", message_tpl="{name}: {current} (threshold: {threshold})"):
            """Evaluate a single threshold and return fire/clear action or None."""
            if current_val is None:
                return None
            if comparison == "gt":
                breached = current_val > threshold
            elif comparison == "lt":
                breached = current_val < threshold
            else:
                breached = False
            return {
                "name": name,
                "entity_key": entity,
                "breached": breached,
                "severity": severity,
                "current_value": float(current_val),
                "threshold_value": float(threshold),
                "message": message_tpl.format(name=name, current=current_val, threshold=threshold),
            }

        checks = []

        try:
            async with self._session_factory() as db:
                # ── PostgreSQL checks ──
                try:
                    # Replication lag
                    rows = (await db.execute(text(
                        "SELECT (EXTRACT(EPOCH FROM replay_lag))::float AS lag_s"
                        " FROM pg_stat_replication"
                    ))).all()
                    for r in rows:
                        if r[0] is not None:
                            checks.append(_check_def(
                                "PostgreSQL Replication Lag", "postgresql|replication_lag",
                                r[0], 30.0, severity="critical",
                                message_tpl="{name}: {current:.1f}s (threshold: {threshold}s)",
                            ))
                            checks.append(_check_def(
                                "PostgreSQL Replication Lag Warning", "postgresql|replication_lag_warn",
                                r[0], 5.0, severity="warning",
                                message_tpl="{name}: {current:.1f}s (threshold: {threshold}s)",
                            ))
                except Exception:
                    pass

                try:
                    # Cache hit ratio
                    row = (await db.execute(text(
                        "SELECT CASE WHEN (blks_hit + blks_read) > 0"
                        "   THEN 100.0 * blks_hit / (blks_hit + blks_read)"
                        "   ELSE 100 END FROM pg_stat_database"
                        " WHERE datname = current_database()"
                    ))).scalar()
                    if row is not None:
                        checks.append(_check_def(
                            "PostgreSQL Cache Hit Ratio", "postgresql|cache_hit",
                            float(row), 95.0, severity="critical", comparison="lt",
                            message_tpl="{name}: {current:.1f}% (threshold: >{threshold}%)",
                        ))
                except Exception:
                    pass

                try:
                    # XID wraparound
                    xid = (await db.execute(text(
                        "SELECT age(datfrozenxid) FROM pg_database"
                        " WHERE datname = current_database()"
                    ))).scalar()
                    if xid is not None:
                        checks.append(_check_def(
                            "PostgreSQL XID Wraparound", "postgresql|xid_age",
                            xid, 1_000_000_000, severity="critical",
                            message_tpl="{name}: {current:,.0f} (threshold: {threshold:,.0f})",
                        ))
                        checks.append(_check_def(
                            "PostgreSQL XID Wraparound Warning", "postgresql|xid_age_warn",
                            xid, 500_000_000, severity="warning",
                            message_tpl="{name}: {current:,.0f} (threshold: {threshold:,.0f})",
                        ))
                except Exception:
                    pass

                try:
                    # Waiting locks
                    locks = (await db.execute(text(
                        "SELECT count(*) FROM pg_locks WHERE NOT granted"
                    ))).scalar() or 0
                    checks.append(_check_def(
                        "PostgreSQL Waiting Locks", "postgresql|waiting_locks",
                        locks, 10, severity="warning",
                    ))
                except Exception:
                    pass

                try:
                    # Connection usage
                    total = (await db.execute(text("SELECT count(*) FROM pg_stat_activity"))).scalar() or 0
                    max_c = (await db.execute(text(
                        "SELECT setting::int FROM pg_settings WHERE name = 'max_connections'"
                    ))).scalar() or 100
                    pct = (total / max_c * 100) if max_c > 0 else 0
                    checks.append(_check_def(
                        "PostgreSQL Connection Usage", "postgresql|connection_pct",
                        pct, 80, severity="warning",
                        message_tpl="{name}: {current:.0f}% ({threshold}% threshold)",
                    ))
                except Exception:
                    pass

        except Exception:
            logger.exception("system_health_pg_checks_failed")

        # ── Patroni checks ──
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                cluster = None
                for _name, ip in parse_node_list(settings.patroni_nodes):
                    try:
                        resp = await client.get(f"http://{ip}:8008/cluster")
                        if resp.status_code == 200:
                            cluster = resp.json()
                            break
                    except Exception:
                        continue

                if cluster:
                    members = cluster.get("members", [])
                    leader = [m for m in members if m.get("role") == "leader"]
                    checks.append(_check_def(
                        "Patroni No Leader", "patroni|no_leader",
                        0 if leader else 1, 0.5, severity="critical",
                        message_tpl="Patroni cluster has no leader!" if not leader else "Patroni leader OK",
                    ))
                    running = [m for m in members if m.get("state") == "running"]
                    checks.append(_check_def(
                        "Patroni Members Down", "patroni|members_down",
                        len(members) - len(running), 0.5, severity="warning",
                        message_tpl="{name}: {current:.0f} members not running",
                    ))
                else:
                    checks.append({
                        "name": "Patroni Unreachable", "entity_key": "patroni|unreachable",
                        "breached": True, "severity": "critical",
                        "current_value": 1.0, "threshold_value": 0.0,
                        "message": "No Patroni node reachable",
                    })
        except Exception:
            logger.exception("system_health_patroni_checks_failed")

        # ── etcd checks ──
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                etcd_nodes = parse_node_list(settings.etcd_nodes)
                healthy = 0
                for _name, ip in etcd_nodes:
                    try:
                        resp = await client.get(f"http://{ip}:2379/health")
                        if resp.status_code == 200 and resp.json().get("health") == "true":
                            healthy += 1
                    except Exception:
                        continue
                total = len(etcd_nodes) or 1
                checks.append(_check_def(
                    "etcd Unhealthy Nodes", "etcd|unhealthy",
                    total - healthy, 0.5, severity="critical" if healthy == 0 else "warning",
                    message_tpl=f"{{name}}: {{current:.0f}} of {total} nodes unhealthy",
                ))
        except Exception:
            logger.exception("system_health_etcd_checks_failed")

        # ── Process results: fire/clear via Redis state ──
        if not _redis:
            return

        alert_records = []
        now = utc_now()
        for check in checks:
            if check is None:
                continue
            key = f"monctl:system_health:alerts:{check['entity_key']}"
            prev_state = await _redis.get(key)
            prev_state = (prev_state if isinstance(prev_state, str) else prev_state.decode()) if prev_state else "ok"

            if check["breached"] and prev_state == "ok":
                # Transition ok → firing
                await _redis.set(key, "firing")
                alert_records.append({
                    "definition_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, check["name"])),
                    "definition_name": check["name"],
                    "entity_key": check["entity_key"],
                    "action": "fire",
                    "severity": check["severity"],
                    "current_value": check["current_value"],
                    "threshold_value": check["threshold_value"],
                    "expression": "",
                    "device_id": SYSTEM_DEVICE_ID,
                    "device_name": "monctl-cluster",
                    "assignment_id": ZERO_UUID,
                    "app_id": SYSTEM_APP_ID,
                    "app_name": "System Health",
                    "tenant_id": ZERO_UUID,
                    "entity_labels": json.dumps({"component": check["entity_key"].split("|")[0]}),
                    "fire_count": 1,
                    "message": check["message"],
                    "metric_values": json.dumps({"value": check["current_value"]}),
                    "threshold_values": json.dumps({"threshold": check["threshold_value"]}),
                    "occurred_at": now,
                })
                logger.warning("system_health_alert_fired check=%s value=%s",
                               check["name"], check["current_value"])

            elif not check["breached"] and prev_state == "firing":
                # Transition firing → ok
                await _redis.set(key, "ok")
                alert_records.append({
                    "definition_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, check["name"])),
                    "definition_name": check["name"],
                    "entity_key": check["entity_key"],
                    "action": "clear",
                    "severity": check["severity"],
                    "current_value": check["current_value"],
                    "threshold_value": check["threshold_value"],
                    "expression": "",
                    "device_id": SYSTEM_DEVICE_ID,
                    "device_name": "monctl-cluster",
                    "assignment_id": ZERO_UUID,
                    "app_id": SYSTEM_APP_ID,
                    "app_name": "System Health",
                    "tenant_id": ZERO_UUID,
                    "entity_labels": json.dumps({"component": check["entity_key"].split("|")[0]}),
                    "fire_count": 0,
                    "message": f"Resolved: {check['name']}",
                    "metric_values": json.dumps({"value": check["current_value"]}),
                    "threshold_values": json.dumps({"threshold": check["threshold_value"]}),
                    "occurred_at": now,
                })
                logger.info("system_health_alert_cleared check=%s", check["name"])

        if alert_records:
            try:
                import asyncio as _aio
                await _aio.to_thread(self._ch.insert_alert_log, alert_records)
                logger.info("system_health_alerts_written count=%d", len(alert_records))
            except Exception:
                logger.exception("system_health_alert_write_failed")

        await _redis.set("monctl:scheduler:last_system_health", now.isoformat())

    async def _sync_alert_instances(self) -> None:
        """Ensure AlertEntities exist for all (definition, assignment) pairs.

        Catches cases where definitions were created after assignments,
        or assignments were created via template auto-apply without triggering sync.
        """
        from sqlalchemy import select
        from monctl_central.storage.models import AlertDefinition, AlertEntity, AppAssignment

        try:
            async with self._session_factory() as session:
                definitions = (
                    await session.execute(
                        select(AlertDefinition).where(AlertDefinition.enabled == True)  # noqa: E712
                    )
                ).scalars().all()

                created = 0
                for defn in definitions:
                    assignments = (
                        await session.execute(
                            select(AppAssignment).where(
                                AppAssignment.app_id == defn.app_id,
                                AppAssignment.enabled == True,  # noqa: E712
                                AppAssignment.device_id.isnot(None),
                            )
                        )
                    ).scalars().all()

                    existing_keys = set(
                        (await session.execute(
                            select(AlertEntity.assignment_id)
                            .where(AlertEntity.definition_id == defn.id)
                        )).scalars().all()
                    )

                    for assignment in assignments:
                        if assignment.id not in existing_keys:
                            session.add(AlertEntity(
                                definition_id=defn.id,
                                assignment_id=assignment.id,
                                device_id=assignment.device_id,
                                enabled=True,
                                state="ok",
                            ))
                            created += 1

                if created:
                    await session.commit()
                    logger.info("alert_instance_sync created=%d", created)
        except Exception:
            logger.exception("alert_instance_sync_error")

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

    async def _evaluate_cron_automations(self) -> None:
        """Run cron automation evaluation if ClickHouse is available."""
        if self._ch is None:
            return
        try:
            from monctl_central.automations.engine import AutomationEngine
            engine = AutomationEngine(
                session_factory=self._session_factory,
                ch_client=self._ch,
            )
            await engine.evaluate_cron_triggers()
        except Exception:
            logger.exception("cron_automation_error")

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
                await self._avail_hourly_rollup()
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
                await self._avail_daily_rollup()
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

    async def _avail_hourly_rollup(self) -> None:
        """Aggregate raw availability_latency data into availability_latency_hourly."""
        sql = """
        INSERT INTO availability_latency_hourly
        SELECT
            device_id,
            assignment_id,
            app_id,
            toStartOfHour(executed_at)    AS hour,
            min(rtt_ms)                   AS rtt_min,
            max(rtt_ms)                   AS rtt_max,
            avg(rtt_ms)                   AS rtt_avg,
            quantile(0.95)(rtt_ms)        AS rtt_p95,
            min(response_time_ms)         AS response_time_min,
            max(response_time_ms)         AS response_time_max,
            avg(response_time_ms)         AS response_time_avg,
            quantile(0.95)(response_time_ms) AS response_time_p95,
            toFloat32(avg(reachable) * 100) AS availability_pct,
            toUInt16(count())             AS sample_count,
            any(device_name)              AS device_name,
            any(app_name)                 AS app_name,
            any(tenant_id)                AS tenant_id,
            any(tenant_name)              AS tenant_name
        FROM availability_latency
        WHERE executed_at >= toStartOfHour(now() - INTERVAL 2 HOUR)
          AND executed_at < toStartOfHour(now())
        GROUP BY device_id, assignment_id, app_id, hour
        """
        self._ch.execute_rollup(sql)
        logger.info("avail_hourly_rollup_complete")

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_avail_hourly_rollup", utc_now().isoformat()
            )

    async def _avail_daily_rollup(self) -> None:
        """Aggregate availability_latency_hourly into availability_latency_daily."""
        sql = """
        INSERT INTO availability_latency_daily
        SELECT
            device_id,
            assignment_id,
            app_id,
            toStartOfDay(hour)            AS day,
            min(rtt_min)                   AS rtt_min,
            max(rtt_max)                   AS rtt_max,
            avg(rtt_avg)                   AS rtt_avg,
            quantile(0.95)(rtt_p95)        AS rtt_p95,
            min(response_time_min)         AS response_time_min,
            max(response_time_max)         AS response_time_max,
            avg(response_time_avg)         AS response_time_avg,
            quantile(0.95)(response_time_p95) AS response_time_p95,
            avg(availability_pct)          AS availability_pct,
            toUInt16(sum(sample_count))    AS sample_count,
            any(device_name)               AS device_name,
            any(app_name)                  AS app_name,
            any(tenant_id)                 AS tenant_id,
            any(tenant_name)               AS tenant_name
        FROM availability_latency_hourly
        WHERE hour >= toStartOfDay(now() - INTERVAL 1 DAY)
          AND hour < toStartOfDay(now())
        GROUP BY device_id, assignment_id, app_id, day
        """
        self._ch.execute_rollup(sql)
        logger.info("avail_daily_rollup_complete")

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_avail_daily_rollup", utc_now().isoformat()
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
        avail_hourly_days = 365
        avail_daily_days = 1825

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
                for key in ["perf_hourly_retention_days", "perf_daily_retention_days"]:
                    setting = await session.get(SystemSetting, key)
                    if setting:
                        if key == "perf_hourly_retention_days":
                            perf_hourly_days = int(setting.value)
                        elif key == "perf_daily_retention_days":
                            perf_daily_days = int(setting.value)

                # Availability rollup retention
                for key in [
                    "avail_raw_retention_days",
                    "avail_hourly_retention_days",
                    "avail_daily_retention_days",
                ]:
                    setting = await session.get(SystemSetting, key)
                    if setting:
                        if key == "avail_raw_retention_days":
                            avail_days = int(setting.value)
                        elif key == "avail_hourly_retention_days":
                            avail_hourly_days = int(setting.value)
                        elif key == "avail_daily_retention_days":
                            avail_daily_days = int(setting.value)

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
            f"ALTER TABLE availability_latency_hourly DELETE WHERE hour < now() - INTERVAL {avail_hourly_days} DAY",
            f"ALTER TABLE availability_latency_daily DELETE WHERE day < today() - INTERVAL {avail_daily_days} DAY",
        ]

        for sql in cleanup_sqls:
            try:
                self._ch.execute_cleanup(sql)
            except Exception:
                logger.debug("Cleanup query failed: %s", sql, exc_info=True)

        logger.info(
            "retention_cleanup_complete iface=%s/%s/%s perf=%s/%s/%s avail=%s/%s/%s config=%s overrides=%s",
            raw_days, hourly_days, daily_days,
            perf_days, perf_hourly_days, perf_daily_days,
            avail_days, avail_hourly_days, avail_daily_days,
            config_days, len(overrides),
        )

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

        # Mark as checked immediately to prevent blocking scheduler on retries
        self._last_os_check = now

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

                logger.info("os_update_check_complete node_count=%d", len(nodes))

        except Exception:
            logger.exception("os_update_check_error")

    async def _rebalance_collector_groups(self) -> None:
        """Periodically rebalance job weights across collector groups.

        For each group with 2+ active collectors, compute total cost per
        collector using avg_execution_time from AppAssignment. If the
        imbalance exceeds 50%, update the weight_snapshot on CollectorGroup
        so that subsequent GET /jobs requests use the new weights.
        """
        import bisect
        import hashlib

        from sqlalchemy import func, select
        from monctl_central.storage.models import (
            AppAssignment, Collector, CollectorGroup, Device,
        )
        from monctl_common.utils import utc_now

        try:
            async with self._session_factory() as session:
                # Find groups with 2+ active collectors
                group_stmt = (
                    select(CollectorGroup.id)
                    .join(Collector, Collector.group_id == CollectorGroup.id)
                    .where(Collector.status == "ACTIVE")
                    .group_by(CollectorGroup.id)
                    .having(func.count(Collector.id) >= 2)
                )
                group_ids = (await session.execute(group_stmt)).scalars().all()

                for gid in group_ids:
                    await self._rebalance_group(session, gid)

                if group_ids:
                    await session.commit()

        except Exception:
            logger.exception("rebalance_collector_groups_error")

    async def _rebalance_group(self, session, group_id) -> None:
        """Rebalance a single collector group if cost imbalance exceeds threshold."""
        import bisect
        import hashlib

        from sqlalchemy import select
        from monctl_central.storage.models import (
            AppAssignment, Collector, CollectorGroup, Device,
        )

        # Get active collectors
        coll_stmt = (
            select(Collector)
            .where(Collector.group_id == group_id, Collector.status == "ACTIVE")
            .order_by(Collector.hostname)
        )
        collectors = (await session.execute(coll_stmt)).scalars().all()
        if len(collectors) < 2:
            return

        active_hostnames = {c.hostname for c in collectors}
        group = await session.get(CollectorGroup, group_id)
        if not group:
            return

        # Get current weights (snapshot or equal)
        snapshot = group.weight_snapshot
        if snapshot and set(snapshot.keys()) == active_hostnames:
            current_weights = snapshot
        else:
            current_weights = {c.hostname: 1.0 for c in collectors}

        # Get all unpinned assignments for devices in this group
        assign_stmt = (
            select(
                AppAssignment.id,
                AppAssignment.avg_execution_time,
                AppAssignment.schedule_value,
            )
            .join(Device, AppAssignment.device_id == Device.id)
            .where(
                Device.collector_group_id == group_id,
                AppAssignment.collector_id.is_(None),
                AppAssignment.enabled == True,  # noqa: E712
                Device.is_enabled == True,  # noqa: E712
            )
        )
        assignments = (await session.execute(assign_stmt)).all()
        if not assignments:
            return

        # Simulate hash-ring to compute cost per collector
        cost_per_collector: dict[str, float] = {h: 0.0 for h in active_hostnames}
        for aid, avg_time, schedule_value in assignments:
            owner = self._hash_ring_owner(str(aid), current_weights)
            if owner not in cost_per_collector:
                continue
            # Cost = avg_execution_time / interval (load contribution)
            try:
                interval = float(schedule_value)
            except (ValueError, TypeError):
                interval = 300.0
            avg = avg_time if avg_time is not None else 5.0  # default estimate
            cost_per_collector[owner] += avg / max(interval, 1.0)

        # Check imbalance
        costs = list(cost_per_collector.values())
        min_cost = min(costs)
        max_cost = max(costs)
        if min_cost <= 0:
            min_cost = 0.001  # avoid division by zero

        imbalance_ratio = max_cost / min_cost
        if imbalance_ratio <= 1.5:
            # Balanced enough — update topology count but keep current weights
            group.weight_snapshot = current_weights
            group.weight_snapshot_topology = len(collectors)
            return

        # Compute new weights inversely proportional to current cost
        new_weights: dict[str, float] = {}
        for hostname, cost in cost_per_collector.items():
            # Inverse: high cost → low weight → fewer jobs
            new_weights[hostname] = 1.0 / max(cost, 0.001)

        # Normalize so max = 1.0, with a floor of 0.05 to prevent starvation
        max_w = max(new_weights.values())
        if max_w > 0:
            new_weights = {h: max(0.05, round(w / max_w, 4)) for h, w in new_weights.items()}

        # Hysteresis: only apply if any weight changed by more than 15%
        significant_change = False
        for h in active_hostnames:
            old_w = current_weights.get(h, 1.0)
            new_w = new_weights.get(h, 1.0)
            if abs(new_w - old_w) / max(old_w, 0.01) > 0.15:
                significant_change = True
                break

        if significant_change:
            group.weight_snapshot = new_weights
            group.weight_snapshot_topology = len(collectors)
            logger.info(
                "rebalance_applied group=%s imbalance=%.2f old=%s new=%s",
                group.name, imbalance_ratio, current_weights, new_weights,
            )
        else:
            # Small drift — keep current weights, just update topology
            group.weight_snapshot = current_weights
            group.weight_snapshot_topology = len(collectors)

    @staticmethod
    def _hash_ring_owner(
        assignment_id: str,
        weights: dict[str, float],
        vnodes_base: int = 100,
    ) -> str:
        """Consistent hash ring — same algorithm as collector_api/router.py."""
        import bisect
        import hashlib

        if not weights:
            return ""
        if len(weights) == 1:
            return next(iter(weights))

        max_w = max(weights.values()) or 1.0
        ring_hashes: list[int] = []
        ring_nodes: list[str] = []
        for hostname, w in sorted(weights.items()):
            n_vnodes = max(1, int(vnodes_base * (w / max_w)))
            for i in range(n_vnodes):
                h = int(hashlib.sha256(f"{hostname}:{i}".encode()).hexdigest(), 16)
                idx = bisect.bisect_left(ring_hashes, h)
                ring_hashes.insert(idx, h)
                ring_nodes.insert(idx, hostname)

        key_hash = int(hashlib.sha256(assignment_id.encode()).hexdigest(), 16)
        idx = bisect.bisect_left(ring_hashes, key_hash)
        if idx >= len(ring_hashes):
            idx = 0
        return ring_nodes[idx]

    # ── Nightly eligibility scan ─────────────────────────────────────────

    async def _finalize_eligibility_runs(self) -> None:
        """Check running eligibility runs and finalize if all devices have reported."""
        if not self._ch:
            return
        try:
            # Find running runs
            from monctl_central.storage.clickhouse import ClickHouseClient
            client = self._ch._get_client()
            sql = "SELECT run_id, app_id, app_name, total_devices, started_at, triggered_by FROM eligibility_runs FINAL WHERE status = 'running'"
            result = client.query(sql)
            for row in result.result_rows:
                run_id, app_id, app_name, total_devices, started_at, triggered_by = row
                if total_devices == 0:
                    continue

                # Count non-pending results (eligible != 2 means probed)
                count_sql = "SELECT countIf(eligible != 2) as done, countIf(eligible = 1) as elig, countIf(eligible = 0) as inelig, countIf(eligible = 2) as pending FROM eligibility_results WHERE run_id = {run_id:UUID}"
                cr = client.query(count_sql, parameters={"run_id": str(run_id)})
                if not cr.result_rows:
                    continue
                done, elig, inelig, pending = cr.result_rows[0]

                # Update progress
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                is_complete = done >= total_devices or (
                    # Also complete if run is older than 10 min (timeout)
                    hasattr(started_at, 'timestamp') and (now.timestamp() - started_at.timestamp()) > 600
                )
                self._ch.update_eligibility_run({
                    "run_id": str(run_id),
                    "app_id": str(app_id),
                    "app_name": app_name,
                    "status": "completed" if is_complete else "running",
                    "started_at": started_at,
                    "finished_at": now if is_complete else started_at,
                    "duration_ms": int((now.timestamp() - started_at.timestamp()) * 1000) if is_complete and hasattr(started_at, 'timestamp') else 0,
                    "total_devices": total_devices,
                    "tested": done,
                    "eligible": elig,
                    "ineligible": inelig,
                    "unreachable": pending if is_complete else 0,
                    "triggered_by": triggered_by,
                })
        except Exception:
            logger.exception("finalize_eligibility_runs_error")

    async def _run_eligibility_scan(self) -> None:
        """Run once daily at configurable time (system setting eligibility_scan_time)."""
        now = datetime.now(timezone.utc)

        # Read scan time from system settings (default 02:00 UTC)
        scan_hour, scan_minute = 2, 0
        try:
            async with self._session_factory() as session:
                from monctl_central.storage.models import SystemSetting
                setting = (await session.execute(
                    select(SystemSetting).where(SystemSetting.key == "eligibility_scan_time")
                )).scalar_one_or_none()
                if setting and setting.value:
                    parts = setting.value.strip().split(":")
                    if len(parts) == 2:
                        scan_hour, scan_minute = int(parts[0]), int(parts[1])
        except Exception:
            pass

        # Check if we should run now
        today_scan = now.replace(hour=scan_hour, minute=scan_minute, second=0, microsecond=0)
        if self._last_eligibility_scan and self._last_eligibility_scan.date() == now.date():
            return  # Already ran today
        if now < today_scan:
            return  # Not yet time

        self._last_eligibility_scan = now
        logger.info("nightly_eligibility_scan_starting")

        try:
            async with self._session_factory() as session:
                from monctl_central.storage.models import (
                    App, AppAssignment, AppVersion, Device, DeviceType, Pack,
                )
                from monctl_central.cache import set_discovery_flag, clear_discovery_phase2_flag

                devices = (await session.execute(
                    select(Device).where(
                        Device.is_enabled == True,  # noqa: E712
                        Device.collector_group_id.isnot(None),
                    )
                )).scalars().all()

                queued = 0
                for device in devices:
                    sys_oid = (device.metadata_ or {}).get("sys_object_id")
                    if not sys_oid or not device.device_type:
                        continue

                    dt = (await session.execute(
                        select(DeviceType).where(DeviceType.name == device.device_type)
                    )).scalar_one_or_none()
                    if not dt or not dt.auto_assign_packs:
                        continue

                    # Check for any unassigned candidate app
                    has_unassigned = False
                    for pack_uid in dt.auto_assign_packs:
                        pack = (await session.execute(
                            select(Pack).where(Pack.pack_uid == pack_uid)
                        )).scalar_one_or_none()
                        if not pack:
                            continue
                        apps = (await session.execute(
                            select(App).where(App.pack_id == pack.id)
                        )).scalars().all()
                        for app in apps:
                            if app.vendor_oid_prefix:
                                pfx = app.vendor_oid_prefix
                                if not (sys_oid == pfx or sys_oid.startswith(pfx + ".")):
                                    continue
                            existing = (await session.execute(
                                select(AppAssignment.id).where(
                                    AppAssignment.app_id == app.id,
                                    AppAssignment.device_id == device.id,
                                )
                            )).scalar_one_or_none()
                            if not existing:
                                has_unassigned = True
                                break
                        if has_unassigned:
                            break

                    if has_unassigned:
                        await clear_discovery_phase2_flag(str(device.id))
                        await set_discovery_flag(str(device.id), ttl=3600)
                        queued += 1

                logger.info("nightly_eligibility_scan_complete",
                            devices_scanned=len(devices), devices_queued=queued)
        except Exception:
            logger.exception("nightly_eligibility_scan_error")
