"""Add credential_type to credential_templates.

Revision ID: e2f3g4h5i6j7
Revises: d1e2f3g4h5i6
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa

revision = "e2f3g4h5i6j7"
down_revision = "d1e2f3g4h5i6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credential_templates",
        sa.Column("credential_type", sa.String(64), nullable=True),
    )
    # Backfill: set credential_type = name for existing templates
    op.execute("UPDATE credential_templates SET credential_type = name WHERE credential_type IS NULL")
    op.alter_column("credential_templates", "credential_type", nullable=False, server_default="")


def downgrade() -> None:
    op.drop_column("credential_templates", "credential_type")
