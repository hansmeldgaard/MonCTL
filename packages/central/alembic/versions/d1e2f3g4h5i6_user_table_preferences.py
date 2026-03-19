"""Add table display preferences to users.

Revision ID: d1e2f3g4h5i6
Revises: c0d1e2f3g4h5
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa

revision = "d1e2f3g4h5i6"
down_revision = "c0d1e2f3g4h5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("table_page_size", sa.Integer(), nullable=False, server_default="50"),
    )
    op.add_column(
        "users",
        sa.Column("table_scroll_mode", sa.String(16), nullable=False, server_default="paginated"),
    )


def downgrade() -> None:
    op.drop_column("users", "table_scroll_mode")
    op.drop_column("users", "table_page_size")
