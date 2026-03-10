"""Add default_credential_id to devices, create system_settings, tls_certificates, templates tables.

Revision ID: l4m5n6o7p8q9
Revises: k3l4m5n6o7p8
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "l4m5n6o7p8q9"
down_revision = "k3l4m5n6o7p8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add default_credential_id to devices
    op.add_column(
        "devices",
        sa.Column("default_credential_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_devices_default_credential_id",
        "devices",
        "credentials",
        ["default_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Create system_settings table
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default="now()"),
    )

    # Create tls_certificates table
    op.create_table(
        "tls_certificates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cert_pem", sa.Text, nullable=False),
        sa.Column("key_pem_encrypted", sa.Text, nullable=False),
        sa.Column("is_self_signed", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("subject_cn", sa.String(255), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
    )

    # Create templates table
    op.create_table(
        "templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
    )


def downgrade() -> None:
    op.drop_table("templates")
    op.drop_table("tls_certificates")
    op.drop_table("system_settings")
    op.drop_constraint("fk_devices_default_credential_id", "devices", type_="foreignkey")
    op.drop_column("devices", "default_credential_id")
