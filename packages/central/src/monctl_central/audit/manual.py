"""Helpers for emitting audit rows that don't flow through the SQLAlchemy
``before_flush`` listener.

Most audit rows are auto-captured: an ORM mutation on a whitelisted table
fires the listener, which builds a row and stages it on the request-scoped
``AuditContext.mutations`` list. Two cases need a different path:

* **Raw-SQL mutations** — endpoints that issue ``update(...)`` /
  ``insert(...)`` / ``delete(...)`` directly via ``session.execute(...)``
  bypass the ORM event hooks. The row never appears in the audit log
  unless we emit it explicitly.

* **Opted-out tables that get *manual* operator action** — ``incidents``
  and ``alert_entities`` are in ``_AUDIT_OPT_OUT`` because the engine
  rewrites them every cycle and the noise would drown out the signal.
  But when an admin **acks**, **silences**, or **force-clears** an
  incident, that's exactly the high-value mutation auditors want to
  see. (S-X-003)

``record_manual_action`` builds the same row shape ``_build_row`` produces
for the listener, then stages it on the request context. The middleware
flushes context.mutations to the audit buffer at response time, so the
new row gets the same `request_id`, status_code, latency, etc. as
auto-captured rows.

Resource type aliases are deliberately namespaced ``<base>_action``
(e.g. ``incident_action``, ``alert_entity_action``) so operators can
filter the audit UI to "manual operator clears" without needing to also
opt those tables INTO the auto-capture set.
"""

from __future__ import annotations

import datetime as _dt
import logging

from monctl_central.audit.context import get_context
from monctl_central.audit.diff import to_json

logger = logging.getLogger(__name__)


def record_manual_action(
    *,
    resource_type: str,
    resource_id: str,
    action: str,
    old: dict | None = None,
    new: dict | None = None,
    error_message: str = "",
) -> None:
    """Stage an audit row for an out-of-band action on the request context.

    Parameters
    ----------
    resource_type
        Short label shown in the audit UI filter, e.g. ``"incident_action"``.
    resource_id
        The mutated entity's primary key (stringified UUID).
    action
        Verb shown in the audit UI: ``"clear" | "ack" | "silence" |
        "force_clear" | ...``
    old, new
        Optional dicts captured before/after the change. Both are JSON-
        serialised with the same redaction the auto-listener uses, so
        passing a value containing ``"password"`` won't leak it.
    error_message
        Optional context surfaced on rows that recorded a failed action.

    Silently no-ops when called outside a request context (background
    tasks). Failures inside the staging logic are logged at debug level
    so audit-pipeline issues never bubble up to the caller — same
    contract as the auto-listener.
    """
    ctx = get_context()
    if ctx is None:
        # No request context (e.g. scheduler task). Operator-driven
        # actions always have a context; if we end up here it's a
        # caller bug, not something worth blowing up the request for.
        logger.debug(
            "audit_manual_skipped_no_context resource=%s action=%s id=%s",
            resource_type, action, resource_id,
        )
        return

    try:
        row = {
            "timestamp": _dt.datetime.now(tz=_dt.timezone.utc),
            "request_id": ctx.request_id or "",
            "user_id": ctx.user_id or "",
            "username": ctx.username or "",
            "auth_type": ctx.auth_type or "",
            "tenant_id": ctx.tenant_id or "",
            "ip_address": ctx.ip_address or "",
            "user_agent": ctx.user_agent or "",
            "method": ctx.method or "",
            "path": ctx.path or "",
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "action": action,
            "status_code": 0,  # filled in by middleware at response time
            "old_values": to_json(old or {}),
            "new_values": to_json(new or {}),
            "changed_fields": (
                sorted(set((old or {}).keys()) | set((new or {}).keys()))
                if (old or new)
                else []
            ),
            "duration_ms": 0,
            "error_message": error_message or "",
        }
        ctx.mutations.append(row)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "audit_manual_capture_failed resource=%s action=%s exc=%s",
            resource_type, action, exc,
        )
