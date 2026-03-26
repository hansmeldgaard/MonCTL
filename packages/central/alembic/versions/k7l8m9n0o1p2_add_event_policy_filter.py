"""Add event_policy_ids filter to automations.

Allows event-triggered automations to fire only for specific event policies.

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-03-26 23:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "k7l8m9n0o1p2"
down_revision = "j6k7l8m9n0o1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("automations", sa.Column("event_policy_ids", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("automations", "event_policy_ids")
