"""Cluster manager - orchestrates membership, hash ring, and failover."""

from __future__ import annotations

import asyncio

import structlog

from monctl_collector.cluster.gossip import GossipProtocol
from monctl_collector.cluster.hash_ring import ConsistentHashRing
from monctl_collector.cluster.membership import MembershipTable, PeerState
from monctl_collector.cluster.peer_server import PeerServer
from monctl_collector.config import collector_settings

logger = structlog.get_logger()


class ClusterManager:
    """Manages cluster participation: membership, hash ring, and failover.

    Coordinates the gossip protocol, consistent hash ring, and
    assignment distribution for this collector within its cluster.
    """

    def __init__(self):
        self.my_id = collector_settings.collector_id
        self.membership = MembershipTable(
            suspect_timeout=15.0,
        )
        self.hash_ring = ConsistentHashRing(vnodes=150)
        self.gossip = GossipProtocol(
            my_id=self.my_id,
            membership=self.membership,
            gossip_interval=3.0,
        )
        self.peer_server = PeerServer(
            my_id=self.my_id,
            membership=self.membership,
            port=collector_settings.peer_port,
        )
        self._my_assignments: dict[str, str] = {}  # {assignment_id: role}
        self._all_assignment_ids: list[str] = []
        self._replication_factor: int = 2

    async def run(self):
        """Start cluster participation."""
        # Start peer server
        await self.peer_server.start()

        # Add self to membership
        self.membership.add_peer(
            self.my_id,
            collector_settings.peer_address.split(":")[0] if ":" in collector_settings.peer_address else collector_settings.peer_address,
            collector_settings.peer_port,
        )
        self.membership.mark_alive(self.my_id)
        self.hash_ring.add_node(self.my_id)

        logger.info("cluster_manager_started", my_id=self.my_id)

        # Run gossip and ring update in parallel
        await asyncio.gather(
            self.gossip.run(),
            self._ring_maintenance_loop(),
        )

    async def _ring_maintenance_loop(self):
        """Periodically update the hash ring based on membership changes."""
        while True:
            await asyncio.sleep(5)

            # Sync hash ring with alive members
            alive_ids = {p.collector_id for p in self.membership.get_alive_peers()}
            alive_ids.add(self.my_id)  # Always include self

            current_ring_nodes = self.hash_ring.nodes

            # Add new nodes
            for node_id in alive_ids - current_ring_nodes:
                self.hash_ring.add_node(node_id)
                logger.info("ring_node_added", node_id=node_id)

            # Remove dead nodes
            for node_id in current_ring_nodes - alive_ids:
                if node_id != self.my_id:  # Never remove self
                    self.hash_ring.remove_node(node_id)
                    logger.info("ring_node_removed", node_id=node_id)

            # Recompute my assignments
            if self._all_assignment_ids:
                new_assignments = self.hash_ring.get_my_assignments(
                    self.my_id,
                    self._all_assignment_ids,
                    replication_factor=self._replication_factor,
                )

                # Detect changes
                added = set(new_assignments) - set(self._my_assignments)
                removed = set(self._my_assignments) - set(new_assignments)

                if added or removed:
                    logger.info(
                        "assignments_redistributed",
                        added=len(added),
                        removed=len(removed),
                        total=len(new_assignments),
                        primary=sum(1 for r in new_assignments.values() if r == "primary"),
                        backup=sum(1 for r in new_assignments.values() if r == "backup"),
                    )

                self._my_assignments = new_assignments

    def update_assignments(self, assignment_ids: list[str], replication_factor: int = 2):
        """Update the list of all assignments for this cluster.

        Called when config sync receives new assignments from central.
        """
        self._all_assignment_ids = assignment_ids
        self._replication_factor = replication_factor
        self._my_assignments = self.hash_ring.get_my_assignments(
            self.my_id, assignment_ids, replication_factor
        )

    def get_my_primary_assignments(self) -> list[str]:
        """Get assignment IDs where this collector is the primary."""
        return [aid for aid, role in self._my_assignments.items() if role == "primary"]

    def get_my_backup_assignments(self) -> list[str]:
        """Get assignment IDs where this collector is the backup."""
        return [aid for aid, role in self._my_assignments.items() if role == "backup"]

    def is_primary_for(self, assignment_id: str) -> bool:
        """Check if this collector is the primary for an assignment."""
        return self._my_assignments.get(assignment_id) == "primary"

    async def join_cluster(self, peers: list[dict]):
        """Join the cluster by announcing to known peers."""
        for peer in peers:
            if peer["collector_id"] == self.my_id:
                continue

            self.membership.add_peer(
                peer["collector_id"],
                peer["address"],
                peer["port"],
            )
            self.hash_ring.add_node(peer["collector_id"])

            # Announce ourselves
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.post(
                        f"http://{peer['address']}:{peer['port']}/join",
                        json={
                            "collector_id": self.my_id,
                            "address": collector_settings.peer_address.split(":")[0] if ":" in collector_settings.peer_address else collector_settings.peer_address,
                            "port": collector_settings.peer_port,
                        },
                    )
                    if response.status_code == 200:
                        # Get peer list from response
                        data = response.json()
                        for p in data.get("peers", []):
                            self.membership.add_peer(p["collector_id"], p["address"], p["port"])
                            self.hash_ring.add_node(p["collector_id"])
                        logger.info("joined_via_peer", peer_id=peer["collector_id"])
                        return  # Successfully joined via one peer
            except Exception as e:
                logger.warning("join_peer_failed", peer_id=peer["collector_id"], error=str(e))

        logger.warning("could_not_join_any_peer")
