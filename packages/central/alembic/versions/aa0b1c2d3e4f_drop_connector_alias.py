"""Drop connector alias concept — slot keyed by connector_type.

Removes ``alias`` and ``use_latest`` from ``app_connector_bindings`` and
``assignment_connector_bindings``; replaces ``alias`` on
``assignment_credential_overrides`` with ``connector_type``. Enforces one
binding per (scope, connector_type). Fails loud if existing data can't be
migrated cleanly — operator must clean up duplicates manually before
retrying.

Revision ID: aa0b1c2d3e4f
Revises: zx4y5z6a7b8c
"""

from alembic import op
import sqlalchemy as sa

revision = "aa0b1c2d3e4f"
down_revision = "ab1c2d3e4f5g"
branch_labels = None
depends_on = None


def _check_alias_matches_type(bind, table: str) -> None:
    """Fail if any row's alias does not equal a connector.connector_type.

    For app_connector_bindings and assignment_connector_bindings we have a
    connector_id FK — assert alias == connector.connector_type. For
    assignment_credential_overrides we don't have an FK to a connector, so
    we assert alias is some known connector_type on *any* connector.
    """
    if table in ("app_connector_bindings", "assignment_connector_bindings"):
        result = bind.execute(
            sa.text(
                f"""
                SELECT t.id, t.alias, c.connector_type
                FROM {table} t
                LEFT JOIN connectors c ON c.id = t.connector_id
                WHERE c.connector_type IS DISTINCT FROM t.alias
                """
            )
        ).fetchall()
    else:
        result = bind.execute(
            sa.text(
                f"""
                SELECT t.id, t.alias
                FROM {table} t
                WHERE NOT EXISTS (
                    SELECT 1 FROM connectors c WHERE c.connector_type = t.alias
                )
                """
            )
        ).fetchall()
    if result:
        raise RuntimeError(
            f"Cannot migrate {table}: alias does not match any connector_type "
            f"for rows: {[tuple(r) for r in result]}. "
            "Fix manually before retrying."
        )


def _check_no_dup_types(bind, table: str, scope_col: str) -> None:
    """Fail if (scope, connector_type) would be non-unique after migration."""
    # For assignment_credential_overrides alias already equals connector_type
    # per pre-check. For *_connector_bindings we key by
    # connectors.connector_type via a join.
    dup_col = "alias" if table == "assignment_credential_overrides" else None

    if dup_col is not None:
        result = bind.execute(
            sa.text(
                f"""
                SELECT {scope_col}, {dup_col}, COUNT(*) AS n
                FROM {table}
                GROUP BY {scope_col}, {dup_col}
                HAVING COUNT(*) > 1
                """
            )
        ).fetchall()
    else:
        result = bind.execute(
            sa.text(
                f"""
                SELECT t.{scope_col}, c.connector_type, COUNT(*) AS n
                FROM {table} t
                JOIN connectors c ON c.id = t.connector_id
                GROUP BY t.{scope_col}, c.connector_type
                HAVING COUNT(*) > 1
                """
            )
        ).fetchall()
    if result:
        raise RuntimeError(
            f"Cannot migrate {table}: duplicate ({scope_col}, connector_type) "
            f"rows found: {[tuple(r) for r in result]}. "
            "Delete duplicates manually before retrying."
        )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Pre-checks — fail loud before any destructive change.
    _check_alias_matches_type(bind, "app_connector_bindings")
    _check_alias_matches_type(bind, "assignment_connector_bindings")
    _check_alias_matches_type(bind, "assignment_credential_overrides")
    _check_no_dup_types(bind, "app_connector_bindings", "app_id")
    _check_no_dup_types(bind, "assignment_connector_bindings", "assignment_id")
    _check_no_dup_types(bind, "assignment_credential_overrides", "assignment_id")

    # 2. assignment_connector_bindings: add connector_type, backfill, drop alias+use_latest.
    op.add_column(
        "assignment_connector_bindings",
        sa.Column("connector_type", sa.String(32), nullable=True),
    )
    op.execute(
        """
        UPDATE assignment_connector_bindings acb
        SET connector_type = c.connector_type
        FROM connectors c
        WHERE acb.connector_id = c.id
        """
    )
    op.alter_column(
        "assignment_connector_bindings",
        "connector_type",
        existing_type=sa.String(32),
        nullable=False,
    )
    # Postgres-generated name for the original (assignment_id, alias) UniqueConstraint.
    op.execute(
        "ALTER TABLE assignment_connector_bindings "
        "DROP CONSTRAINT IF EXISTS assignment_connector_bindings_assignment_id_alias_key"
    )
    op.execute(
        "ALTER TABLE assignment_connector_bindings "
        "DROP CONSTRAINT IF EXISTS uq_assignment_connector_bindings_assignment_id_alias"
    )
    op.drop_column("assignment_connector_bindings", "alias")
    op.drop_column("assignment_connector_bindings", "use_latest")
    op.alter_column(
        "assignment_connector_bindings",
        "connector_version_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_unique_constraint(
        "uq_assignment_binding_type",
        "assignment_connector_bindings",
        ["assignment_id", "connector_type"],
    )

    # 3. assignment_credential_overrides: rename alias → connector_type.
    op.add_column(
        "assignment_credential_overrides",
        sa.Column("connector_type", sa.String(32), nullable=True),
    )
    op.execute(
        "UPDATE assignment_credential_overrides SET connector_type = alias"
    )
    op.alter_column(
        "assignment_credential_overrides",
        "connector_type",
        existing_type=sa.String(32),
        nullable=False,
    )
    op.execute(
        "ALTER TABLE assignment_credential_overrides "
        "DROP CONSTRAINT IF EXISTS uq_assignment_cred_override_alias"
    )
    op.drop_column("assignment_credential_overrides", "alias")
    op.create_unique_constraint(
        "uq_assignment_cred_override_type",
        "assignment_credential_overrides",
        ["assignment_id", "connector_type"],
    )

    # 4. app_connector_bindings: drop alias, use_latest; new unique on (app, type).
    op.execute(
        "ALTER TABLE app_connector_bindings "
        "DROP CONSTRAINT IF EXISTS uq_app_connector_alias"
    )
    op.drop_column("app_connector_bindings", "alias")
    op.drop_column("app_connector_bindings", "use_latest")
    op.create_unique_constraint(
        "uq_app_connector_type",
        "app_connector_bindings",
        ["app_id", "connector_type"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "aa0b1c2d3e4f is a destructive refactor (drops alias concept); "
        "rollback not supported"
    )
