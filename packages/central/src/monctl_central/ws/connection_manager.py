"""Manages active WebSocket connections and pending requests.

Uses Redis to share connection state across multiple central nodes,
so GET /ws-connections returns ALL connected collectors regardless
of which central node handles the HTTP request.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

import structlog
from fastapi import WebSocket

logger = structlog.get_logger()

REQUEST_TIMEOUT_SECONDS = 60
KEEPALIVE_INTERVAL_SECONDS = 30
_REDIS_WS_PREFIX = "ws:conn:"
_REDIS_WS_TTL = 60  # seconds — refreshed every keepalive ping
_REDIS_CMD_CHANNEL = "ws:commands"
_REDIS_CMD_RESPONSE_PREFIX = "ws:cmd:resp:"


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
                self.last_seen_at = datetime.now(timezone.utc)
                await _redis_set_connection(self.collector_id, self.name,
                                            self.connected_at, self.last_seen_at)
            except Exception as exc:
                logger.info(
                    "ws_keepalive_stopped",
                    collector_id=str(self.collector_id),
                    name=self.name,
                    error=str(exc),
                )
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


async def _get_redis():
    """Get the shared Redis connection (lazy import to avoid circular deps)."""
    from monctl_central.cache import _redis
    return _redis


async def _redis_set_connection(
    collector_id: uuid.UUID, name: str,
    connected_at: datetime, last_seen_at: datetime,
):
    """Write connection info to Redis with TTL."""
    r = await _get_redis()
    if r is None:
        return
    try:
        key = f"{_REDIS_WS_PREFIX}{collector_id}"
        value = json.dumps({
            "collector_id": str(collector_id),
            "name": name,
            "connected_at": connected_at.isoformat(),
            "last_seen_at": last_seen_at.isoformat(),
            "node": os.environ.get("HOSTNAME", "unknown"),
        })
        await r.set(key, value, ex=_REDIS_WS_TTL)
    except Exception as exc:
        logger.debug("ws_redis_set_failed", error=str(exc))


async def _redis_del_connection(collector_id: uuid.UUID):
    """Remove connection info from Redis."""
    r = await _get_redis()
    if r is None:
        return
    try:
        await r.delete(f"{_REDIS_WS_PREFIX}{collector_id}")
    except Exception as exc:
        logger.debug("ws_redis_del_failed", error=str(exc))


async def _redis_get_all_connections() -> list[dict]:
    """Read all WS connections from Redis (across all central nodes)."""
    r = await _get_redis()
    if r is None:
        return []
    try:
        keys = []
        async for key in r.scan_iter(match=f"{_REDIS_WS_PREFIX}*", count=100):
            keys.append(key)
        if not keys:
            return []
        values = await r.mget(keys)
        result = []
        for v in values:
            if v:
                result.append(json.loads(v))
        return result
    except Exception as exc:
        logger.debug("ws_redis_scan_failed", error=str(exc))
        return []


class ConnectionManager:
    """Tracks all active collector WebSocket connections.

    Local in-memory dict for send/receive; Redis for cross-node status queries.
    """

    def __init__(self):
        self._connections: dict[uuid.UUID, CollectorConnection] = {}

    async def connect(self, collector_id: uuid.UUID, name: str, websocket: WebSocket):
        """Register a new collector connection. Replaces any existing."""
        if collector_id in self._connections:
            old = self._connections[collector_id]
            await old.stop_keepalive()
            try:
                await old.websocket.close(code=4000, reason="Replaced by new connection")
            except Exception as exc:
                logger.debug(
                    "ws_stale_close_failed",
                    collector_id=str(collector_id),
                    error=str(exc),
                )

        conn = CollectorConnection(collector_id, name, websocket)
        self._connections[collector_id] = conn
        await conn.start_keepalive()
        await _redis_set_connection(collector_id, name, conn.connected_at, conn.last_seen_at)
        logger.info("ws_collector_connected", collector_id=str(collector_id), name=name)

    def disconnect(self, collector_id: uuid.UUID):
        conn = self._connections.pop(collector_id, None)
        if conn:
            asyncio.ensure_future(conn.stop_keepalive())
            asyncio.ensure_future(_redis_del_connection(collector_id))
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

    def is_connected_local(self, collector_id: uuid.UUID) -> bool:
        """Check local in-memory only (for command routing)."""
        return collector_id in self._connections

    async def is_connected(self, collector_id: uuid.UUID) -> bool:
        """Check if collector is connected on any central node (via Redis)."""
        if collector_id in self._connections:
            return True
        r = await _get_redis()
        if r is None:
            return False
        try:
            return await r.exists(f"{_REDIS_WS_PREFIX}{collector_id}") > 0
        except Exception as exc:
            logger.warning(
                "ws_redis_exists_failed",
                collector_id=str(collector_id),
                error=str(exc),
            )
            return False

    async def get_connection_info(self, collector_id: uuid.UUID) -> dict | None:
        """Get connection info from local or Redis."""
        conn = self._connections.get(collector_id)
        if conn:
            return {
                "collector_id": str(collector_id),
                "name": conn.name,
                "connected_at": conn.connected_at.isoformat(),
                "last_seen_at": conn.last_seen_at.isoformat(),
            }
        r = await _get_redis()
        if r is None:
            return None
        try:
            val = await r.get(f"{_REDIS_WS_PREFIX}{collector_id}")
            if val:
                return json.loads(val)
        except Exception as exc:
            logger.warning(
                "ws_redis_get_failed",
                collector_id=str(collector_id),
                error=str(exc),
            )
        return None

    def get_local_status(self) -> list[dict]:
        """Return connections on this node only (no Redis)."""
        return [
            {
                "collector_id": str(cid),
                "name": conn.name,
                "connected_at": conn.connected_at.isoformat(),
                "last_seen_at": conn.last_seen_at.isoformat(),
            }
            for cid, conn in self._connections.items()
        ]

    async def get_status(self) -> list[dict]:
        """Return all connections across all central nodes (via Redis)."""
        connections = await _redis_get_all_connections()
        if connections:
            return connections
        # Fallback to local-only if Redis unavailable
        return self.get_local_status()

    # ── Cross-node command broadcast via Redis ───────────────────────────────

    async def broadcast_command(
        self,
        collector_id: uuid.UUID,
        msg_type: str,
        payload: dict,
        timeout: float = 10.0,
    ) -> dict:
        """Broadcast a command via Redis so any central node can route it.

        1. Publish command to Redis channel
        2. Wait for response via BLPOP on a per-request key
        """
        # Try local first (fast path)
        conn = self._connections.get(collector_id)
        if conn:
            result = await conn.send_request(msg_type, payload, timeout=timeout)
            # Normalise to the same shape as the Redis-fanout path which
            # unwraps the WS envelope in _handle_broadcast_command.
            if isinstance(result, dict) and "payload" in result:
                return result["payload"]
            return result

        # Broadcast via Redis
        r = await _get_redis()
        if r is None:
            raise KeyError(f"Redis unavailable, collector {collector_id} not connected locally")

        request_id = str(uuid.uuid4())
        response_key = f"{_REDIS_CMD_RESPONSE_PREFIX}{request_id}"

        cmd = json.dumps({
            "request_id": request_id,
            "collector_id": str(collector_id),
            "msg_type": msg_type,
            "payload": payload,
        })

        await r.publish(_REDIS_CMD_CHANNEL, cmd)

        # Wait for response from the node that has the connection
        result = await r.blpop(response_key, timeout=int(timeout))
        if result is None:
            raise asyncio.TimeoutError(
                f"No central node could route command to collector {collector_id}"
            )

        _, raw = result
        return json.loads(raw)

    async def notify_config_reload(
        self,
        collector_ids: Iterable[uuid.UUID],
        timeout: float = 3.0,
    ) -> int:
        """Fire `config_reload` to every collector in parallel.

        Uses :meth:`broadcast_command` so the reload is routed via Redis if the
        collector's WebSocket lives on a different central node. Errors
        per-collector (disconnect, timeout, Redis down) are logged at DEBUG
        and swallowed — a single broken WS must not abort the caller.

        Returns the count of collectors that ACKed within ``timeout``.
        """
        ids = list(collector_ids)
        if not ids:
            return 0

        async def _one(cid: uuid.UUID) -> int:
            try:
                await self.broadcast_command(cid, "config_reload", {}, timeout=timeout)
                return 1
            except Exception as exc:
                logger.debug(
                    "ws_config_reload_failed",
                    collector_id=str(cid),
                    error=str(exc),
                )
                return 0

        results = await asyncio.gather(*(_one(cid) for cid in ids))
        return sum(results)

    async def start_command_listener(self) -> asyncio.Task:
        """Subscribe to Redis command channel and route to local connections.

        Each central node runs this listener. When a command arrives,
        only the node with the local WebSocket connection handles it.
        """
        task = asyncio.create_task(self._command_listener_loop(), name="ws_cmd_listener")
        logger.info("ws_command_listener_started")
        return task

    async def _command_listener_loop(self):
        """Background loop: subscribe to Redis, handle commands for local collectors."""
        while True:
            try:
                r = await _get_redis()
                if r is None:
                    await asyncio.sleep(5)
                    continue

                pubsub = r.pubsub()
                await pubsub.subscribe(_REDIS_CMD_CHANNEL)

                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        await self._handle_broadcast_command(json.loads(message["data"]))
                    except Exception as exc:
                        logger.warning("ws_broadcast_cmd_error", error=str(exc))

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("ws_cmd_listener_error", error=str(exc))
                await asyncio.sleep(2)

    async def _handle_broadcast_command(self, cmd: dict):
        """Handle a broadcast command if we have the collector connected locally."""
        collector_id = uuid.UUID(cmd["collector_id"])
        conn = self._connections.get(collector_id)
        if not conn:
            return  # Not on this node — another node will handle it

        logger.debug("ws_broadcast_handling", collector_id=str(collector_id), request_id=cmd["request_id"])

        request_id = cmd["request_id"]
        response_key = f"{_REDIS_CMD_RESPONSE_PREFIX}{request_id}"

        try:
            result = await conn.send_request(
                cmd["msg_type"], cmd["payload"], timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response = result.get("payload", result) if isinstance(result, dict) else result
        except asyncio.TimeoutError:
            response = {"success": False, "error": "Collector did not respond in time"}
        except Exception as exc:
            response = {"success": False, "error": str(exc)}

        r = await _get_redis()
        if r:
            await r.lpush(response_key, json.dumps(response))
            await r.expire(response_key, 30)  # cleanup after 30s

