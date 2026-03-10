"""Add timezone column to users table.

Revision ID: n6o7p8q9r0s1
Revises: l4m5n6o7p8q9
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa

revision = "n6o7p8q9r0s1"
down_revision = "l4m5n6o7p8q9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(50), nullable=False, server_default="UTC"),
    )


def downgrade() -> None:
    op.drop_column("users", "timezone")
