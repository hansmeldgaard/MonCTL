"""Drop default_credential_id from devices — use credentials JSONB instead.

Revision ID: zc3d4e5f6g7h
Revises: zb2c3d4e5f6g
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "zc3d4e5f6g7h"
down_revision = "zb2c3d4e5f6g"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migrate any remaining default_credential_id values into the credentials JSONB
    # Only for devices that have a default_credential_id but don't already have
    # the corresponding type in their credentials JSONB.
    op.execute("""
        UPDATE devices d
        SET credentials = d.credentials || jsonb_build_object(c.credential_type, d.default_credential_id::text)
        FROM credentials c
        WHERE d.default_credential_id IS NOT NULL
          AND c.id = d.default_credential_id
          AND c.credential_type IS NOT NULL
          AND c.credential_type != ''
          AND NOT d.credentials ? c.credential_type
    """)

    op.drop_constraint("devices_default_credential_id_fkey", "devices", type_="foreignkey")
    op.drop_column("devices", "default_credential_id")


def downgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("default_credential_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "devices_default_credential_id_fkey",
        "devices",
        "credentials",
        ["default_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )
