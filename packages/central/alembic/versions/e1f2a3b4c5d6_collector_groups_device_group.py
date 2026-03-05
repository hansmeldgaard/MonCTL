"""Add group_id to collectors and collector_group_id to devices.

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-03-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "e1f2a3b4c5d6"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add group_id FK to collectors (nullable, SET NULL on group delete)
    op.add_column(
        "collectors",
        sa.Column(
            "group_id",
            UUID(as_uuid=True),
            sa.ForeignKey("collector_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_collectors_group", "collectors", ["group_id"])

    # Add collector_group_id FK to devices (nullable, SET NULL on group delete)
    op.add_column(
        "devices",
        sa.Column(
            "collector_group_id",
            UUID(as_uuid=True),
            sa.ForeignKey("collector_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_devices_collector_group", "devices", ["collector_group_id"])


def downgrade() -> None:
    op.drop_index("idx_devices_collector_group", table_name="devices")
    op.drop_column("devices", "collector_group_id")
    op.drop_index("idx_collectors_group", table_name="collectors")
    op.drop_column("collectors", "group_id")
