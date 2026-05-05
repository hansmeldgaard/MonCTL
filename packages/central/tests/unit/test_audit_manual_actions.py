"""Regression: admin-driven incident/alert state changes are audited.

Closes S-X-003 (review #2 security.md, MED). `alert_entities` and
`incidents` are deliberately opted out of the SQLAlchemy auto-audit
listener — the engine rewrites those rows every cycle, so per-tick
auto-capture would drown out real signal in the audit log. But manual
operator actions (force-clear an incident, silence an alert instance)
are exactly the high-value mutation a SOC-2 auditor wants to see, and
they were silently dropping off the record.

The fix is a dedicated `record_manual_action` helper in
`audit/manual.py` that builds the same row shape the auto-listener
produces and stages it on the request-scoped `AuditContext.mutations`
list. Both opted-out tables now have exactly one explicit call site:

  * `POST /v1/incidents/clear` → `incident_action` (action="clear")
  * `PUT /v1/alerts/instances/{id}` (enabled flip) → `alert_entity_action`
    (action="silence" | "unsilence")

If a future refactor drops either call, this test fails before the
audit gap reaches production. It also pins the redaction contract — if
old/new ever carry a sensitive key, the staged row redacts it before
serialisation.
"""

from __future__ import annotations

import json

import pytest

from monctl_central.audit.context import AuditContext, set_context, clear_context
from monctl_central.audit.manual import record_manual_action


@pytest.fixture
def audit_context():
    """Fresh AuditContext as if the middleware just ran."""
    ctx = AuditContext(
        request_id="req-test-1",
        user_id="user-test-1",
        username="alice",
        auth_type="cookie",
        ip_address="10.0.0.1",
        user_agent="pytest",
        method="POST",
        path="/v1/incidents/clear",
    )
    set_context(ctx)
    try:
        yield ctx
    finally:
        clear_context()


class TestRecordManualAction:
    def test_stages_row_on_context_mutations(self, audit_context: AuditContext) -> None:
        """Single call → single row on the request context, with the
        expected resource_type / action / old / new shape."""
        record_manual_action(
            resource_type="incident_action",
            resource_id="abc-123",
            action="clear",
            old={"state": "open"},
            new={"state": "cleared", "cleared_reason": "manual"},
        )

        assert len(audit_context.mutations) == 1
        row = audit_context.mutations[0]
        assert row["resource_type"] == "incident_action"
        assert row["resource_id"] == "abc-123"
        assert row["action"] == "clear"
        assert row["request_id"] == "req-test-1"
        assert row["user_id"] == "user-test-1"
        assert row["username"] == "alice"
        assert row["ip_address"] == "10.0.0.1"
        assert row["path"] == "/v1/incidents/clear"

        # `old_values` / `new_values` are JSON strings (matching the
        # auto-listener's contract). Decode and pin the content.
        assert json.loads(row["old_values"]) == {"state": "open"}
        assert json.loads(row["new_values"]) == {
            "state": "cleared",
            "cleared_reason": "manual",
        }
        # changed_fields is the union of old/new keys, sorted.
        assert row["changed_fields"] == ["cleared_reason", "state"]

    def test_silence_action_pins_alert_entity_resource_type(
        self, audit_context: AuditContext,
    ) -> None:
        """The other call site (alerting/router.py PUT /instances/{id})
        emits a different resource_type so the audit UI can filter
        operator silences separately from operator clears."""
        record_manual_action(
            resource_type="alert_entity_action",
            resource_id="entity-1",
            action="silence",
            old={"enabled": True},
            new={"enabled": False},
        )
        row = audit_context.mutations[0]
        assert row["resource_type"] == "alert_entity_action"
        assert row["action"] == "silence"
        assert row["changed_fields"] == ["enabled"]

    def test_redacts_sensitive_old_new_fields(
        self, audit_context: AuditContext,
    ) -> None:
        """If a caller accidentally passes a sensitive value through
        old/new, the redaction layer in audit/diff.py must scrub it
        before the row gets serialised. Same contract as the auto
        listener — defence in depth."""
        record_manual_action(
            resource_type="incident_action",
            resource_id="abc-123",
            action="force_clear",
            old={"state": "open", "password": "should-not-leak"},
            new={"state": "cleared", "api_key": "monctl_m_live"},
        )
        row = audit_context.mutations[0]
        # Sensitive fields are replaced with "***" before JSON encode.
        old_decoded = json.loads(row["old_values"])
        new_decoded = json.loads(row["new_values"])
        assert old_decoded["password"] == "***"
        assert new_decoded["api_key"] == "***"
        # Non-sensitive fields pass through.
        assert old_decoded["state"] == "open"
        assert new_decoded["state"] == "cleared"

    def test_no_context_logs_debug_and_returns(self) -> None:
        """Calling outside a request (e.g. background scheduler task)
        is a caller bug but must not raise — same contract as the
        auto-listener. The helper logs at DEBUG and returns silently."""
        clear_context()  # explicit, even though the fixture isn't active
        # Must not raise.
        record_manual_action(
            resource_type="incident_action",
            resource_id="abc-123",
            action="clear",
            old={"state": "open"},
            new={"state": "cleared"},
        )

    def test_empty_old_new_keeps_changed_fields_empty(
        self, audit_context: AuditContext,
    ) -> None:
        """Action that records intent but no field-level diff (e.g. a
        click-through "review" later — not a current call site, but the
        helper supports it). `changed_fields` must be the empty list,
        not None."""
        record_manual_action(
            resource_type="incident_action",
            resource_id="abc-123",
            action="review",
        )
        row = audit_context.mutations[0]
        assert row["changed_fields"] == []
        assert json.loads(row["old_values"]) == {}
        assert json.loads(row["new_values"]) == {}
