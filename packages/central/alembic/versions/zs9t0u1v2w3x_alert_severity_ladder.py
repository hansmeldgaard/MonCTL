"""Add severity + ladder_key + ladder_rank to alert_definitions.

Introduces the severity-ladder concept: two (or more) alert definitions
sharing a non-null `ladder_key` are sibling thresholds on the same
signal. The alerting engine uses `ladder_rank` (higher = more severe)
to suppress lower-rank siblings for an (assignment, entity_key) while
a higher-rank sibling is firing. Eliminates the "warning + critical
fire simultaneously" double-alert pattern for the same metric.

Columns are additive and default-safe — legacy defs with NULL
ladder_key behave exactly as before (no suppression).

Revision ID: zs9t0u1v2w3x
Revises: zr8s9t0u1v2w
"""

import sqlalchemy as sa
from alembic import op

revision = "zs9t0u1v2w3x"
down_revision = "zr8s9t0u1v2w"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alert_definitions",
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="warning"),
    )
    op.add_column(
        "alert_definitions",
        sa.Column("ladder_key", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "alert_definitions",
        sa.Column("ladder_rank", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_alert_definitions_ladder_key",
        "alert_definitions",
        ["ladder_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_alert_definitions_ladder_key", table_name="alert_definitions")
    op.drop_column("alert_definitions", "ladder_rank")
    op.drop_column("alert_definitions", "ladder_key")
    op.drop_column("alert_definitions", "severity")
