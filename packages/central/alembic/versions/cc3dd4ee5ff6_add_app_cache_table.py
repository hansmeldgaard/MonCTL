"""Add app_cache table for shared collector cache.

Revision ID: cc3dd4ee5ff6
Revises: bb2cc3dd4ee5
Create Date: 2026-03-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "cc3dd4ee5ff6"
down_revision = "bb2cc3dd4ee5"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = :name)"
    ), {"name": name})
    return result.scalar()


def upgrade() -> None:
    if _table_exists("app_cache"):
        return
    op.create_table(
        "app_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("collector_group_id", UUID(as_uuid=True),
                  sa.ForeignKey("collector_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_id", UUID(as_uuid=True),
                  sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", UUID(as_uuid=True),
                  sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cache_key", sa.String(255), nullable=False),
        sa.Column("cache_value", JSONB, nullable=False),
        sa.Column("ttl_seconds", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "collector_group_id", "app_id", "device_id", "cache_key",
            name="uq_app_cache_entry",
        ),
    )
    op.create_index(
        "ix_app_cache_group_updated", "app_cache",
        ["collector_group_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("app_cache")
