"""Add device_types table and tenant_id to devices.

Revision ID: c4d5e6f7a8b9
Revises: a1b2c3d4e5f6
Create Date: 2026-03-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "c4d5e6f7a8b9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create device_types table
    op.create_table(
        "device_types",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="uq_device_types_name"),
    )

    # Add tenant_id to devices
    op.add_column(
        "devices",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=True,
        ),
    )
    op.create_index("idx_devices_tenant_id", "devices", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_devices_tenant_id", table_name="devices")
    op.drop_column("devices", "tenant_id")
    op.drop_table("device_types")
