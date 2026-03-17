"""App-level alert system — replaces global AlertRule/AlertState.

Revision ID: aa1bb2cc3dd4
Revises: z7a8b9c0d1e2
Create Date: 2026-03-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "aa1bb2cc3dd4"
down_revision = "c3d4e5f6g7h8"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = :name)"
    ), {"name": name})
    return result.scalar()


def upgrade() -> None:
    # 1. Drop old tables if they exist
    if _table_exists("alert_states"):
        op.drop_table("alert_states")
    if _table_exists("alert_rules"):
        op.drop_table("alert_rules")

    # 2. Create new tables (skip if create_all already made them)
    if not _table_exists("app_alert_definitions"):
        op.create_table(
            "app_alert_definitions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("app_id", UUID(as_uuid=True), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("app_version_id", UUID(as_uuid=True), sa.ForeignKey("app_versions.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("expression", sa.Text, nullable=False),
            sa.Column("window", sa.String(20), nullable=False, server_default="5m"),
            sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("message_template", sa.Text),
            sa.Column("notification_channels", JSONB, nullable=False, server_default="[]"),
            sa.Column("pack_origin", sa.String(255)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("app_version_id", "name", name="uq_alert_def_version_name"),
        )

    if not _table_exists("alert_instances"):
        op.create_table(
            "alert_instances",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("definition_id", UUID(as_uuid=True), sa.ForeignKey("app_alert_definitions.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("assignment_id", UUID(as_uuid=True), sa.ForeignKey("app_assignments.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("state", sa.String(20), nullable=False, server_default="ok"),
            sa.Column("current_value", sa.Float, nullable=True),
            sa.Column("fire_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("fire_history", JSONB, nullable=False, server_default="[]"),
            sa.Column("last_evaluated_at", sa.DateTime(timezone=True)),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
            sa.Column("event_created", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("entity_key", sa.String(500), nullable=False, server_default=""),
            sa.Column("entity_labels", JSONB, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("definition_id", "assignment_id", name="uq_instance_def_assignment"),
        )

    if not _table_exists("threshold_overrides"):
        op.create_table(
            "threshold_overrides",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("definition_id", UUID(as_uuid=True), sa.ForeignKey("app_alert_definitions.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("entity_key", sa.String(500), nullable=False, server_default=""),
            sa.Column("overrides", JSONB, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("definition_id", "device_id", "entity_key", name="uq_override_def_device_entity"),
        )


def downgrade() -> None:
    op.drop_table("threshold_overrides")
    op.drop_table("alert_instances")
    op.drop_table("app_alert_definitions")

    op.create_table(
        "alert_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("rule_type", sa.String(20), nullable=False),
        sa.Column("condition", JSONB, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("notification_channels", JSONB, nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "alert_states",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_id", UUID(as_uuid=True), sa.ForeignKey("alert_rules.id"), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("labels", JSONB, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("last_notified_at", sa.DateTime(timezone=True)),
        sa.Column("annotations", JSONB),
    )
