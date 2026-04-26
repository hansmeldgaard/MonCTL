"""Drop analytics_dashboards + analytics_widgets, retire `dashboard` RBAC resource.

Superset replaces the in-app SQL Explorer + Custom Dashboards.

Revision ID: af7g8h9i0j1k
Revises: ae6f7g8h9i0j
Create Date: 2026-04-26 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "af7g8h9i0j1k"
down_revision = "ae6f7g8h9i0j"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM role_permissions WHERE resource = 'dashboard'")
    op.execute(
        "UPDATE users SET default_page = '/devices' "
        "WHERE default_page IN ('/analytics/explorer', '/analytics/dashboards')"
    )
    op.drop_index("ix_analytics_widgets_dashboard_id", table_name="analytics_widgets")
    op.drop_table("analytics_widgets")
    op.drop_table("analytics_dashboards")


def downgrade():
    op.create_table(
        "analytics_dashboards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("variables", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "analytics_widgets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "dashboard_id",
            UUID(as_uuid=True),
            sa.ForeignKey("analytics_dashboards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("layout", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_analytics_widgets_dashboard_id", "analytics_widgets", ["dashboard_id"])
