"""Add incident-trigger fields to automations for the cut-over step 1.

Cut-over step 1 of the event policy rework: let an Automation subscribe
to incident state transitions (opened / escalated / cleared) from the
new IncidentEngine instead of (or in addition to) the legacy events
path. New columns are nullable so existing event- and cron-typed
automations are untouched.

See docs/event-policy-rework.md and
`packages/central/src/monctl_central/automations/engine.py::on_incident_transition`.

Revision ID: zo5p6q7r8s9t
Revises: zn4o5p6q7r8s
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "zo5p6q7r8s9t"
down_revision = "zn4o5p6q7r8s"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automations",
        sa.Column("incident_rule_ids", JSONB(), nullable=True),
    )
    op.add_column(
        "automations",
        sa.Column("incident_state_trigger", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("automations", "incident_state_trigger")
    op.drop_column("automations", "incident_rule_ids")
