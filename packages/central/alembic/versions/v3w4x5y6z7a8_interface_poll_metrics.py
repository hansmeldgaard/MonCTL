"""Add poll_metrics column to interface_metadata.

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-03-16
"""

import sqlalchemy as sa
from alembic import op

revision = "v3w4x5y6z7a8"
down_revision = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='interface_metadata' AND column_name='poll_metrics'"
        )
    )
    if result.fetchone() is None:
        op.add_column(
            "interface_metadata",
            sa.Column("poll_metrics", sa.String(50), nullable=False, server_default="all"),
        )


def downgrade() -> None:
    op.drop_column("interface_metadata", "poll_metrics")
