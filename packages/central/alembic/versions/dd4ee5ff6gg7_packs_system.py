"""Add packs system — pack and pack_versions tables + pack_id FK on entity tables.

Revision ID: dd4ee5ff6gg7
Revises: cc3dd4ee5ff6
Create Date: 2026-03-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "dd4ee5ff6gg7"
down_revision = "cc3dd4ee5ff6"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = :name)"
    ), {"name": name})
    return result.scalar()


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column)"
    ), {"table": table, "column": column})
    return result.scalar()


def upgrade() -> None:
    # 1. Create packs table
    if not _table_exists("packs"):
        op.create_table(
            "packs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("pack_uid", sa.String(128), unique=True, nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("author", sa.String(255), nullable=True),
            sa.Column("current_version", sa.String(32), nullable=False),
            sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
        )

    # 2. Create pack_versions table
    if not _table_exists("pack_versions"):
        op.create_table(
            "pack_versions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("pack_id", UUID(as_uuid=True),
                      sa.ForeignKey("packs.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("version", sa.String(32), nullable=False),
            sa.Column("manifest", JSONB, nullable=False, server_default="{}"),
            sa.Column("changelog", sa.Text, nullable=True),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.UniqueConstraint("pack_id", "version", name="uq_pack_version"),
        )

    # 3. Add pack_id FK to entity tables
    for table in ["apps", "app_alert_definitions", "credential_templates", "snmp_oids",
                   "templates", "device_types", "label_keys", "connectors"]:
        if not _column_exists(table, "pack_id"):
            op.add_column(table, sa.Column("pack_id", UUID(as_uuid=True), nullable=True))
            op.create_foreign_key(
                f"fk_{table}_pack_id", table, "packs",
                ["pack_id"], ["id"], ondelete="SET NULL"
            )
            op.create_index(f"ix_{table}_pack_id", table, ["pack_id"])


def downgrade() -> None:
    for table in ["apps", "app_alert_definitions", "credential_templates", "snmp_oids",
                   "templates", "device_types", "label_keys", "connectors"]:
        op.drop_constraint(f"fk_{table}_pack_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_pack_id", table)
        op.drop_column(table, "pack_id")
    op.drop_table("pack_versions")
    op.drop_table("packs")
