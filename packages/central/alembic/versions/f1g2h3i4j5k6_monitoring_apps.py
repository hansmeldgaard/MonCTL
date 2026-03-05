"""Add monitoring app infrastructure: role on assignments, snmp_oids table, clear legacy data.

Revision ID: f1g2h3i4j5k6
Revises: e1f2a3b4c5d6
Create Date: 2026-03-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f1g2h3i4j5k6"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add role column to app_assignments
    op.add_column(
        "app_assignments",
        sa.Column("role", sa.String(20), nullable=True),
    )

    # 2. Create snmp_oids catalog table
    op.create_table(
        "snmp_oids",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("oid", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 3. Seed common SNMP OIDs
    op.execute("""
        INSERT INTO snmp_oids (name, oid, description) VALUES
          ('System Uptime',          '1.3.6.1.2.1.1.3.0',     'sysUpTime — time since last reboot'),
          ('System Description',     '1.3.6.1.2.1.1.1.0',     'sysDescr — hardware and OS description'),
          ('Interface 1 Status',     '1.3.6.1.2.1.2.2.1.8.1', 'ifOperStatus for interface index 1 (1=up, 2=down)'),
          ('Interface 1 In Octets',  '1.3.6.1.2.1.2.2.1.10.1','ifInOctets — inbound byte counter for interface 1'),
          ('Interface 1 Out Octets', '1.3.6.1.2.1.2.2.1.16.1','ifOutOctets — outbound byte counter for interface 1')
    """)

    # 4. Clear all existing availability/latency data (fresh start with new app system)
    op.execute("TRUNCATE TABLE check_results")
    op.execute("DELETE FROM app_assignments")


def downgrade() -> None:
    op.drop_column("app_assignments", "role")
    op.drop_table("snmp_oids")
