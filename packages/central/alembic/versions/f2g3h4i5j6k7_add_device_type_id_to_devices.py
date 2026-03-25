"""Add device_type_id FK to devices table.

Revision ID: f2g3h4i5j6k7
Revises: ef6gh7ij8kl9
Create Date: 2026-03-25 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f2g3h4i5j6k7"
down_revision = "ef6gh7ij8kl9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "devices",
        sa.Column("device_type_id", UUID(as_uuid=True), sa.ForeignKey("device_types.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_devices_device_type_id", "devices", ["device_type_id"])


def downgrade():
    op.drop_index("ix_devices_device_type_id", table_name="devices")
    op.drop_column("devices", "device_type_id")
