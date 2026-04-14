"""Per-tier message templates + explicit healthy tier.

Today every AlertDefinition has a single def-level `message_template`
used for every fire/escalate/downgrade and prefixed with "Cleared: "
on clear. This collapses warning and critical into the same prose and
gives no control over the recovery text.

This migration:
  1. Copies the def-level `message_template` into each non-healthy
     tier that doesn't already have its own (so no message text is
     lost on upgrade).
  2. Prepends a `healthy` tier to every def that doesn't already have
     one. The healthy tier's expression is `null` and its
     `message_template` is a sensible default that engines + UI will
     use as the one-time recovery message.
  3. Drops `alert_definitions.message_template` — it no longer has a
     meaning.

No alert_entities are touched; the engine's next cycle will start
producing `clear severity='healthy'` rows using the new tier.

Revision ID: zx4y5z6a7b8c
Revises: zw3x4y5z6a7b
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "zx4y5z6a7b8c"
down_revision = "zw3x4y5z6a7b"
branch_labels = None
depends_on = None


_DEFAULT_HEALTHY = "{definition_name} on {device_name} recovered"


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT id, name, message_template, severity_tiers FROM alert_definitions"
        )
    ).fetchall()

    for r in rows:
        old_msg = r.message_template or f"{r.name} on {{device_name}}"
        tiers_in = list(r.severity_tiers or [])

        # Step 1: ensure every non-healthy tier carries a message_template.
        rebuilt: list[dict] = []
        has_healthy = False
        for t in tiers_in:
            if not isinstance(t, dict):
                continue
            sev = t.get("severity")
            if sev == "healthy":
                has_healthy = True
                rebuilt.append(
                    {
                        "severity": "healthy",
                        "expression": None,
                        "message_template": t.get("message_template") or _DEFAULT_HEALTHY,
                    }
                )
            else:
                rebuilt.append(
                    {
                        "severity": sev,
                        "expression": t.get("expression"),
                        "message_template": t.get("message_template") or old_msg,
                    }
                )

        # Step 2: prepend a healthy tier if missing.
        if not has_healthy:
            rebuilt.insert(
                0,
                {
                    "severity": "healthy",
                    "expression": None,
                    "message_template": _DEFAULT_HEALTHY,
                },
            )

        conn.execute(
            sa.text(
                "UPDATE alert_definitions SET severity_tiers = CAST(:t AS jsonb) "
                "WHERE id = :id"
            ),
            {"t": json.dumps(rebuilt), "id": r.id},
        )

    # Step 3: drop the def-level column.
    op.drop_column("alert_definitions", "message_template")


def downgrade() -> None:
    op.add_column(
        "alert_definitions",
        sa.Column("message_template", sa.Text(), nullable=True),
    )
    conn = op.get_bind()
    for r in conn.execute(
        sa.text("SELECT id, severity_tiers FROM alert_definitions")
    ).fetchall():
        tiers = r.severity_tiers or []
        # Pick the first non-healthy tier's template as the best
        # single-string fallback for the restored column.
        template = None
        for t in tiers:
            if isinstance(t, dict) and t.get("severity") != "healthy":
                template = t.get("message_template")
                break
        if template:
            conn.execute(
                sa.text("UPDATE alert_definitions SET message_template = :m WHERE id = :id"),
                {"m": template, "id": r.id},
            )
