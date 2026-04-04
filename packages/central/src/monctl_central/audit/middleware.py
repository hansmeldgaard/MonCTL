"""Audit middleware — populates AuditContext for every request.

This runs on every request (not just mutations). For mutations, after the
response is produced, any rows buffered in `ctx.mutations` by the SQLAlchemy
event listener are forwarded to the audit buffer for batched insert to
ClickHouse.

The middleware also manages the X-Request-Id header (generated if absent,
returned on every response).
"""

from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from monctl_central.audit.buffer import audit_buffer
from monctl_central.audit.context import (
    AuditContext,
    clear_context,
    new_request_id,
    set_context,
)
from monctl_central.audit.request_helpers import get_client_ip, get_user_agent

logger = structlog.get_logger()

REQUEST_ID_HEADER = "X-Request-Id"


class AuditContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER.lower()) or new_request_id()

        ctx = AuditContext(
            request_id=request_id,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            method=request.method,
            path=request.url.path,
        )
        set_context(ctx)

        try:
            response: Response = await call_next(request)
        finally:
            # Flush any mutation rows captured for this request
            if ctx.mutations:
                try:
                    audit_buffer.extend(ctx.mutations)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("audit_buffer_failed", error=str(exc))
            clear_context()

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
