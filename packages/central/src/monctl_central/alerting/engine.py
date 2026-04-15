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

from monctl_central.alerting import severity as _sev
from monctl_central.alerting.dsl import compile_to_sql, parse_expression
from monctl_central.alerting.notifier import send_notifications
from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import (
    AlertEntity,
    AlertDefinition,
    Device,
    Tenant,
    ThresholdOverride,
    ThresholdVariable,
)

logger = logging.getLogger(__name__)

# Sentinel to distinguish "key not in dict" from "key present with value None".
_UNSET = object()


def _expression_for_severity(defn, severity: str | None) -> str:
    """Return the DSL expression for the given severity tier on `defn`.

    Falls back to the first tier's expression when `severity` is None
    (clear events have no live severity by the time log records are
    built) or unknown.
    """
    tiers = defn.severity_tiers or []
    if not tiers:
        return ""
    if severity:
        for t in tiers:
            if t.get("severity") == severity:
                return t.get("expression", "")
    return tiers[0].get("expression", "")


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

            logger.info("alert_eval_cycle definition_count=%d", len(definitions))

            for defn in definitions:
                try:
                    records = await self._evaluate_definition(session, defn)
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

    async def _evaluate_definition(
        self,
        session: AsyncSession,
        defn: AlertDefinition,
    ) -> list[dict]:
        """Evaluate one tiered alert definition. Returns alert_log records.

        Each tier is an independent DSL expression; the engine evaluates
        them all and picks the HIGHEST-severity tier whose expression
        matched as the effective severity for the entity. Log actions
        are chosen relative to the entity's previous severity:

          - ok → severity X  : `fire`
          - sev A → sev B > A: `escalate`
          - sev A → sev B < A: `downgrade`
          - sev A → sev A    : no-op (still firing at same severity)
          - firing → ok      : `clear`

        This replaces the old ladder_key/ladder_rank coordination
        between sibling defs — a ladder is now one definition.
        """
        target_table = defn.app.target_table
        tiers: list[dict] = list(defn.severity_tiers or [])
        if not tiers:
            logger.debug("eval_definition_no_tiers name=%s", defn.name)
            return []

        # Parse and compile every tier's expression up front. Non-healthy
        # tiers fire the alert; the healthy tier (if it has an expression)
        # acts as a POSITIVE CLEAR — it only clears an already-firing entity
        # and never fires a new one. If a healthy tier has no expression,
        # we fall back to the legacy behavior (any non-matching sample
        # clears the entity) for back-compat. If any tier fails to compile
        # the whole definition is skipped for this cycle — partial
        # evaluation could mis-classify severity.
        compiled_tiers: list[tuple[str, object]] = []
        # The healthy tier MAY carry an expression that describes when
        # the entity is recovered (e.g. `rtt_ms < rtt_ms_warn`). When
        # present it acts as a POSITIVE CLEAR and is also the source of
        # truth for `current_value` / `metric_values` / `threshold_values`
        # on the clear log row — otherwise that row would carry the
        # stale last-firing snapshot.
        healthy_compiled: object | None = None
        healthy_expr: str = ""
        for tier in tiers:
            if not tier.get("expression"):
                continue
            try:
                ast = parse_expression(tier["expression"])
                compiled = compile_to_sql(ast, target_table, defn.window)
            except Exception:
                logger.exception(
                    "dsl_compile_error definition_id=%s tier=%s",
                    defn.id, tier.get("severity"),
                )
                return []
            if tier.get("severity") == "healthy":
                healthy_compiled = compiled
                healthy_expr = tier["expression"]
            else:
                compiled_tiers.append((tier["severity"], compiled))
        if not compiled_tiers:
            logger.debug("eval_definition_no_non_healthy_tiers name=%s", defn.name)
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

        # Build device_id → (tenant_id, tenant_name) map so log records
        # can carry tenant context without extra round-trips per entity.
        device_ids = [i.device_id for i in instances if i.device_id]
        tenant_by_device: dict[uuid.UUID, tuple[uuid.UUID | None, str]] = {}
        if device_ids:
            rows = (
                await session.execute(
                    select(Device.id, Device.tenant_id, Tenant.name)
                    .join(Tenant, Device.tenant_id == Tenant.id, isouter=True)
                    .where(Device.id.in_(device_ids))
                )
            ).all()
            tenant_by_device = {r[0]: (r[1], r[2] or "") for r in rows}

        # Freshness check runs once — target_table and config-changed
        # flag are uniform across tiers for a single definition (they
        # come from the app + window, not the expression).
        is_cc = getattr(compiled_tiers[0][1], "is_config_changed", False)
        fresh_aids = await self._fresh_assignments(target_table, instances, is_cc)

        # Threshold vars + overrides (same for every tier of the def)
        threshold_vars = (
            await session.execute(
                select(ThresholdVariable)
                .where(ThresholdVariable.app_id == defn.app_id)
            )
        ).scalars().all()
        var_by_name: dict[str, ThresholdVariable] = {v.name: v for v in threshold_vars}
        var_ids = [v.id for v in threshold_vars]

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

        # Evaluate every tier. Each returns firing_keys: {(aid, entity_key): fire_data}
        tier_results: list[tuple[str, dict]] = []
        for severity, compiled in compiled_tiers:
            if is_cc:
                fk = await self._evaluate_config_changed(
                    defn, instances, getattr(compiled, "config_changed_key", "") or ""
                )
            else:
                fk = await self._execute_compiled_query(
                    compiled, instances, overrides_by_device, var_by_name
                )
            tier_results.append((severity, fk))

        # Evaluate the healthy tier if it has an expression. Matching
        # keys drive POSITIVE CLEAR; the per-key fire_data is consumed
        # when building the clear log record so it reflects the current
        # aggregate rather than the stale last-firing snapshot.
        healthy_fk: dict[tuple[str, str], dict] = {}
        if healthy_compiled is not None:
            try:
                if is_cc:
                    healthy_fk = await self._evaluate_config_changed(
                        defn,
                        instances,
                        getattr(healthy_compiled, "config_changed_key", "") or "",
                    )
                else:
                    healthy_fk = await self._execute_compiled_query(
                        healthy_compiled, instances, overrides_by_device, var_by_name
                    )
            except Exception:
                # A failure here must not block the eval cycle — worst
                # case a clear row carries null values.
                logger.exception(
                    "healthy_tier_eval_error definition_id=%s", defn.id
                )
                healthy_fk = {}
        healthy_keys: set[tuple[str, str]] = set(healthy_fk.keys())

        total_firing = sum(len(fk) for _, fk in tier_results)
        logger.info(
            "eval_definition_result name=%s tiers=%d firing_total=%d instances=%d healthy_positive=%s",
            defn.name, len(tier_results), total_firing, len(instances),
            healthy_compiled is not None,
        )

        log_records: list[dict] = []

        for inst in instances:
            if str(inst.assignment_id) not in fresh_aids:
                continue

            key = (str(inst.assignment_id), inst.entity_key)

            # Effective severity = highest-rank tier that matched
            effective_sev: str | None = None
            fire_data: dict = {}
            for severity, fk in tier_results:
                if key in fk and _sev.compare(severity, effective_sev) > 0:
                    effective_sev = severity
                    fire_data = fk[key]

            inst.last_evaluated_at = now
            prev_sev = inst.severity
            prev_state = inst.state

            if effective_sev is None:
                # No fire tier matched. Behavior depends on whether a
                # healthy-tier expression is defined:
                #   * healthy defined + matches → positive clear
                #   * healthy defined + no match → ambiguous middle,
                #     no state change, no log, no fire_history update
                #   * healthy not defined → legacy auto-clear (back-compat)
                def _refresh_from_healthy() -> None:
                    """Replace stale last-firing snapshot with current aggregate."""
                    hd = healthy_fk.get(key)
                    if hd is not None:
                        inst.current_value = hd.get("value")
                        inst.metric_values = hd.get("metric_values", {}) or {}
                        inst.threshold_values = hd.get("threshold_values", {}) or {}
                    else:
                        inst.current_value = None
                        inst.metric_values = {}
                        inst.threshold_values = {}

                if healthy_compiled is not None:
                    if key in healthy_keys and prev_state == "firing":
                        inst.fire_history = (inst.fire_history or [])[-19:] + [False]
                        inst.state = "resolved"
                        inst.severity = None
                        inst.last_cleared_at = now
                        inst.fire_count = 0
                        _refresh_from_healthy()
                        await send_notifications(defn, str(inst.assignment_id), "resolved")
                        log_records.append(
                            self._build_log_record(
                                defn, inst, "clear", now, tenant_by_device,
                                clear_expression=healthy_expr,
                            )
                        )
                    # else: ambiguous middle — skip entirely (no history append)
                    continue
                # Legacy: clear on any non-matching cycle.
                inst.fire_history = (inst.fire_history or [])[-19:] + [False]
                if prev_state == "firing":
                    inst.state = "resolved"
                    inst.severity = None
                    inst.last_cleared_at = now
                    inst.fire_count = 0
                    _refresh_from_healthy()
                    await send_notifications(defn, str(inst.assignment_id), "resolved")
                    log_records.append(
                        self._build_log_record(
                            defn, inst, "clear", now, tenant_by_device,
                            clear_expression=healthy_expr,
                        )
                    )
                continue

            # A fire tier matched — record it in history before continuing.
            inst.fire_history = (inst.fire_history or [])[-19:] + [True]

            # Firing at some severity — record metric data from the
            # winning tier (value/labels/thresholds).
            inst.current_value = fire_data.get("value")
            if fire_data.get("labels"):
                inst.entity_labels = fire_data["labels"]
            inst.metric_values = fire_data.get("metric_values", {})
            inst.threshold_values = fire_data.get("threshold_values", {})

            if prev_state != "firing":
                # Fresh fire from ok/resolved.
                inst.state = "firing"
                inst.severity = effective_sev
                inst.started_firing_at = now
                inst.fire_count = 1
                await send_notifications(defn, str(inst.assignment_id), "firing")
                log_records.append(self._build_log_record(defn, inst, "fire", now, tenant_by_device))
            else:
                # Already firing — evaluate severity transition.
                inst.fire_count += 1
                cmp = _sev.compare(effective_sev, prev_sev)
                if cmp > 0:
                    inst.severity = effective_sev
                    log_records.append(self._build_log_record(defn, inst, "escalate", now, tenant_by_device))
                elif cmp < 0:
                    inst.severity = effective_sev
                    log_records.append(self._build_log_record(defn, inst, "downgrade", now, tenant_by_device))
                # same severity → fire_count updated, no log record

        return log_records

    def _build_log_record(
        self,
        defn: AlertDefinition,
        inst: AlertEntity,
        action: str,
        now: datetime,
        tenant_by_device: dict[uuid.UUID, tuple[uuid.UUID | None, str]] | None = None,
        clear_expression: str = "",
    ) -> dict:
        """Build an alert_log record for ClickHouse."""
        labels = inst.entity_labels or {}
        _zero = "00000000-0000-0000-0000-000000000000"
        tid, tname = (None, "")
        if tenant_by_device and inst.device_id:
            tid, tname = tenant_by_device.get(inst.device_id, (None, ""))
        # Representative scalar threshold for the legacy single-value column.
        # The full per-variable map lives in `threshold_values` (JSON) below.
        tv_map = inst.threshold_values or {}
        threshold_scalar = 0.0
        for _v in tv_map.values():
            try:
                threshold_scalar = float(_v)
            except (TypeError, ValueError):
                threshold_scalar = 0.0
            break
        return {
            "definition_id": str(defn.id),
            "definition_name": defn.name,
            "entity_key": inst.entity_key or "",
            "action": action,
            # Clear rows carry severity='healthy' (the def's recovery
            # tier); fire/escalate/downgrade rows carry the live
            # entity severity (set by the tier-eval loop before the
            # log record is built).
            "severity": ("healthy" if action == "clear" else (inst.severity or "")),
            "current_value": float(inst.current_value) if inst.current_value is not None else 0.0,
            "threshold_value": threshold_scalar,
            # `expression` column in alert_log carries the effective tier's
            # expression — the one whose match drove the action. On clear
            # rows that's the healthy-tier expression (the condition that
            # now holds); on fire/escalate/downgrade it's the winning tier.
            "expression": (
                clear_expression if action == "clear"
                else _expression_for_severity(defn, inst.severity)
            ),
            "device_id": str(inst.device_id) if inst.device_id else _zero,
            "device_name": labels.get("device_name", ""),
            "assignment_id": str(inst.assignment_id),
            "app_id": str(defn.app_id),
            "app_name": (defn.app.name if defn.app else ""),
            "tenant_id": str(tid) if tid else _zero,
            "tenant_name": tname,
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
        """Build alert message from the appropriate tier's template.

        - For `fire`/`escalate`/`downgrade`: the tier whose severity
          matches `inst.severity` (the live/just-entered severity).
        - For `clear`: the `healthy` tier's template if the def has
          one; else a generic "{name} on {device} recovered" fallback.
        """
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

        tiers = defn.severity_tiers or []
        target_severity = "healthy" if action == "clear" else inst.severity
        template: str | None = None
        if target_severity:
            for t in tiers:
                if t.get("severity") == target_severity:
                    template = t.get("message_template")
                    break

        if template:
            rendered = self._render_template(
                template, defn, inst, labels, metrics, thresholds
            )
            if rendered:
                return rendered

        # Fallbacks — only when a template is missing or renders empty.
        if action == "clear":
            return f"{defn.name} on {device} recovered".strip()
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
            # Both plain `{rtt_ms_warn}` and legacy `{$rtt_ms_warn}` work.
            formatted = _fmt_number(v)
            context[k] = formatted
            context[f"${k}"] = formatted
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
        # fresh evidence. The `config` table has no error_category
        # column (collector only writes successful diff rows there), so
        # the filter is omitted for it.
        error_filter = "" if table == "config" else "  AND error_category = '' "
        sql = (
            f"SELECT toString(assignment_id) AS aid, "
            f"       max(received_at) AS max_rcv "
            f"FROM {table} "
            f"WHERE assignment_id IN ({aid_list}) "
            f"  AND received_at > {{cutoff:DateTime64(3, 'UTC')}} "
            f"{error_filter}"
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
