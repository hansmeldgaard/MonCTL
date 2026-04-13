"""Backfill severity + ladder_key + ladder_rank on built-in alert defs.

The pack auto-importer keyed on (pack_uid, version) skips already-imported
packs, so editing the JSON file alone does not push new ladder metadata
to an existing deployment without bumping the pack version. This
migration does the backfill directly by (app_name, alert_def_name).

Idempotent: `UPDATE ... WHERE ladder_key IS NULL` won't clobber any
operator-authored ladder wiring, and repeats are no-ops.

Revision ID: zu1v2w3x4y5z
Revises: zt0u1v2w3x4y
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "zu1v2w3x4y5z"
down_revision = "zt0u1v2w3x4y"
branch_labels = None
depends_on = None


# (app_name, alert_def_name, severity, ladder_key, ladder_rank)
_LADDER_ROWS = [
    # ping_check
    ("ping_check", "Ping - Device Unreachable", "critical", None, None),
    ("ping_check", "Ping - High RTT Warning",   "warning",  "ping_rtt",  1),
    ("ping_check", "Ping - High RTT Critical",  "critical", "ping_rtt",  2),
    ("ping_check", "Ping - Packet Loss Warning", "warning",  "ping_loss", 1),
    ("ping_check", "Ping - Packet Loss Critical", "critical", "ping_loss", 2),
    # snmp_check
    ("snmp_check", "SNMP Unreachable",       "critical", None,       None),
    ("snmp_check", "High SNMP Latency",      "warning",  "snmp_rtt", 1),
    ("snmp_check", "Critical SNMP Latency",  "critical", "snmp_rtt", 2),
]


def upgrade() -> None:
    conn = op.get_bind()
    for app_name, def_name, severity, lkey, lrank in _LADDER_ROWS:
        conn.execute(
            sa.text(
                "UPDATE alert_definitions d "
                "SET severity = :sev, "
                "    ladder_key = COALESCE(d.ladder_key, :lkey), "
                "    ladder_rank = COALESCE(d.ladder_rank, :lrank) "
                "FROM apps a "
                "WHERE d.app_id = a.id "
                "  AND a.name = :app "
                "  AND d.name = :def_name"
            ),
            {
                "sev": severity,
                "lkey": lkey,
                "lrank": lrank,
                "app": app_name,
                "def_name": def_name,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE alert_definitions SET ladder_key = NULL, ladder_rank = NULL, severity = 'warning'"
        )
    )
