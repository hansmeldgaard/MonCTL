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
    ThresholdVariable,
)

logger = logging.getLogger(__name__)

# Sentinel to distinguish "key not in dict" from "key present with value None".
_UNSET = object()


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

            # Preload severity-ladder active state: for every
            # (ladder_key, assignment_id, entity_key) collect the set
            # of ranks currently firing. _evaluate_definition consults
            # and mutates this so the *highest* firing rank suppresses
            # lower-rank siblings (and supersedes them when a new high
            # rank opens this cycle). Definitions with no ladder_key
            # are unaffected.
            ladder_state = await self._load_ladder_state(session)

            # Evaluate higher-rank (more severe) ladder definitions
            # first so a newly-firing critical suppresses the warning
            # in the same cycle rather than one cycle later.
            definitions_sorted = sorted(
                definitions,
                key=lambda d: -(d.ladder_rank or 0),
            )

            logger.info("alert_eval_cycle definition_count=%d", len(definitions))

            for defn in definitions_sorted:
                try:
                    records = await self._evaluate_definition(
                        session, defn, ladder_state
                    )
                    alert_log_records.extend(records)
                except Exception:
                    logger.exception(
                        "alert_def_eval_error definition_id=%s name=%s",
                        defn.id, defn.name,
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

    async def _load_ladder_state(
        self, session: AsyncSession
    ) -> dict[tuple[str, str, str], set[int]]:
        """Snapshot currently-firing ladder siblings.

        Key: (ladder_key, assignment_id, entity_key).
        Value: set of ranks currently firing for that ladder at that
        entity. Used by `_evaluate_definition` to decide whether a
        lower-rank sibling should be suppressed (higher rank active)
        or cleared with reason "superseded".
        """
        rows = (
            await session.execute(
                select(
                    AlertDefinition.ladder_key,
                    AlertDefinition.ladder_rank,
                    AlertEntity.assignment_id,
                    AlertEntity.entity_key,
                )
                .join(AlertEntity, AlertEntity.definition_id == AlertDefinition.id)
                .where(
                    AlertDefinition.ladder_key.isnot(None),
                    AlertDefinition.ladder_rank.isnot(None),
                    AlertEntity.state == "firing",
                )
            )
        ).all()

        state: dict[tuple[str, str, str], set[int]] = {}
        for ladder_key, rank, aid, ekey in rows:
            key = (ladder_key, str(aid), ekey or "")
            state.setdefault(key, set()).add(int(rank))
        return state

    async def _evaluate_definition(
        self,
        session: AsyncSession,
        defn: AlertDefinition,
        ladder_state: dict[tuple[str, str, str], set[int]] | None = None,
    ) -> list[dict]:
        """Evaluate one alert definition. Returns alert_log records."""
        target_table = defn.app.target_table

        # Parse and compile expression
        try:
            ast = parse_expression(defn.expression)
            compiled = compile_to_sql(ast, target_table, defn.window)
        except Exception:
            logger.exception("dsl_compile_error definition_id=%s", defn.id)
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
            logger.debug("eval_definition_no_instances name=%s", defn.name)
            return []

        # Determine which assignments have fresh data since last evaluation
        fresh_aids = await self._fresh_assignments(
            target_table, instances, compiled.is_config_changed
        )

        logger.debug(
            "eval_definition name=%s table=%s instances=%d",
            defn.name, target_table, len(instances),
        )

        # Load threshold variables for this app
        threshold_vars = (
            await session.execute(
                select(ThresholdVariable)
                .where(ThresholdVariable.app_id == defn.app_id)
            )
        ).scalars().all()
        var_by_name: dict[str, ThresholdVariable] = {v.name: v for v in threshold_vars}
        var_ids = [v.id for v in threshold_vars]

        # Load threshold overrides for these variables
        overrides_by_device: dict[uuid.UUID, dict[str, dict[str, ThresholdOverride]]] = {}
        if var_ids:
            overrides = (
                await session.execute(
                    select(ThresholdOverride)
                    .where(ThresholdOverride.variable_id.in_(var_ids))
                )
            ).scalars().all()
            for ov in overrides:
                overrides_by_device.setdefault(ov.device_id, {}).setdefault(
                    ov.entity_key, {}
                )[str(ov.variable_id)] = ov

        now = datetime.now(timezone.utc)

        # Config CHANGED: special evaluation path
        if compiled.is_config_changed:
            firing_keys = await self._evaluate_config_changed(
                defn, instances, compiled.config_changed_key or ""
            )
        else:
            firing_keys = await self._execute_compiled_query(
                compiled, instances, overrides_by_device, var_by_name
            )

        logger.info(
            "eval_definition_result name=%s firing=%d total_instances=%d",
            defn.name, len(firing_keys), len(instances),
        )

        # Build alert_log records and update instance states
        log_records: list[dict] = []

        # Ladder parameters for this definition (None for stand-alone defs).
        ladder_key = defn.ladder_key
        ladder_rank = defn.ladder_rank
        has_ladder = bool(ladder_key and ladder_rank is not None)

        for inst in instances:
            has_fresh_data = str(inst.assignment_id) in fresh_aids
            # Without fresh data, the ClickHouse query result is either
            # unchanged (stale window) or empty (race between eval and
            # collector forward — window contains no rows because the
            # next data point hasn't been inserted yet). Either way,
            # this cycle carries no new evidence for this entity and
            # must not mutate its state or produce log records.
            if not has_fresh_data:
                continue

            key = (str(inst.assignment_id), inst.entity_key)
            is_firing = key in firing_keys

            # Severity ladder suppression: if a strictly higher-rank
            # sibling is active for the same (ladder_key, assignment,
            # entity_key), this lower-rank def must not fire. If it is
            # already firing we emit a single "clear" with reason
            # superseded and leave the state as resolved. The caller
            # seeded `ladder_state` with pre-cycle firing ranks, and we
            # update it as we go (higher ranks iterate first).
            suppressed_by_ladder = False
            if has_ladder and ladder_state is not None:
                lkey = (ladder_key, str(inst.assignment_id), inst.entity_key or "")
                active_ranks = ladder_state.get(lkey, set())
                if any(r > ladder_rank for r in active_ranks):
                    suppressed_by_ladder = True

            if suppressed_by_ladder:
                if inst.state == "firing":
                    inst.state = "resolved"
                    inst.last_cleared_at = now
                    inst.fire_count = 0
                    inst.last_evaluated_at = now
                    log_records.append(
                        self._build_log_record(defn, inst, "clear", now)
                    )
                    if has_ladder:
                        ladder_state.setdefault(
                            (ladder_key, str(inst.assignment_id), inst.entity_key or ""),
                            set(),
                        ).discard(ladder_rank)
                else:
                    inst.last_evaluated_at = now
                continue

            inst.fire_history = (inst.fire_history or [])[-19:] + [is_firing]
            inst.last_evaluated_at = now

            if is_firing:
                firing_data = firing_keys.get(key, {})
                inst.current_value = firing_data.get("value")
                if firing_data.get("labels"):
                    inst.entity_labels = firing_data["labels"]
                inst.metric_values = firing_data.get("metric_values", {})
                inst.threshold_values = firing_data.get("threshold_values", {})

                if inst.state != "firing":
                    inst.state = "firing"
                    inst.started_firing_at = now
                    inst.fire_count = 1
                    await send_notifications(defn, str(inst.assignment_id), "firing")
                else:
                    inst.fire_count += 1

                # Register in ladder state so lower-rank siblings
                # evaluated later in the cycle see us firing and
                # suppress themselves.
                if has_ladder and ladder_state is not None:
                    ladder_state.setdefault(
                        (ladder_key, str(inst.assignment_id), inst.entity_key or ""),
                        set(),
                    ).add(ladder_rank)

                log_records.append(self._build_log_record(
                    defn, inst, "fire", now
                ))
            else:
                if inst.state == "firing":
                    inst.state = "resolved"
                    inst.last_cleared_at = now
                    inst.fire_count = 0
                    if has_ladder and ladder_state is not None:
                        ladder_state.setdefault(
                            (ladder_key, str(inst.assignment_id), inst.entity_key or ""),
                            set(),
                        ).discard(ladder_rank)
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
            "severity": getattr(defn, "severity", "") or "",
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
            "metric_values": json.dumps(inst.metric_values or {}),
            "threshold_values": json.dumps(inst.threshold_values or {}),
            "occurred_at": now,
        }

    def _build_message(
        self, defn: AlertDefinition, inst: AlertEntity, action: str
    ) -> str:
        """Build alert message from template or defaults."""
        labels = inst.entity_labels or {}
        metrics = inst.metric_values or {}
        thresholds = inst.threshold_values or {}
        value = inst.current_value
        device = labels.get("device_name", "unknown")
        entity = (
            labels.get("if_name")
            or labels.get("component")
            or inst.entity_key
            or ""
        )

        if action == "clear":
            if defn.message_template:
                rendered = self._render_template(
                    defn.message_template, defn, inst, labels, metrics, thresholds
                )
                if rendered:
                    return f"Cleared: {rendered}"
            return f"Cleared: {defn.name} on {device} {entity}".strip()

        if defn.message_template:
            rendered = self._render_template(
                defn.message_template, defn, inst, labels, metrics, thresholds
            )
            if rendered:
                return rendered

        val_str = f" = {round(value, 2)}" if value is not None else ""
        return f"{defn.name}{val_str} on {device} {entity} [{inst.fire_count}x]".strip()

    def _render_template(
        self,
        template: str,
        defn: AlertDefinition,
        inst: AlertEntity,
        labels: dict,
        metrics: dict,
        thresholds: dict,
    ) -> str | None:
        """Render a message template with all available variables."""
        value = inst.current_value
        context: dict[str, str] = {}
        for k, v in labels.items():
            context[k] = str(v)
        context["value"] = _fmt_number(value)
        context["fire_count"] = str(inst.fire_count)
        context["alert_name"] = defn.name
        context["entity_key"] = inst.entity_key or ""
        for k, v in metrics.items():
            context[k] = _fmt_number(v)
        for k, v in thresholds.items():
            context[f"${k}"] = _fmt_number(v)
        try:
            return template.format_map(_SafeFormatDict(context))
        except (ValueError, TypeError):
            return None

    async def _execute_compiled_query(
        self,
        compiled,
        instances: list[AlertEntity],
        overrides_by_device: dict,
        var_by_name: dict[str, "ThresholdVariable"] | None = None,
    ) -> dict[tuple[str, str], dict]:
        """Execute compiled ClickHouse query and return firing entity keys.

        Resolves effective threshold per param using the 4-level hierarchy:
        1. Per-entity override (variable_id + device_id + entity_key)
        2. Per-device override (variable_id + device_id + entity_key="")
        3. App-level value (ThresholdVariable.app_value)
        4. Default value (ThresholdVariable.default_value / compiled param)
        """
        # Build assignment_id filter
        assignment_ids = list({str(inst.assignment_id) for inst in instances})

        # Add assignment_id scope to WHERE clause
        aid_list = ", ".join(f"'{aid}'" for aid in assignment_ids)
        scoped_sql = compiled.sql.replace(
            "WHERE ",
            f"WHERE assignment_id IN ({aid_list}) AND ",
            1,
        )

        # Resolve effective thresholds — use app_value from ThresholdVariable
        # if set, otherwise fall back to default_value from ThresholdVariable,
        # then to the compiled default param value
        params = dict(compiled.params)
        if var_by_name and compiled.threshold_params:
            for tp in compiled.threshold_params:
                var = var_by_name.get(tp.name)
                if var is not None:
                    if var.app_value is not None:
                        params[tp.param_key] = var.app_value
                    elif var.default_value is not None:
                        params[tp.param_key] = var.default_value

        try:
            rows = await asyncio.to_thread(
                self._ch.query_for_alert, scoped_sql, params
            )
        except Exception:
            # Propagate: a ClickHouse query failure must NOT be
            # interpreted as "no entity firing". Doing so would
            # spuriously clear every currently-firing entity whose
            # fresh check happened to pass this cycle. Let the outer
            # handler in `_evaluate_definition` catch and skip the def
            # for this cycle, preserving existing state until the next
            # successful query.
            logger.exception("ch_query_error sql=%s", scoped_sql[:200])
            raise

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

            # Extract ALL metric values using the alias mapping
            metric_vals: dict[str, float | None] = {}
            for metric_name, alias in compiled.metric_aliases.items():
                raw = row.get(alias)
                metric_vals[metric_name] = round(float(raw), 4) if raw is not None else None

            # Primary value = first metric (backward compat with current_value)
            value = next(iter(metric_vals.values()), None) if metric_vals else None
            if value is None:
                # Fallback: try any _agg_ or _arith_ column
                for k, v in row.items():
                    if k.startswith(("_agg_", "_arith_")):
                        value = float(v) if v is not None else None
                        break

            # Resolved threshold values for this entity
            resolved_thresholds: dict[str, float] = {}
            if compiled.threshold_params:
                for tp in compiled.threshold_params:
                    resolved_thresholds[tp.name] = params.get(tp.param_key, tp.default_value)

            firing[(aid, entity_key)] = {
                "value": value,
                "labels": labels,
                "assignment_id": aid,
                "metric_values": metric_vals,
                "threshold_values": resolved_thresholds,
            }

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


    async def _fresh_assignments(
        self,
        target_table: str,
        instances: list[AlertEntity],
        is_config_changed: bool,
    ) -> set[str]:
        """Return the set of assignment_ids that have received new data
        since *their own* last evaluation.

        Filtering happens per-assignment: an assignment is "fresh" iff
        ClickHouse has rows for it with received_at > its own
        last_evaluated_at. Using a single global cutoff would return
        false positives whenever assignments in the same definition
        have divergent last_evaluated_at values — an assignment whose
        data was already processed can still appear newer than some
        *other* assignment's older cutoff.

        Assignments with last_evaluated_at IS NULL are always considered
        fresh (first-time evaluation).
        """
        # Collect per-assignment cutoff: the oldest last_evaluated_at
        # seen across all instances for that assignment.  If any instance
        # for an aid has never been evaluated, treat the whole aid as
        # first-time (cutoff = None → always fresh).
        cutoff_by_aid: dict[str, datetime | None] = {}
        for inst in instances:
            aid = str(inst.assignment_id)
            prev = cutoff_by_aid.get(aid, _UNSET)
            if inst.last_evaluated_at is None:
                cutoff_by_aid[aid] = None
            elif prev is _UNSET:
                cutoff_by_aid[aid] = inst.last_evaluated_at
            elif prev is not None and inst.last_evaluated_at < prev:
                cutoff_by_aid[aid] = inst.last_evaluated_at
            # else: prev is None (first-time) — keep as None

        fresh: set[str] = set()
        aids_to_check: dict[str, datetime] = {}
        for aid, cutoff in cutoff_by_aid.items():
            if cutoff is None:
                fresh.add(aid)
            else:
                aids_to_check[aid] = (
                    cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
                )

        if not aids_to_check:
            return fresh

        # Batch query: max(received_at) per assignment. We filter with a
        # cheap global prefilter (the oldest cutoff minus a small guard)
        # to bound the scan; then compare per-aid in Python against each
        # assignment's own cutoff. Without the per-aid compare, any aid
        # whose data is newer than the oldest cutoff would be flagged
        # fresh — including aids whose data is already fully processed.
        oldest = min(aids_to_check.values())
        aid_list = ", ".join(f"'{a}'" for a in aids_to_check)
        table = "config" if is_config_changed else target_table

        # Exclude error rows (error_category != '') from freshness.
        # A timeout/unreachable poll still writes a row with a current
        # received_at, which — if counted as "fresh" — would cause the
        # engine to re-evaluate with a NULL metric and spuriously clear
        # already-firing alerts. Only *successful* samples count as
        # fresh evidence. The `config` table does not carry
        # error_category on legacy deployments, but the filter is still
        # safe (column defaults to '').
        sql = (
            f"SELECT toString(assignment_id) AS aid, "
            f"       max(received_at) AS max_rcv "
            f"FROM {table} "
            f"WHERE assignment_id IN ({aid_list}) "
            f"  AND received_at > {{cutoff:DateTime64(3, 'UTC')}} "
            f"  AND error_category = '' "
            f"GROUP BY assignment_id"
        )

        try:
            rows = await asyncio.to_thread(
                self._ch.query_for_alert, sql, {"cutoff": oldest}
            )
        except Exception:
            # On freshness-query failure, return an EMPTY fresh set so
            # every already-seen assignment skips evaluation this cycle.
            # The previous behaviour ("treat all as fresh") combined
            # with a concurrent main-query failure produced spurious
            # clears: has_fresh_data=True + empty firing_keys → each
            # firing entity got written as cleared. Preferring false
            # negatives (one cycle of skipped eval) over false positives
            # (ghost clears logged forever) is the safe choice.
            logger.warning("fresh_assignments_check_error table=%s", table)
            return fresh

        for row in rows:
            aid = row.get("aid")
            max_rcv = row.get("max_rcv")
            if aid is None or max_rcv is None:
                continue
            if not isinstance(max_rcv, datetime):
                # ClickHouse driver may return str — best effort parse
                try:
                    max_rcv = datetime.fromisoformat(str(max_rcv))
                except ValueError:
                    continue
            if max_rcv.tzinfo is None:
                max_rcv = max_rcv.replace(tzinfo=timezone.utc)
            aid_cutoff = aids_to_check.get(aid)
            if aid_cutoff is not None and max_rcv > aid_cutoff:
                fresh.add(aid)

        return fresh


def _fmt_number(v: float | None) -> str:
    """Format a numeric value for display in messages."""
    if v is None:
        return "N/A"
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


class _SafeFormatDict(dict):
    """Dict that returns '{key}' for missing keys instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
