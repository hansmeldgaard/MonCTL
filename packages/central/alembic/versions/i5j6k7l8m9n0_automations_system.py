"""Add automations system: actions, automations, automation_steps.

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m9
Create Date: 2026-03-26 22:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "i5j6k7l8m9n0"
down_revision = "h4i5j6k7l8m9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Actions table
    op.create_table(
        "actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("target", sa.String(20), nullable=False, server_default="collector"),
        sa.Column("source_code", sa.Text, nullable=False, server_default=""),
        sa.Column("credential_type", sa.String(100), nullable=True),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="60"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 2. Automations table
    op.create_table(
        "automations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("event_severity_filter", sa.String(20), nullable=True),
        sa.Column("event_label_filter", JSONB, nullable=True),
        sa.Column("cron_expression", sa.String(100), nullable=True),
        sa.Column("cron_device_label_filter", JSONB, nullable=True),
        sa.Column("cron_device_ids", JSONB, nullable=True),
        sa.Column("cooldown_seconds", sa.Integer, nullable=False, server_default="300"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 3. Automation steps (join table)
    op.create_table(
        "automation_steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("automation_id", UUID(as_uuid=True), sa.ForeignKey("automations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", UUID(as_uuid=True), sa.ForeignKey("actions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("credential_type_override", sa.String(100), nullable=True),
        sa.Column("timeout_override", sa.Integer, nullable=True),
    )
    op.create_index(
        "ix_automation_steps_automation_order",
        "automation_steps",
        ["automation_id", "step_order"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("automation_steps")
    op.drop_table("automations")
    op.drop_table("actions")
