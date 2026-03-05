"""Lightweight HTTP server for peer-to-peer gossip communication."""

from __future__ import annotations

import asyncio
import json

import httpx
import structlog
from aiohttp import web

from monctl_collector.cluster.membership import MembershipTable

logger = structlog.get_logger()


class PeerServer:
    """HTTP server that handles gossip protocol messages from peers."""

    def __init__(
        self,
        my_id: str,
        membership: MembershipTable,
        host: str = "0.0.0.0",
        port: int = 9901,
    ):
        self.my_id = my_id
        self.membership = membership
        self.host = host
        self.port = port
        self._app = web.Application()
        self._setup_routes()

    def _setup_routes(self):
        self._app.router.add_post("/ping", self._handle_ping)
        self._app.router.add_post("/ping-req", self._handle_ping_req)
        self._app.router.add_post("/join", self._handle_join)
        self._app.router.add_post("/state", self._handle_state)
        self._app.router.add_get("/health", self._handle_health)

    async def start(self):
        """Start the peer server."""
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info("peer_server_started", host=self.host, port=self.port)

    async def _handle_ping(self, request: web.Request) -> web.Response:
        """Handle a PING from a peer - respond with ACK and gossip events."""
        data = await request.json()
        from_id = data.get("from")

        # Mark the sender as alive
        if from_id:
            self.membership.mark_alive(from_id)

        # Apply any gossip events from the sender
        if "events" in data:
            self.membership.apply_events(data["events"])

        # Respond with our own recent events
        import time
        events = self.membership.get_recent_events(since=time.time() - 30)
        response_events = [
            {
                "collector_id": e.collector_id,
                "state": e.state.value,
                "incarnation": e.incarnation,
                "timestamp": e.timestamp,
            }
            for e in events
        ]

        return web.json_response({"status": "ok", "from": self.my_id, "events": response_events})

    async def _handle_ping_req(self, request: web.Request) -> web.Response:
        """Handle an indirect probe request - ping the target on behalf of requester."""
        data = await request.json()
        target_address = data["target_address"]
        target_port = data["target_port"]

        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                response = await client.post(
                    f"http://{target_address}:{target_port}/ping",
                    json={"from": self.my_id, "events": []},
                )
                alive = response.status_code == 200
        except Exception:
            alive = False

        return web.json_response({"alive": alive})

    async def _handle_join(self, request: web.Request) -> web.Response:
        """Handle a new member joining the cluster."""
        data = await request.json()
        collector_id = data["collector_id"]
        address = data["address"]
        port = data["port"]

        self.membership.add_peer(collector_id, address, port)
        self.membership.mark_alive(collector_id)
        logger.info("peer_joined", peer_id=collector_id, address=f"{address}:{port}")

        # Return full membership state
        peers = [
            {
                "collector_id": p.collector_id,
                "address": p.address,
                "port": p.port,
                "state": p.state.value,
            }
            for p in self.membership.get_all_peers()
        ]

        return web.json_response({"status": "ok", "peers": peers})

    async def _handle_state(self, request: web.Request) -> web.Response:
        """Exchange full membership state (used on startup)."""
        peers = [
            {
                "collector_id": p.collector_id,
                "address": p.address,
                "port": p.port,
                "state": p.state.value,
            }
            for p in self.membership.get_all_peers()
        ]
        return web.json_response({"peers": peers})

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Peer health check."""
        alive_count = len(self.membership.get_alive_peers())
        total = len(self.membership.get_all_peers())
        return web.json_response({
            "status": "healthy",
            "collector_id": self.my_id,
            "peers_alive": alive_count,
            "peers_total": total,
        })
