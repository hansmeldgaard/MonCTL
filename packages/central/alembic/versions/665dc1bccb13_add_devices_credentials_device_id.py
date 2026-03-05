"""add devices, credentials, and device_id on app_assignments

Revision ID: 665dc1bccb13
Revises:
Create Date: 2026-03-02

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '665dc1bccb13'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create devices table
    op.create_table(
        'devices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('address', sa.String(512), nullable=False),
        sa.Column('device_type', sa.String(64), nullable=False, server_default='host'),
        sa.Column('collector_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('collectors.id'), nullable=True),
        sa.Column('labels', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('metadata', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_devices_collector', 'devices', ['collector_id'])
    op.create_index('idx_devices_type', 'devices', ['device_type'])

    # Create credentials table
    op.create_table(
        'credentials',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('credential_type', sa.String(64), nullable=False),
        sa.Column('secret_data', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # Add device_id to app_assignments
    op.add_column(
        'app_assignments',
        sa.Column('device_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('devices.id'), nullable=True),
    )
    op.create_index('idx_assignments_device', 'app_assignments', ['device_id'])


def downgrade() -> None:
    op.drop_index('idx_assignments_device', 'app_assignments')
    op.drop_column('app_assignments', 'device_id')
    op.drop_table('credentials')
    op.drop_index('idx_devices_type', 'devices')
    op.drop_index('idx_devices_collector', 'devices')
    op.drop_table('devices')
