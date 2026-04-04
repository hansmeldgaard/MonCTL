"""Drop os_cached_packages table — replaced by nginx apt-proxy.

Revision ID: zk1l2m3n4o5p
Revises: zj0k1l2m3n4o
Create Date: 2026-04-04
"""

from alembic import op

revision = "zk1l2m3n4o5p"
down_revision = "zj0k1l2m3n4o"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS os_cached_packages CASCADE")


def downgrade() -> None:
    # Intentional no-op — we don't restore archive-based distribution
    pass
