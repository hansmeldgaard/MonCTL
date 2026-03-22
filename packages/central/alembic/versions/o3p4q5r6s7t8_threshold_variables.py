"""Add threshold_variables table and rebuild threshold_overrides.

Revision ID: o3p4q5r6s7t8
Revises: n2o3p4q5r6s7
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "o3p4q5r6s7t8"
down_revision = "n2o3p4q5r6s7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old threshold_overrides table (may not exist in all envs)
    op.execute("DROP TABLE IF EXISTS threshold_overrides CASCADE")

    # Create threshold_variables table
    op.create_table(
        "threshold_variables",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("app_id", UUID(as_uuid=True), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("default_value", sa.Float, nullable=False),
        sa.Column("app_value", sa.Float, nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("app_id", "name", name="uq_threshold_var_app_name"),
    )

    # Create new threshold_overrides table referencing threshold_variables
    op.create_table(
        "threshold_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("variable_id", UUID(as_uuid=True), sa.ForeignKey("threshold_variables.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("entity_key", sa.String(500), nullable=False, server_default=""),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("variable_id", "device_id", "entity_key", name="uq_threshold_override_var_device_entity"),
    )


def downgrade() -> None:
    op.drop_table("threshold_overrides")
    op.drop_table("threshold_variables")

    # Recreate the old threshold_overrides table
    op.create_table(
        "threshold_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("definition_id", UUID(as_uuid=True), sa.ForeignKey("alert_definitions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("entity_key", sa.String(500), nullable=False, server_default=""),
        sa.Column("overrides", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("definition_id", "device_id", "entity_key", name="uq_override_def_device_entity"),
    )
