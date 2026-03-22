"""Add retention_overrides JSONB column to devices."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "h5i6j7k8l9m0"
down_revision = "g4h5i6j7k8l9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = 'devices' AND column_name = 'retention_overrides'")
    )
    if result.fetchone():
        return
    op.add_column(
        "devices",
        sa.Column("retention_overrides", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("devices", "retention_overrides")
