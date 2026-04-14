"""Rename IncidentRule rows to drop legacy "Event" / "Promote to Event"
suffixes.

The pre-rework system called these "events"; after the EventPolicy
deprecation (see docs/event-policy-rework.md) the platform talks
"incidents" end-to-end. Rule names still carried the old suffixes
because they were originally seeded from the EventPolicy mirror.

Transforms applied in order to each row's `name`:

  1. strip trailing " - Promote to Event"
  2. strip trailing " Event"
  3. strip trailing " Warning" / " Critical" on the two survivors from
     the dedup migration whose names now describe a single severity-
     tiered signal, so they read as the signal itself.

Idempotent — re-running produces no further changes.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "zz6a7b8c9d0e"
down_revision = "zy5z6a7b8c9d"
branch_labels = None
depends_on = None


def _rename(name: str) -> str:
    """Return the cleaned name. Pure function, easy to reason about."""
    for suffix in (" - Promote to Event",):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if name.endswith(" Event"):
        name = name[: -len(" Event")]
    # Post-dedup survivors whose single name still implied a tier.
    # Only strip if the rule name has "High RTT" or "Latency" stem —
    # these are the two known cases; a generic endswith strip would be
    # too aggressive and could rename a legitimately single-tier rule.
    if name in ("Ping High RTT Warning", "Ping High RTT Critical"):
        name = "Ping High RTT"
    elif name in ("SNMP Latency Warning", "SNMP Latency Critical"):
        name = "SNMP Latency"
    return name


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, name FROM incident_rules")
    ).mappings().all()

    for r in rows:
        new_name = _rename(r["name"])
        if new_name == r["name"]:
            continue
        conn.execute(
            sa.text(
                "UPDATE incident_rules "
                "SET name = :name, updated_at = now() "
                "WHERE id = :id"
            ),
            {"name": new_name, "id": r["id"]},
        )


def downgrade() -> None:
    # One-way rename. Original names are not worth preserving.
    raise RuntimeError(
        "zz6a7b8c9d0e is a non-reversible rename migration"
    )
