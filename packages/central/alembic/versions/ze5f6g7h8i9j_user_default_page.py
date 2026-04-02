"""Add default_page column to users.

Revision ID: ze5f6g7h8i9j
Revises: zd4e5f6g7h8i
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa

revision = "ze5f6g7h8i9j"
down_revision = "zd4e5f6g7h8i"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("default_page", sa.String(255), nullable=False, server_default="/"))


def downgrade() -> None:
    op.drop_column("users", "default_page")
