"""Phase deprecation: retire EventPolicy + ActiveEvent tables.

Final step of the event policy rework (see docs/event-policy-rework.md).
After cut-over step 2 (revision zp6q7r8s9t0u) retired the
`on_new_events` hook and migrated all event-typed automations to the
incident path, nothing in the running system still reads or writes
`event_policies` / `active_events`. This migration finishes the job:

1. **Flip mirror IncidentRules to native**. Rules with `source='mirror'`
   were auto-synced from EventPolicy rows and carry a
   `source_policy_id` FK back to `event_policies`. Before the
   referenced table can drop, we need to (a) null out the FK and (b)
   flip the `source` column so operators can edit these rules directly.
2. **Drop the `source_policy_id` column** from `incident_rules`
   (implicitly drops the FK and the `uq_incident_rule_source_policy`
   unique constraint).
3. **Drop the `active_events` table** — the tracker rows used by the
   legacy auto-clear path. EventEngine is gone; no code reads this.
4. **Drop the `event_policies` table** — the legacy config surface.
   The `events` CH table is NOT touched; historical events remain
   queryable via the Events UI Active/Cleared tabs.

Reversible only to the extent of re-adding empty columns/tables —
the data in `event_policies` / `active_events` / `source_policy_id`
is gone once this lands.

Revision ID: zq7r8s9t0u1v
Revises: zp6q7r8s9t0u
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "zq7r8s9t0u1v"
down_revision = "zp6q7r8s9t0u"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Flip existing mirror rules to native. Operators will now be
    #    able to edit every field via the Incident Rules UI; the mirror
    #    sync task is gone, so nothing will try to overwrite them.
    op.execute(
        """
        UPDATE incident_rules
        SET source = 'native',
            source_policy_id = NULL,
            updated_at = now()
        WHERE source = 'mirror'
        """
    )

    # 2. Drop the source_policy_id FK + column. This also drops the
    #    unique constraint `uq_incident_rule_source_policy` because it
    #    was defined over this single column.
    op.drop_constraint(
        "uq_incident_rule_source_policy", "incident_rules", type_="unique"
    )
    op.drop_column("incident_rules", "source_policy_id")

    # 3. Drop the active_events table (legacy tracker for event
    #    auto-clear). Nothing reads or writes this after the code
    #    removal in the same PR.
    op.drop_table("active_events")

    # 4. Drop the event_policies table. The `events` CH table is
    #    untouched — historical rows stay queryable via the Events UI.
    op.drop_table("event_policies")


def downgrade() -> None:
    # Schema-only rollback. Data in the dropped tables/column is not
    # recoverable without a pre-upgrade backup.
    op.create_table(
        "event_policies",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "definition_id",
            UUID(as_uuid=True),
            sa.ForeignKey("alert_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(20), nullable=False, server_default="consecutive"),
        sa.Column("fire_count_threshold", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("window_size", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("event_severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("message_template", sa.Text(), nullable=True),
        sa.Column(
            "auto_clear_on_resolve", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("pack_origin", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "active_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "policy_id",
            UUID(as_uuid=True),
            sa.ForeignKey("event_policies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_key", sa.String(500), nullable=False),
        sa.Column("assignment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", UUID(as_uuid=True), nullable=True),
        sa.Column("clickhouse_event_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("fire_history", JSONB(), nullable=True),
        sa.Column("fire_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "incident_rules",
        sa.Column(
            "source_policy_id",
            UUID(as_uuid=True),
            sa.ForeignKey("event_policies.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_incident_rule_source_policy",
        "incident_rules",
        ["source_policy_id"],
    )
    # NOTE: The source='native' → 'mirror' flip is NOT reverted. After
    # re-applying the mirror sync task the relationship will re-populate
    # on the next cycle for any rules that still match an event policy.
