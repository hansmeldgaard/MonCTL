"""Add OS update management tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "j7k8l9m0n1o2"
down_revision = "i6j7k8l9m0n1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- os_available_updates ---
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'os_available_updates'")
    )
    if not result.fetchone():
        op.create_table(
            "os_available_updates",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("node_hostname", sa.String(200), nullable=False, index=True),
            sa.Column("node_role", sa.String(50), nullable=False),
            sa.Column("package_name", sa.String(200), nullable=False),
            sa.Column("current_version", sa.String(100), nullable=False, server_default=sa.text("''")),
            sa.Column("new_version", sa.String(100), nullable=False),
            sa.Column("severity", sa.String(50), nullable=False, server_default=sa.text("'normal'")),
            sa.Column("is_downloaded", sa.Boolean, nullable=False, server_default=sa.text("false")),
            sa.Column("is_installed", sa.Boolean, nullable=False, server_default=sa.text("false")),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("node_hostname", "package_name", name="uq_os_update_node_pkg"),
        )

    # --- os_cached_packages ---
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'os_cached_packages'")
    )
    if not result.fetchone():
        op.create_table(
            "os_cached_packages",
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("package_name", sa.String(200), nullable=False),
            sa.Column("version", sa.String(100), nullable=False),
            sa.Column("architecture", sa.String(50), nullable=False, server_default=sa.text("'amd64'")),
            sa.Column("filename", sa.String(500), nullable=False),
            sa.Column("file_size", sa.Integer, nullable=False),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("filename", name="uq_os_cached_filename"),
        )


def downgrade() -> None:
    op.drop_table("os_cached_packages")
    op.drop_table("os_available_updates")
