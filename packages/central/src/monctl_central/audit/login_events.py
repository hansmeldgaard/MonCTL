"""Helper for writing authentication audit events to PostgreSQL."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401  (kept for callers typing)

from monctl_central.audit.context import get_context
from monctl_central.storage.models import AuditLoginEvent

logger = structlog.get_logger()


async def record_login_event(
    db: AsyncSession,
    *,
    event_type: str,
    username: str,
    user_id: uuid.UUID | None = None,
    failure_reason: str | None = None,
    auth_type: str = "cookie",
    tenant_id: uuid.UUID | None = None,
) -> None:
    """Insert an audit_login_events row.

    Uses its OWN session so that login failures — which raise HTTPException
    and trigger the request-session rollback — still commit the audit row.
    The `db` parameter is ignored but kept for API stability.

    Pulls ip_address, user_agent, and request_id from the current AuditContext.
    Failures to write are logged but not raised — login flows must not break
    because audit storage is unavailable.
    """
    _ = db  # intentionally unused; see docstring
    ctx = get_context()
    ip = ctx.ip_address if ctx else None
    ua = ctx.user_agent if ctx else None
    req_id = ctx.request_id if ctx else None

    try:
        from monctl_central.dependencies import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            session.add(
                AuditLoginEvent(
                    event_type=event_type,
                    user_id=user_id,
                    username=username or "",
                    ip_address=ip,
                    user_agent=ua,
                    auth_type=auth_type,
                    failure_reason=failure_reason,
                    request_id=req_id,
                    tenant_id=tenant_id,
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "audit_login_event_failed",
            event_type=event_type,
            username=username,
            error=str(exc),
        )
