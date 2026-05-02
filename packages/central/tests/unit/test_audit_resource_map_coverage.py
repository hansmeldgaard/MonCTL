"""F-CEN-050 — the audit whitelist stays in sync with the model set.

`audit/resource_map.py::TABLE_TO_RESOURCE` is a whitelist, not a blacklist:
a new SQLAlchemy model is not audited until someone remembers to add it
to the map. That's how several audit-gap regressions have shipped in the
past. This test closes the loop:

  * every mapped table must either be in TABLE_TO_RESOURCE or appear in
    `_AUDIT_OPT_OUT` with a short reason,
  * every key in TABLE_TO_RESOURCE must still correspond to a live mapper
    (prevents the map rotting after a model rename / drop),
  * the `_AUDIT_OPT_OUT` set itself must not drift onto real audited
    tables — adding something to both sets should fail loudly.

Adding a new model? The test tells you exactly which table is missing.
Pick one of:

  a) Audit it — add `"my_table": "my_resource"` to TABLE_TO_RESOURCE in
     `audit/resource_map.py`.
  b) Don't — add `"my_table"` to `_AUDIT_OPT_OUT` below with a short
     "Why:" comment. Use this sparingly; the bar is "this table stores
     churn state (queue rows, cache, counters) that would drown the
     audit log with no operator value".
"""

from __future__ import annotations

from monctl_central.audit.resource_map import TABLE_TO_RESOURCE
from monctl_central.storage.models import Base


# Tables that are deliberately unaudited. Each entry needs a short
# reason as the dict value — reviewers read these when bumping the list.
_AUDIT_OPT_OUT: dict[str, str] = {
    # Audit-related / bookkeeping. `audit_login_events` IS the audit log
    # itself, so it would recurse. `registration_tokens` are short-lived
    # bootstrap one-shots (token created at register, deleted on first
    # use) so audit value would be near zero.
    # `api_keys` was previously here with the same rationale; review #2
    # (S-CEN-018) reclassified it because issuance / revocation does not
    # mutate the parent user/collector row, so the before_flush listener
    # never fired and issuing a long-lived management key left no trail.
    # Now mapped in TABLE_TO_RESOURCE.
    "registration_tokens": "ephemeral one-time bootstrap tokens",
    "audit_login_events": "this IS the audit log — recursion",
    # Derived or computed state — recomputed from audited parents.
    "alert_entities": "derived from alert_definitions + live results; churn would swamp the log",
    "incidents": "derived from alert_entities; see alert_definitions / incident_rules for the policy surface",
    "interface_metadata": "denormalized from SNMP discovery, not user-authored",
    # Edge tables whose parents are audited separately (avoid double-writes).
    "app_connector_bindings": "edge of apps — parent is the audited entity",
    "assignment_connector_bindings": "edge of app_assignments — parent is audited",
    # `assignment_credential_overrides` was opted out with the same
    # "edge of app_assignments" rationale, but updating ONLY the override
    # row leaves the parent untouched — so we lost every credential
    # rebind. Reclassified in S-CEN-019; now mapped.
    "os_install_job_steps": "edge of os_install_jobs — parent is audited",
    "upgrade_job_steps": "edge of upgrade_jobs — parent is audited",
    "pack_versions": "edge of packs — the pack row captures version moves",
    "python_module_versions": "edge of python_modules — parent row is audited",
    # Collector-pushed / sidecar-pushed state. Non-user-authored, arrives
    # on every poll / heartbeat / scan and would drown the audit log.
    "app_cache": "gRPC-pushed cache state shared across collector group",
    "node_packages": "sidecar-pushed package inventory — overwrites on each pull",
    "os_available_updates": "snapshot of apt/dpkg state",
    "os_update_packages": "edge of os_available_updates snapshot",
    "system_versions": "snapshot of node version info",
    "wheel_files": "pack artifact cache — written by the pack import path",
}


def _mapped_tablenames() -> set[str]:
    """Every SQLAlchemy-mapped table that Base knows about."""
    return {
        mapper.local_table.name
        for mapper in Base.registry.mappers
        if mapper.local_table is not None
    }


def test_every_mapped_table_is_either_audited_or_opted_out() -> None:
    mapped = _mapped_tablenames()
    unhandled = (
        mapped
        - set(TABLE_TO_RESOURCE.keys())
        - set(_AUDIT_OPT_OUT.keys())
    )
    assert not unhandled, (
        f"new SQLAlchemy tables are neither audited nor explicitly opted out: "
        f"{sorted(unhandled)}. "
        f"Either add them to TABLE_TO_RESOURCE in audit/resource_map.py or "
        f"to _AUDIT_OPT_OUT in this test file with a reason."
    )


def test_no_table_is_in_both_sets() -> None:
    overlap = set(TABLE_TO_RESOURCE.keys()) & set(_AUDIT_OPT_OUT.keys())
    assert not overlap, (
        f"tables present in both TABLE_TO_RESOURCE and _AUDIT_OPT_OUT: "
        f"{sorted(overlap)}. Pick one."
    )


def test_audit_map_entries_correspond_to_real_tables() -> None:
    mapped = _mapped_tablenames()
    stale = set(TABLE_TO_RESOURCE.keys()) - mapped
    assert not stale, (
        f"TABLE_TO_RESOURCE references tables that no longer exist as "
        f"SQLAlchemy models: {sorted(stale)}. Remove from the map or "
        f"restore the model."
    )


def test_opt_out_entries_correspond_to_real_tables() -> None:
    mapped = _mapped_tablenames()
    stale = set(_AUDIT_OPT_OUT.keys()) - mapped
    assert not stale, (
        f"_AUDIT_OPT_OUT references tables that no longer exist: "
        f"{sorted(stale)}. Drop the entry."
    )


def test_resource_labels_are_non_empty() -> None:
    bad = [t for t, r in TABLE_TO_RESOURCE.items() if not r or not r.strip()]
    assert not bad, f"empty resource label for: {bad}"
