"""Add credential_templates table and link to credentials.

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-03-13 21:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "r9s0t1u2v3w4"
down_revision = "q8r9s0t1u2v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. New credential keys for SNMPv3
    conn.exec_driver_sql("""
        INSERT INTO credential_keys (id, name, description, is_secret) VALUES
        (gen_random_uuid(), 'auth_protocol', 'SNMPv3 auth protocol (MD5/SHA/SHA256)', false),
        (gen_random_uuid(), 'auth_key', 'SNMPv3 authentication key', true),
        (gen_random_uuid(), 'priv_protocol', 'SNMPv3 privacy protocol (DES/AES/AES256)', false),
        (gen_random_uuid(), 'priv_key', 'SNMPv3 privacy key', true),
        (gen_random_uuid(), 'version', 'Protocol version (e.g. 2c, 3)', false)
        ON CONFLICT (name) DO NOTHING
    """)

    # 2. Create credential_templates table (idempotent — handles partial prior run)
    # Drop and recreate if table exists without proper defaults (from create_all)
    conn.exec_driver_sql("DROP TABLE IF EXISTS credential_templates CASCADE")
    conn.exec_driver_sql("""
        CREATE TABLE credential_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(64) UNIQUE NOT NULL,
            description TEXT,
            fields JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # 3. Seed built-in templates
    conn.exec_driver_sql("""
        INSERT INTO credential_templates (name, description, fields) VALUES
        ('snmpv2c', 'SNMP v2c community-based', '[{"key_name":"community","required":true,"default_value":null,"display_order":1},{"key_name":"version","required":true,"default_value":"2c","display_order":2},{"key_name":"port","required":false,"default_value":"161","display_order":3}]'),
        ('snmpv3', 'SNMP v3 USM authentication', '[{"key_name":"username","required":true,"default_value":null,"display_order":1},{"key_name":"auth_protocol","required":true,"default_value":"SHA","display_order":2},{"key_name":"auth_key","required":true,"default_value":null,"display_order":3},{"key_name":"priv_protocol","required":false,"default_value":"AES","display_order":4},{"key_name":"priv_key","required":false,"default_value":null,"display_order":5},{"key_name":"port","required":false,"default_value":"161","display_order":6}]'),
        ('ssh_password', 'SSH with username/password', '[{"key_name":"username","required":true,"default_value":null,"display_order":1},{"key_name":"password","required":true,"default_value":null,"display_order":2},{"key_name":"port","required":false,"default_value":"22","display_order":3}]'),
        ('ssh_key', 'SSH with private key', '[{"key_name":"username","required":true,"default_value":null,"display_order":1},{"key_name":"private_key","required":true,"default_value":null,"display_order":2},{"key_name":"port","required":false,"default_value":"22","display_order":3}]'),
        ('api_token', 'API key/token authentication', '[{"key_name":"api_key","required":true,"default_value":null,"display_order":1}]'),
        ('api_basic_auth', 'API with basic auth', '[{"key_name":"username","required":true,"default_value":null,"display_order":1},{"key_name":"password","required":true,"default_value":null,"display_order":2}]')
        ON CONFLICT (name) DO NOTHING
    """)

    # 4. Add template_id FK to credentials (idempotent)
    conn.exec_driver_sql("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'credentials' AND column_name = 'template_id'
            ) THEN
                ALTER TABLE credentials ADD COLUMN template_id UUID;
                ALTER TABLE credentials ADD CONSTRAINT fk_credentials_template_id
                    FOREIGN KEY (template_id) REFERENCES credential_templates(id) ON DELETE SET NULL;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_constraint("fk_credentials_template_id", "credentials", type_="foreignkey")
    op.drop_column("credentials", "template_id")
    op.drop_table("credential_templates")
