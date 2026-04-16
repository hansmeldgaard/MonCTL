"""Add labels JSONB to interface_metadata.

User-applied labels on individual interfaces. Mirrors devices.labels —
same JSONB column, same LabelKey registry for allowed keys, same auto-
registration flow on update.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "aa2b3c4d5e6f"
down_revision = "zz7b8c9d0e1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interface_metadata",
        sa.Column(
            "labels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("interface_metadata", "labels")
