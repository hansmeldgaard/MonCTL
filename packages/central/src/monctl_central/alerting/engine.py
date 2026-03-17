"""Alert engine — evaluates AlertInstances via DSL compiler against ClickHouse.

Runs periodically on the leader-elected scheduler instance.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.alerting.dsl import compile_to_sql, parse_expression
from monctl_central.alerting.notifier import send_notifications
from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import (
    AlertInstance,
    AppAlertDefinition,
    ThresholdOverride,
)

logger = logging.getLogger(__name__)


class AlertEngine:
    """Evaluates all enabled AlertInstances against ClickHouse data."""

    def __init__(self, session_factory, ch_client: ClickHouseClient):
        self._session_factory = session_factory
        self._ch = ch_client

    async def evaluate_all(self) -> None:
        """Main evaluation loop. Called every 30s by the scheduler."""
        async with self._session_factory() as session:
            definitions = (
                await session.execute(
                    select(AppAlertDefinition)
                    .where(AppAlertDefinition.enabled == True)  # noqa: E712
                    .options(selectinload(AppAlertDefinition.app))
                )
            ).scalars().all()

            for defn in definitions:
                try:
                    await self._evaluate_definition(session, defn)
                except Exception:
                    logger.exception(
                        "alert_def_eval_error",
                        definition_id=str(defn.id),
                        name=defn.name,
                    )

            await session.commit()

    async def _evaluate_definition(
        self, session: AsyncSession, defn: AppAlertDefinition
    ) -> None:
        """Evaluate one alert definition across all its enabled instances."""
        target_table = defn.app.target_table

        # Parse and compile expression
        try:
            ast = parse_expression(defn.expression)
            compiled = compile_to_sql(ast, target_table, defn.window)
        except Exception:
            logger.exception("dsl_compile_error", definition_id=str(defn.id))
            return

        # Load enabled instances
        instances = (
            await session.execute(
                select(AlertInstance)
                .where(
                    AlertInstance.definition_id == defn.id,
                    AlertInstance.enabled == True,  # noqa: E712
                )
            )
        ).scalars().all()

        if not instances:
            return

        # Load threshold overrides
        overrides = (
            await session.execute(
                select(ThresholdOverride)
                .where(ThresholdOverride.definition_id == defn.id)
            )
        ).scalars().all()
        overrides_by_device: dict[uuid.UUID, dict[str, ThresholdOverride]] = {}
        for ov in overrides:
            overrides_by_device.setdefault(ov.device_id, {})[ov.entity_key] = ov

        now = datetime.now(timezone.utc)

        # Config CHANGED: special evaluation path
        if compiled.is_config_changed:
            firing_keys = await self._evaluate_config_changed(
                defn, instances, compiled.config_changed_key or ""
            )
        else:
            firing_keys = await self._execute_compiled_query(
                compiled, instances, overrides_by_device
            )

        # Update instance states
        for inst in instances:
            key = (str(inst.assignment_id), inst.entity_key)
            is_firing = key in firing_keys

            inst.fire_history = (inst.fire_history or [])[-19:] + [is_firing]
            inst.last_evaluated_at = now

            if is_firing:
                firing_data = firing_keys.get(key, {})
                inst.current_value = firing_data.get("value")
                if firing_data.get("labels"):
                    inst.entity_labels = firing_data["labels"]

                if inst.state != "firing":
                    inst.state = "firing"
                    inst.started_at = now
                    inst.fire_count = 1
                    inst.event_created = False
                    await send_notifications(defn, str(inst.assignment_id), "firing")
                else:
                    inst.fire_count += 1
            else:
                if inst.state == "firing":
                    inst.state = "resolved"
                    inst.resolved_at = now
                    inst.fire_count = 0
                    await send_notifications(defn, str(inst.assignment_id), "resolved")

    async def _execute_compiled_query(
        self,
        compiled,
        instances: list[AlertInstance],
        overrides_by_device: dict,
    ) -> dict[tuple[str, str], dict]:
        """Execute compiled ClickHouse query and return firing entity keys."""
        # Build assignment_id filter
        assignment_ids = list({str(inst.assignment_id) for inst in instances})

        # Add assignment_id scope to WHERE clause
        aid_list = ", ".join(f"'{aid}'" for aid in assignment_ids)
        scoped_sql = compiled.sql.replace(
            "WHERE ",
            f"WHERE assignment_id IN ({aid_list}) AND ",
            1,
        )

        # Apply threshold overrides per device
        # For simplicity, use default thresholds first; per-device overrides
        # would require multiple queries. For now, use the default params.
        params = dict(compiled.params)

        try:
            rows = await asyncio.to_thread(
                self._ch.query_for_alert, scoped_sql, params
            )
        except Exception:
            logger.exception("ch_query_error", sql=scoped_sql[:200])
            return {}

        firing: dict[tuple[str, str], dict] = {}
        for row in rows:
            aid = row.get("assignment_id", "")
            entity_key = ""
            labels: dict[str, str] = {}

            if "interface_id" in row:
                entity_key = f"{row.get('device_id', '')}|{row['interface_id']}"
                labels = {
                    "device_name": row.get("device_name", ""),
                    "if_name": row.get("if_name", ""),
                }
            elif "component_type" in row:
                entity_key = (
                    f"{row.get('device_id', '')}|"
                    f"{row.get('component_type', '')}|"
                    f"{row.get('component', '')}"
                )
                labels = {"device_name": row.get("device_name", "")}
            elif "config_key" in row:
                entity_key = f"{row.get('device_id', '')}|{row['config_key']}"
                labels = {"device_name": row.get("device_name", "")}
            else:
                labels = {"device_name": row.get("device_name", "")}

            # Extract numeric value from first aggregation column
            value = None
            for k, v in row.items():
                if k.startswith("_agg_"):
                    value = float(v) if v is not None else None
                    break
                if k == "val":
                    value = float(v) if v is not None else None
                    break

            firing[(aid, entity_key)] = {"value": value, "labels": labels, "assignment_id": aid}

        return firing

    async def _evaluate_config_changed(
        self,
        defn: AppAlertDefinition,
        instances: list[AlertInstance],
        config_key: str,
    ) -> dict[tuple[str, str], dict]:
        """Evaluate config CHANGED expressions."""
        assignment_ids = list({str(inst.assignment_id) for inst in instances})
        aid_list = ", ".join(f"'{aid}'" for aid in assignment_ids)

        sql = (
            "SELECT toString(device_id) AS device_id, config_key, config_hash, config_value, "
            "any(device_name) AS device_name "
            f"FROM config_latest FINAL "
            f"WHERE config_key = {{key:String}} AND assignment_id IN ({aid_list}) "
            f"GROUP BY device_id, config_key, config_hash, config_value"
        )

        try:
            rows = await asyncio.to_thread(
                self._ch.query_for_alert, sql, {"key": config_key}
            )
        except Exception:
            logger.exception("config_changed_query_error")
            return {}

        firing: dict[tuple[str, str], dict] = {}
        # Build lookup: instance by (assignment_id, entity_key)
        inst_lookup = {
            (str(inst.assignment_id), inst.entity_key): inst for inst in instances
        }

        for row in rows:
            device_id = row.get("device_id", "")
            entity_key = f"{device_id}|{row.get('config_key', '')}"
            current_hash = row.get("config_hash", "")

            # Find matching instance to check previous hash
            for (aid, ek), inst in inst_lookup.items():
                if ek == entity_key or ek == "":
                    prev_hash = (inst.entity_labels or {}).get("last_config_hash")
                    if prev_hash is not None and prev_hash != current_hash:
                        firing[(aid, entity_key)] = {
                            "value": None,
                            "labels": {
                                "device_name": row.get("device_name", ""),
                                "last_config_hash": current_hash,
                            },
                            "assignment_id": aid,
                        }
                    elif prev_hash is None:
                        # First evaluation — store baseline hash, don't fire
                        inst.entity_labels = {
                            **(inst.entity_labels or {}),
                            "last_config_hash": current_hash,
                        }
                    break

        return firing
