"""Consistent hash ring for distributing assignments across cluster members."""

from __future__ import annotations

import bisect
import hashlib


class ConsistentHashRing:
    """Consistent hash ring with virtual nodes for even distribution.

    Each collector gets multiple virtual nodes (vnodes) on the ring.
    Assignments are hashed to a position and assigned to the next
    collector clockwise (primary) and the one after (backup).
    """

    def __init__(self, vnodes: int = 150):
        self.vnodes = vnodes
        self._ring: list[tuple[int, str]] = []  # (hash_position, collector_id)
        self._sorted_keys: list[int] = []
        self._nodes: set[str] = set()

    def add_node(self, node_id: str) -> None:
        """Add a collector to the ring."""
        if node_id in self._nodes:
            return
        self._nodes.add(node_id)
        for i in range(self.vnodes):
            key = self._hash(f"{node_id}:{i}")
            self._ring.append((key, node_id))
        self._ring.sort(key=lambda x: x[0])
        self._sorted_keys = [k for k, _ in self._ring]

    def remove_node(self, node_id: str) -> None:
        """Remove a collector from the ring."""
        if node_id not in self._nodes:
            return
        self._nodes.discard(node_id)
        self._ring = [(k, n) for k, n in self._ring if n != node_id]
        self._sorted_keys = [k for k, _ in self._ring]

    def get_nodes_for_key(self, key: str, count: int = 2) -> list[str]:
        """Get the primary and backup node(s) for a key.

        Returns up to `count` distinct nodes responsible for this key.
        """
        if not self._ring:
            return []

        hash_val = self._hash(key)
        idx = bisect.bisect_right(self._sorted_keys, hash_val)
        if idx >= len(self._ring):
            idx = 0

        result: list[str] = []
        seen: set[str] = set()
        checked = 0

        while len(result) < count and checked < len(self._ring):
            _, node_id = self._ring[(idx + checked) % len(self._ring)]
            if node_id not in seen:
                seen.add(node_id)
                result.append(node_id)
            checked += 1

        return result

    def get_primary(self, key: str) -> str | None:
        """Get the primary node for a key."""
        nodes = self.get_nodes_for_key(key, count=1)
        return nodes[0] if nodes else None

    def get_my_assignments(
        self, my_node_id: str, all_assignment_ids: list[str], replication_factor: int = 2
    ) -> dict[str, str]:
        """Determine which assignments this node is responsible for.

        Returns a dict of {assignment_id: role} where role is 'primary' or 'backup'.
        """
        my_assignments: dict[str, str] = {}
        for assignment_id in all_assignment_ids:
            nodes = self.get_nodes_for_key(assignment_id, count=replication_factor)
            if my_node_id in nodes:
                role = "primary" if nodes[0] == my_node_id else "backup"
                my_assignments[assignment_id] = role
        return my_assignments

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def nodes(self) -> set[str]:
        return self._nodes.copy()

    @staticmethod
    def _hash(key: str) -> int:
        """Hash a key to a position on the ring [0, 2^32)."""
        digest = hashlib.md5(key.encode()).hexdigest()
        return int(digest[:8], 16)
