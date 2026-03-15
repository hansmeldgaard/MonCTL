"""Add key_type + enum_values to credential_keys, replace is_secret.

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-03-15 20:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "t1u2v3w4x5y6"
down_revision = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add key_type + enum_values columns
    op.add_column("credential_keys",
        sa.Column("key_type", sa.String(16), nullable=False, server_default="plain"))
    op.add_column("credential_keys",
        sa.Column("enum_values", JSONB, nullable=True))

    # 2. Migrate is_secret → key_type
    conn = op.get_bind()
    conn.exec_driver_sql(
        "UPDATE credential_keys SET key_type = 'secret' WHERE is_secret = true")
    conn.exec_driver_sql(
        "UPDATE credential_keys SET key_type = 'plain' WHERE is_secret = false")

    # 3. Drop is_secret
    op.drop_column("credential_keys", "is_secret")

    # 4. Seed enum-type keys + update existing
    conn.exec_driver_sql("""
        INSERT INTO credential_keys (id, name, description, key_type, enum_values) VALUES
        (gen_random_uuid(), 'version', 'SNMP version', 'enum', '["1","2c","3"]'),
        (gen_random_uuid(), 'auth_protocol', 'SNMPv3 auth protocol', 'enum',
            '["MD5","SHA","SHA224","SHA256","SHA384","SHA512"]'),
        (gen_random_uuid(), 'priv_protocol', 'SNMPv3 privacy protocol', 'enum',
            '["DES","3DES","AES","AES192","AES256"]'),
        (gen_random_uuid(), 'security_level', 'SNMPv3 security level', 'enum',
            '["noAuthNoPriv","authNoPriv","authPriv"]')
        ON CONFLICT (name) DO UPDATE SET
            key_type = EXCLUDED.key_type,
            enum_values = EXCLUDED.enum_values
    """)

    # 5. Seed secret-keys for SNMPv3 (if not already present)
    conn.exec_driver_sql("""
        INSERT INTO credential_keys (id, name, description, key_type) VALUES
        (gen_random_uuid(), 'auth_key', 'SNMPv3 authentication key', 'secret'),
        (gen_random_uuid(), 'priv_key', 'SNMPv3 privacy key', 'secret')
        ON CONFLICT (name) DO NOTHING
    """)

    # 6. Seed base credential keys (plain + secret)
    conn.exec_driver_sql("""
        INSERT INTO credential_keys (id, name, description, key_type) VALUES
        (gen_random_uuid(), 'username', 'Login username', 'plain'),
        (gen_random_uuid(), 'password', 'Login password', 'secret'),
        (gen_random_uuid(), 'community', 'SNMP community string', 'secret'),
        (gen_random_uuid(), 'port', 'Connection port', 'plain'),
        (gen_random_uuid(), 'api_key', 'API key or token', 'secret'),
        (gen_random_uuid(), 'private_key', 'SSH private key', 'secret'),
        (gen_random_uuid(), 'token', 'Authentication token', 'secret'),
        (gen_random_uuid(), 'auth_password', 'SNMPv3 auth passphrase', 'secret'),
        (gen_random_uuid(), 'priv_password', 'SNMPv3 privacy passphrase', 'secret')
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    op.add_column("credential_keys",
        sa.Column("is_secret", sa.Boolean, nullable=False, server_default=sa.text("false")))

    conn = op.get_bind()
    conn.exec_driver_sql(
        "UPDATE credential_keys SET is_secret = true WHERE key_type = 'secret'")

    op.drop_column("credential_keys", "enum_values")
    op.drop_column("credential_keys", "key_type")
