"""Add log_level_filter to collectors.

Revision ID: a1b2c3d4e5f6
Revises: z7a8b9c0d1e2
Create Date: 2026-03-25 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "cd3ef4gh5ij6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "collectors",
        sa.Column("log_level_filter", sa.String(20), server_default="INFO", nullable=False),
    )


def downgrade():
    op.drop_column("collectors", "log_level_filter")
