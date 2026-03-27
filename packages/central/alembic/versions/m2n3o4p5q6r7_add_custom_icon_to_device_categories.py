"""add custom icon to device categories

Revision ID: m2n3o4p5q6r7
Revises: l8m9n0o1p2q3
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "m2n3o4p5q6r7"
down_revision = "l8m9n0o1p2q3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("device_categories", sa.Column("icon_data", sa.LargeBinary(), nullable=True))
    op.add_column("device_categories", sa.Column("icon_mime_type", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("device_categories", "icon_mime_type")
    op.drop_column("device_categories", "icon_data")
