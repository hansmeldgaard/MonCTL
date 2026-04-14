"""Collapse ladder-paired alert defs into one def per signal with severity tiers.

Before this revision, each signal with warning + critical thresholds had
TWO AlertDefinition rows joined via `ladder_key` + `ladder_rank`. The
engine emitted clear+fire pairs every time a noisy metric crossed the
threshold between tiers, which reads in alert history as "alert cleared
and a new one fired" — when really the signal was never healthy.

This migration folds ladder siblings into a single AlertDefinition with
an ordered `severity_tiers` JSONB list. The engine will emit a single
`escalate` / `downgrade` record for severity transitions and reserve
`clear` for the firing→ok transition only.

The migration is destructive (no compat): old columns dropped, existing
AlertEntity rows wiped so the engine recreates them with the new
multi-tier model on the next cycle. `alert_log` history stays intact
(it's in ClickHouse and this migration doesn't touch it).

Revision ID: zw3x4y5z6a7b
Revises: zv2w3x4y5z6a
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "zw3x4y5z6a7b"
down_revision = "zv2w3x4y5z6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add the new columns (alert_definitions.severity_tiers,
    #    alert_entities.severity). severity_tiers starts empty; we
    #    populate it from the legacy expression/severity/ladder
    #    columns before dropping them.
    op.add_column(
        "alert_definitions",
        sa.Column(
            "severity_tiers",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "alert_entities",
        sa.Column("severity", sa.String(length=20), nullable=True),
    )

    # 2. Data migration: merge ladder pairs, carry single defs over.
    #
    # a) For every (app_id, ladder_key) with non-null ladder_key:
    #    - Sort the siblings by ladder_rank asc (lowest → highest severity).
    #    - Pick a merged name (strip trailing " Warning"/" Critical"
    #      from the highest-rank sibling's name; fall back to ladder_key).
    #    - Pick one sibling to KEEP (highest-rank — its id likely owns
    #      more downstream references like IncidentRule.definition_id).
    #    - Set its severity_tiers = [{severity, expression}, ...] in
    #      rank order, rename it, and delete the other siblings.
    #    - CASCADE on incident_rules.definition_id drops orphaned
    #      rules pointing at the deleted sibling. Acceptable per plan.
    #
    # b) For every non-ladder def: severity_tiers = [{severity, expression}].
    rows = conn.execute(
        sa.text(
            "SELECT id, app_id, name, expression, severity, ladder_key, ladder_rank "
            "FROM alert_definitions"
        )
    ).fetchall()

    # Group by (app_id, ladder_key)
    ladder_groups: dict[tuple, list] = {}
    singletons: list = []
    for r in rows:
        if r.ladder_key:
            ladder_groups.setdefault((r.app_id, r.ladder_key), []).append(r)
        else:
            singletons.append(r)

    # Singletons: one-tier list derived from existing expression + severity.
    for r in singletons:
        tier = [{"severity": r.severity or "warning", "expression": r.expression}]
        conn.execute(
            sa.text(
                "UPDATE alert_definitions SET severity_tiers = CAST(:tiers AS jsonb) "
                "WHERE id = :id"
            ),
            {"tiers": json.dumps(tier), "id": r.id},
        )

    # Ladder groups: merge.
    for (app_id, ladder_key), siblings in ladder_groups.items():
        siblings.sort(key=lambda s: (s.ladder_rank or 0))
        tiers = [
            {"severity": s.severity or "warning", "expression": s.expression}
            for s in siblings
        ]
        # Keep the highest-rank sibling, delete the rest.
        keeper = siblings[-1]
        victims = siblings[:-1]

        # Best-effort merged name: drop common severity suffixes.
        merged_name = keeper.name
        for suffix in (" Critical", " Warning", " Warn", " Crit"):
            if merged_name.endswith(suffix):
                merged_name = merged_name[: -len(suffix)]
                break

        conn.execute(
            sa.text(
                "UPDATE alert_definitions "
                "SET severity_tiers = CAST(:tiers AS jsonb), name = :name "
                "WHERE id = :id"
            ),
            {"tiers": json.dumps(tiers), "name": merged_name, "id": keeper.id},
        )

        # Re-point any IncidentRule that referenced a victim to the keeper
        # before we delete the victim (CASCADE would drop the rule).
        if victims:
            conn.execute(
                sa.text(
                    "UPDATE incident_rules SET definition_id = :keeper "
                    "WHERE definition_id = ANY(:victims)"
                ),
                {"keeper": keeper.id, "victims": [v.id for v in victims]},
            )
            conn.execute(
                sa.text("DELETE FROM alert_definitions WHERE id = ANY(:ids)"),
                {"ids": [v.id for v in victims]},
            )

    # 3. Wipe AlertEntities. engine will recreate them on next cycle via
    #    sync_instances_for_definition, starting from a clean 'ok' state
    #    so the FIRST fire after deploy is a real fire (not a leftover
    #    pre-migration firing entity that suddenly looks weird under the
    #    new model).
    conn.execute(sa.text("DELETE FROM alert_entities"))

    # 4. Drop the old columns + index now that data is migrated.
    op.drop_index("ix_alert_definitions_ladder_key", table_name="alert_definitions")
    op.drop_column("alert_definitions", "ladder_rank")
    op.drop_column("alert_definitions", "ladder_key")
    op.drop_column("alert_definitions", "severity")
    op.drop_column("alert_definitions", "expression")


def downgrade() -> None:
    # Re-add old columns so engine-level rollback works. Data in
    # severity_tiers gets flattened back to expression + severity (first
    # tier wins; loses any extra tiers). Ladder key/rank not restored —
    # downgrade is best-effort.
    op.add_column(
        "alert_definitions",
        sa.Column("expression", sa.Text(), nullable=True),
    )
    op.add_column(
        "alert_definitions",
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="warning"),
    )
    op.add_column(
        "alert_definitions",
        sa.Column("ladder_key", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "alert_definitions",
        sa.Column("ladder_rank", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_alert_definitions_ladder_key",
        "alert_definitions",
        ["ladder_key"],
    )

    conn = op.get_bind()
    for r in conn.execute(
        sa.text("SELECT id, severity_tiers FROM alert_definitions")
    ).fetchall():
        tiers = r.severity_tiers or []
        if not tiers:
            continue
        top = tiers[0]
        conn.execute(
            sa.text(
                "UPDATE alert_definitions SET expression = :e, severity = :s WHERE id = :id"
            ),
            {"e": top.get("expression", ""), "s": top.get("severity", "warning"), "id": r.id},
        )

    op.alter_column("alert_definitions", "expression", nullable=False)
    op.drop_column("alert_entities", "severity")
    op.drop_column("alert_definitions", "severity_tiers")
