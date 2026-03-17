"""Add Python module registry tables.

Revision ID: b2c3d4e5f6g7
Revises: z7a8b9c0d1e2
Create Date: 2026-03-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "b2c3d4e5f6g7"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "python_modules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("homepage_url", sa.String(500), nullable=True),
        sa.Column("is_approved", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
    )

    op.create_table(
        "python_module_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "module_id", UUID(as_uuid=True),
            sa.ForeignKey("python_modules.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("dependencies", JSONB, nullable=False, server_default="[]"),
        sa.Column("python_requires", sa.String(100), nullable=True),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.UniqueConstraint("module_id", "version"),
    )

    op.create_table(
        "wheel_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "module_version_id", UUID(as_uuid=True),
            sa.ForeignKey("python_module_versions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("python_tag", sa.String(50), nullable=False),
        sa.Column("abi_tag", sa.String(50), nullable=False),
        sa.Column("platform_tag", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.UniqueConstraint("filename"),
    )


def downgrade() -> None:
    op.drop_table("wheel_files")
    op.drop_table("python_module_versions")
    op.drop_table("python_modules")
