"""Add unique index on (app_id, device_id) for device-level assignments.

Prevents duplicate app assignments to the same device. Cleans up existing
duplicates first by keeping only the most recently updated assignment.

Revision ID: za1b2c3d4e5f
Revises: z7a8b9c0d1e2
Create Date: 2026-03-29
"""

from __future__ import annotations

from alembic import op

revision = "za1b2c3d4e5f"
down_revision = "p5q6r7s8t9u0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicate assignments: keep only the most recently updated per (app_id, device_id)
    op.execute("""
        DELETE FROM app_assignments
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY app_id, device_id
                           ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                       ) AS rn
                FROM app_assignments
                WHERE device_id IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
    """)

    # Add partial unique index for device-level assignments
    op.create_index(
        "uq_app_device_assignment",
        "app_assignments",
        ["app_id", "device_id"],
        unique=True,
        postgresql_where="device_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_app_device_assignment", table_name="app_assignments")
