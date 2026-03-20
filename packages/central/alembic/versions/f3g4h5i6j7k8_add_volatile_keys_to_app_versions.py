"""Add volatile_keys to app_versions.

Revision ID: f3g4h5i6j7k8
Revises: e2f3g4h5i6j7
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "f3g4h5i6j7k8"
down_revision = "e2f3g4h5i6j7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_versions", sa.Column("volatile_keys", JSONB, nullable=True, server_default="[]"))


def downgrade() -> None:
    op.drop_column("app_versions", "volatile_keys")
