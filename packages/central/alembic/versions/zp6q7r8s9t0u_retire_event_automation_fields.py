"""Cut-over step 2: migrate event-typed automations to incident triggers, drop columns.

Phase cut-over step 2 of the event policy rework. Step 1 (revision
zo5p6q7r8s9t) added the `on_incident_transition` hook and the
`incident_rule_ids` / `incident_state_trigger` columns. Step 2 here
migrates any remaining `trigger_type='event'` automation rows onto the
new incident path and then drops the event-specific columns.

Mapping rules (applied in the data migration below):

- For each row with `trigger_type='event'`:
  - If `event_policy_ids` is a non-empty JSONB array, look up the
    mirror IncidentRule via `incident_rules.source_policy_id IN (...)`.
    Set `incident_rule_ids` to the matched rule ids.
  - If `event_policy_ids` is NULL or empty, leave `incident_rule_ids`
    NULL — the new automation will match on any incident rule (broad,
    but matches the legacy "no policy filter" behavior).
  - Always set `incident_state_trigger = 'any'` so the migrated
    automation fires on opened/escalated/cleared (matches the
    legacy "trigger on any event" behavior — the old hook had no
    state filter because events were append-only).
  - `trigger_type` flips to `'incident'`.
  - `event_severity_filter` is dropped. Incident severity is owned by
    the rule (via the severity ladder or base severity), not filtered
    at dispatch time. Any severity-based scoping should be reflected
    via scope filters on the rule itself or by picking specific rules
    in `incident_rule_ids`.

After the data migration, the three event-specific columns are
dropped. The legacy `on_new_events` hook and its caller in
`events/engine.py` are removed in the same PR.

Revision ID: zp6q7r8s9t0u
Revises: zo5p6q7r8s9t
"""

from alembic import op
import sqlalchemy as sa

revision = "zp6q7r8s9t0u"
down_revision = "zo5p6q7r8s9t"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Step 2a: migrate existing event-typed automations ──────────────
    #
    # For rows with `event_policy_ids`, map each policy_id to its mirror
    # IncidentRule via `source_policy_id`, aggregate the ids back into
    # the automation's new `incident_rule_ids` JSONB column. The
    # jsonb_array_elements_text unpack + to_jsonb(array_agg) round-trip
    # keeps the output shape identical to what the API writes
    # (`["<uuid-str>", ...]`).
    # Note on guard order: `jsonb_array_length` errors on non-array
    # scalars, and `event_policy_ids` can hold a JSONB `null` literal
    # (distinct from SQL NULL). Postgres's planner may evaluate WHERE
    # conjuncts out-of-order, so we can't rely on `IS NOT NULL AND
    # jsonb_typeof = 'array' AND jsonb_array_length(...) > 0` to
    # short-circuit — it'll still call jsonb_array_length on a scalar
    # and raise `cannot get array length of a scalar`.
    #
    # Fix: drop the `length > 0` guard. An empty array yields an empty
    # `jsonb_array_elements_text` result set, which makes `array_agg`
    # return NULL and `to_jsonb(NULL)` write SQL NULL to
    # `incident_rule_ids` — equivalent to the wildcard-match fallback
    # below. The row still flips trigger_type='incident' and escapes
    # the second UPDATE's WHERE.
    op.execute(
        """
        UPDATE automations a
        SET trigger_type = 'incident',
            incident_state_trigger = 'any',
            incident_rule_ids = (
                SELECT to_jsonb(array_agg(ir.id::text))
                FROM incident_rules ir
                WHERE ir.source_policy_id::text IN (
                    SELECT jsonb_array_elements_text(a.event_policy_ids)
                )
            )
        WHERE a.trigger_type = 'event'
          AND a.event_policy_ids IS NOT NULL
          AND jsonb_typeof(a.event_policy_ids) = 'array'
        """
    )

    # For rows with SQL NULL / JSONB null / any non-array scalar,
    # flip to incident with a wildcard match. Matches the legacy
    # behavior where no policy filter meant "fire on any event".
    op.execute(
        """
        UPDATE automations
        SET trigger_type = 'incident',
            incident_state_trigger = 'any',
            incident_rule_ids = NULL
        WHERE trigger_type = 'event'
        """
    )

    # ── Step 2b: drop the event-specific columns ───────────────────────
    op.drop_column("automations", "event_policy_ids")
    op.drop_column("automations", "event_severity_filter")
    op.drop_column("automations", "event_label_filter")


def downgrade() -> None:
    # Schema rollback only — data in the dropped columns is lost on
    # upgrade and cannot be restored automatically. Re-creating the
    # columns gives operators a place to put their data back if they
    # restored from a pre-step-2 snapshot.
    from sqlalchemy.dialects.postgresql import JSONB

    op.add_column(
        "automations",
        sa.Column("event_label_filter", JSONB(), nullable=True),
    )
    op.add_column(
        "automations",
        sa.Column("event_severity_filter", sa.String(20), nullable=True),
    )
    op.add_column(
        "automations",
        sa.Column("event_policy_ids", JSONB(), nullable=True),
    )
    # `trigger_type` flips from event→incident are NOT reverted — that
    # would require tracking the original trigger somewhere, and the
    # new on_incident_transition hook is the replacement path anyway.
