"""Drop peer_address column from collectors (unused work-stealing remnant).

Revision ID: zf6g7h8i9j0k
Revises: ze5f6g7h8i9j
Create Date: 2026-04-02
"""

from alembic import op
import sqlalchemy as sa

revision = "zf6g7h8i9j0k"
down_revision = "ze5f6g7h8i9j"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("collectors", "peer_address")


def downgrade() -> None:
    op.add_column("collectors", sa.Column("peer_address", sa.String(255), nullable=True))
