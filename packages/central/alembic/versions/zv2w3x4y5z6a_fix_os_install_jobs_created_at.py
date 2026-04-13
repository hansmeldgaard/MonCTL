"""Fix os_install_jobs.created_at default and backfill stuck rows.

The original column was added with `server_default=sa.text("now()")`, but the
deployed schema ended up with a literal frozen timestamp as the column DEFAULT
(every new row got the same value as old rows, making the OS Install Jobs list
effectively unsorted). Reset the default to `now()` and backfill any rows still
holding the frozen value to use `started_at` so the list sorts by real time.

Revision ID: zv2w3x4y5z6a
Revises: zu1v2w3x4y5z
Create Date: 2026-04-13
"""

from __future__ import annotations

from alembic import op


revision = "zv2w3x4y5z6a"
down_revision = "zu1v2w3x4y5z"
branch_labels = None
depends_on = None


FROZEN_DEFAULT = "2026-04-02 21:44:16.534462+00"


def upgrade() -> None:
    # Reset the column default to a live now() expression
    op.execute(
        "ALTER TABLE os_install_jobs "
        "ALTER COLUMN created_at SET DEFAULT now()"
    )
    # Backfill rows whose created_at is still the frozen value: prefer
    # started_at, then completed_at; fall back to leaving the row alone.
    op.execute(
        "UPDATE os_install_jobs "
        "SET created_at = COALESCE(started_at, completed_at, created_at) "
        f"WHERE created_at = TIMESTAMPTZ '{FROZEN_DEFAULT}'"
    )


def downgrade() -> None:
    # No-op: we don't restore a frozen literal default.
    pass
