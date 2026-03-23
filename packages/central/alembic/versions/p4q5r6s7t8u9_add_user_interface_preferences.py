"""Add interface tab display preferences to users table.

Revision ID: p4q5r6s7t8u9
Revises: o3p4q5r6s7t8
"""

from alembic import op
import sqlalchemy as sa

revision = "p4q5r6s7t8u9"
down_revision = "o3p4q5r6s7t8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "iface_status_filter",
        sa.String(16), nullable=False, server_default="all",
        comment="Default interface status filter: all | up | down | unmonitored",
    ))
    op.add_column("users", sa.Column(
        "iface_traffic_unit",
        sa.String(8), nullable=False, server_default="auto",
        comment="Default traffic unit: auto | bps | kbps | mbps | pct",
    ))
    op.add_column("users", sa.Column(
        "iface_chart_metric",
        sa.String(16), nullable=False, server_default="traffic",
        comment="Default chart metric: traffic | errors | discards",
    ))
    op.add_column("users", sa.Column(
        "iface_time_range",
        sa.String(16), nullable=False, server_default="24h",
        comment="Default interface time range: 1h | 6h | 24h | 7d | 30d",
    ))


def downgrade() -> None:
    op.drop_column("users", "iface_status_filter")
    op.drop_column("users", "iface_traffic_unit")
    op.drop_column("users", "iface_chart_metric")
    op.drop_column("users", "iface_time_range")
