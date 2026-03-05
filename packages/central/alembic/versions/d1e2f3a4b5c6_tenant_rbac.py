"""Add user_tenants table and all_tenants flag for tenant RBAC.

Revision ID: d1e2f3a4b5c6
Revises: c4d5e6f7a8b9
Create Date: 2026-03-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d1e2f3a4b5c6"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add all_tenants flag to users (False = restricted to assigned tenants)
    op.add_column(
        "users",
        sa.Column("all_tenants", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Create user_tenants many-to-many join table
    op.create_table(
        "user_tenants",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    op.create_index("idx_user_tenants_user", "user_tenants", ["user_id"])
    op.create_index("idx_user_tenants_tenant", "user_tenants", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_user_tenants_tenant", table_name="user_tenants")
    op.drop_index("idx_user_tenants_user", table_name="user_tenants")
    op.drop_table("user_tenants")
    op.drop_column("users", "all_tenants")
