"""add job cost and weight snapshot

Revision ID: o4p5q6r7s8t9
Revises: n3o4p5q6r7s8
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "o4p5q6r7s8t9"
down_revision = "n3o4p5q6r7s8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_assignments", sa.Column("avg_execution_time", sa.Float(), nullable=True))
    op.add_column("collector_groups", sa.Column("weight_snapshot", JSONB(), nullable=True))
    op.add_column(
        "collector_groups",
        sa.Column("weight_snapshot_topology", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("collector_groups", "weight_snapshot_topology")
    op.drop_column("collector_groups", "weight_snapshot")
    op.drop_column("app_assignments", "avg_execution_time")
