"""Request-scoped audit context via contextvars.

The audit middleware populates this on every request so downstream layers
(auth dependency, SQLAlchemy event listeners, route handlers) can access
the current user, IP, request_id, etc. without passing them explicitly.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class AuditContext:
    request_id: str = ""
    user_id: str = ""
    username: str = ""
    auth_type: str = ""
    tenant_id: str = ""
    ip_address: str = ""
    user_agent: str = ""
    method: str = ""
    path: str = ""
    # Mutations captured during the request (populated by SQLA event listener)
    mutations: list[dict] = field(default_factory=list)


_current: ContextVar[AuditContext | None] = ContextVar("audit_context", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def set_context(ctx: AuditContext) -> None:
    _current.set(ctx)


def get_context() -> AuditContext | None:
    return _current.get()


def clear_context() -> None:
    _current.set(None)
