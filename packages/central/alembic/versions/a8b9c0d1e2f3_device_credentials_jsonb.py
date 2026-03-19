"""Add credentials JSONB column to devices for per-protocol credential mapping.

Revision ID: a8b9c0d1e2f3
Revises: z7a8b9c0d1e2
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "a8b9c0d1e2f3"
down_revision = "ee5ff6gg7hh8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("credentials", JSONB, nullable=False, server_default="{}"),
    )
    # Migrate existing default_credential_id into the new credentials JSONB
    # by looking up the credential_type from the credentials table
    op.execute("""
        UPDATE devices d
        SET credentials = jsonb_build_object(c.credential_type, d.default_credential_id::text)
        FROM credentials c
        WHERE d.default_credential_id IS NOT NULL
          AND c.id = d.default_credential_id
    """)


def downgrade() -> None:
    op.drop_column("devices", "credentials")
