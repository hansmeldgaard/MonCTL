"""Add token_version to users for server-side session revocation.

Used by F-CEN-006: every issued JWT embeds the user's current
`token_version`; on decode we reject any token whose version is lower
than the user's current value. Bumping the column invalidates every
outstanding access + refresh token for that user in one shot — we do
this on logout and on role/permission changes.

Revision ID: ac4d5e6f7g8h
Revises: ab3c4d5e6f7g
"""

from alembic import op
import sqlalchemy as sa


revision = "ac4d5e6f7g8h"
down_revision = "ab3c4d5e6f7g"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment=(
                "Monotonic counter embedded in access + refresh JWTs. A token "
                "is only accepted if its tv claim equals the current user "
                "row value. Bumped on logout and role/permission mutation "
                "to force re-auth fleet-wide."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
