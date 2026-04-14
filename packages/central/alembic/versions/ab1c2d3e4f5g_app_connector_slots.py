"""App connector bindings: slot model (nullable connector_id, type, orphaned).

Option C of the connector-alias rework (see
``streamed-prancing-sunbeam`` plan). Turns ``app_connector_bindings``
into a "slot" model: the Poller code declares which aliases it needs,
central pre-creates the rows, and the operator just picks which
concrete connector fills each slot.

Changes:

* ``connector_id`` → nullable. A slot can exist before the operator
  has picked a concrete connector. Assignment creation is blocked
  until every non-orphaned slot on the app has a connector_id set.
* ``connector_type`` → new required ``String(32)`` column. Records the
  kind of connector each slot expects so the UI can filter its picker
  without joining on the Connector table. Backfilled from the related
  Connector row during upgrade.
* ``is_orphaned`` → new ``Boolean`` column, default false. Marks slots
  that have been removed by a later version of the app source but are
  retained so existing assignments keep working; the collector engine
  ignores orphaned slots at runtime.

Revision ID: zo5p6q7r8s9t
Revises: zn4o5p6q7r8s
"""

from alembic import op
import sqlalchemy as sa

revision = "ab1c2d3e4f5g"
down_revision = "zx4y5z6a7b8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add columns (connector_type nullable during backfill, then NOT NULL).
    op.add_column(
        "app_connector_bindings",
        sa.Column("connector_type", sa.String(32), nullable=True),
    )
    op.add_column(
        "app_connector_bindings",
        sa.Column(
            "is_orphaned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 2. Backfill connector_type from the related Connector row.
    op.execute(
        """
        UPDATE app_connector_bindings acb
        SET connector_type = c.connector_type
        FROM connectors c
        WHERE acb.connector_id = c.id
          AND acb.connector_type IS NULL
        """
    )

    # 3. Any rows that still have NULL connector_type (shouldn't happen on
    #    real data, but just in case — defend against orphan FKs from a
    #    bad state) get a sentinel so we can make the column NOT NULL.
    op.execute(
        """
        UPDATE app_connector_bindings
        SET connector_type = 'unknown'
        WHERE connector_type IS NULL
        """
    )

    # 4. Lock in NOT NULL on connector_type.
    op.alter_column(
        "app_connector_bindings",
        "connector_type",
        existing_type=sa.String(32),
        nullable=False,
    )

    # 5. Relax connector_id to nullable so unfilled slots can exist.
    op.alter_column(
        "app_connector_bindings",
        "connector_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Re-tighten connector_id to NOT NULL. This will fail (intentionally)
    # if any slot is currently empty — operator must fill or delete such
    # rows first before rolling back.
    op.alter_column(
        "app_connector_bindings",
        "connector_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_column("app_connector_bindings", "is_orphaned")
    op.drop_column("app_connector_bindings", "connector_type")
