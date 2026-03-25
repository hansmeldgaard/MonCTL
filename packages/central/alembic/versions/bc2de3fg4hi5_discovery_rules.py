"""Add discovery_rules table and icon/auto_assign_packs to device_types.

Revision ID: bc2de3fg4hi5
Revises: ab1cd2ef3gh4
Create Date: 2026-03-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "bc2de3fg4hi5"
down_revision = "ab1cd2ef3gh4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add icon and auto_assign_packs to device_types
    op.add_column(
        "device_types",
        sa.Column("icon", sa.String(64), nullable=True),
    )
    op.add_column(
        "device_types",
        sa.Column("auto_assign_packs", JSONB, nullable=False, server_default="[]"),
    )

    # Set default icons for seeded device types
    for name, icon in [
        ("host", "server"),
        ("virtual-machine", "server"),
        ("container", "container"),
        ("network", "router"),
        ("storage", "hard-drive"),
        ("printer", "printer"),
        ("iot", "cpu"),
        ("api", "cloud"),
        ("service", "globe"),
        ("database", "database"),
    ]:
        op.execute(
            sa.text("UPDATE device_types SET icon = :icon WHERE name = :name").bindparams(
                icon=icon, name=name
            )
        )

    # 2. Create discovery_rules table
    op.create_table(
        "discovery_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sys_object_id_pattern", sa.String(256), nullable=False),
        sa.Column(
            "device_type_id", UUID(as_uuid=True),
            sa.ForeignKey("device_types.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("vendor", sa.String(128), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("os_family", sa.String(128), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "pack_id", UUID(as_uuid=True),
            sa.ForeignKey("packs.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("sys_object_id_pattern", name="uq_discovery_rules_pattern"),
        sa.Index("ix_discovery_rules_pack_id", "pack_id"),
    )

    # 3. Seed common discovery rules for well-known vendors
    op.execute(sa.text("""
        INSERT INTO discovery_rules (name, sys_object_id_pattern, device_type_id, vendor, priority)
        SELECT 'Cisco Devices', '1.3.6.1.4.1.9', dt.id, 'Cisco', 0
        FROM device_types dt WHERE dt.name = 'network'
        UNION ALL
        SELECT 'Juniper Devices', '1.3.6.1.4.1.2636', dt.id, 'Juniper', 0
        FROM device_types dt WHERE dt.name = 'network'
        UNION ALL
        SELECT 'Arista Devices', '1.3.6.1.4.1.30065', dt.id, 'Arista', 0
        FROM device_types dt WHERE dt.name = 'network'
        UNION ALL
        SELECT 'HP/HPE Devices', '1.3.6.1.4.1.11', dt.id, 'HP', 0
        FROM device_types dt WHERE dt.name = 'network'
        UNION ALL
        SELECT 'Dell Devices', '1.3.6.1.4.1.674', dt.id, 'Dell', 0
        FROM device_types dt WHERE dt.name = 'host'
        UNION ALL
        SELECT 'Linux (net-snmp)', '1.3.6.1.4.1.8072', dt.id, 'Linux', 0
        FROM device_types dt WHERE dt.name = 'host'
        UNION ALL
        SELECT 'Ubiquiti Devices', '1.3.6.1.4.1.41112', dt.id, 'Ubiquiti', 0
        FROM device_types dt WHERE dt.name = 'network'
        UNION ALL
        SELECT 'Palo Alto Devices', '1.3.6.1.4.1.25461', dt.id, 'Palo Alto', 0
        FROM device_types dt WHERE dt.name = 'network'
        UNION ALL
        SELECT 'Fortinet Devices', '1.3.6.1.4.1.12356', dt.id, 'Fortinet', 0
        FROM device_types dt WHERE dt.name = 'network'
        UNION ALL
        SELECT 'MikroTik Devices', '1.3.6.1.4.1.14988', dt.id, 'MikroTik', 0
        FROM device_types dt WHERE dt.name = 'network'
    """))


def downgrade() -> None:
    op.drop_table("discovery_rules")
    op.drop_column("device_types", "auto_assign_packs")
    op.drop_column("device_types", "icon")
