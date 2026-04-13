"""Add companion-alert clear fields to incident_rules.

Extends IncidentRule with two new columns so operators can configure
"clear this incident when a healthy/recovery alert fires":

- `clear_on_companion_ids` (JSONB list of AlertDefinition UUIDs) —
  companion alerts whose `resolved` state should clear the incident.
  NULL / empty list = feature disabled (use only `auto_clear_on_resolve`).
- `clear_companion_mode` ("any" | "all", default "any") — combine
  semantics when multiple companions are listed. "any" clears on the
  first healthy companion; "all" requires every listed companion to be
  healthy for the same entity.

Both columns are additive and default safely — existing rules keep
working unchanged.

Revision ID: zr8s9t0u1v2w
Revises: zq7r8s9t0u1v
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "zr8s9t0u1v2w"
down_revision = "zq7r8s9t0u1v"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incident_rules",
        sa.Column("clear_on_companion_ids", JSONB, nullable=True),
    )
    op.add_column(
        "incident_rules",
        sa.Column(
            "clear_companion_mode",
            sa.String(10),
            nullable=False,
            server_default="any",
        ),
    )


def downgrade() -> None:
    op.drop_column("incident_rules", "clear_companion_mode")
    op.drop_column("incident_rules", "clear_on_companion_ids")
