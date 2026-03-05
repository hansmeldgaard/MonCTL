"""SWIM-lite gossip protocol for peer failure detection."""

from __future__ import annotations

import asyncio
import random
import time

import httpx
import structlog

from monctl_collector.cluster.membership import MembershipTable, PeerInfo, PeerState

logger = structlog.get_logger()


class GossipProtocol:
    """Simplified SWIM gossip protocol for peer failure detection.

    Every gossip_interval seconds:
    1. Pick a random peer
    2. Send PING
    3. If no response, try indirect probe via other peers
    4. Mark as SUSPECT or DEAD based on results
    """

    def __init__(
        self,
        my_id: str,
        membership: MembershipTable,
        gossip_interval: float = 3.0,
        ping_timeout: float = 1.0,
        indirect_probe_count: int = 2,
    ):
        self.my_id = my_id
        self.membership = membership
        self.gossip_interval = gossip_interval
        self.ping_timeout = ping_timeout
        self.indirect_probe_count = indirect_probe_count
        self._last_gossip_time: float = 0

    async def run(self):
        """Main gossip loop."""
        logger.info("gossip_started", my_id=self.my_id)
        while True:
            try:
                await self._gossip_round()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("gossip_error", error=str(e))
            await asyncio.sleep(self.gossip_interval)

    async def _gossip_round(self):
        """Execute one round of the gossip protocol."""
        # Check if any suspects should be promoted to DEAD
        newly_dead = self.membership.check_suspects()
        for dead_id in newly_dead:
            logger.warning("peer_confirmed_dead", peer_id=dead_id)

        # Pick a random alive or suspect peer to probe
        candidates = [
            p for p in self.membership.get_all_peers()
            if p.collector_id != self.my_id and p.state != PeerState.DEAD
        ]
        if not candidates:
            return

        target = random.choice(candidates)

        # Try direct ping
        alive = await self._ping(target)
        if alive:
            self.membership.mark_alive(target.collector_id)
            return

        # Direct ping failed - try indirect probes
        other_peers = [
            p for p in self.membership.get_alive_peers()
            if p.collector_id != self.my_id and p.collector_id != target.collector_id
        ]
        probers = random.sample(other_peers, min(self.indirect_probe_count, len(other_peers)))

        if probers:
            results = await asyncio.gather(
                *[self._ping_req(prober, target) for prober in probers],
                return_exceptions=True,
            )
            if any(r is True for r in results):
                self.membership.mark_alive(target.collector_id)
                return

        # All probes failed - mark as suspect
        changed = self.membership.mark_suspect(target.collector_id)
        if changed:
            logger.warning("peer_suspected", peer_id=target.collector_id)

    async def _ping(self, peer: PeerInfo) -> bool:
        """Send a direct PING to a peer. Returns True if alive."""
        try:
            async with httpx.AsyncClient(timeout=self.ping_timeout) as client:
                response = await client.post(
                    f"http://{peer.address}:{peer.port}/ping",
                    json={
                        "from": self.my_id,
                        "events": self._get_gossip_events(),
                    },
                )
                if response.status_code == 200:
                    # Process any events in the response
                    data = response.json()
                    if "events" in data:
                        self.membership.apply_events(data["events"])
                    return True
        except Exception:
            pass
        return False

    async def _ping_req(self, prober: PeerInfo, target: PeerInfo) -> bool:
        """Ask a prober to ping the target on our behalf."""
        try:
            async with httpx.AsyncClient(timeout=self.ping_timeout * 2) as client:
                response = await client.post(
                    f"http://{prober.address}:{prober.port}/ping-req",
                    json={
                        "from": self.my_id,
                        "target_address": target.address,
                        "target_port": target.port,
                        "target_id": target.collector_id,
                    },
                )
                if response.status_code == 200:
                    return response.json().get("alive", False)
        except Exception:
            pass
        return False

    def _get_gossip_events(self) -> list[dict]:
        """Get recent membership events to piggyback on messages."""
        events = self.membership.get_recent_events(since=time.time() - 30)
        return [
            {
                "collector_id": e.collector_id,
                "state": e.state.value,
                "incarnation": e.incarnation,
                "timestamp": e.timestamp,
            }
            for e in events
        ]
