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
    token: str = Query(...),
    collector_id: str | None = Query(None),
):
    """Persistent WebSocket for collector command channel."""
    cid, collector_name = await authenticate_ws(websocket, token, collector_id)
    collector_id = cid
    if collector_id is None:
        return

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
