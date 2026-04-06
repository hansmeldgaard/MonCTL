"""Enforce at most one assignment per role per device.

Revision ID: zm3n4o5p6q7r
Revises: zl2m3n4o5p6q
Create Date: 2026-04-06
"""

from alembic import op

revision = "zm3n4o5p6q7r"
down_revision = "zl2m3n4o5p6q"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicates first — keep the newest row per (device_id, role)
    op.execute("""
        DELETE FROM app_assignments
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY device_id, role
                           ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                       ) AS rn
                FROM app_assignments
                WHERE device_id IS NOT NULL AND role IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
    """)

    op.create_index(
        "uq_device_role",
        "app_assignments",
        ["device_id", "role"],
        unique=True,
        postgresql_where="device_id IS NOT NULL AND role IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_device_role", table_name="app_assignments")
