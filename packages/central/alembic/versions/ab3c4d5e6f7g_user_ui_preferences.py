"""Add ui_preferences JSONB to users for per-table column config.

Revision ID: ab3c4d5e6f7g
Revises: aa2b3c4d5e6f
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "ab3c4d5e6f7g"
down_revision = "aa2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "ui_preferences",
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
        comment=(
            "Versioned per-table UI state: hidden / width / order per "
            "column. Shape: {tables: {<tableId>: {v1: {<colKey>: "
            "{width?, hidden?, order?}}}}}"
        ),
    ))


def downgrade() -> None:
    op.drop_column("users", "ui_preferences")
