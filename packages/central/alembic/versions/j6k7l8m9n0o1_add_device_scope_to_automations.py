"""Add unified device scope columns to automations.

Adds device_ids and device_label_filter that work for both
event-triggered and cron-triggered automations.

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-03-26 23:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "j6k7l8m9n0o1"
down_revision = "i5j6k7l8m9n0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("automations", sa.Column("device_ids", JSONB, nullable=True))
    op.add_column("automations", sa.Column("device_label_filter", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("automations", "device_label_filter")
    op.drop_column("automations", "device_ids")
