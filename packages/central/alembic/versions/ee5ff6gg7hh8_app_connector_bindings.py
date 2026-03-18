"""Move connector bindings from assignment to app level.

Creates app_connector_bindings table, assignment_credential_overrides table,
and adds credential_id to app_assignments. Migrates existing data from
assignment_connector_bindings.

Revision ID: ee5ff6gg7hh8
Revises: dd4ee5ff6gg7
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "ee5ff6gg7hh8"
down_revision = "dd4ee5ff6gg7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create app_connector_bindings
    op.create_table(
        "app_connector_bindings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("app_id", UUID(as_uuid=True), sa.ForeignKey("apps.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("connector_id", UUID(as_uuid=True), sa.ForeignKey("connectors.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("alias", sa.String(64), nullable=False),
        sa.Column("use_latest", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("connector_version_id", UUID(as_uuid=True),
                  sa.ForeignKey("connector_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("app_id", "alias", name="uq_app_connector_alias"),
    )

    # 2. Add credential_id to app_assignments
    op.add_column(
        "app_assignments",
        sa.Column("credential_id", UUID(as_uuid=True),
                  sa.ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True),
    )

    # 3. Create assignment_credential_overrides
    op.create_table(
        "assignment_credential_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("assignment_id", UUID(as_uuid=True),
                  sa.ForeignKey("app_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(64), nullable=False),
        sa.Column("credential_id", UUID(as_uuid=True),
                  sa.ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("assignment_id", "alias", name="uq_assignment_cred_override_alias"),
    )

    # 4. Migrate existing assignment_connector_bindings → app_connector_bindings
    conn = op.get_bind()
    conn.exec_driver_sql("""
        INSERT INTO app_connector_bindings (app_id, connector_id, alias, use_latest, connector_version_id, settings)
        SELECT DISTINCT ON (a.app_id, acb.alias)
            a.app_id, acb.connector_id, acb.alias, acb.use_latest, acb.connector_version_id, acb.settings
        FROM assignment_connector_bindings acb
        JOIN app_assignments a ON a.id = acb.assignment_id
        ORDER BY a.app_id, acb.alias, acb.created_at DESC
    """)

    # 5. Migrate per-assignment credentials to assignment_credential_overrides
    conn.exec_driver_sql("""
        INSERT INTO assignment_credential_overrides (assignment_id, alias, credential_id)
        SELECT acb.assignment_id, acb.alias, acb.credential_id
        FROM assignment_connector_bindings acb
        WHERE acb.credential_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_table("assignment_credential_overrides")
    op.drop_column("app_assignments", "credential_id")
    op.drop_table("app_connector_bindings")
