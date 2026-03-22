"""Alert engine — evaluates AlertEntities via DSL compiler against ClickHouse.

Runs periodically on the leader-elected scheduler instance.
Writes fire/clear records to the ClickHouse alert_log table.
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

from monctl_central.alerting.dsl import compile_to_sql, parse_expression
from monctl_central.alerting.notifier import send_notifications
from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import (
    AlertEntity,
    AlertDefinition,
    ThresholdOverride,
)

logger = logging.getLogger(__name__)


class AlertEngine:
    """Evaluates all enabled AlertEntities against ClickHouse data."""

    def __init__(self, session_factory, ch_client: ClickHouseClient):
        self._session_factory = session_factory
        self._ch = ch_client

    async def evaluate_all(self) -> None:
        """Main evaluation loop. Called every 30s by the scheduler."""
        alert_log_records: list[dict] = []

        async with self._session_factory() as session:
            definitions = (
                await session.execute(
                    select(AlertDefinition)
                    .where(AlertDefinition.enabled == True)  # noqa: E712
                    .options(selectinload(AlertDefinition.app))
                )
            ).scalars().all()

            for defn in definitions:
                try:
                    records = await self._evaluate_definition(session, defn)
                    alert_log_records.extend(records)
                except Exception:
                    logger.exception(
                        "alert_def_eval_error",
                        definition_id=str(defn.id),
                        name=defn.name,
                    )

            await session.commit()

        # Batch insert all fire/clear records to ClickHouse
        if alert_log_records:
            try:
                await asyncio.to_thread(
                    self._ch.insert_alert_log, alert_log_records
                )
                logger.info("alert_log_inserted count=%d", len(alert_log_records))
            except Exception:
                logger.exception("alert_log_insert_error")

    async def _evaluate_definition(
        self, session: AsyncSession, defn: AlertDefinition
    ) -> list[dict]:
        """Evaluate one alert definition. Returns alert_log records."""
        target_table = defn.app.target_table

        # Parse and compile expression
        try:
            ast = parse_expression(defn.expression)
            compiled = compile_to_sql(ast, target_table, defn.window)
        except Exception:
            logger.exception("dsl_compile_error", definition_id=str(defn.id))
            return []

        # Load enabled instances
        instances = (
            await session.execute(
                select(AlertEntity)
                .where(
                    AlertEntity.definition_id == defn.id,
                    AlertEntity.enabled == True,  # noqa: E712
                )
            )
        ).scalars().all()

        if not instances:
            return []

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

        # Build alert_log records and update instance states
        log_records: list[dict] = []

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
                    inst.started_firing_at = now
                    inst.fire_count = 1
                    await send_notifications(defn, str(inst.assignment_id), "firing")
                else:
                    inst.fire_count += 1

                # Write "fire" record to alert_log
                log_records.append(self._build_log_record(
                    defn, inst, "fire", now
                ))
            else:
                if inst.state == "firing":
                    inst.state = "resolved"
                    inst.last_cleared_at = now
                    inst.fire_count = 0
                    await send_notifications(defn, str(inst.assignment_id), "resolved")

                    # Write exactly one "clear" record
                    log_records.append(self._build_log_record(
                        defn, inst, "clear", now
                    ))

        return log_records

    def _build_log_record(
        self,
        defn: AlertDefinition,
        inst: AlertEntity,
        action: str,
        now: datetime,
    ) -> dict:
        """Build an alert_log record for ClickHouse."""
        labels = inst.entity_labels or {}
        _zero = "00000000-0000-0000-0000-000000000000"
        return {
            "definition_id": str(defn.id),
            "definition_name": defn.name,
            "entity_key": inst.entity_key or "",
            "action": action,
            "severity": defn.severity,
            "current_value": float(inst.current_value) if inst.current_value is not None else 0.0,
            "threshold_value": 0.0,
            "expression": defn.expression,
            "device_id": str(inst.device_id) if inst.device_id else _zero,
            "device_name": labels.get("device_name", ""),
            "assignment_id": str(inst.assignment_id),
            "app_id": str(defn.app_id),
            "app_name": labels.get("app_name", ""),
            "tenant_id": labels.get("tenant_id", _zero),
            "entity_labels": json.dumps(labels),
            "fire_count": inst.fire_count,
            "message": self._build_message(defn, inst, action),
            "occurred_at": now,
        }

    def _build_message(
        self, defn: AlertDefinition, inst: AlertEntity, action: str
    ) -> str:
        """Build alert message from template or defaults."""
        labels = inst.entity_labels or {}
        device = labels.get("device_name", "unknown")
        entity = labels.get("if_name") or labels.get("component") or inst.entity_key or ""
        value = inst.current_value

        if action == "clear":
            return f"Cleared: {defn.name} on {device} {entity}".strip()

        if defn.message_template:
            try:
                return defn.message_template.format(
                    device_name=device,
                    value=round(value, 2) if value is not None else "N/A",
                    threshold="",
                    fire_count=inst.fire_count,
                    **{k: v for k, v in labels.items() if k != "device_name"},
                )
            except (KeyError, IndexError, TypeError):
                pass

        val_str = f" = {round(value, 2)}" if value is not None else ""
        return f"{defn.name}{val_str} on {device} {entity} [{inst.fire_count}x]".strip()

    async def _execute_compiled_query(
        self,
        compiled,
        instances: list[AlertEntity],
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
        defn: AlertDefinition,
        instances: list[AlertEntity],
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
