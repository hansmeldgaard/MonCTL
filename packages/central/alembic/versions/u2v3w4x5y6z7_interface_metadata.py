"""Add interface_metadata table for stable interface identity.

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-03-15 22:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "u2v3w4x5y6z7"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table may already exist via Base.metadata.create_all in entrypoint
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    if "interface_metadata" not in inspector.get_table_names():
        op.create_table(
            "interface_metadata",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("if_name", sa.String(255), nullable=False),
            sa.Column("current_if_index", sa.Integer, nullable=False),
            sa.Column("if_descr", sa.String(255), nullable=False, server_default=""),
            sa.Column("if_alias", sa.Text, nullable=False, server_default=""),
            sa.Column("if_speed_mbps", sa.Integer, nullable=False, server_default="0"),
            sa.Column("polling_enabled", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("alerting_enabled", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
            sa.UniqueConstraint("device_id", "if_name", name="uq_device_if_name"),
        )


def downgrade() -> None:
    op.drop_table("interface_metadata")
