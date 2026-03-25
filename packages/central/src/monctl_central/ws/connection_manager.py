"""Manages active WebSocket connections and pending requests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import WebSocket

logger = structlog.get_logger()

REQUEST_TIMEOUT_SECONDS = 60
KEEPALIVE_INTERVAL_SECONDS = 30


class CollectorConnection:
    """Represents one active WebSocket connection from a collector."""

    def __init__(self, collector_id: uuid.UUID, name: str, websocket: WebSocket):
        self.collector_id = collector_id
        self.name = name
        self.websocket = websocket
        self.connected_at = datetime.now(timezone.utc)
        self.last_seen_at = datetime.now(timezone.utc)
        self._pending: dict[str, asyncio.Future] = {}
        self._keepalive_task: asyncio.Task | None = None

    async def start_keepalive(self):
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def stop_keepalive(self):
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass

    async def _keepalive_loop(self):
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
            try:
                await self.send({
                    "message_id": str(uuid.uuid4()),
                    "type": "ping",
                    "in_reply_to": None,
                    "payload": {},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                break

    async def send(self, message: dict) -> None:
        await self.websocket.send_json(message)

    async def send_request(
        self, msg_type: str, payload: dict, timeout: float = REQUEST_TIMEOUT_SECONDS
    ) -> dict:
        """Send a request and wait for a response with matching in_reply_to."""
        message_id = str(uuid.uuid4())
        message = {
            "message_id": message_id,
            "type": msg_type,
            "in_reply_to": None,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[message_id] = future

        try:
            await self.send(message)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "ws_request_timeout", collector=self.name,
                type=msg_type, message_id=message_id,
            )
            raise
        finally:
            self._pending.pop(message_id, None)

    def resolve_response(self, message: dict) -> bool:
        """Try to match an incoming message to a pending request."""
        in_reply_to = message.get("in_reply_to")
        if in_reply_to and in_reply_to in self._pending:
            future = self._pending.pop(in_reply_to)
            if not future.done():
                future.set_result(message)
            return True
        return False


class ConnectionManager:
    """Tracks all active collector WebSocket connections."""

    def __init__(self):
        self._connections: dict[uuid.UUID, CollectorConnection] = {}

    async def connect(self, collector_id: uuid.UUID, name: str, websocket: WebSocket):
        """Register a new collector connection. Replaces any existing."""
        if collector_id in self._connections:
            old = self._connections[collector_id]
            await old.stop_keepalive()
            try:
                await old.websocket.close(code=4000, reason="Replaced by new connection")
            except Exception:
                pass

        conn = CollectorConnection(collector_id, name, websocket)
        self._connections[collector_id] = conn
        await conn.start_keepalive()
        logger.info("ws_collector_connected", collector_id=str(collector_id), name=name)

    def disconnect(self, collector_id: uuid.UUID):
        conn = self._connections.pop(collector_id, None)
        if conn:
            asyncio.ensure_future(conn.stop_keepalive())
            logger.info("ws_collector_removed", collector_id=str(collector_id), name=conn.name)

    async def handle_message(self, collector_id: uuid.UUID, data: dict):
        conn = self._connections.get(collector_id)
        if not conn:
            return

        conn.last_seen_at = datetime.now(timezone.utc)

        if conn.resolve_response(data):
            return

        msg_type = data.get("type")
        if msg_type == "pong":
            return

        logger.debug("ws_unsolicited_message", collector_id=str(collector_id), type=msg_type)

    async def send_command(
        self,
        collector_id: uuid.UUID,
        msg_type: str,
        payload: dict,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> dict:
        """Send a command to a collector and wait for a response."""
        conn = self._connections.get(collector_id)
        if not conn:
            raise KeyError(f"Collector {collector_id} not connected via WebSocket")
        return await conn.send_request(msg_type, payload, timeout=timeout)

    def is_connected(self, collector_id: uuid.UUID) -> bool:
        return collector_id in self._connections

    def get_status(self) -> list[dict]:
        return [
            {
                "collector_id": str(cid),
                "name": conn.name,
                "connected_at": conn.connected_at.isoformat(),
                "last_seen_at": conn.last_seen_at.isoformat(),
            }
            for cid, conn in self._connections.items()
        ]

    def get_connection_info(self, collector_id: uuid.UUID) -> dict | None:
        conn = self._connections.get(collector_id)
        if not conn:
            return None
        return {
            "collector_id": str(collector_id),
            "name": conn.name,
            "connected_at": conn.connected_at.isoformat(),
            "last_seen_at": conn.last_seen_at.isoformat(),
        }
