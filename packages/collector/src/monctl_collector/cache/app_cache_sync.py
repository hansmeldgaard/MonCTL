"""App cache sync loop — runs on the cache-node process.

Pushes dirty local entries to central and pulls updates from central
for the collector's group. Runs every SYNC_INTERVAL seconds.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import structlog

from monctl_collector.cache.local_cache import LocalCache
from monctl_collector.central.api_client import CentralAPIClient

logger = structlog.get_logger()

SYNC_INTERVAL = 10.0  # seconds


class AppCacheSyncLoop:
    def __init__(
        self,
        local_cache: LocalCache,
        central_client: CentralAPIClient,
        node_id: str = "",
    ) -> None:
        self._cache = local_cache
        self._central = central_client
        self._node_id = node_id
        self._last_pull_at: float = 0.0
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> asyncio.Task:
        self._running = True
        self._task = asyncio.create_task(self._run(), name="app_cache_sync")
        logger.info("app_cache_sync_started")
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while self._running:
            try:
                await self._push_dirty()
                await self._pull_updates()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("app_cache_sync_error", error=str(exc))
            await asyncio.sleep(SYNC_INTERVAL)

    async def _push_dirty(self) -> None:
        """Push locally-written entries to central."""
        dirty = await self._cache.app_cache_get_dirty(limit=500)
        if not dirty:
            return

        entries = []
        for row in dirty:
            cache_value = row["cache_value"]
            if isinstance(cache_value, str):
                cache_value = json.loads(cache_value)
            entries.append({
                "app_id": row["app_id"],
                "device_id": row["device_id"],
                "cache_key": row["cache_key"],
                "cache_value": cache_value,
                "ttl_seconds": row["ttl_seconds"],
                "updated_at": datetime.fromtimestamp(
                    row["updated_at"], tz=timezone.utc
                ).isoformat(),
            })

        resp = await self._central.push_app_cache(entries, node_id=self._node_id)
        if resp:
            keys = [(e["app_id"], e["device_id"], e["cache_key"]) for e in entries]
            await self._cache.app_cache_mark_clean(keys)
            logger.debug("app_cache_pushed", count=len(entries))

    async def _pull_updates(self) -> None:
        """Pull entries updated since last pull from central."""
        since = (
            datetime.fromtimestamp(self._last_pull_at, tz=timezone.utc).isoformat()
            if self._last_pull_at > 0
            else None
        )

        has_more = True
        while has_more:
            resp = await self._central.pull_app_cache(since=since, node_id=self._node_id)
            if not resp or not resp.get("entries"):
                break

            await self._cache.app_cache_upsert_from_central(resp["entries"])

            if resp["entries"]:
                last_entry = resp["entries"][-1]
                self._last_pull_at = datetime.fromisoformat(
                    last_entry["updated_at"]
                ).timestamp()
                since = last_entry["updated_at"]

            has_more = resp.get("has_more", False)

        logger.debug("app_cache_pulled", last_pull_at=self._last_pull_at)
