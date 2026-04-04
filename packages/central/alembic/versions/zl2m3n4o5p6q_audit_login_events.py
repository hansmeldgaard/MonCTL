"""Add audit_login_events table for authentication audit log.

Revision ID: zl2m3n4o5p6q
Revises: zk1l2m3n4o5p
Create Date: 2026-04-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "zl2m3n4o5p6q"
down_revision = "zk1l2m3n4o5p"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_login_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("username", sa.String(255), nullable=False, server_default=""),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("auth_type", sa.String(20), nullable=False, server_default="cookie"),
        sa.Column("failure_reason", sa.String(100), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_audit_login_events_timestamp", "audit_login_events", ["timestamp"])
    op.create_index("ix_audit_login_events_user_ts", "audit_login_events", ["user_id", "timestamp"])
    op.create_index("ix_audit_login_events_type_ts", "audit_login_events", ["event_type", "timestamp"])
    op.create_index("ix_audit_login_events_ip_ts", "audit_login_events", ["ip_address", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_audit_login_events_ip_ts", table_name="audit_login_events")
    op.drop_index("ix_audit_login_events_type_ts", table_name="audit_login_events")
    op.drop_index("ix_audit_login_events_user_ts", table_name="audit_login_events")
    op.drop_index("ix_audit_login_events_timestamp", table_name="audit_login_events")
    op.drop_table("audit_login_events")
