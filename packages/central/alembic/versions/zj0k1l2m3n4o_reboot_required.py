"""Add reboot_required column to system_versions.

Revision ID: zj0k1l2m3n4o
Revises: zi9j0k1l2m3n
Create Date: 2026-04-03
"""

from alembic import op
import sqlalchemy as sa

revision = "zj0k1l2m3n4o"
down_revision = "zi9j0k1l2m3n"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("system_versions", sa.Column("reboot_required", sa.Boolean, nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("system_versions", "reboot_required")
