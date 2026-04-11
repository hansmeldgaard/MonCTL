"""IncidentEngine — phase 1 (shadow mode) + phase 2a (severity ladders).

Runs after the scheduler's AlertEngine + EventEngine each cycle. Reads
AlertEntities and IncidentRules from PG and upserts rows in the
incidents table. Does NOT (yet):

- write ClickHouse events
- send notifications
- trigger automations
- apply correlation groups, dependencies, scope filters, or flap guard
  windows (columns exist but are reserved for later phases)

Phase 2a adds wall-clock severity ladders: an IncidentRule with a
`severity_ladder` JSONB is promoted over time after opening. The ladder
runs on wall-clock time after `opened_at` and is independent of
`mode` — cumulative only controls *when* an incident opens, not how
its severity evolves afterwards. See docs/event-policy-rework.md
open question #3.

The feature flag `settings.incident_engine` controls whether
`evaluate_all()` does any work at all:
- "off"   → no-op (early return)
- "shadow" → runs the full loop (default)

See docs/event-policy-rework.md.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.alerting.engine import _fmt_number, _SafeFormatDict
from monctl_central.config import settings
from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import (
    AlertDefinition,
    AlertEntity,
    Incident,
    IncidentRule,
)

logger = logging.getLogger(__name__)


_SEVERITY_PRIORITY = {"info": 0, "warning": 1, "critical": 2, "emergency": 3}


def _validate_ladder(raw) -> list[dict] | None:
    """Validate and normalize a severity_ladder JSONB value.

    Returns the ladder as a list of `{after_seconds, severity}` dicts,
    or `None` if the ladder is missing, empty, or malformed. Malformed
    ladders are logged at WARNING so a typo in one rule doesn't silently
    skip promotion.

    Rules:
    - Must be a non-empty list of dicts.
    - Each entry must have `after_seconds` (int >= 0) and `severity`
      (one of info/warning/critical/emergency — `recovery` is a state,
      not a ladder level).
    - First entry must have `after_seconds == 0` (defines base severity).
    - Entries must be strictly ascending by `after_seconds`.
    - Severities must be monotonically non-decreasing in priority
      (info < warning < critical < emergency) — a ladder only escalates.
    """
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        logger.warning("incident_ladder_invalid reason=not_a_list value=%r", raw)
        return None

    normalized: list[dict] = []
    last_seconds = -1
    last_priority = -1
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            logger.warning("incident_ladder_invalid reason=entry_not_dict idx=%d", idx)
            return None
        after = entry.get("after_seconds")
        sev = entry.get("severity")
        if not isinstance(after, int) or after < 0:
            logger.warning(
                "incident_ladder_invalid reason=bad_after_seconds idx=%d value=%r",
                idx, after,
            )
            return None
        if sev not in _SEVERITY_PRIORITY:
            logger.warning(
                "incident_ladder_invalid reason=bad_severity idx=%d value=%r",
                idx, sev,
            )
            return None
        if after <= last_seconds:
            logger.warning(
                "incident_ladder_invalid reason=not_ascending idx=%d after=%d prev=%d",
                idx, after, last_seconds,
            )
            return None
        priority = _SEVERITY_PRIORITY[sev]
        if priority < last_priority:
            logger.warning(
                "incident_ladder_invalid reason=severity_decreasing idx=%d sev=%s prev_priority=%d",
                idx, sev, last_priority,
            )
            return None
        last_seconds = after
        last_priority = priority
        normalized.append({"after_seconds": after, "severity": sev})

    if normalized[0]["after_seconds"] != 0:
        logger.warning(
            "incident_ladder_invalid reason=first_step_not_zero first=%d",
            normalized[0]["after_seconds"],
        )
        return None

    return normalized


def _ladder_severity_at(ladder: list[dict], elapsed_seconds: float) -> str:
    """Return the ladder step severity for the given elapsed time.

    Assumes ladder is already validated (sorted ascending, first step
    at 0). Walks from the top down and returns the first step whose
    `after_seconds` has been reached.
    """
    for step in reversed(ladder):
        if elapsed_seconds >= step["after_seconds"]:
            return step["severity"]
    # Unreachable when ladder is validated (first step is 0), but keep a
    # safe fallback.
    return ladder[0]["severity"]


def _validate_scope_filter(raw) -> dict[str, str] | None:
    """Validate and normalize a scope_filter JSONB value.

    Returns a flat `{label_key: required_value}` dict, or `None` when
    the filter is missing, empty, or malformed. Malformed filters are
    logged at WARNING so a typo in one rule doesn't silently disable
    scope restriction.

    Format:
    - Flat dict of string → string.
    - All keys AND-match against `AlertEntity.entity_labels`.
    - Empty-string value = wildcard ("key must exist", any value).
    - `None` or empty dict → returns `None` (rule has no scope filter).

    Kept intentionally minimal — no regex, IN lists, or negation.
    Those can be added later if real operator demand surfaces.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        logger.warning("incident_scope_invalid reason=not_a_dict value=%r", raw)
        return None
    if not raw:
        return None

    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            logger.warning(
                "incident_scope_invalid reason=key_not_string key=%r", key
            )
            return None
        if not isinstance(value, str):
            logger.warning(
                "incident_scope_invalid reason=value_not_string key=%s value=%r",
                key, value,
            )
            return None
        normalized[key] = value

    return normalized


