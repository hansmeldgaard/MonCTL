"""Add data retention overrides table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "g4h5i6j7k8l9"
down_revision = "f3g4h5i6j7k8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'data_retention_overrides'")
    )
    if result.fetchone():
        return

    op.create_table(
        "data_retention_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("app_id", UUID(as_uuid=True), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data_type", sa.String(30), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("device_id", "app_id", "data_type", name="uq_retention_device_app_type"),
    )


def downgrade() -> None:
    op.drop_table("data_retention_overrides")
