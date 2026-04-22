"""Add sidecar_job_id to os_install_job_steps for resume-across-leader-death.

When a central step kicks off `POST /os/install` the sidecar returns a
job_id that identifies the systemd-run'd apt unit. The central caller
polls `/os/install/status?job_id=...` until terminal.

Previously the job_id lived only in the poller's async task. If the
leader central died mid-poll (e.g. its own dockerd was being upgraded),
the poller died, the DB step stayed `status='running'` forever, and
no other central could take over because it didn't know the job_id.

Persisting job_id on the step lets any leader — the same one after a
restart, or a newly elected one — resume polling.

Revision ID: ad5e6f7g8h9i
Revises: ac4d5e6f7g8h
"""

import sqlalchemy as sa
from alembic import op

revision = "ad5e6f7g8h9i"
down_revision = "ac4d5e6f7g8h"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "os_install_job_steps",
        sa.Column("sidecar_job_id", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("os_install_job_steps", "sidecar_job_id")
