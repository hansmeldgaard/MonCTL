"""Add CASCADE delete on app_assignments.device_id FK.

Revision ID: zi9j0k1l2m3n
Revises: zh8i9j0k1l2m
Create Date: 2026-04-03
"""

from alembic import op

revision = "zi9j0k1l2m3n"
down_revision = "zh8i9j0k1l2m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Clean up orphaned assignments whose device no longer exists
    op.execute("""
        DELETE FROM app_assignments
        WHERE device_id IS NOT NULL
          AND device_id NOT IN (SELECT id FROM devices)
    """)

    # Drop old FK and re-create with ON DELETE CASCADE
    op.drop_constraint(
        "app_assignments_device_id_fkey", "app_assignments", type_="foreignkey"
    )
    op.create_foreign_key(
        "app_assignments_device_id_fkey",
        "app_assignments",
        "devices",
        ["device_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "app_assignments_device_id_fkey", "app_assignments", type_="foreignkey"
    )
    op.create_foreign_key(
        "app_assignments_device_id_fkey",
        "app_assignments",
        "devices",
        ["device_id"],
        ["id"],
    )
