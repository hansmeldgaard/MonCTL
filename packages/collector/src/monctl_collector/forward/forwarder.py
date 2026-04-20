"""Forwarder — reads buffered results from SQLite and posts them to central.

The forwarder runs as a separate process (container) and reads from the
same SQLite database as the cache-node (shared volume).

Behaviour:
  - Polls `results` table for unsent rows every `flush_interval` seconds.
  - Sends batches of up to `batch_size` results to POST /api/v1/results.
  - On success: marks rows as sent (they are cleaned up after 24h).
  - On failure: exponential backoff from 1s → max 300s, then retries.
  - If central is down for extended periods, new results keep accumulating
    in SQLite (design supports 2-3 days of offline buffering).
"""

from __future__ import annotations

import asyncio
import json
import time

import aiohttp
import structlog

from monctl_collector.cache.local_cache import LocalCache
from monctl_collector.config import CentralConfig

logger = structlog.get_logger()

_MIN_BACKOFF = 1.0
_MAX_BACKOFF = 300.0
_BATCH_SIZE = 100
# Cap the forwarder buffer. A 10M-row limit at ~1 KB/row ≈ 10 GB on disk, which
# is the point at which a small-disk collector would crash anyway. Older rows
# are FIFO-dropped past the cap so the container stays alive.
_MAX_BUFFER_ROWS = 10_000_000
_BUFFER_CHECK_INTERVAL = 60.0  # seconds between size-cap checks


class Forwarder:
    """Reads buffered results from SQLite and POSTs them to central."""

    def __init__(
        self,
        *,
        node_id: str,
        local_cache: LocalCache,
        config: CentralConfig,
        flush_interval: float = 5.0,
        batch_size: int = _BATCH_SIZE,
        cleanup_interval: float = 3600.0,
    ) -> None:
        self._node_id = node_id
        self._cache = local_cache
        self._cfg = config
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._cleanup_interval = cleanup_interval
        self._backoff = _MIN_BACKOFF
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_cleanup = 0.0
        self._last_buffer_check = 0.0
        self._dropped_total = 0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> asyncio.Task:
        connector = aiohttp.TCPConnector(ssl=self._cfg.verify_ssl)
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers=self._auth_headers(),
            connector=connector,
        )
        self._running = True
        self._task = asyncio.create_task(self._run(), name="forwarder")
        logger.info("forwarder_started", node_id=self._node_id, central=self._cfg.url)
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("forwarder_stopped")

    # ── Main loop ────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        while self._running:
            try:
                sent = await self._flush_batch()
                if sent > 0:
                    self._backoff = _MIN_BACKOFF  # reset on success
                    logger.debug("results_forwarded", count=sent)
                else:
                    # No pending results — sleep full interval
                    await asyncio.sleep(self._flush_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("forwarder_error", error=str(exc))
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _MAX_BACKOFF)

            # Periodic cleanup of sent rows older than 24h
            now = time.time()
            if now - self._last_cleanup > self._cleanup_interval:
                await self._cleanup()
                self._last_cleanup = now

            # Size-cap check — prevents the buffer from filling the disk when
            # central has been unreachable for days.
            if now - self._last_buffer_check > _BUFFER_CHECK_INTERVAL:
                await self._enforce_size_cap()
                self._last_buffer_check = now

    async def _flush_batch(self) -> int:
        """Send one batch of unsent results. Returns number of results sent."""
        rows = await self._cache.dequeue_results(self._batch_size)
        if not rows:
            return 0

        ids = [row_id for row_id, _ in rows]
        results = [result for _, result in rows]

        url = f"{self._cfg.url.rstrip('/')}/api/v1/results"
        payload = {
            "collector_node": self._node_id,
            "results": results,
        }

        async with self._session.post(url, json=payload) as resp:
            if resp.status in (200, 201, 202, 204):
                await self._cache.mark_results_sent(ids)
                return len(ids)
            elif resp.status == 422:
                # Validation error — bad data, mark as sent anyway to avoid retrying forever
                body = await resp.text()
                logger.error(
                    "results_validation_error",
                    status=resp.status,
                    body=body[:500],
                    count=len(ids),
                )
                await self._cache.mark_results_sent(ids)
                return len(ids)
            else:
                body = await resp.text()
                raise RuntimeError(
                    f"Central returned HTTP {resp.status}: {body[:200]}"
                )

    async def _cleanup(self) -> None:
        """Remove sent results older than 24h from the buffer table."""
        try:
            deleted = await self._cache.cleanup_sent_results(older_than_seconds=86400)
            if deleted:
                logger.info("results_buffer_cleaned", deleted=deleted)
        except Exception as exc:
            logger.warning("cleanup_error", error=str(exc))

    async def _enforce_size_cap(self) -> None:
        """FIFO-drop oldest rows when the buffer exceeds `_MAX_BUFFER_ROWS`."""
        try:
            total = await self._cache.count_results()
            if total <= _MAX_BUFFER_ROWS:
                return
            overshoot = total - _MAX_BUFFER_ROWS
            # Drop 5% extra in one go so we don't re-trigger immediately.
            to_drop = overshoot + (_MAX_BUFFER_ROWS // 20)
            dropped = await self._cache.drop_oldest_results(to_drop)
            self._dropped_total += dropped
            logger.warning(
                "forwarder_buffer_dropped",
                total_before=total,
                dropped=dropped,
                dropped_total=self._dropped_total,
                max_rows=_MAX_BUFFER_ROWS,
            )
        except Exception as exc:
            logger.warning("buffer_cap_check_failed", error=str(exc))

    def _auth_headers(self) -> dict:
        if self._cfg.api_key:
            return {"Authorization": f"Bearer {self._cfg.api_key}"}
        return {}
