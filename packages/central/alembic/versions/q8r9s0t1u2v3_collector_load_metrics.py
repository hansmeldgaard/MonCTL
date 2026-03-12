"""Add load metric columns to collectors for weighted job partitioning.

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-03-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "q8r9s0t1u2v3"
down_revision = "p7q8r9s0t1u2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collectors", sa.Column("load_score", sa.Float(), nullable=False, server_default="0.0"))
    op.add_column("collectors", sa.Column("effective_load", sa.Float(), nullable=False, server_default="0.0"))
    op.add_column("collectors", sa.Column("total_jobs", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("collectors", sa.Column("worker_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("collectors", sa.Column("deadline_miss_rate", sa.Float(), nullable=False, server_default="0.0"))
    op.add_column("collectors", sa.Column("load_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("collectors", "load_updated_at")
    op.drop_column("collectors", "deadline_miss_rate")
    op.drop_column("collectors", "worker_count")
    op.drop_column("collectors", "total_jobs")
    op.drop_column("collectors", "effective_load")
    op.drop_column("collectors", "load_score")
