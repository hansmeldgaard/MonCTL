"""Remove severity from alert_definitions, add metric/threshold values to entities.

Revision ID: ab1cd2ef3gh4
Revises: p4q5r6s7t8u9
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "ab1cd2ef3gh4"
down_revision = "p4q5r6s7t8u9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("alert_definitions", "severity")

    op.add_column(
        "alert_entities",
        sa.Column("metric_values", JSONB, nullable=False, server_default="{}"),
    )
    op.add_column(
        "alert_entities",
        sa.Column("threshold_values", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("alert_entities", "threshold_values")
    op.drop_column("alert_entities", "metric_values")
    op.add_column(
        "alert_definitions",
        sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
    )
