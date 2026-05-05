"""Per-user saved views (devices-beta + future list pages).

Generalized `page` text column from day 1 so future list pages
(apps, assignments, alerts, etc.) can adopt the same table.

Revision ID: ag8h9i0j1k2l
Revises: af7g8h9i0j1k
Create Date: 2026-05-05 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "ag8h9i0j1k2l"
down_revision = "af7g8h9i0j1k"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saved_views",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("filter_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_saved_views_user_page_position",
        "saved_views",
        ["user_id", "page", "position"],
    )
    # RBAC seed: grant all four saved_view actions to the admin role.
    # Admins bypass require_permission anyway, but explicit rows make the
    # capability discoverable in the role-editor UI and let custom roles
    # be granted it via the existing permission editor.
    op.execute(
        "INSERT INTO role_permissions (id, role_id, resource, action) "
        "SELECT gen_random_uuid(), r.id, 'saved_view', a "
        "FROM roles r "
        "CROSS JOIN (VALUES ('view'), ('create'), ('edit'), ('delete')) AS t(a) "
        "WHERE r.name = 'admin' "
        "ON CONFLICT (role_id, resource, action) DO NOTHING"
    )


def downgrade():
    op.execute("DELETE FROM role_permissions WHERE resource = 'saved_view'")
    op.drop_index("ix_saved_views_user_page_position", table_name="saved_views")
    op.drop_table("saved_views")
