"""Add target_table on apps, is_latest on app_versions, use_latest on app_assignments.

Revision ID: a1b2c3d4e5f6
Revises: f1g2h3i4j5k6
Create Date: 2026-03-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "p7q8r9s0t1u2"
down_revision = "n6o7p8q9r0s1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # App target_table — which ClickHouse table results go to
    op.add_column(
        "apps",
        sa.Column("target_table", sa.String(50), nullable=False, server_default="availability_latency"),
    )

    # AppVersion is_latest — explicit latest version marker
    op.add_column(
        "app_versions",
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default="false"),
    )

    # AppAssignment use_latest — follow latest version dynamically
    op.add_column(
        "app_assignments",
        sa.Column("use_latest", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Data migration: set is_latest=true for the newest version per app
    op.execute("""
        UPDATE app_versions SET is_latest = true
        WHERE id IN (
            SELECT DISTINCT ON (app_id) id
            FROM app_versions
            ORDER BY app_id, published_at DESC
        )
    """)


def downgrade() -> None:
    op.drop_column("app_assignments", "use_latest")
    op.drop_column("app_versions", "is_latest")
    op.drop_column("apps", "target_table")
