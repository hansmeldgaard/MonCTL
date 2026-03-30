"""Add interface_rules to devices and rules_managed to interface_metadata.

Supports declarative interface configuration via templates: rules match on
interface properties (alias, name, speed) and set monitoring parameters.

Revision ID: zb2c3d4e5f6g
Revises: za1b2c3d4e5f
Create Date: 2026-03-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "zb2c3d4e5f6g"
down_revision = "za1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("interface_rules", JSONB, nullable=True))
    op.add_column(
        "interface_metadata",
        sa.Column("rules_managed", sa.Boolean, nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("interface_metadata", "rules_managed")
    op.drop_column("devices", "interface_rules")
