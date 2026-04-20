"""WebSocket client for the central command channel.

Maintains a persistent WebSocket connection to central. Central can send
commands (poll_device, config_reload, etc.) and the collector responds.
Reconnects automatically with soft backoff on disconnect.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime, timezone
from typing import Callable, Awaitable

import aiohttp
import structlog

logger = structlog.get_logger()

_BACKOFF_STEPS = [1, 2, 3, 5]
# Fleet-wide reconnect storms are the concern — when central drops, every worker
# tries to reconnect on the same cadence. Spread each step by ±30% so 4 workers
# don't pile onto central at the same second.
_BACKOFF_JITTER_FRACTION = 0.3


class WebSocketClient:
    """Persistent WebSocket client for collector → central command channel."""

    def __init__(
        self,
        central_url: str,
        api_key: str,
        node_id: str,
        verify_ssl: bool = True,
        collector_id: str = "",
    ):
        ws_url = central_url.replace("https://", "wss://").replace("http://", "ws://")
        # Auth goes in the Authorization header (F-CEN-018) — URL query strings
        # get logged by HAProxy + intermediate proxies, which is a classic
        # token-leak vector. Only the collector_id hint stays in the URL.
        base = f"{ws_url.rstrip('/')}/ws/collector"
        self._ws_url = (
            f"{base}?collector_id={collector_id}" if collector_id else base
        )
        self._api_key = api_key
        self._node_id = node_id
        self._verify_ssl = verify_ssl
        self._handlers: dict[str, Callable[..., Awaitable]] = {}
        self._running = False
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    def register_handler(self, msg_type: str, handler: Callable[..., Awaitable]):
        """Register a handler for a specific message type.

        Handler signature: async def handler(payload: dict) -> dict
        """
        self._handlers[msg_type] = handler

    async def run(self):
        """Main loop: connect, handle messages, reconnect on failure."""
        self._running = True
        attempt = 0

        ssl_ctx = None if self._verify_ssl else False

        while self._running:
            try:
                self._session = aiohttp.ClientSession()
                self._ws = await self._session.ws_connect(
                    self._ws_url,
                    ssl=ssl_ctx,
                    heartbeat=30,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                logger.info("ws_connected", url=self._ws_url.split("?")[0])
                attempt = 0

                async for msg in self._ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(msg.data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.warning("ws_error", error=self._ws.exception())
                        break
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSED,
                    ):
                        break

            except (aiohttp.ClientError, OSError) as exc:
                logger.warning("ws_connect_failed", error=str(exc), attempt=attempt)
            except Exception as exc:
                logger.error("ws_unexpected_error", error=str(exc))
            finally:
                if self._ws and not self._ws.closed:
                    await self._ws.close()
                if self._session:
                    await self._session.close()
                self._ws = None
                self._session = None

            if not self._running:
                break

            base_delay = _BACKOFF_STEPS[min(attempt, len(_BACKOFF_STEPS) - 1)]
            jitter = random.uniform(-_BACKOFF_JITTER_FRACTION, _BACKOFF_JITTER_FRACTION)
            delay = max(0.1, base_delay * (1.0 + jitter))
            logger.info("ws_reconnecting", delay=round(delay, 2), attempt=attempt)
            await asyncio.sleep(delay)
            attempt += 1

    async def stop(self):
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def _handle_message(self, raw: str):
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ws_invalid_json", raw=raw[:200])
            return

        msg_type = message.get("type")
        message_id = message.get("message_id")
        payload = message.get("payload", {})

        if msg_type == "ping":
            await self._send_response(message_id, "pong", {})
            return

        handler = self._handlers.get(msg_type)
        if handler is None:
            logger.warning("ws_unknown_type", type=msg_type)
            await self._send_response(message_id, "error", {
                "code": "UNKNOWN_TYPE",
                "detail": f"No handler for message type: {msg_type}",
            })
            return

        try:
            # Cap every handler at 30s — a hung SNMP probe or wedged sidecar call
            # must not block the WS reader loop from processing other commands.
            result_payload = await asyncio.wait_for(handler(payload), timeout=30.0)
            if msg_type in ("config_reload", "module_update"):
                response_type = f"{msg_type}_ack"
            else:
                response_type = f"{msg_type}_result"
            await self._send_response(message_id, response_type, result_payload)
        except asyncio.TimeoutError:
            logger.error("ws_handler_timeout", type=msg_type)
            await self._send_response(message_id, "error", {
                "code": "HANDLER_TIMEOUT",
                "detail": "TimeoutError",
            })
        except Exception as exc:
            # Log the full error locally, but only return the exception class name
            # over the WS so we don't leak internal detail (paths, creds) to central.
            logger.error("ws_handler_error", type=msg_type, error=str(exc))
            await self._send_response(message_id, "error", {
                "code": "HANDLER_ERROR",
                "detail": type(exc).__name__,
            })

    async def _send_response(self, in_reply_to: str, msg_type: str, payload: dict):
        if self._ws is None or self._ws.closed:
            return
        message = {
            "message_id": str(uuid.uuid4()),
            "type": msg_type,
            "in_reply_to": in_reply_to,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._ws.send_json(message)
