"""Add security_level + auth_password/priv_password credential keys, update snmpv3 template.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-03-13 22:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "s0t1u2v3w4x5"
down_revision = "r9s0t1u2v3w4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add new credential keys for SNMPv3 (auth_password, priv_password, security_level)
    conn.exec_driver_sql("""
        INSERT INTO credential_keys (id, name, description, is_secret) VALUES
        (gen_random_uuid(), 'auth_password', 'SNMPv3 auth passphrase', true),
        (gen_random_uuid(), 'priv_password', 'SNMPv3 privacy passphrase', true),
        (gen_random_uuid(), 'security_level', 'SNMPv3 security level (noAuthNoPriv, authNoPriv, authPriv)', false)
        ON CONFLICT (name) DO NOTHING
    """)

    # 2. Update snmpv3 template with security_level and auth_password/priv_password fields
    conn.exec_driver_sql("""
        UPDATE credential_templates
        SET fields = '[
          {"key_name":"version","required":true,"default_value":"3","display_order":1},
          {"key_name":"security_level","required":true,"default_value":"authPriv","display_order":2},
          {"key_name":"username","required":true,"default_value":null,"display_order":3},
          {"key_name":"auth_protocol","required":false,"default_value":"SHA","display_order":4},
          {"key_name":"auth_password","required":false,"default_value":null,"display_order":5},
          {"key_name":"priv_protocol","required":false,"default_value":"AES","display_order":6},
          {"key_name":"priv_password","required":false,"default_value":null,"display_order":7},
          {"key_name":"port","required":false,"default_value":"161","display_order":8}
        ]'::jsonb,
        updated_at = now()
        WHERE name = 'snmpv3'
    """)

    # 3. Also add version field to snmpv2c template
    conn.exec_driver_sql("""
        UPDATE credential_templates
        SET fields = '[
          {"key_name":"community","required":true,"default_value":null,"display_order":1},
          {"key_name":"version","required":true,"default_value":"2c","display_order":2},
          {"key_name":"port","required":false,"default_value":"161","display_order":3}
        ]'::jsonb,
        updated_at = now()
        WHERE name = 'snmpv2c'
    """)


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("""
        UPDATE credential_templates
        SET fields = '[
          {"key_name":"username","required":true,"default_value":null,"display_order":1},
          {"key_name":"auth_protocol","required":true,"default_value":"SHA","display_order":2},
          {"key_name":"auth_key","required":true,"default_value":null,"display_order":3},
          {"key_name":"priv_protocol","required":false,"default_value":"AES","display_order":4},
          {"key_name":"priv_key","required":false,"default_value":null,"display_order":5},
          {"key_name":"port","required":false,"default_value":"161","display_order":6}
        ]'::jsonb
        WHERE name = 'snmpv3'
    """)
