"""Add source_code, requirements, entry_class to app_versions for collector API.

Revision ID: a2b3c4d5e6f7
Revises: f1g2h3i4j5k6
Create Date: 2026-03-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "a2b3c4d5e6f7"
down_revision = "f1g2h3i4j5k6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns to app_versions for the new collector API
    # source_code: Python source code of the poll app
    op.add_column(
        "app_versions",
        sa.Column("source_code", sa.Text(), nullable=True),
    )
    # requirements: pip requirements list (e.g. ["pysnmp>=4.4", "aiohttp>=3.9"])
    op.add_column(
        "app_versions",
        sa.Column("requirements", JSONB(), nullable=False, server_default="[]"),
    )
    # entry_class: name of the class implementing BasePoller (e.g. "PingPoller")
    op.add_column(
        "app_versions",
        sa.Column("entry_class", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_versions", "source_code")
    op.drop_column("app_versions", "requirements")
    op.drop_column("app_versions", "entry_class")
