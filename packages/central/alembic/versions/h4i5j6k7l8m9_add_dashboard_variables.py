"""Add variables column to analytics_dashboards.

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-03-26 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "h4i5j6k7l8m9"
down_revision = "g3h4i5j6k7l8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "analytics_dashboards",
        sa.Column("variables", JSONB, nullable=False, server_default="[]"),
    )


def downgrade():
    op.drop_column("analytics_dashboards", "variables")
