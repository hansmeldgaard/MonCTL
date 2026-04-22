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
import os
from datetime import datetime, timedelta, timezone

from monctl_central.config import parse_node_list, settings
from monctl_central.scheduler.leader import LeaderElection

logger = logging.getLogger(__name__)


def _log_task_exception(task: asyncio.Task) -> None:
    """Done-callback that surfaces exceptions from fire-and-forget tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception(
            "scheduler_background_task_failed", exc_info=exc, extra={"task": task.get_name()}
        )


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
        self._last_inventory_collect: datetime | None = None
        self._last_eligibility_scan: datetime | None = None
        self._last_template_auto_apply: datetime | None = None
        self._alert_cycle_lock = asyncio.Lock()
        # Track OS install jobs this instance is currently driving, so the
        # resume-orphaned-jobs scan doesn't double-spawn them.
        self._active_os_jobs: set[str] = set()

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
        # One-shot at startup: configure apt source on this central node (so
        # `apt-get install` via sidecar uses the local apt-cache proxy).
        apt_task = asyncio.create_task(
            self._setup_local_apt_source(), name="setup_local_apt_source"
        )
        apt_task.add_done_callback(_log_task_exception)
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
                # IncidentEngine — runs opened/escalated/cleared transitions
                # and dispatches to AutomationEngine.on_incident_transition.
                # The legacy EventEngine + event_policies sync were retired
                # in the event policy rework's phase deprecation.
                await self._evaluate_incidents()
                # Cron automation evaluation
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
                # DB size history sampler — every 15 min (every 30th cycle)
                if cycle % 30 == 6:
                    await self._sample_db_sizes()
                # Ingestion-rate sampler — every 5 min (every 10th cycle, offset)
                if cycle % 10 == 3:
                    await self._sample_ingestion_rates()
                # OS update check (daily) — fire-and-forget to avoid blocking alerts
                os_task = asyncio.create_task(
                    self._check_os_updates(), name="check_os_updates"
                )
                os_task.add_done_callback(_log_task_exception)
                # Package inventory collection (every 6h) — fire-and-forget
                inv_task = asyncio.create_task(
                    self._collect_package_inventory(), name="collect_package_inventory"
                )
                inv_task.add_done_callback(_log_task_exception)
                # Template auto-apply (interval-based, configurable)
                if cycle % 10 == 7:
                    await self._run_template_auto_apply()
                # Nightly eligibility scan (daily, configurable time)
                await self._run_eligibility_scan()
                # Finalize completed eligibility runs (every cycle)
                await self._finalize_eligibility_runs()
                # Resume orphaned OS install jobs — a prior leader that died
                # mid-poll (e.g. its own dockerd was upgraded) leaves
                # os_install_jobs.status='running' with no driver. Any new
                # leader picks them up here.
                await self._resume_orphaned_os_jobs()
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
        """Run alert engine evaluation if ClickHouse is available.

        Guarded by `_alert_cycle_lock` so a slow CH query (>30s) can't overlap
        with the next cycle's invocation and fire duplicate state transitions.
        """
        if self._ch is None:
            return

        if self._alert_cycle_lock.locked():
            logger.warning("alert_evaluation_skipped_previous_cycle_in_flight")
            return

        async with self._alert_cycle_lock:
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

    async def _evaluate_incidents(self) -> None:
        """IncidentEngine — dispatches opened/escalated/cleared transitions
        to `AutomationEngine.on_incident_transition`. See
        docs/event-policy-rework.md. The legacy EventEngine was retired
        in phase deprecation (alembic revision zq7r8s9t0u1v); this is the
        only event-producing hook now.
        """
        try:
            from monctl_central.incidents.engine import IncidentEngine
            from monctl_central.automations.engine import AutomationEngine

            automation_engine = None
            if self._ch is not None:
                automation_engine = AutomationEngine(
                    session_factory=self._session_factory,
                    ch_client=self._ch,
                )

            engine = IncidentEngine(
                session_factory=self._session_factory,
                ch_client=self._ch,
                automation_engine=automation_engine,
            )
            await engine.evaluate_all()
        except Exception:
            logger.exception("incident_engine_error")

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
                self._last_hourly_rollup = now  # avoid retry storm

            try:
                await self._config_dedup()
            except Exception:
                logger.exception("config_dedup_error")

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
            if(max(in_errors) > min(in_errors), max(in_errors) - min(in_errors), 0) AS in_errors_total,
            if(max(out_errors) > min(out_errors), max(out_errors) - min(out_errors), 0) AS out_errors_total,
            if(max(in_discards) > min(in_discards), max(in_discards) - min(in_discards), 0) AS in_discards_total,
            if(max(out_discards) > min(out_discards), max(out_discards) - min(out_discards), 0) AS out_discards_total,
            (countIf(if_oper_status = 'up') / count()) * 100 AS availability_pct,
            toUInt16(count()) AS sample_count,
            max(if_speed_mbps) AS if_speed_mbps,
            any(device_name) AS device_name,
            any(if_name) AS if_name,
            any(tenant_id) AS tenant_id,
            any(tenant_name) AS tenant_name,
            max(counter_bits) AS counter_bits
        FROM interface
        WHERE executed_at >= toStartOfHour(now() - INTERVAL 1 HOUR)
          AND executed_at < toStartOfHour(now())
        GROUP BY device_id, interface_id, hour
        """
        await asyncio.to_thread(self._ch.execute_rollup, sql)
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
        await asyncio.to_thread(self._ch.execute_rollup, sql)
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
            any(tenant_name) AS tenant_name,
            max(counter_bits) AS counter_bits
        FROM interface_hourly
        WHERE hour >= toStartOfDay(now() - INTERVAL 1 DAY)
          AND hour < toStartOfDay(now())
        GROUP BY device_id, interface_id, day
        """
        await asyncio.to_thread(self._ch.execute_rollup, sql)
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
        await asyncio.to_thread(self._ch.execute_rollup, sql)
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
        await asyncio.to_thread(self._ch.execute_rollup, sql)
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
        await asyncio.to_thread(self._ch.execute_rollup, sql)
        logger.info("avail_daily_rollup_complete")

        from monctl_central.cache import _redis
        from monctl_common.utils import utc_now

        if _redis:
            await _redis.set(
                "monctl:scheduler:last_avail_daily_rollup", utc_now().isoformat()
            )

    async def _config_dedup(self) -> None:
        """Remove duplicate config rows where the value hasn't changed.

        For each (device_id, component_type, component, config_key), keep only:
        - The most recent row (always kept — represents current state)
        - Rows where config_hash differs from the latest hash (change points)

        This keeps the config table lean while preserving change history.
        Only processes data older than 2 hours to avoid interfering with
        in-flight writes.
        """
        if self._ch is None:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        sql = f"""
        ALTER TABLE config DELETE WHERE
            executed_at < '{cutoff}'
            AND (device_id, component_type, component, config_key, executed_at) IN (
                SELECT device_id, component_type, component, config_key, executed_at
                FROM config
                WHERE executed_at < '{cutoff}'
                AND (device_id, component_type, component, config_key, config_hash) IN (
                    SELECT device_id, component_type, component, config_key,
                           argMax(config_hash, executed_at) AS latest_hash
                    FROM config
                    GROUP BY device_id, component_type, component, config_key
                )
                AND (device_id, component_type, component, config_key, executed_at) NOT IN (
                    SELECT device_id, component_type, component, config_key,
                           max(executed_at)
                    FROM config
                    GROUP BY device_id, component_type, component, config_key
                )
            )
        """
        try:
            client = self._ch._get_client()
            await asyncio.to_thread(
                client.command,
                sql,
                settings={"allow_nondeterministic_mutations": 1},
            )
            logger.info("config_dedup_complete")
        except Exception:
            logger.exception("config_dedup_error")

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

        # ClickHouse ALTER DELETE forbids non-deterministic functions like now() — use literals
        def _ts_cutoff(days: int) -> str:
            return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        def _day_cutoff(days: int) -> str:
            return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        for override in overrides:
            table = override.data_type
            if table not in override_exclusions:
                continue
            ts_col = "hour" if table == "interface_hourly" else (
                "day" if table == "interface_daily" else "executed_at"
            )
            cutoff = _day_cutoff(override.retention_days) if ts_col in ("hour", "day") else _ts_cutoff(override.retention_days)
            try:
                await asyncio.to_thread(
                    self._ch.execute_cleanup,
                    f"ALTER TABLE {table} DELETE WHERE "
                    f"device_id = '{override.device_id}' AND app_id = '{override.app_id}' "
                    f"AND {ts_col} < '{cutoff}'",
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
            f"ALTER TABLE interface DELETE WHERE executed_at < '{_ts_cutoff(raw_days)}'{_exclude_clause('interface')}",
            f"ALTER TABLE interface_hourly DELETE WHERE hour < '{_ts_cutoff(hourly_days)}'",
            f"ALTER TABLE interface_daily DELETE WHERE day < '{_day_cutoff(daily_days)}'",
            f"ALTER TABLE config DELETE WHERE executed_at < '{_ts_cutoff(config_days)}'{_exclude_clause('config')}",
            f"ALTER TABLE performance DELETE WHERE executed_at < '{_ts_cutoff(perf_days)}'{_exclude_clause('performance')}",
            f"ALTER TABLE performance_hourly DELETE WHERE hour < '{_ts_cutoff(perf_hourly_days)}'",
            f"ALTER TABLE performance_daily DELETE WHERE day < '{_day_cutoff(perf_daily_days)}'",
            f"ALTER TABLE availability_latency DELETE WHERE executed_at < '{_ts_cutoff(avail_days)}'{_exclude_clause('availability_latency')}",
            f"ALTER TABLE availability_latency_hourly DELETE WHERE hour < '{_ts_cutoff(avail_hourly_days)}'",
            f"ALTER TABLE availability_latency_daily DELETE WHERE day < '{_day_cutoff(avail_daily_days)}'",
        ]

        for sql in cleanup_sqls:
            try:
                await asyncio.to_thread(self._ch.execute_cleanup, sql)
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

        # Cleanup audit_login_events (PostgreSQL). ClickHouse audit_mutations
        # has its own TTL set in the table DDL.
        try:
            from sqlalchemy import text as _sa_text
            from monctl_central.storage.models import SystemSetting

            login_days = 730  # default: 2 years
            async with self._session_factory() as session:
                setting = await session.get(SystemSetting, "audit_logins_retention_days")
                if setting and setting.value:
                    try:
                        login_days = int(setting.value)
                    except ValueError:
                        pass
                result = await session.execute(
                    _sa_text(
                        "DELETE FROM audit_login_events "
                        "WHERE timestamp < now() - (:days || ' days')::interval"
                    ),
                    {"days": login_days},
                )
                await session.commit()
                logger.info("audit_login_events_cleanup rows=%s days=%s",
                            result.rowcount, login_days)
        except Exception:
            logger.debug("audit_login_events_cleanup_failed", exc_info=True)

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

    async def _setup_local_apt_source(self) -> None:
        """One-shot: configure /etc/apt/sources.list.d/monctl.list on this central node.

        Runs once at scheduler startup — calls the local docker-stats sidecar's
        /os/setup-apt-source endpoint. Idempotent: does nothing if already configured.
        """
        await asyncio.sleep(15)  # Let central fully start
        try:
            import httpx
            # Central's docker-stats sidecar is accessible via the host IP on port 9100
            node_ip = os.environ.get("MONCTL_NODE_IP", "127.0.0.1")
            sidecar_url = os.environ.get("MONCTL_DOCKER_STATS_URL", f"http://{node_ip}:9100")
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{sidecar_url}/os/apt-source-status")
                if resp.status_code == 200 and resp.json().get("configured"):
                    logger.info("central_apt_source_already_configured")
                    return

            # Use VIP from env or fall back to a sensible default
            central_vip = os.environ.get("MONCTL_VIP_ADDRESS", "10.145.210.40")
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    f"{sidecar_url}/os/setup-apt-source",
                    json={"central_vip": central_vip, "distro": "noble",
                          "components": "main restricted universe multiverse"},
                )
                result = resp.json() if resp.status_code == 200 else {"success": False}
                if result.get("success"):
                    logger.info("central_apt_source_configured")
                else:
                    logger.warning("central_apt_source_setup_failed",
                                   output=(result.get("output") or "")[:500])
        except Exception:
            logger.exception("central_apt_source_setup_error")

    async def _resume_orphaned_os_jobs(self) -> None:
        """Find OS install jobs the leader isn't actively driving and take over.

        A job is considered orphaned when its row is still
        `status='running'` but its ID isn't in `self._active_os_jobs` — i.e.
        no background task on this instance is polling for it. This happens
        after the previous leader died mid-poll (e.g. its own dockerd was
        being upgraded). We re-spawn `execute_os_install_job`; its
        `_run_steps` path resumes orphaned running-install steps via the
        persisted `sidecar_job_id`.

        Idempotent: if we're already running a job (ID in set), skip. If a
        re-spawn races another instance, the FK-protected step transitions
        will serialise via PG row locking; one of them wins.
        """
        from sqlalchemy import select
        from monctl_central.storage.models import OsInstallJob
        from monctl_central.upgrades.os_service import execute_os_install_job

        try:
            async with self._session_factory() as session:
                stmt = select(OsInstallJob.id).where(OsInstallJob.status == "running")
                orphans = (await session.execute(stmt)).scalars().all()
        except Exception:
            logger.warning("resume_orphaned_os_jobs_query_failed", exc_info=True)
            return

        for job_id in orphans:
            job_id_s = str(job_id)
            if job_id_s in self._active_os_jobs:
                continue
            logger.info("os_install_job_resuming_as_orphan job_id=%s", job_id_s)
            self._active_os_jobs.add(job_id_s)

            def _clear_tracking(t: asyncio.Task, jid: str = job_id_s) -> None:
                self._active_os_jobs.discard(jid)
                if t.cancelled():
                    logger.warning("os_install_job_resume_cancelled job_id=%s", jid)
                elif t.exception() is not None:
                    logger.warning(
                        "os_install_job_resume_ended_badly job_id=%s exc=%s",
                        jid, t.exception(),
                    )

            task = asyncio.create_task(
                execute_os_install_job(self._session_factory, job_id),
                name=f"os_install_resume_{job_id_s}",
            )
            task.add_done_callback(_clear_tracking)

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

                # Only scan central nodes — collectors self-scan and report via
                # POST /api/v1/os-packages/report-updates (workers are offline,
                # central cannot reach their sidecars)
                result = await session.execute(
                    select(SystemVersion).where(SystemVersion.node_role == "central")
                )
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

    async def _collect_package_inventory(self) -> None:
        """Collect installed package inventory from all nodes (every 6 hours)."""
        now = datetime.now(timezone.utc)
        if self._last_inventory_collect is not None and (
            now - self._last_inventory_collect
        ).total_seconds() < 21600:
            return

        self._last_inventory_collect = now

        try:
            from monctl_central.upgrades.os_inventory import collect_all_inventory

            summary = await collect_all_inventory(self._session_factory)
            logger.info("package_inventory_collected nodes=%d", len(summary))
        except Exception:
            logger.exception("package_inventory_collection_error")

    # Core ingestion tables — everything a collector writes into, plus
    # alert_log since it's a high-cardinality central-written table.
    _INGESTION_TABLES = (
        "availability_latency", "performance", "interface", "config",
        "logs", "events", "alert_log",
    )

    async def _sample_ingestion_rates(self) -> None:
        """Sample rows-per-second per result table and append to history.

        Counts rows inserted in the last 5 min (via received_at / timestamp)
        for each core ingestion table, divides by the window, and writes one
        row per table into `ingestion_rate_history`. Runs on the leader only.
        """
        from datetime import datetime, timezone

        if self._ch is None:
            return

        window_seconds = 300
        ts = datetime.now(timezone.utc).replace(microsecond=0).replace(tzinfo=None)

        def _count_all() -> list[dict]:
            out: list[dict] = []
            for tbl in self._INGESTION_TABLES:
                try:
                    count = self._ch.count_rows_since(tbl, window_seconds)
                except Exception:
                    logger.exception("ingestion_rate_count_error table=%s", tbl)
                    continue
                out.append({
                    "timestamp": ts,
                    "table_name": tbl,
                    "row_count": count,
                    "rows_per_second": count / window_seconds,
                    "window_seconds": window_seconds,
                })
            return out

        try:
            rows = await asyncio.to_thread(_count_all)
        except Exception:
            logger.exception("ingestion_rate_sampler_error")
            return

        if not rows:
            return

        try:
            await asyncio.to_thread(self._ch.insert_ingestion_rate_rows, rows)
            logger.info("ingestion_rate_sampled tables=%d", len(rows))
        except Exception:
            logger.exception("ingestion_rate_sampler_insert_error")

    async def _sample_db_sizes(self) -> None:
        """Sample PG + CH sizes and append to db_size_history.

        One row per sampled scope: PG database total, each PG user table,
        each CH table. Writes to the `db_size_history` ClickHouse table.
        Runs every 15 min on the leader only. Failures are logged but
        do not block the scheduler.
        """
        from datetime import datetime, timezone

        from sqlalchemy import text as sa_text

        if self._ch is None:
            return

        ts = datetime.now(timezone.utc).replace(microsecond=0).replace(tzinfo=None)
        rows: list[dict] = []

        # ── PostgreSQL ────────────────────────────────────────────────
        try:
            async with self._session_factory() as session:
                db_name_row = await session.execute(
                    sa_text("SELECT current_database()"),
                )
                db_name = db_name_row.scalar() or ""

                total_row = await session.execute(
                    sa_text("SELECT pg_database_size(current_database())"),
                )
                total_bytes = int(total_row.scalar() or 0)
                rows.append({
                    "timestamp": ts,
                    "source": "postgres",
                    "scope": "database",
                    "database_name": db_name,
                    "table_name": "",
                    "bytes": max(total_bytes, 0),
                    "rows": 0,
                    "parts": 0,
                })

                # Per-user-table bytes + approximate live row count (reltuples).
                # Excludes system/toast schemas.
                # reltuples is -1 for never-analyzed tables; clamp to 0 so
                # the UInt64 column in ClickHouse doesn't blow up on insert.
                pg_tables = await session.execute(sa_text("""
                    SELECT c.relname AS table_name,
                           pg_total_relation_size(c.oid) AS bytes,
                           GREATEST(COALESCE(c.reltuples, 0)::bigint, 0) AS approx_rows
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind = 'r'
                      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                      AND n.nspname NOT LIKE 'pg_toast%'
                """))
                for r in pg_tables.mappings():
                    rows.append({
                        "timestamp": ts,
                        "source": "postgres",
                        "scope": "table",
                        "database_name": db_name,
                        "table_name": r["table_name"],
                        "bytes": max(int(r["bytes"] or 0), 0),
                        "rows": max(int(r["approx_rows"] or 0), 0),
                        "parts": 0,
                    })
        except Exception:
            logger.exception("db_size_sampler_pg_error")

        # ── ClickHouse ────────────────────────────────────────────────
        def _ch_sample() -> list[dict]:
            client = self._ch._get_client()
            res = client.query(
                "SELECT database AS database_name, table AS table_name, "
                "       sum(bytes_on_disk) AS bytes, "
                "       sum(rows) AS rows, "
                "       count() AS parts "
                "FROM system.parts "
                "WHERE active AND database = currentDatabase() "
                "GROUP BY database, table "
                "SETTINGS max_memory_usage = 500000000"
            )
            out: list[dict] = []
            for r in res.named_results():
                out.append({
                    "timestamp": ts,
                    "source": "clickhouse",
                    "scope": "table",
                    "database_name": r["database_name"],
                    "table_name": r["table_name"],
                    "bytes": max(int(r["bytes"] or 0), 0),
                    "rows": max(int(r["rows"] or 0), 0),
                    "parts": max(int(r["parts"] or 0), 0),
                })
            return out

        try:
            rows.extend(await asyncio.to_thread(_ch_sample))
        except Exception:
            logger.exception("db_size_sampler_ch_error")

        if not rows:
            return

        try:
            await asyncio.to_thread(self._ch.insert_db_size_rows, rows)
            logger.info("db_size_sampled rows=%d", len(rows))
        except Exception:
            logger.exception("db_size_sampler_insert_error")

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

        # Compute target weights inversely proportional to current cost
        target_weights: dict[str, float] = {}
        for hostname, cost in cost_per_collector.items():
            target_weights[hostname] = 1.0 / max(cost, 0.001)

        # Normalize targets so max = 1.0
        max_tw = max(target_weights.values())
        if max_tw > 0:
            target_weights = {h: w / max_tw for h, w in target_weights.items()}

        # EMA blend: move current weights toward target gradually to prevent
        # oscillation (aggressive inverse weights flip the distribution instead
        # of equalising it).
        alpha = 0.3
        new_weights: dict[str, float] = {}
        for hostname in active_hostnames:
            cur = current_weights.get(hostname, 1.0)
            tgt = target_weights.get(hostname, 1.0)
            new_weights[hostname] = alpha * tgt + (1 - alpha) * cur

        # Normalize so max = 1.0, with a floor of 0.3 to prevent starvation
        max_w = max(new_weights.values())
        if max_w > 0:
            new_weights = {h: max(0.3, round(w / max_w, 4)) for h, w in new_weights.items()}

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

        def _run_sync() -> None:
            """Do all CH work in a single thread — the loop of per-run count
            queries + update writes would otherwise thrash to_thread context
            switches on every iteration."""
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

        try:
            await asyncio.to_thread(_run_sync)
        except Exception:
            logger.exception("finalize_eligibility_runs_error")

    async def _run_template_auto_apply(self) -> None:
        """Apply templates to devices on a configurable interval.

        Reads three SystemSettings:
        - template_auto_apply_enabled  ("true"/"false")
        - template_auto_apply_interval_hours  (int)
        - template_auto_apply_scope  ("has_type" | "all")
        Stores the last run timestamp in template_auto_apply_last_run.
        """
        now = datetime.now(timezone.utc)

        try:
            async with self._session_factory() as session:
                from sqlalchemy import select
                from monctl_central.storage.models import Device, SystemSetting

                enabled = (await session.execute(
                    select(SystemSetting).where(SystemSetting.key == "template_auto_apply_enabled")
                )).scalar_one_or_none()
                if not enabled or enabled.value != "true":
                    return

                interval_hours = 24
                iv = (await session.execute(
                    select(SystemSetting).where(SystemSetting.key == "template_auto_apply_interval_hours")
                )).scalar_one_or_none()
                if iv and iv.value:
                    try:
                        interval_hours = max(1, int(iv.value))
                    except ValueError:
                        pass

                if self._last_template_auto_apply is not None:
                    elapsed = (now - self._last_template_auto_apply).total_seconds()
                    if elapsed < interval_hours * 3600:
                        return

                scope_setting = (await session.execute(
                    select(SystemSetting).where(SystemSetting.key == "template_auto_apply_scope")
                )).scalar_one_or_none()
                scope = scope_setting.value if scope_setting and scope_setting.value in ("all", "has_type") else "has_type"

                self._last_template_auto_apply = now
                logger.info("template_auto_apply_starting scope=%s interval_hours=%d", scope, interval_hours)

                stmt = select(Device).where(Device.is_enabled == True)  # noqa: E712
                if scope == "has_type":
                    stmt = stmt.where(Device.device_type_id.isnot(None))
                devices = (await session.execute(stmt)).scalars().all()

                if not devices:
                    logger.info("template_auto_apply_no_devices scope=%s", scope)
                    return

                from monctl_central.templates.resolver import resolve_templates_for_devices
                from monctl_central.templates.router import apply_config_to_device

                results = await resolve_templates_for_devices(devices, session)
                applied = 0
                for result in results:
                    config = result.get("resolved_config")
                    if not config:
                        continue
                    import uuid as _uuid
                    device = await session.get(Device, _uuid.UUID(result["device_id"]))
                    if device is None:
                        continue
                    await apply_config_to_device(device, config, session)
                    applied += 1

                await session.flush()

                last_run = await session.get(SystemSetting, "template_auto_apply_last_run")
                if last_run is None:
                    last_run = SystemSetting(key="template_auto_apply_last_run", updated_at=now)
                    session.add(last_run)
                last_run.value = now.isoformat()
                last_run.updated_at = now

                await session.commit()
                logger.info(
                    "template_auto_apply_complete applied=%d total=%d scope=%s",
                    applied, len(devices), scope,
                )

        except Exception:
            logger.exception("template_auto_apply_error")

    async def _run_eligibility_scan(self) -> None:
        """Run once daily at configurable time (system setting eligibility_scan_time)."""
        now = datetime.now(timezone.utc)

        # Read scan time from system settings (default 02:00 UTC)
        scan_hour, scan_minute = 2, 0
        try:
            async with self._session_factory() as session:
                from sqlalchemy import select
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
                from sqlalchemy import select
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
