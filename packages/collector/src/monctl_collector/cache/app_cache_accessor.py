"""App cache accessor — the interface apps use to read/write shared cache.

Uses gRPC to communicate with the local cache-node, which owns the SQLite
database and handles sync to central.
"""

from __future__ import annotations

from monctl_collector.peer.client import PeerClient


class AppCacheAccessor:
    """Scoped cache accessor for a single app+device combination.

    Usage in a BasePoller::

        async def poll(self, ctx: PollContext) -> PollResult:
            # Read data written by another app for this device
            interfaces = await ctx.cache.get_from_app(
                discovery_app_id, "discovered_interfaces"
            )
            # Write data for other apps to consume
            await ctx.cache.set("arp_table", {"entries": [...]}, ttl=3600)
    """

    def __init__(self, peer_client: PeerClient, app_id: str, device_id: str) -> None:
        self._client = peer_client
        self._app_id = app_id
        self._device_id = device_id

    async def get(self, key: str) -> dict | None:
        """Read a cache entry. Returns the JSON value or None if missing/expired."""
        return await self._client.app_cache_get(self._app_id, self._device_id, key)

    async def set(self, key: str, value: dict, ttl: int | None = None) -> None:
        """Write a cache entry. Replicated to other collectors in the group."""
        await self._client.app_cache_set(
            self._app_id, self._device_id, key, value,
            ttl_seconds=ttl or 0,
        )

    async def delete(self, key: str) -> None:
        """Delete a cache entry locally."""
        await self._client.app_cache_delete(self._app_id, self._device_id, key)

    async def get_from_app(self, source_app_id: str, key: str) -> dict | None:
        """Read a cache entry written by a different app for the same device."""
        return await self._client.app_cache_get(source_app_id, self._device_id, key)
