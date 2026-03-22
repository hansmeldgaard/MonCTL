"""Add idle_timeout_minutes to users table.

Revision ID: k8l9m0n1o2p3
Revises: j7k8l9m0n1o2
"""

from alembic import op
import sqlalchemy as sa

revision = "k8l9m0n1o2p3"
down_revision = "j7k8l9m0n1o2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "idle_timeout_minutes",
            sa.Integer,
            nullable=True,
            comment="Per-user idle timeout override. NULL = use system default.",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "idle_timeout_minutes")
