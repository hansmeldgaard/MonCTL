"""WebSocket endpoint for collector command channel.

Collectors connect to /ws/collector?token=<api_key> and maintain
a persistent bidirectional channel. Central can push commands
(poll_device, config_reload, health_check, etc.) and collectors
respond with results.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from monctl_central.ws.connection_manager import ConnectionManager
from monctl_central.ws.auth import authenticate_ws

logger = structlog.get_logger()
router = APIRouter()

manager = ConnectionManager()


@router.websocket("/ws/collector")
async def collector_ws(
    websocket: WebSocket,
    token: str | None = Query(None),
    collector_id: str | None = Query(None),
):
    """Persistent WebSocket for collector command channel.

    Auth: prefer `Authorization: Bearer <key>` on the upgrade request.
    Fall back to `?token=<key>` for backwards compatibility with older
    collectors (F-CEN-018). Tokens in URLs leak into HAProxy / proxy
    access logs, so the query path emits a deprecation warning so ops
    can identify stragglers before removing it entirely.
    """
    auth_header = websocket.headers.get("authorization", "")
    effective_token: str | None = None
    used_header = False
    if auth_header.lower().startswith("bearer "):
        effective_token = auth_header[7:].strip()
        used_header = True
    elif token:
        effective_token = token
        logger.warning(
            "ws_auth_query_param_deprecated",
            client_host=websocket.client.host if websocket.client else None,
            hint="Upgrade collector to send Authorization header",
        )

    if not effective_token:
        await websocket.accept()
        await websocket.close(code=4001, reason="Missing auth token")
        return

    cid, collector_name = await authenticate_ws(
        websocket, effective_token, collector_id,
    )
    collector_id = cid
    if collector_id is None:
        return

    if used_header:
        logger.debug("ws_auth_header", collector_id=str(collector_id))

    await websocket.accept()
    await manager.connect(collector_id, collector_name, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            await manager.handle_message(collector_id, data)
    except WebSocketDisconnect:
        logger.info(
            "ws_collector_disconnected",
            collector_id=str(collector_id), name=collector_name,
        )
    except Exception as exc:
        logger.error(
            "ws_collector_error",
            collector_id=str(collector_id), error=str(exc),
        )
    finally:
        manager.disconnect(collector_id)
