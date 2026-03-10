"""Add reported_peer_states to collectors.

Revision ID: k3l4m5n6o7p8
Revises: j2k3l4m5n6o7
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "k3l4m5n6o7p8"
down_revision = "j2k3l4m5n6o7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collectors", sa.Column("reported_peer_states", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("collectors", "reported_peer_states")
