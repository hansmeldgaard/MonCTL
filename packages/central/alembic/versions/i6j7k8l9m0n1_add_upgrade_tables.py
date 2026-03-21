"""Add upgrade management tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

revision = "i6j7k8l9m0n1"
down_revision = "h5i6j7k8l9m0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- system_versions ---
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'system_versions'")
    )
    if not result.fetchone():
        op.create_table(
            "system_versions",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("node_hostname", sa.String(200), nullable=False),
            sa.Column("node_role", sa.String(50), nullable=False),
            sa.Column("node_ip", sa.String(50), nullable=False),
            sa.Column("monctl_version", sa.String(50)),
            sa.Column("docker_image_id", sa.String(100)),
            sa.Column("os_version", sa.String(200)),
            sa.Column("kernel_version", sa.String(100)),
            sa.Column("python_version", sa.String(50)),
            sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("node_hostname", name="uq_system_version_hostname"),
        )

    # --- upgrade_packages ---
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'upgrade_packages'")
    )
    if not result.fetchone():
        op.create_table(
            "upgrade_packages",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("version", sa.String(50), nullable=False, unique=True),
            sa.Column("package_type", sa.String(50), nullable=False),
            sa.Column("filename", sa.String(500), nullable=False),
            sa.Column("file_size", sa.Integer, nullable=False),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("changelog", sa.Text),
            sa.Column("metadata", JSONB),
            sa.Column("contains_central", sa.Boolean, server_default=sa.text("false")),
            sa.Column("contains_collector", sa.Boolean, server_default=sa.text("false")),
            sa.Column("uploaded_by", sa.String(200)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    # --- upgrade_jobs ---
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'upgrade_jobs'")
    )
    if not result.fetchone():
        op.create_table(
            "upgrade_jobs",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("upgrade_package_id", PG_UUID(as_uuid=True), sa.ForeignKey("upgrade_packages.id"), nullable=False),
            sa.Column("target_version", sa.String(50), nullable=False),
            sa.Column("scope", sa.String(50), nullable=False),
            sa.Column("strategy", sa.String(50), nullable=False),
            sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("started_by", sa.String(200)),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("error_message", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    # --- upgrade_job_steps ---
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'upgrade_job_steps'")
    )
    if not result.fetchone():
        op.create_table(
            "upgrade_job_steps",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("job_id", PG_UUID(as_uuid=True), sa.ForeignKey("upgrade_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("step_order", sa.Integer, nullable=False),
            sa.Column("node_hostname", sa.String(200), nullable=False),
            sa.Column("node_role", sa.String(50), nullable=False),
            sa.Column("node_ip", sa.String(50), nullable=False),
            sa.Column("action", sa.String(50), nullable=False),
            sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("output_log", sa.Text),
            sa.Column("error_message", sa.Text),
        )

    # --- os_update_packages ---
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'os_update_packages'")
    )
    if not result.fetchone():
        op.create_table(
            "os_update_packages",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("package_name", sa.String(200), nullable=False),
            sa.Column("version", sa.String(100), nullable=False),
            sa.Column("architecture", sa.String(50), nullable=False, server_default=sa.text("'amd64'")),
            sa.Column("filename", sa.String(500), nullable=False),
            sa.Column("file_size", sa.Integer, nullable=False),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("severity", sa.String(50), server_default=sa.text("'normal'")),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("is_downloaded", sa.Boolean, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("package_name", "version", "architecture"),
        )


def downgrade() -> None:
    op.drop_table("os_update_packages")
    op.drop_table("upgrade_job_steps")
    op.drop_table("upgrade_jobs")
    op.drop_table("upgrade_packages")
    op.drop_table("system_versions")
