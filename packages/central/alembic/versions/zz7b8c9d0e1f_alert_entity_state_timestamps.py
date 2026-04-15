"""Add current_state_since and last_triggered_at to alert_entities.

Paired with the per-tier fire_count change: we now track when the
entity entered its current severity tier (current_state_since) and
the last evaluation cycle where a fire tier matched (last_triggered_at).
started_firing_at is preserved as the overall firing start (across
tier transitions).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "zz7b8c9d0e1f"
down_revision = "aa1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alert_entities",
        sa.Column("current_state_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alert_entities",
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill: for currently-firing entities, seed both from started_firing_at
    # so the UI doesn't show dashes until the next evaluation cycle.
    op.execute(
        """
        UPDATE alert_entities
           SET current_state_since = started_firing_at,
               last_triggered_at = COALESCE(last_evaluated_at, started_firing_at)
         WHERE state = 'firing'
        """
    )


def downgrade() -> None:
    op.drop_column("alert_entities", "last_triggered_at")
    op.drop_column("alert_entities", "current_state_since")
