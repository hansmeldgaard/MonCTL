"""WebSocket authentication for collector connections."""

from __future__ import annotations

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
) -> tuple[uuid.UUID | None, str | None]:
    """Authenticate a WebSocket connection using a collector API key.

    Returns (collector_id, collector_name) on success, (None, None) on failure.
    On failure, the WebSocket is accepted and then closed with a 4001 code.
    """
    try:
        factory = get_session_factory()
        async with factory() as db:
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
