"""Alerts & events redesign: rename tables, columns, add active_events.

Revision ID: m1n2o3p4q5r6
Revises: k8l9m0n1o2p3
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "m1n2o3p4q5r6"
down_revision = "k8l9m0n1o2p3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Rename app_alert_definitions → alert_definitions ──────────────

    # Drop FKs that reference app_alert_definitions BEFORE renaming
    op.drop_constraint(
        "alert_instances_definition_id_fkey", "alert_instances", type_="foreignkey"
    )
    op.drop_constraint(
        "threshold_overrides_definition_id_fkey", "threshold_overrides", type_="foreignkey"
    )
    op.drop_constraint(
        "event_policies_definition_id_fkey", "event_policies", type_="foreignkey"
    )

    # Drop the pack_id FK before dropping the column
    op.drop_constraint(
        "app_alert_definitions_pack_id_fkey", "app_alert_definitions", type_="foreignkey"
    )

    op.rename_table("app_alert_definitions", "alert_definitions")

    # Drop columns from alert_definitions
    op.drop_column("alert_definitions", "notification_channels")
    op.drop_column("alert_definitions", "pack_id")

    # Recreate FKs pointing to the renamed table
    op.create_foreign_key(
        "alert_entities_definition_id_fkey",
        "alert_instances",
        "alert_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "threshold_overrides_definition_id_fkey",
        "threshold_overrides",
        "alert_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "event_policies_definition_id_fkey",
        "event_policies",
        "alert_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── 2. Rename alert_instances → alert_entities ───────────────────────

    # Drop the FK we just created (it references old table name in constraint)
    op.drop_constraint(
        "alert_entities_definition_id_fkey", "alert_instances", type_="foreignkey"
    )

    op.rename_table("alert_instances", "alert_entities")

    # Rename columns
    op.alter_column("alert_entities", "started_at", new_column_name="started_firing_at")
    op.alter_column("alert_entities", "resolved_at", new_column_name="last_cleared_at")

    # Drop columns
    op.drop_column("alert_entities", "event_created")

    # Recreate FK on the renamed table
    op.create_foreign_key(
        "alert_entities_definition_id_fkey",
        "alert_entities",
        "alert_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── 3. Create active_events table ────────────────────────────────────

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
        sa.Column("clickhouse_event_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("policy_id", "entity_key", name="uq_active_event_policy_entity"),
    )


def downgrade() -> None:
    # ── Drop active_events ───────────────────────────────────────────────
    op.drop_table("active_events")

    # ── Reverse alert_entities → alert_instances ─────────────────────────

    op.drop_constraint(
        "alert_entities_definition_id_fkey", "alert_entities", type_="foreignkey"
    )

    # Add back dropped column
    op.add_column(
        "alert_entities",
        sa.Column("event_created", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Reverse column renames
    op.alter_column("alert_entities", "last_cleared_at", new_column_name="resolved_at")
    op.alter_column("alert_entities", "started_firing_at", new_column_name="started_at")

    op.rename_table("alert_entities", "alert_instances")

    op.create_foreign_key(
        "alert_instances_definition_id_fkey",
        "alert_instances",
        "alert_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── Reverse alert_definitions → app_alert_definitions ────────────────

    op.drop_constraint(
        "alert_instances_definition_id_fkey", "alert_instances", type_="foreignkey"
    )
    op.drop_constraint(
        "threshold_overrides_definition_id_fkey", "threshold_overrides", type_="foreignkey"
    )
    op.drop_constraint(
        "event_policies_definition_id_fkey", "event_policies", type_="foreignkey"
    )

    # Add back dropped columns
    op.add_column(
        "alert_definitions",
        sa.Column("notification_channels", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "alert_definitions",
        sa.Column("pack_id", UUID(as_uuid=True), nullable=True),
    )

    op.rename_table("alert_definitions", "app_alert_definitions")

    # Recreate pack_id FK
    op.create_foreign_key(
        "app_alert_definitions_pack_id_fkey",
        "app_alert_definitions",
        "packs",
        ["pack_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Recreate FKs pointing to app_alert_definitions
    op.create_foreign_key(
        "alert_instances_definition_id_fkey",
        "alert_instances",
        "app_alert_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "threshold_overrides_definition_id_fkey",
        "threshold_overrides",
        "app_alert_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "event_policies_definition_id_fkey",
        "event_policies",
        "app_alert_definitions",
        ["definition_id"],
        ["id"],
        ondelete="CASCADE",
    )
