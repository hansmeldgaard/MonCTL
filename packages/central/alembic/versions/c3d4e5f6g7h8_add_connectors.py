"""Add connectors, connector_versions, and assignment_connector_bindings tables.

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-03-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "c3d4e5f6g7h8"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connectors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("connector_type", sa.String(32), nullable=False),
        sa.Column("requirements", JSONB, nullable=True),
        sa.Column("is_builtin", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "connector_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connector_id", UUID(as_uuid=True),
            sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("source_code", sa.Text, nullable=False),
        sa.Column("requirements", JSONB, nullable=True),
        sa.Column("entry_class", sa.String(64), nullable=False, server_default="Connector"),
        sa.Column("is_latest", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("connector_id", "version"),
    )

    op.create_table(
        "assignment_connector_bindings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assignment_id", UUID(as_uuid=True),
            sa.ForeignKey("app_assignments.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "connector_id", UUID(as_uuid=True),
            sa.ForeignKey("connectors.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "connector_version_id", UUID(as_uuid=True),
            sa.ForeignKey("connector_versions.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "credential_id", UUID(as_uuid=True),
            sa.ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("alias", sa.String(64), nullable=False),
        sa.Column("use_latest", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("assignment_id", "alias"),
    )


def downgrade() -> None:
    op.drop_table("assignment_connector_bindings")
    op.drop_table("connector_versions")
    op.drop_table("connectors")
