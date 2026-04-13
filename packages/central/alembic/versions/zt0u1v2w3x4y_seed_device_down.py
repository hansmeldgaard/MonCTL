"""Seed a built-in "Device Down" master incident rule and wire siblings.

Data-only migration. Produces one operator-visible change:

1. If an AlertDefinition named "Ping - Device Unreachable" exists
   (shipped by pack `basic-checks`), ensure there is an IncidentRule
   bound to it called "Device Down", severity=critical, with
   auto_clear_on_resolve=true. This rule is the single master
   incident per device when ping reachability drops.

2. For every *other* IncidentRule whose underlying AlertDefinition
   belongs to one of the device-reachability-adjacent built-in apps
   (ping_check, snmp_check, http_check, port_check, snmp_uptime,
   entity_mib_inventory), set `depends_on` so those child incidents
   open suppressed under the Device Down parent, and set
   `clear_on_companion_ids` so they auto-clear the moment Ping
   reachability recovers. The filter checks `depends_on IS NULL` so
   operators that already configured their own dependency tree are
   not overwritten.

The migration is idempotent and silently skips when the anchor
AlertDefinition is missing (fresh installs before pack import).

Revision ID: zt0u1v2w3x4y
Revises: zs9t0u1v2w3x
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "zt0u1v2w3x4y"
down_revision = "zs9t0u1v2w3x"
branch_labels = None
depends_on = None


CHILD_APP_NAMES = (
    "ping_check",
    "snmp_check",
    "http_check",
    "port_check",
    "snmp_uptime",
    "entity_mib_inventory",
)


def upgrade() -> None:
    conn = op.get_bind()

    ping_def = conn.execute(
        sa.text(
            "SELECT d.id FROM alert_definitions d "
            "JOIN apps a ON a.id = d.app_id "
            "WHERE d.name = 'Ping - Device Unreachable' "
            "  AND a.name = 'ping_check' "
            "LIMIT 1"
        )
    ).first()
    if ping_def is None:
        # Fresh DB — pack import hasn't run yet. The built-in "Device
        # Down" rule will be seeded by a later migration or by manual
        # operator action. Non-fatal.
        return
    ping_def_id = ping_def[0]

    existing_master = conn.execute(
        sa.text(
            "SELECT id FROM incident_rules "
            "WHERE name = 'Device Down' AND definition_id = :did"
        ),
        {"did": ping_def_id},
    ).first()

    if existing_master is None:
        master_id = uuid.uuid4()
        conn.execute(
            sa.text(
                "INSERT INTO incident_rules ("
                "  id, name, description, definition_id, mode, "
                "  fire_count_threshold, window_size, severity, "
                "  auto_clear_on_resolve, enabled, source, "
                "  clear_companion_mode"
                ") VALUES ("
                "  :id, :name, :desc, :did, 'consecutive', "
                "  2, 5, 'critical', "
                "  true, true, 'native', "
                "  'any'"
                ")"
            ),
            {
                "id": master_id,
                "name": "Device Down",
                "desc": (
                    "Master incident when a device stops answering ICMP. "
                    "Suppresses companion latency/SNMP/HTTP/port incidents "
                    "for the same device until ping reachability recovers."
                ),
                "did": ping_def_id,
            },
        )
    else:
        master_id = existing_master[0]

    # Wire children. Only IncidentRules that don't already have
    # depends_on are touched — operator-authored dependency trees are
    # preserved. Children are matched via app_name lookup on their
    # definition.
    depends_on_json = json.dumps(
        {"rule_ids": [str(master_id)], "match_on": ["device_id"]}
    )
    companion_json = json.dumps([str(ping_def_id)])

    conn.execute(
        sa.text(
            "UPDATE incident_rules r "
            "SET depends_on = CAST(:dep AS jsonb), "
            "    clear_on_companion_ids = CAST(:comp AS jsonb), "
            "    clear_companion_mode = 'any' "
            "FROM alert_definitions d, apps a "
            "WHERE r.definition_id = d.id "
            "  AND d.app_id = a.id "
            "  AND a.name = ANY(:apps) "
            "  AND r.id <> :master "
            "  AND r.depends_on IS NULL"
        ),
        {
            "dep": depends_on_json,
            "comp": companion_json,
            "apps": list(CHILD_APP_NAMES),
            "master": master_id,
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Unwire children we touched (best effort — we can't distinguish
    # rows we wired vs. rows an operator set to the same payload).
    conn.execute(
        sa.text(
            "UPDATE incident_rules "
            "SET depends_on = NULL, clear_on_companion_ids = NULL "
            "WHERE name <> 'Device Down' "
            "  AND depends_on IS NOT NULL "
            "  AND depends_on::jsonb -> 'match_on' = '[\"device_id\"]'::jsonb"
        )
    )
    conn.execute(
        sa.text("DELETE FROM incident_rules WHERE name = 'Device Down'")
    )
