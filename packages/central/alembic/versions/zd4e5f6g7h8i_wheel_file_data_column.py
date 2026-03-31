"""Add file_data column to wheel_files for multi-node wheel distribution.

Revision ID: zd4e5f6g7h8i
Revises: zc3d4e5f6g7h
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa

revision = "zd4e5f6g7h8i"
down_revision = "zc3d4e5f6g7h"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wheel_files", sa.Column("file_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("wheel_files", "file_data")
