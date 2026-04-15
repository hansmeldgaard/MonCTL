"""Add content_hash column to pack_versions.

Tracks the sha256 of the pack JSON file at import time so the startup
auto-import can detect in-place edits of an already-shipped version
and trigger an automatic reconcile. See the pack-reconcile plan
(``proud-tickling-acorn``) for motivation.

Revision ID: aa1b2c3d4e5f
Revises: ab1c2d3e4f5g
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "aa1b2c3d4e5f"
down_revision = "ab1c2d3e4f5g"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pack_versions",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pack_versions", "content_hash")
