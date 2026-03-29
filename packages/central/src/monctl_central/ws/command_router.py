"""REST endpoints for sending commands to collectors via WebSocket."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from monctl_central.dependencies import require_collector_auth
from monctl_central.ws.router import manager

logger = structlog.get_logger()
router = APIRouter()


class CommandRequest(BaseModel):
    payload: dict = Field(default_factory=dict)
    timeout: float = Field(default=60.0, ge=5.0, le=300.0)


@router.get("/collectors/{collector_id}/ws-status")
async def get_ws_status(
    collector_id: str,
    auth: dict = Depends(require_collector_auth),
):
    """Check if a collector is connected via WebSocket."""
    cid = uuid.UUID(collector_id)
    info = await manager.get_connection_info(cid)
    return {
        "status": "success",
        "data": {
            "connected": info is not None,
            "connection": info,
        },
    }


@router.get("/collectors/ws-connections")
async def list_ws_connections(
    auth: dict = Depends(require_collector_auth),
):
    """List all active WebSocket connections."""
    return {"status": "success", "data": {"connections": await manager.get_status()}}


@router.post("/collectors/{collector_id}/command/{command_type}")
async def send_command(
    collector_id: str,
    command_type: str,
    request: CommandRequest,
    auth: dict = Depends(require_collector_auth),
):
    """Send an ad-hoc command to a collector via WebSocket."""
    allowed_types = {
        "poll_device", "config_reload", "health_check",
        "module_update", "docker_health", "docker_logs",
        "probe_oids",
    }
    if command_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown command type: {command_type}. Allowed: {sorted(allowed_types)}",
        )

    cid = uuid.UUID(collector_id)
    try:
        result = await manager.send_command(
            cid, command_type, request.payload, timeout=request.timeout,
        )
        return {"status": "success", "data": result}
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collector {collector_id} is not connected via WebSocket",
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Collector {collector_id} did not respond within {request.timeout}s",
        )
