"""Move alert definitions from app-version level to app level.

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "n2o3p4q5r6s7"
down_revision = "m1n2o3p4q5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deduplicate: if same (app_id, name) exists from different versions,
    # keep the one with the latest updated_at and delete others
    op.execute("""
        DELETE FROM alert_definitions
        WHERE id NOT IN (
            SELECT DISTINCT ON (app_id, name) id
            FROM alert_definitions
            ORDER BY app_id, name, updated_at DESC
        )
    """)

    # Drop the old unique constraint (app_version_id, name)
    op.drop_constraint("uq_alert_def_version_name", "alert_definitions", type_="unique")

    # Drop FK to app_versions
    op.drop_constraint(
        "alert_definitions_app_version_id_fkey", "alert_definitions", type_="foreignkey"
    )

    # Drop the column
    op.drop_column("alert_definitions", "app_version_id")

    # Add new unique constraint (app_id, name)
    op.create_unique_constraint("uq_alert_def_app_name", "alert_definitions", ["app_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_alert_def_app_name", "alert_definitions", type_="unique")
    op.add_column(
        "alert_definitions",
        sa.Column("app_version_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "alert_definitions_app_version_id_fkey",
        "alert_definitions",
        "app_versions",
        ["app_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_alert_def_version_name", "alert_definitions", ["app_version_id", "name"]
    )
