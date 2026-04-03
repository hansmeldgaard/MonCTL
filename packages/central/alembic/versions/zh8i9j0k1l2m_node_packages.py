"""Add node_packages table for OS package inventory.

Revision ID: zh8i9j0k1l2m
Revises: zg7h8i9j0k1l
Create Date: 2026-04-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "zh8i9j0k1l2m"
down_revision = "zg7h8i9j0k1l"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_packages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("node_hostname", sa.String(200), nullable=False),
        sa.Column("node_role", sa.String(50), nullable=False),
        sa.Column("package_name", sa.String(200), nullable=False),
        sa.Column("installed_version", sa.String(100), nullable=False),
        sa.Column("architecture", sa.String(50), nullable=False, server_default="amd64"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("node_hostname", "package_name", name="uq_node_pkg"),
    )
    op.create_index("ix_node_packages_node_hostname", "node_packages", ["node_hostname"])
    op.create_index("ix_node_packages_package_name", "node_packages", ["package_name"])


def downgrade() -> None:
    op.drop_table("node_packages")
