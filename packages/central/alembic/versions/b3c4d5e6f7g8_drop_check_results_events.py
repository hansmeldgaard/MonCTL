"""Drop check_results and events tables — moved to ClickHouse.

Revision ID: b3c4d5e6f7g8
Revises: a2b3c4d5e6f7
Create Date: 2026-03-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "b3c4d5e6f7g8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("events")
    op.drop_table("check_results")


def downgrade() -> None:
    # Recreate check_results
    op.create_table(
        "check_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assignment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("collector_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.SmallInteger(), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("performance_data", JSONB(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("execution_time", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_check_results_assignment_time", "check_results", ["assignment_id", sa.text("executed_at DESC")])
    op.create_index("idx_check_results_collector_time", "check_results", ["collector_id", sa.text("executed_at DESC")])

    # Recreate events
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("collector_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSONB(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_events_collector_time", "events", ["collector_id", sa.text("occurred_at DESC")])
    op.create_index("idx_events_severity", "events", ["severity", sa.text("occurred_at DESC")])
