"""Add os_install_jobs and os_install_job_steps tables.

Revision ID: zg7h8i9j0k1l
Revises: zf6g7h8i9j0k
Create Date: 2026-04-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "zg7h8i9j0k1l"
down_revision = "zf6g7h8i9j0k"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "os_install_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("package_names", JSONB, nullable=False),
        sa.Column("scope", sa.String(50), nullable=False),
        sa.Column("target_nodes", JSONB, nullable=True),
        sa.Column("strategy", sa.String(50), nullable=False, server_default="rolling"),
        sa.Column("restart_policy", sa.String(50), nullable=False, server_default="none"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("started_by", sa.String(200), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "os_install_job_steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("os_install_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("node_hostname", sa.String(200), nullable=False),
        sa.Column("node_role", sa.String(50), nullable=False),
        sa.Column("node_ip", sa.String(50), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("is_test_node", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_log", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_os_install_job_steps_job_id", "os_install_job_steps", ["job_id"])


def downgrade() -> None:
    op.drop_table("os_install_job_steps")
    op.drop_table("os_install_jobs")
