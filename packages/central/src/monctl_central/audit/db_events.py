"""SQLAlchemy event listeners for capturing mutations into the audit log.

Hook flow:
  1. Before each async session flush, we walk the session's new/dirty/deleted
     object sets and build audit rows describing the change.
  2. The rows are stashed on the current AuditContext (request-scoped).
  3. AuditContextMiddleware forwards the rows to the async audit buffer after
     the response is produced (or on request completion even if the handler
     raised — the middleware has a try/finally).

Why `before_flush` and not `after_flush`/`after_commit`: we need the old
values from the SQLAlchemy attribute history, which is still available in
`before_flush`. After the flush, attribute history is cleared. Committing
is handled at the outer `get_db` dependency boundary, so by the time
`before_flush` fires the data has been validated by the handler and is
about to hit the DB — a good point to record the change.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import structlog
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from monctl_central.audit.context import get_context
from monctl_central.audit.diff import to_json
from monctl_central.audit.resource_map import resource_type_for

logger = structlog.get_logger()


def _model_to_dict(obj: Any) -> dict[str, Any]:
    """Return the current column values of a mapped object as a plain dict."""
    try:
        state = inspect(obj)
        return {col.key: getattr(obj, col.key, None) for col in state.mapper.column_attrs}
    except Exception:
        return {}


def _old_values_from_history(obj: Any) -> dict[str, Any]:
    """Extract previous column values from attribute history (UPDATE only)."""
    try:
        state = inspect(obj)
        old: dict[str, Any] = {}
        for col in state.mapper.column_attrs:
            hist = state.attrs[col.key].history
            if hist.has_changes() and hist.deleted:
                old[col.key] = hist.deleted[0]
        return old
    except Exception:
        return {}


def _changed_new_values(obj: Any) -> dict[str, Any]:
    """Return only the changed fields' new values (UPDATE only)."""
    try:
        state = inspect(obj)
        new: dict[str, Any] = {}
        for col in state.mapper.column_attrs:
            hist = state.attrs[col.key].history
            if hist.has_changes():
                new[col.key] = getattr(obj, col.key, None)
        return new
    except Exception:
        return {}


def _resource_id(obj: Any) -> str:
    try:
        pk = inspect(obj).identity
        if pk:
            return str(pk[0]) if len(pk) == 1 else ",".join(str(p) for p in pk)
        # Not yet flushed — try .id
        val = getattr(obj, "id", None)
        return str(val) if val is not None else ""
    except Exception:
        return ""


def _build_row(action: str, obj: Any, old: dict, new: dict) -> dict | None:
    tablename = getattr(type(obj), "__tablename__", None)
    if not tablename:
        return None
    resource_type = resource_type_for(tablename)
    if not resource_type:
        return None

    ctx = get_context()
    timestamp = _dt.datetime.now(tz=_dt.timezone.utc)

    return {
        "timestamp": timestamp,
        "request_id": (ctx.request_id if ctx else ""),
        "user_id": (ctx.user_id if ctx else ""),
        "username": (ctx.username if ctx else ""),
        "auth_type": (ctx.auth_type if ctx else "system"),
        "tenant_id": (ctx.tenant_id if ctx else ""),
        "ip_address": (ctx.ip_address if ctx else ""),
        "user_agent": (ctx.user_agent if ctx else ""),
        "method": (ctx.method if ctx else ""),
        "path": (ctx.path if ctx else ""),
        "resource_type": resource_type,
        "resource_id": _resource_id(obj),
        "action": action,
        "status_code": 0,  # not known at flush time; updated by middleware
        "old_values": to_json(old) if old else "{}",
        "new_values": to_json(new) if new else "{}",
        "changed_fields": sorted(set(old.keys()) | set(new.keys())) if (old or new) else [],
        "duration_ms": 0,
        "error_message": "",
    }


def _on_before_flush(session: Session, flush_context, instances) -> None:
    ctx = get_context()
    # No context → called from a system task (not a request). Skip to avoid
    # polluting the audit log with scheduler internals.
    if ctx is None:
        return

    try:
        for obj in session.new:
            new = _model_to_dict(obj)
            row = _build_row("create", obj, {}, new)
            if row:
                ctx.mutations.append(row)

        for obj in session.dirty:
            if not session.is_modified(obj, include_collections=False):
                continue
            old = _old_values_from_history(obj)
            new = _changed_new_values(obj)
            if not old and not new:
                continue
            row = _build_row("update", obj, old, new)
            if row:
                ctx.mutations.append(row)

        for obj in session.deleted:
            old = _model_to_dict(obj)
            row = _build_row("delete", obj, old, {})
            if row:
                ctx.mutations.append(row)
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit_capture_failed", error=str(exc))


def install_listeners() -> None:
    """Register the before_flush listener on the global Session class.

    AsyncSession wraps a sync Session under the hood and the `before_flush`
    event fires on the underlying sync session, so this catches async flushes
    as well as any sync session usage.
    """
    event.listen(Session, "before_flush", _on_before_flush)
