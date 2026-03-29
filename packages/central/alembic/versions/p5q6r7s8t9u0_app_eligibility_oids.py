"""Add vendor_oid_prefix to apps, eligibility_oids to app_versions, auto_assign_packs to device_types."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "p5q6r7s8t9u0"
down_revision = "o4p5q6r7s8t9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("apps", sa.Column("vendor_oid_prefix", sa.String(128), nullable=True))
    op.add_column("app_versions", sa.Column("eligibility_oids", JSONB, nullable=True))
    op.add_column("device_types", sa.Column("auto_assign_packs", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("device_types", "auto_assign_packs")
    op.drop_column("app_versions", "eligibility_oids")
    op.drop_column("apps", "vendor_oid_prefix")
