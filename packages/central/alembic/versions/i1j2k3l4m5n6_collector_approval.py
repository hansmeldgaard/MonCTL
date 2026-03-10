"""Add collector approval workflow fields.

Revision ID: i1j2k3l4m5n6
Revises: g1h2i3j4k5l6
Create Date: 2026-03-08
"""

from alembic import op
import sqlalchemy as sa

revision = "i1j2k3l4m5n6"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collectors", sa.Column("fingerprint", sa.String(64), nullable=True))
    op.add_column("collectors", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("collectors", sa.Column("approved_by", sa.String(255), nullable=True))
    op.add_column("collectors", sa.Column("rejected_reason", sa.Text(), nullable=True))
    op.create_index("ix_collectors_fingerprint", "collectors", ["fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_collectors_fingerprint", table_name="collectors")
    op.drop_column("collectors", "rejected_reason")
    op.drop_column("collectors", "approved_by")
    op.drop_column("collectors", "approved_at")
    op.drop_column("collectors", "fingerprint")
