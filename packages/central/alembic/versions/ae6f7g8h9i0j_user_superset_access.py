"""Add superset_access tier column to users.

Orthogonal to `role` (which gates MonCTL itself) — this column controls
what a user can DO in Superset:

  none      → OAuth /authorize denies the Superset client for this user
  viewer    → MonCTLViewer (read-only, no SQL Lab) — today's default for
              non-admins
  analyst   → MonCTLAnalyst (Alpha + SQL Lab + all_datasource_access);
              Layer 3 row policies still scope rows server-side
  admin     → Superset Admin

Existing rows are backfilled deterministically — admins → 'admin',
everyone else → 'viewer' — so the new field is non-NULL after the
migration runs even though the column itself stays nullable (NULL means
"derive from role" if the OAuth userinfo encounters one).

Revision ID: ae6f7g8h9i0j
Revises: ad5e6f7g8h9i
"""

import sqlalchemy as sa
from alembic import op

revision = "ae6f7g8h9i0j"
down_revision = "ad5e6f7g8h9i"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "superset_access",
            sa.String(20),
            nullable=True,
            comment="Superset BI access tier: none | viewer | analyst | admin",
        ),
    )
    # Deterministic backfill so existing users land on a sensible tier
    # immediately after deploy. Stored explicitly (not left NULL) so an
    # admin can revoke later without the value being recomputed.
    op.execute(
        "UPDATE users "
        "SET superset_access = "
        "CASE WHEN role = 'admin' THEN 'admin' ELSE 'viewer' END "
        "WHERE superset_access IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "superset_access")