def _validate_depends_on(raw) -> dict | None:
    """Validate and normalize a depends_on JSONB value.

    Returns `{"rule_ids": [uuid.UUID, ...], "match_on": [str, ...]}` or
    `None` if missing/empty/malformed. Malformed values log at WARNING so
    a single rule typo doesn't silently disable dependency suppression.

    Format:
    ```json
    {
      "rule_ids": ["uuid-str", ...],
      "match_on": ["device_id", "device_name"]
    }
    ```

    - `rule_ids`: list of parent IncidentRule UUIDs as strings. Required,
      non-empty. Self-references are allowed (engine skips them at runtime).
    - `match_on`: list of label keys. Optional (default empty list). When
      non-empty, dependency only applies if the parent and child incidents
      have equal non-null values for *every* key in the list. Empty list
      means "any open parent incident of any listed rule suppresses" —
      too broad for most cases, but supported.
    - Transitive parents are not resolved — a suppressed parent still
      counts as a valid parent for its children. Operators model the tree
      explicitly if they care.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        logger.warning("incident_depends_on_invalid reason=not_a_dict value=%r", raw)
        return None

    rule_ids_raw = raw.get("rule_ids")
    if not isinstance(rule_ids_raw, list) or not rule_ids_raw:
        logger.warning(
            "incident_depends_on_invalid reason=rule_ids_missing_or_empty"
        )
        return None

    rule_ids: list[uuid.UUID] = []
    for rid in rule_ids_raw:
        if not isinstance(rid, str):
            logger.warning(
                "incident_depends_on_invalid reason=rule_id_not_string value=%r", rid
            )
            return None
        try:
            rule_ids.append(uuid.UUID(rid))
        except (ValueError, TypeError):
            logger.warning(
                "incident_depends_on_invalid reason=rule_id_not_uuid value=%r", rid
            )
            return None

    match_on_raw = raw.get("match_on", [])
    if not isinstance(match_on_raw, list):
        logger.warning("incident_depends_on_invalid reason=match_on_not_list")
        return None
    match_on: list[str] = []
    for key in match_on_raw:
        if not isinstance(key, str):
            logger.warning(
                "incident_depends_on_invalid reason=match_on_key_not_string value=%r", key
            )
            return None
        match_on.append(key)

    return {"rule_ids": rule_ids, "match_on": match_on}


class IncidentEngine:
    """Phase 1 incident engine — observation + automation trigger (cut-over step 1).

    An optional `automation_engine` can be passed in; when set, the
    engine dispatches `on_incident_transition` calls after each cycle's
    session.commit() for every opened / escalated / cleared transition
    observed this cycle. The old `AutomationEngine.on_new_events` hook
    continues to fire in parallel for `trigger_type='event'` automations
    during the cut-over period.
    """

    def __init__(
        self,
        session_factory,
        ch_client: ClickHouseClient | None = None,
        automation_engine=None,
    ) -> None:
        self._session_factory = session_factory
        self._ch = ch_client  # unused in phase 1, reserved for phase 2
        self._automation_engine = automation_engine

    async def evaluate_all(self) -> None:
        if settings.incident_engine == "off":
            return

        async with self._session_factory() as session:
            rules = (
                await session.execute(
                    select(IncidentRule)
                    .where(IncidentRule.enabled == True)  # noqa: E712
                    .options(selectinload(IncidentRule.definition))
                )
            ).scalars().all()

            opened = 0
            updated = 0
            cleared = 0
            escalated = 0
            transitions: list[dict] = []

            for rule in rules:
                try:
                    o, u, c, e = await self._evaluate_rule(session, rule, transitions)
                    opened += o
                    updated += u
                    cleared += c
                    escalated += e
                except Exception:
                    logger.exception(
                        "incident_rule_error rule_id=%s name=%s",
                        str(rule.id), rule.name,
                    )

            await session.commit()

            if opened or updated or cleared or escalated:
                logger.info(
                    "incident_cycle opened=%d updated=%d cleared=%d escalated=%d rules=%d",
                    opened, updated, cleared, escalated, len(rules),
                )

        # Dispatch transitions AFTER the session is closed so the
        # AutomationEngine sees committed state. Collected during
        # `_evaluate_rule` as plain dicts (no ORM refs) to avoid
        # lazy-load surprises across sessions.
        if transitions and self._automation_engine is not None:
            for t in transitions:
                try:
                    await self._automation_engine.on_incident_transition(
                        incident_id=t["incident_id"],
                        rule_id=t["rule_id"],
                        transition=t["transition"],
                        device_id=t["device_id"],
                        severity=t["severity"],
                        message=t["message"],
                        labels=t["labels"],
                    )
                except Exception:
                    logger.exception(
                        "incident_transition_dispatch_error rule_id=%s transition=%s",
                        t["rule_id"], t["transition"],
                    )

    async def _evaluate_rule(
        self,
        session: AsyncSession,
        rule: IncidentRule,
        transitions: list[dict] | None = None,
    ) -> tuple[int, int, int, int]:
        """Evaluate one rule. Returns (opened, updated, cleared, escalated) counts.

        `transitions` is an optional list that is appended to when an
        incident enters a new state (`opened` / `escalated` / `cleared`).
        Each entry is a plain dict the engine passes to
        `AutomationEngine.on_incident_transition` after commit.
        """
        if transitions is None:
            transitions = []

        def _record(incident: Incident, transition: str) -> None:
            """Append a transition dict for later dispatch to the AutomationEngine."""
            labels = incident.labels or {}
            transitions.append(
                {
                    "incident_id": str(incident.id),
                    "rule_id": str(rule.id),
                    "transition": transition,
                    "device_id": (
                        str(incident.device_id) if incident.device_id else ""
                    ),
                    "severity": incident.severity,
                    "message": incident.message or "",
                    "labels": dict(labels),
                }
            )
        defn = rule.definition
        if not defn or not defn.enabled:
            return 0, 0, 0, 0

        entities = (
            await session.execute(
                select(AlertEntity).where(
                    AlertEntity.definition_id == defn.id,
                    AlertEntity.enabled == True,  # noqa: E712
                )
            )
        ).scalars().all()

        # Load currently-open incidents for this rule.
        open_incidents = (
            await session.execute(
                select(Incident).where(
                    Incident.rule_id == rule.id,
                    Incident.state == "open",
                )
            )
        ).scalars().all()
        open_by_key = {inc.entity_key: inc for inc in open_incidents}

        ladder = _validate_ladder(rule.severity_ladder)
        scope = _validate_scope_filter(rule.scope_filter)

        # Dependency resolution: if this rule depends on other rules, load
        # their currently-open incidents once and reuse for every entity in
        # this rule. Parents from the *same* rule as the child are excluded
        # (a rule can't suppress its own incidents). Transitive parents are
        # not resolved — a suppressed parent still counts as a valid parent.
        depends = _validate_depends_on(rule.depends_on)
        if depends:
            parent_rule_ids = [rid for rid in depends["rule_ids"] if rid != rule.id]
            if parent_rule_ids:
                parent_candidates = (
                    await session.execute(
                        select(Incident).where(
                            Incident.rule_id.in_(parent_rule_ids),
                            Incident.state == "open",
                        )
                    )
                ).scalars().all()
            else:
                parent_candidates = []
            match_on = depends["match_on"]
        else:
            parent_candidates = []
            match_on = []

        now = datetime.now(timezone.utc)
        opened = updated = cleared = escalated = 0

        for inst in entities:
            entity_key = f"{inst.assignment_id}|{inst.entity_key}"
            incident = open_by_key.get(entity_key)

            # Scope filter: entities outside the rule's scope are skipped. If
            # the filter was narrowed while an incident was already open, the
            # open incident is cleared with cleared_reason="out_of_scope" so
            # operators can distinguish it from natural auto-clears.
            if scope and not self._entity_in_scope(inst, scope):
                if incident is not None:
                    incident.state = "cleared"
                    incident.cleared_at = now
                    incident.cleared_reason = "out_of_scope"
                    cleared += 1
                    _record(incident, "cleared")
                    logger.info(
                        "incident_cleared rule=%s entity=%s reason=out_of_scope",
                        rule.name, inst.entity_key or "-",
                    )
                continue

            if inst.state == "firing":
                if incident is None:
                    # Threshold check mirrors the EventEngine's consecutive/cumulative logic.
                    if not self._meets_threshold(rule, inst):
                        continue
                    # Seed severity from ladder[0] if present, else rule default.
                    base_severity = ladder[0]["severity"] if ladder else rule.severity
                    # Dependency: find a matching parent, if any. Suppressed
                    # children share lifecycle with normal open incidents —
                    # they still track fire counts, escalate, and auto-clear.
                    # `parent_incident_id` carries the suppression link; phase 3
                    # UI filters on `parent_incident_id IS NULL` to show primaries.
                    parent_id = self._find_matching_parent(
                        parent_candidates, match_on, inst.entity_labels or {}
                    )
                    new_inc = Incident(
                        rule_id=rule.id,
                        entity_key=entity_key,
                        assignment_id=inst.assignment_id,
                        device_id=inst.device_id,
                        state="open",
                        severity=base_severity,
                        message=self._render_message(rule, defn, inst),
                        labels=inst.entity_labels or {},
                        fire_count=1,
                        opened_at=now,
                        last_fired_at=now,
                        severity_reached_at=now,
                        parent_incident_id=parent_id,
                    )
                    session.add(new_inc)
                    opened += 1
                    _record(new_inc, "opened")
                    logger.info(
                        "incident_opened rule=%s entity=%s device=%s severity=%s parent=%s",
                        rule.name, inst.entity_key or "-",
                        (inst.entity_labels or {}).get("device_name", "-"),
                        base_severity,
                        str(parent_id) if parent_id else "-",
                    )
                else:
                    incident.last_fired_at = now
                    incident.fire_count += 1
                    incident.message = self._render_message(rule, defn, inst)
                    # Refresh labels in case entity_labels grew new keys since open.
                    if inst.entity_labels:
                        incident.labels = inst.entity_labels
                    updated += 1

                    # Recompute parent on each cycle so parent clears
                    # auto-unsuppress children, and new parents suppress
                    # previously-primary incidents.
                    if depends:
                        new_parent_id = self._find_matching_parent(
                            parent_candidates, match_on, incident.labels or {}
                        )
                        if new_parent_id != incident.parent_incident_id:
                            old_parent_id = incident.parent_incident_id
                            incident.parent_incident_id = new_parent_id
                            logger.info(
                                "incident_suppression_changed rule=%s entity=%s parent=%s was=%s",
                                rule.name, inst.entity_key or "-",
                                str(new_parent_id) if new_parent_id else "-",
                                str(old_parent_id) if old_parent_id else "-",
                            )

                    # Apply severity ladder (wall-clock time since opened_at).
                    if ladder and self._apply_ladder(incident, ladder, now):
                        escalated += 1
                        _record(incident, "escalated")
                        logger.info(
                            "incident_escalated rule=%s entity=%s severity=%s elapsed=%ds",
                            rule.name, inst.entity_key or "-",
                            incident.severity,
                            int((now - incident.opened_at).total_seconds()),
                        )

            elif inst.state == "resolved" and incident is not None:
                if not rule.auto_clear_on_resolve:
                    continue
                # Flap guard: if configured and not yet elapsed since
                # last_fired_at, hold the clear. `last_fired_at` advances
                # on every firing cycle, so if the alert flaps back within
                # the window the same incident keeps riding — no new open,
                # no new UUID, notifications in phase 3+ fire only on the
                # eventual real clear. NULL / 0 flap_guard_seconds = legacy
                # immediate-clear behavior (phase 1-2b default).
                guard_s = rule.flap_guard_seconds
                if guard_s is not None and guard_s > 0:
                    age = (now - incident.last_fired_at).total_seconds()
                    if age < guard_s:
                        logger.info(
                            "incident_hold rule=%s entity=%s age=%ds guard=%ds",
                            rule.name, inst.entity_key or "-",
                            int(age), guard_s,
                        )
                        continue
                incident.state = "cleared"
                incident.cleared_at = now
                incident.cleared_reason = "auto"
                cleared += 1
                _record(incident, "cleared")
                logger.info(
                    "incident_cleared rule=%s entity=%s reason=auto",
                    rule.name, inst.entity_key or "-",
                )

        return opened, updated, cleared, escalated

    @staticmethod
    def _find_matching_parent(
        parent_candidates: list[Incident],
        match_on: list[str],
        child_labels: dict,
    ) -> uuid.UUID | None:
        """Return the id of the first parent incident that matches the child.

        If `match_on` is empty, the first parent wins (any open parent
        suppresses). Otherwise every key in `match_on` must exist on both
        the parent and the child labels and the values must be equal.
        Returns None if no match is found.
        """
        for parent in parent_candidates:
            if not match_on:
                return parent.id
            parent_labels = parent.labels or {}
            matched = True
            for key in match_on:
                p_val = parent_labels.get(key)
                c_val = child_labels.get(key)
                if p_val is None or c_val is None:
                    matched = False
                    break
                if str(p_val) != str(c_val):
                    matched = False
                    break
            if matched:
                return parent.id
        return None

    @staticmethod
    def _entity_in_scope(inst: AlertEntity, scope: dict[str, str]) -> bool:
        """Return True if the AlertEntity's labels AND-match the scope filter.

        Missing keys or value mismatches fail the check. An empty string
        in the scope value acts as a wildcard — the key must exist on the
        entity, but its value is unconstrained.
        """
        labels = inst.entity_labels or {}
        for key, required in scope.items():
            actual = labels.get(key)
            if actual is None:
                return False
            if required == "":
                # Wildcard: key must exist, value doesn't matter.
                continue
            if str(actual) != required:
                return False
        return True

    @staticmethod
    def _apply_ladder(incident: Incident, ladder: list[dict], now: datetime) -> bool:
        """Advance the incident's severity along the ladder if enough wall-clock
        time has elapsed since `opened_at`. Returns True if severity was
        promoted. Never demotes — a ladder with non-decreasing priorities
        (enforced by `_validate_ladder`) guarantees monotonic escalation."""
        elapsed = (now - incident.opened_at).total_seconds()
        target = _ladder_severity_at(ladder, elapsed)
        if target == incident.severity:
            return False
        target_priority = _SEVERITY_PRIORITY[target]
        current_priority = _SEVERITY_PRIORITY.get(incident.severity, -1)
        if target_priority <= current_priority:
            return False
        incident.severity = target
        incident.severity_reached_at = now
        return True

    @staticmethod
    def _meets_threshold(rule: IncidentRule, inst: AlertEntity) -> bool:
        """Same consecutive/cumulative semantics as EventEngine._check_criteria."""
        if rule.mode == "consecutive":
            return (inst.fire_count or 0) >= rule.fire_count_threshold
        if rule.mode == "cumulative":
            history = inst.fire_history or []
            window = history[-rule.window_size :] if rule.window_size else history
            fires_in_window = sum(1 for x in window if x)
            return fires_in_window >= rule.fire_count_threshold
        return False

    @staticmethod
    def _render_message(
        rule: IncidentRule, defn: AlertDefinition, inst: AlertEntity
    ) -> str:
        """Same template priority as EventEngine: rule.message_template → defn.message_template → fallback."""
        labels = inst.entity_labels or {}
        metrics = getattr(inst, "metric_values", None) or {}
        thresholds = getattr(inst, "threshold_values", None) or {}
        value = inst.current_value

        for template in [rule.message_template, defn.message_template]:
            if not template:
                continue
            context: dict[str, str] = {}
            for k, v in labels.items():
                context[k] = str(v)
            context["value"] = _fmt_number(value)
            context["alert_name"] = defn.name
            context["rule_name"] = defn.name
            context["fire_count"] = str(inst.fire_count)
            context["entity_key"] = inst.entity_key or ""
            for k, v in metrics.items():
                context[k] = _fmt_number(v)
            for k, v in thresholds.items():
                context[f"${k}"] = _fmt_number(v)
            try:
                return template.format_map(_SafeFormatDict(context))
            except (ValueError, TypeError):
                continue

        device = labels.get("device_name", "unknown")
        entity = labels.get("if_name") or labels.get("component") or inst.entity_key or ""
        val_str = f" = {round(value, 2)}" if value is not None else ""
        return f"{defn.name}{val_str} on {device} {entity} [{inst.fire_count}x]".strip()


# `sync_incident_rules_from_event_policies` was retired in alembic
# revision zq7r8s9t0u1v as part of the phase deprecation of the event
# policy rework. Pre-existing mirror rows were flipped in place to
# `source='native'` and the `source_policy_id` FK was dropped. No
# replacement — operators now manage incident rules directly via the
# `/v1/incident-rules` API (see docs/event-policy-rework.md).
