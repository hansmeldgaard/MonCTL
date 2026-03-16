"""Add label_keys registry table.

Revision ID: w4x5y6z7a8b9
Revises: v3w4x5y6z7a8
Create Date: 2026-03-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "w4x5y6z7a8b9"
down_revision = "v3w4x5y6z7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "label_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("key", sa.String(64), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("show_description", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("predefined_values", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Seed common label keys
    op.execute(sa.text("""
        INSERT INTO label_keys (key, description, show_description, predefined_values) VALUES
        ('site', 'Lokation', true, '["aarhus", "copenhagen"]'),
        ('env', 'Miljø', true, '["production", "staging", "development", "test"]'),
        ('role', 'Rolle', true, '["web", "db", "cache", "proxy", "monitoring"]'),
        ('owner', 'Ansvarlig', true, '[]'),
        ('criticality', 'Kritikalitet', true, '["critical", "high", "medium", "low"]')
    """))

    # Backfill: register all existing label keys from devices
    op.execute(sa.text("""
        INSERT INTO label_keys (key)
        SELECT DISTINCT jsonb_object_keys(labels) AS k
        FROM devices
        WHERE labels != '{}'::jsonb
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_table("label_keys")
