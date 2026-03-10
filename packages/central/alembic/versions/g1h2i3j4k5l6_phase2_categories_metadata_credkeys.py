"""Phase 2: DeviceType category, Tenant metadata, CredentialKey/CredentialValue tables.

Revision ID: g1h2i3j4k5l6
Revises: b3c4d5e6f7g8
Create Date: 2026-03-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "g1h2i3j4k5l6"
down_revision = "b3c4d5e6f7g8"
branch_labels = None
depends_on = None

# Category mapping for existing seeded device types
_CATEGORY_MAP = {
    "host": "server",
    "virtual-machine": "server",
    "container": "server",
    "network": "network",
    "storage": "storage",
    "printer": "printer",
    "iot": "iot",
    "api": "service",
    "service": "service",
    "database": "database",
}


def upgrade() -> None:
    # 1. Add category column to device_types
    op.add_column(
        "device_types",
        sa.Column("category", sa.String(32), nullable=False, server_default="other"),
    )
    # Update seeded types with proper categories
    for name, category in _CATEGORY_MAP.items():
        op.execute(
            sa.text(
                "UPDATE device_types SET category = :cat WHERE name = :name"
            ).bindparams(cat=category, name=name)
        )

    # 2. Add metadata column to tenants
    op.add_column(
        "tenants",
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )

    # 3. Create credential_keys table
    op.create_table(
        "credential_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_secret", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Seed default credential keys
    op.execute(sa.text("""
        INSERT INTO credential_keys (name, description, is_secret) VALUES
        ('username', 'Login username', false),
        ('password', 'Login password', true),
        ('community', 'SNMP community string', true),
        ('api_key', 'API key or token', true),
        ('port', 'Connection port', false),
        ('private_key', 'SSH/TLS private key', true),
        ('token', 'Authentication token', true)
    """))

    # 4. Create credential_values table
    op.create_table(
        "credential_values",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("credential_id", UUID(as_uuid=True), sa.ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_id", UUID(as_uuid=True), sa.ForeignKey("credential_keys.id"), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.UniqueConstraint("credential_id", "key_id"),
    )


def downgrade() -> None:
    op.drop_table("credential_values")
    op.drop_table("credential_keys")
    op.drop_column("tenants", "metadata")
    op.drop_column("device_types", "category")
