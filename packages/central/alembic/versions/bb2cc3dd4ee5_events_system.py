"""Add events system — event_policies table.

Revision ID: bb2cc3dd4ee5
Revises: aa1bb2cc3dd4
Create Date: 2026-03-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "bb2cc3dd4ee5"
down_revision = "aa1bb2cc3dd4"
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
    if _table_exists("event_policies"):
        return
    op.create_table(
        "event_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("definition_id", UUID(as_uuid=True),
                  sa.ForeignKey("app_alert_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="consecutive"),
        sa.Column("fire_count_threshold", sa.Integer, nullable=False, server_default="1"),
        sa.Column("window_size", sa.Integer, nullable=False, server_default="5"),
        sa.Column("event_severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("message_template", sa.Text, nullable=True),
        sa.Column("auto_clear_on_resolve", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("event_policies")
