"""Add credential_types table for managed credential type list.

Revision ID: b9c0d1e2f3g4
Revises: a8b9c0d1e2f3
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
import uuid

revision = "b9c0d1e2f3g4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credential_types",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
    )
    # Seed from existing distinct credential_type values
    op.execute("""
        INSERT INTO credential_types (id, name)
        SELECT gen_random_uuid(), credential_type
        FROM (SELECT DISTINCT credential_type FROM credentials) sub
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("credential_types")
