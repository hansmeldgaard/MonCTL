"""Incident engine phase 1: incident_rules + incidents tables.

Adds the new data model for the event policy rework while leaving the
existing event_policies / active_events / events pipeline fully intact.
See docs/event-policy-rework.md for the bigger picture.

The new IncidentEngine runs in shadow mode via MONCTL_INCIDENT_ENGINE
(default "shadow"). It reads AlertEntities and IncidentRules and writes
to incidents only — no CH writes, no notifications, no automations.

Phase 2+ features have columns reserved nullable so no follow-up
migration is needed when ladders, correlation, dependencies, etc land.

Revision ID: zn4o5p6q7r8s
Revises: zm3n4o5p6q7r
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "zn4o5p6q7r8s"
down_revision = "zm3n4o5p6q7r"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── incident_rules ──────────────────────────────────────────────────
    op.create_table(
        "incident_rules",
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
            index=True,
        ),
        sa.Column("mode", sa.String(20), nullable=False, server_default="consecutive"),
        sa.Column("fire_count_threshold", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("window_size", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("message_template", sa.Text(), nullable=True),
        sa.Column(
            "auto_clear_on_resolve", sa.Boolean(), nullable=False, server_default="true"
        ),
        # Phase 2 columns — reserved, unused by phase-1 engine
        sa.Column("scope_filter", JSONB(), nullable=True),
        sa.Column("severity_ladder", JSONB(), nullable=True),
        sa.Column("correlation_group", sa.String(500), nullable=True),
        sa.Column("depends_on", JSONB(), nullable=True),
        sa.Column("flap_guard_seconds", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("source", sa.String(20), nullable=False, server_default="mirror"),
        sa.Column(
            "source_policy_id",
            UUID(as_uuid=True),
            sa.ForeignKey("event_policies.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
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
        sa.UniqueConstraint(
            "source_policy_id", name="uq_incident_rule_source_policy"
        ),
    )

    # ── incidents ──────────────────────────────────────────────────────
    op.create_table(
        "incidents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "rule_id",
            UUID(as_uuid=True),
            sa.ForeignKey("incident_rules.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("entity_key", sa.String(500), nullable=False),
        sa.Column(
            "assignment_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("device_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("labels", JSONB(), nullable=False, server_default="{}"),
        sa.Column("fire_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_fired_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_reason", sa.String(32), nullable=True),
        # Phase 2 columns
        sa.Column("correlation_key", sa.String(500), nullable=True),
        sa.Column(
            "parent_incident_id",
            UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("severity_reached_at", sa.DateTime(timezone=True), nullable=True),
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

    # Partial unique index — only one open incident per (rule, entity) at a time.
    # Cleared rows are unconstrained so history can accumulate.
    op.create_index(
        "uq_incidents_rule_entity_open",
        "incidents",
        ["rule_id", "entity_key"],
        unique=True,
        postgresql_where=sa.text("state = 'open'"),
    )

    # ── Seed incident_rules from event_policies ────────────────────────
    # One-time mirror of every existing EventPolicy. Ongoing sync is done
    # by the scheduler's _sync_incident_rules task.
    op.execute(
        """
        INSERT INTO incident_rules (
            id, name, description, definition_id,
            mode, fire_count_threshold, window_size,
            severity, message_template, auto_clear_on_resolve,
            enabled, source, source_policy_id,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            name,
            description,
            definition_id,
            mode,
            fire_count_threshold,
            window_size,
            event_severity,
            message_template,
            auto_clear_on_resolve,
            enabled,
            'mirror',
            id,
            created_at,
            updated_at
        FROM event_policies
        """
    )


def downgrade() -> None:
    op.drop_index("uq_incidents_rule_entity_open", table_name="incidents")
    op.drop_table("incidents")
    op.drop_table("incident_rules")
