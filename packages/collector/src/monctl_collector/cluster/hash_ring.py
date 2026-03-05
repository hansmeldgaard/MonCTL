"""Consistent hash ring for cache key placement and job home-node assignment.

Uses SHA-256 with 150 virtual nodes (vnodes) per physical node for even distribution.
Supports replication to R physically distinct nodes.

Performance targets:
  - Hash ring lookup: < 0.1ms
  - Job assignment (5000 jobs): < 100ms
"""

from __future__ import annotations

import bisect
import hashlib
from dataclasses import dataclass, field


def _sha256_uint32(text: str) -> int:
    """Hash a string to a uint32 using the first 4 bytes of SHA-256."""
    digest = hashlib.sha256(text.encode()).digest()
    return int.from_bytes(digest[:4], "big")


@dataclass
class HashRing:
    """Consistent hash ring with virtual nodes and replication support.

    The ring is a sorted list of (hash_value, node_id) pairs. Each physical
    node contributes `vnodes_per_node` virtual positions derived from:
        sha256(f"{node_id}:{vnode_index}")

    For replication, `get_nodes(key, count)` walks the ring clockwise from
    the primary node and collects `count` *distinct physical* nodes.
    """

    vnodes_per_node: int = 150
    replication_factor: int = 3

    # Internals — sorted ring and set of current nodes
    _ring: list[tuple[int, str]] = field(default_factory=list, repr=False)
    _nodes: set[str] = field(default_factory=set, repr=False)

    def add_node(self, node_id: str) -> set[str]:
        """Add a node to the ring.

        Returns the set of cache keys (conceptually) that need to migrate TO
        this node (i.e. keys previously owned by the node's successor that now
        belong to the new node). Callers use this for data migration.
        """
        if node_id in self._nodes:
            return set()

        self._nodes.add(node_id)
        for i in range(self.vnodes_per_node):
            h = _sha256_uint32(f"{node_id}:{i}")
            bisect.insort(self._ring, (h, node_id))

        return set()  # Migration detection is handled by distributed_cache

    def remove_node(self, node_id: str) -> set[str]:
        """Remove a node from the ring.

        Returns the set of keys that need to migrate (best-effort; callers
        may use this to trigger key re-replication to new owners).
        """
        if node_id not in self._nodes:
            return set()

        self._nodes.discard(node_id)
        self._ring = [(h, n) for (h, n) in self._ring if n != node_id]
        return set()

    def get_node(self, key: str) -> str | None:
        """Return the primary node for a key, or None if ring is empty."""
        if not self._ring:
            return None
        h = _sha256_uint32(key)
        idx = bisect.bisect_left(self._ring, (h, ""))
        idx = idx % len(self._ring)
        return self._ring[idx][1]

    def get_nodes(self, key: str, count: int) -> list[str]:
        """Return up to `count` distinct physical nodes for a key (primary first).

        Used for replication: primary + R-1 replicas on distinct servers.
        """
        if not self._ring:
            return []
        h = _sha256_uint32(key)
        idx = bisect.bisect_left(self._ring, (h, ""))
        seen: set[str] = set()
        result: list[str] = []
        for i in range(len(self._ring)):
            node = self._ring[(idx + i) % len(self._ring)][1]
            if node not in seen:
                seen.add(node)
                result.append(node)
                if len(result) >= count:
                    break
        return result

    def get_all_nodes(self) -> list[str]:
        """Return all physical nodes currently in the ring."""
        return list(self._nodes)

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._nodes
