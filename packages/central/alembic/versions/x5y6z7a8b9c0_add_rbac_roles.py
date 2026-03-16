"""Add RBAC roles and permissions tables, add role_id to users.

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
Create Date: 2026-03-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "x5y6z7a8b9c0"
down_revision = "w4x5y6z7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "role_permissions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource", sa.String(50), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.UniqueConstraint("role_id", "resource", "action", name="uq_role_resource_action"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])

    op.add_column(
        "users",
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_users_role_id", "users", ["role_id"])

    # Seed Viewer role
    op.execute("""
        INSERT INTO roles (id, name, description, is_system)
        VALUES (gen_random_uuid(), 'Viewer', 'Read-only access to all resources', true)
    """)
    op.execute("""
        INSERT INTO role_permissions (id, role_id, resource, action)
        SELECT gen_random_uuid(), r.id, res.resource, 'view'
        FROM roles r
        CROSS JOIN (VALUES
            ('device'), ('app'), ('assignment'), ('credential'),
            ('alert'), ('collector'), ('tenant'), ('user'),
            ('template'), ('settings'), ('result')
        ) AS res(resource)
        WHERE r.name = 'Viewer'
    """)

    # Seed Operator role
    op.execute("""
        INSERT INTO roles (id, name, description, is_system)
        VALUES (gen_random_uuid(), 'Operator', 'Can view and edit devices, apps, and assignments', true)
    """)
    op.execute("""
        INSERT INTO role_permissions (id, role_id, resource, action)
        SELECT gen_random_uuid(), r.id, perm.resource, perm.action
        FROM roles r
        CROSS JOIN (VALUES
            ('device', 'view'), ('device', 'create'), ('device', 'edit'),
            ('app', 'view'), ('app', 'create'), ('app', 'edit'),
            ('assignment', 'view'), ('assignment', 'create'), ('assignment', 'edit'),
            ('credential', 'view'),
            ('alert', 'view'), ('alert', 'create'), ('alert', 'edit'),
            ('collector', 'view'),
            ('template', 'view'), ('template', 'create'), ('template', 'edit'),
            ('result', 'view')
        ) AS perm(resource, action)
        WHERE r.name = 'Operator'
    """)

    # Migrate existing "viewer" users to Viewer role
    op.execute("""
        UPDATE users
        SET role_id = (SELECT id FROM roles WHERE name = 'Viewer'),
            role = 'user'
        WHERE role = 'viewer'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE users SET role = 'viewer', role_id = NULL
        WHERE role_id IN (SELECT id FROM roles WHERE name = 'Viewer')
    """)
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_column("users", "role_id")
    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_table("roles")
