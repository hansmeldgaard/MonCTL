"""Distributed cache — transparent read/write across the cluster.

Get strategy (local-first):
  1. Check local SQLite
  2. Determine primary node via consistent hash ring
  3. If primary == us → we are authoritative (local miss = global miss for this key)
  4. Ask primary via gRPC
  5. On primary miss: try up to R-1 replicas
  6. On any remote hit: store locally with shorter TTL for next-hit acceleration

Put strategy (replicate asynchronously):
  1. Always write locally first (guarantees local durability)
  2. If we are the primary: fire-and-forget replicate to R-1 replica nodes
  3. Replicas that receive is_replica=True do NOT re-replicate (breaks cycles)
"""

from __future__ import annotations

import asyncio
import time

import structlog

from monctl_collector.cache.local_cache import CacheEntry, LocalCache
from monctl_collector.cluster.hash_ring import HashRing
from monctl_collector.cluster.membership import MembershipTable, MemberStatus
from monctl_collector.peer.client import PeerChannelPool

logger = structlog.get_logger()


class DistributedCache:
    """Distributed cache layer on top of LocalCache + gRPC peer clients."""

    def __init__(
        self,
        *,
        node_id: str,
        local_cache: LocalCache,
        channel_pool: PeerChannelPool,
        hash_ring: HashRing,
        membership: MembershipTable,
        replication_factor: int = 3,
        remote_cache_ttl: int = 300,
    ) -> None:
        self._node_id = node_id
        self._local = local_cache
        self._pool = channel_pool
        self._ring = hash_ring
        self._membership = membership
        self._R = replication_factor
        self._remote_ttl = remote_cache_ttl

    # ── Public API ───────────────────────────────────────────────────────────

    async def get(self, key: str) -> CacheEntry | None:
        """Return the cache entry for `key`, searching locally then remotely.

        Returns None if the key is not found anywhere in the cluster.
        """
        # 1. Local hit — fastest path
        entry = await self._local.get(key)
        if entry is not None:
            return entry

        # 2. Who owns this key?
        nodes = self._ring.get_nodes(key, self._R)
        if not nodes:
            return None

        primary_id = nodes[0]

        # 3. We are the primary — if it's not in our local cache it doesn't exist
        if primary_id == self._node_id:
            return None

        # 4. Try primary first, then replicas
        search_order = nodes  # [primary, replica1, replica2, ...]
        for node_id in search_order:
            if node_id == self._node_id:
                continue  # already checked locally

            member = self._membership.get(node_id)
            if member is None or member.status != MemberStatus.ALIVE:
                continue

            try:
                client = await self._pool.get(member.address)
                resp = await client.get_cache(key)
                if resp is not None and resp.found:
                    # Cache locally for future requests (shorter TTL)
                    ttl = min(resp.ttl or self._remote_ttl, self._remote_ttl)
                    await self._local.put(
                        key, resp.value, ttl,
                        origin_node=resp.origin_node or node_id,
                        is_primary=False,
                    )
                    return CacheEntry(
                        key=key,
                        value=resp.value,
                        ttl_seconds=ttl,
                        created_at=resp.created_at or time.time(),
                        origin_node=resp.origin_node or node_id,
                        is_primary=False,
                    )
            except Exception as exc:
                logger.debug("dist_cache_get_error", key=key, node=node_id, error=str(exc))

        return None

    async def put(
        self,
        key: str,
        value: bytes,
        ttl: int,
        origin_node: str = "",
        is_primary: bool = True,
    ) -> None:
        """Write `key` locally and, if we are the primary, replicate async.

        Args:
            key: cache key
            value: serialised value bytes
            ttl: time-to-live in seconds
            origin_node: node that originated this value (for provenance)
            is_primary: if True, trigger async replication to replicas.
                        Replicas set this to False to prevent chained replication.
        """
        await self._local.put(
            key, value, ttl,
            origin_node=origin_node or self._node_id,
            is_primary=is_primary,
        )

        if not is_primary:
            return

        # Determine replica nodes (exclude ourselves — we already wrote locally)
        nodes = self._ring.get_nodes(key, self._R)
        replicas = [n for n in nodes if n != self._node_id]
        if not replicas:
            return

        replica_addresses: list[str] = []
        for replica_id in replicas:
            member = self._membership.get(replica_id)
            if member and member.status == MemberStatus.ALIVE:
                replica_addresses.append(member.address)

        if replica_addresses:
            asyncio.create_task(
                self._replicate(key, value, ttl, origin_node or self._node_id, replica_addresses),
                name=f"replicate_{key[:20]}",
            )

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _replicate(
        self,
        key: str,
        value: bytes,
        ttl: int,
        origin_node: str,
        replica_addresses: list[str],
    ) -> None:
        """Best-effort async replication to replica nodes.

        Errors are logged but not propagated — the primary copy is already written.
        """
        for address in replica_addresses:
            try:
                client = await self._pool.get(address)
                await client.put_cache(
                    key, value, ttl, origin_node, is_replica=True
                )
            except Exception as exc:
                logger.debug(
                    "replication_failed",
                    key=key,
                    replica=address,
                    error=str(exc),
                )
