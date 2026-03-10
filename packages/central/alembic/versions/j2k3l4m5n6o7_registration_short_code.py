"""Add short_code to registration_tokens.

Revision ID: j2k3l4m5n6o7
Revises: i1j2k3l4m5n6
Create Date: 2026-03-08
"""

from alembic import op
import sqlalchemy as sa

revision = "j2k3l4m5n6o7"
down_revision = "i1j2k3l4m5n6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("registration_tokens", sa.Column("short_code", sa.String(8), nullable=True))
    op.create_index("ix_registration_tokens_short_code", "registration_tokens", ["short_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_registration_tokens_short_code", table_name="registration_tokens")
    op.drop_column("registration_tokens", "short_code")
