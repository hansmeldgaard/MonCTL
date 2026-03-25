"""Rename device_types→device_categories, discovery_rules→device_types.

Device categories are groupings like cisco-router, juniper-switch.
Device types are specific hardware models with sysObjectID patterns.

Revision ID: cd3ef4gh5ij6
Revises: bc2de3fg4hi5
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa

revision = "cd3ef4gh5ij6"
down_revision = "bc2de3fg4hi5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop FK constraints that reference the tables being renamed
    op.drop_constraint("discovery_rules_device_type_id_fkey", "discovery_rules", type_="foreignkey")
    op.drop_constraint("discovery_rules_pack_id_fkey", "discovery_rules", type_="foreignkey")

    # 2. Rename device_types → device_categories
    op.rename_table("device_types", "device_categories")

    # 3. Drop auto_assign_packs from device_categories
    op.drop_column("device_categories", "auto_assign_packs")

    # 4. Rename discovery_rules → device_types
    op.rename_table("discovery_rules", "device_types")

    # 5. Rename column discovery_rules.device_type_id → device_category_id
    op.alter_column("device_types", "device_type_id", new_column_name="device_category_id")

    # 6. Rename Device.device_type → Device.device_category
    op.alter_column("devices", "device_type", new_column_name="device_category")

    # 7. Re-create FK constraints with new names
    op.create_foreign_key(
        "device_types_device_category_id_fkey", "device_types",
        "device_categories", ["device_category_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "device_types_pack_id_fkey", "device_types",
        "packs", ["pack_id"], ["id"],
        ondelete="SET NULL",
    )

    # 8. Rename unique constraint on sys_object_id_pattern
    op.execute(sa.text(
        "ALTER INDEX IF EXISTS uq_discovery_rules_pattern RENAME TO uq_device_types_pattern"
    ))

    # 9. Rename pack_id index
    op.execute(sa.text(
        "ALTER INDEX IF EXISTS ix_discovery_rules_pack_id RENAME TO ix_device_types_pack_id"
    ))


def downgrade() -> None:
    # Reverse: rename back
    op.alter_column("devices", "device_category", new_column_name="device_type")
    op.alter_column("device_types", "device_category_id", new_column_name="device_type_id")

    op.drop_constraint("device_types_device_category_id_fkey", "device_types", type_="foreignkey")
    op.drop_constraint("device_types_pack_id_fkey", "device_types", type_="foreignkey")

    op.rename_table("device_types", "discovery_rules")
    op.rename_table("device_categories", "device_types")

    op.add_column("device_types", sa.Column("auto_assign_packs", sa.JSON, nullable=False, server_default="[]"))

    op.create_foreign_key(
        "discovery_rules_device_type_id_fkey", "discovery_rules",
        "device_types", ["device_type_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "discovery_rules_pack_id_fkey", "discovery_rules",
        "packs", ["pack_id"], ["id"],
        ondelete="SET NULL",
    )
