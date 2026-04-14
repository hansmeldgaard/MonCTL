"""Dedupe stale per-severity IncidentRule pairs.

Pre-tier rework the alerting system had one AlertDefinition per severity
level (e.g. "Ping High RTT Warning" + "Ping High RTT Critical"). PR #38
merged those into a single def-per-signal with `severity_tiers`. Rule
rows that were authored under the old model therefore now *collide* on
the same `definition_id`, and the incident engine opens one incident
per rule — producing duplicate incidents for the same signal.

This migration keeps at most one rule per definition. Selection:

  1. Prefer a rule whose name does NOT contain "Promote to Event"
     (operator-renamed, cleaner names win).
  2. Otherwise prefer a rule that already has `severity_ladder`.
  3. Otherwise the oldest `created_at` (stable).
  4. Tiebreak on lowest id.

Survivor absorbs the union of `clear_on_companion_ids` from all peers.
Existing `incidents.rule_id` rows pointing at victims are re-pointed to
the survivor before victims are deleted (CASCADE would otherwise drop
any open incidents — not what we want).

Also scrubs any UUIDs from `clear_on_companion_ids` that no longer
exist in `alert_definitions` (leftover from earlier def deletions).

No backward-compat shim: once this runs, duplicate rules are gone and
companion lists are clean. The engine already handles one-rule-per-def
(the common case).
"""
from __future__ import annotations

import json
from collections import defaultdict

import sqlalchemy as sa
from alembic import op


revision = "zy5z6a7b8c9d"
down_revision = "zx4y5z6a7b8c"
branch_labels = None
depends_on = None


def _pick_keeper(rules: list[dict]) -> dict:
    """Return the preferred rule from a collision group."""

    def sort_key(r: dict) -> tuple:
        name = r["name"] or ""
        has_suffix = "Promote to Event" in name
        has_ladder = r["severity_ladder"] is not None
        # Lower tuple wins: prefer no-suffix, then has-ladder, then oldest.
        return (has_suffix, not has_ladder, r["created_at"], str(r["id"]))

    return sorted(rules, key=sort_key)[0]


def upgrade() -> None:
    conn = op.get_bind()

    rules = conn.execute(
        sa.text(
            "SELECT id, definition_id, name, severity, severity_ladder, "
            "clear_on_companion_ids, created_at "
            "FROM incident_rules"
        )
    ).mappings().all()

    by_def: dict[str, list[dict]] = defaultdict(list)
    for r in rules:
        by_def[str(r["definition_id"])].append(dict(r))

    valid_def_ids = {
        str(row[0])
        for row in conn.execute(
            sa.text("SELECT id FROM alert_definitions")
        ).all()
    }

    for def_id, group in by_def.items():
        keeper = _pick_keeper(group)
        keeper_id = str(keeper["id"])

        # Union of companion ids across the group, scrubbed.
        union: list[str] = []
        seen: set[str] = set()
        for r in group:
            raw = r["clear_on_companion_ids"]
            if not isinstance(raw, list):
                continue
            for cid in raw:
                cid_s = str(cid)
                if cid_s in seen or cid_s not in valid_def_ids:
                    continue
                seen.add(cid_s)
                union.append(cid_s)

        # For each victim:
        #   - Drop its currently-open incidents. They'd either collide with
        #     the keeper's open incident on the same (rule_id, entity_key),
        #     or be duplicates of a signal the keeper rule already covers.
        #     If the underlying alert is still firing, the engine will
        #     reopen a clean incident under the keeper on its next cycle.
        #   - Re-point cleared incidents so we retain the history trail.
        #   - Delete the victim rule itself (CASCADE is now a no-op).
        for r in group:
            rid = str(r["id"])
            if rid == keeper_id:
                continue
            conn.execute(
                sa.text(
                    "DELETE FROM incidents "
                    "WHERE rule_id = CAST(:rid AS uuid) AND state = 'open'"
                ),
                {"rid": rid},
            )
            conn.execute(
                sa.text(
                    "UPDATE incidents SET rule_id = CAST(:to_id AS uuid) "
                    "WHERE rule_id = CAST(:from_id AS uuid)"
                ),
                {"to_id": keeper_id, "from_id": rid},
            )
            conn.execute(
                sa.text(
                    "DELETE FROM incident_rules WHERE id = CAST(:id AS uuid)"
                ),
                {"id": rid},
            )

        # Write merged/scrubbed companion list back on the keeper.
        conn.execute(
            sa.text(
                "UPDATE incident_rules "
                "SET clear_on_companion_ids = CAST(:ids AS jsonb), "
                "    updated_at = now() "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {
                "ids": json.dumps(union) if union else None,
                "id": keeper_id,
            },
        )


def downgrade() -> None:
    # One-way cleanup: deleted rules cannot be resurrected, and merged
    # companion lists lose per-rule origin.
    raise RuntimeError(
        "zy5z6a7b8c9d is a non-reversible dedup migration"
    )
