"""WebSocket authentication for collector connections."""

from __future__ import annotations

import hmac
import os
import uuid

import structlog
from fastapi import WebSocket
from sqlalchemy import select

from monctl_central.dependencies import get_session_factory
from monctl_central.storage.models import ApiKey, Collector
from monctl_common.utils import hash_api_key

logger = structlog.get_logger()


async def authenticate_ws(
    websocket: WebSocket,
    token: str,
    collector_id_hint: str | None = None,
) -> tuple[uuid.UUID | None, str | None]:
    """Authenticate a WebSocket connection.

    Supports two auth modes:
    1. Individual collector API key (looked up in api_keys table)
    2. Shared secret (MONCTL_COLLECTOR_API_KEY env var) + collector_id query param

    Returns (collector_id, collector_name) on success, (None, None) on failure.
    """
    try:
        factory = get_session_factory()
        async with factory() as db:
            # Mode 1: Try shared secret first.
            # R-CEN-009 — F-CEN-012 hardened the HTTP path with
            # hmac.compare_digest; do the same here so the WS auth path
            # doesn't reintroduce the timing-side-channel.
            shared_secret = os.environ.get("MONCTL_COLLECTOR_API_KEY", "")
            if (
                shared_secret
                and hmac.compare_digest(token, shared_secret)
                and collector_id_hint
            ):
                try:
                    cid = uuid.UUID(collector_id_hint)
                    collector = await db.get(Collector, cid)
                    if collector and collector.status == "ACTIVE":
                        return collector.id, collector.name
                except (ValueError, AttributeError):
                    pass

            # Mode 2: Individual collector API key
            token_hash = hash_api_key(token)
            stmt = select(ApiKey).where(ApiKey.key_hash == token_hash)
            result = await db.execute(stmt)
            api_key = result.scalar_one_or_none()

            if api_key is None or api_key.key_type != "collector":
                await websocket.accept()
                await websocket.close(code=4001, reason="Invalid or unauthorized API key")
                return None, None

            collector = await db.get(Collector, api_key.collector_id)
            if collector is None or collector.status != "ACTIVE":
                await websocket.accept()
                await websocket.close(code=4001, reason="Collector not found or not active")
                return None, None

            return collector.id, collector.name

    except Exception as exc:
        logger.error("ws_auth_error", error=str(exc))
        try:
            await websocket.accept()
            await websocket.close(code=4011, reason="Authentication error")
        except Exception:
            pass
        return None, None
