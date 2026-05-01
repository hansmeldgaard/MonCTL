"""Async buffer for ClickHouse inserts.

Collects rows in memory and flushes them to ClickHouse either when a size
threshold is reached or on a periodic timer — whichever comes first.

This decouples the HTTP request lifecycle from ClickHouse write latency.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from monctl_central.storage.clickhouse import ClickHouseClient

logger = logging.getLogger(__name__)

# Module-level singleton — set during lifespan startup
_buffer: "ClickHouseWriteBuffer | None" = None


def get_ch_buffer() -> "ClickHouseWriteBuffer | None":
    return _buffer


_FLUSH_INTERVAL_SEC = 2.0
_FLUSH_THRESHOLD_ROWS = 500
_MAX_BUFFER_ROWS = 10_000


class ClickHouseWriteBuffer:
    """Thread-safe async buffer that batches ClickHouse inserts."""

    def __init__(self, ch_client: "ClickHouseClient"):
        self._ch = ch_client
        self._buffers: dict[str, list[dict]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._total_rows = 0
        self._total_flushes = 0
        self._total_flush_ms = 0.0

    async def start(self) -> None:
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush_all()

    async def append(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        async with self._lock:
            self._buffers[table].extend(rows)
            table_size = len(self._buffers[table])

        if table_size >= _FLUSH_THRESHOLD_ROWS:
            await self._flush_table(table)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL_SEC)
            try:
                await self._flush_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ch_buffer_flush_error")

    async def _flush_all(self) -> None:
        async with self._lock:
            tables = list(self._buffers.keys())
        for table in tables:
            await self._flush_table(table)

    async def _flush_table(self, table: str) -> None:
        async with self._lock:
            rows = self._buffers.pop(table, [])
        if not rows:
            return

        t0 = time.monotonic()
        try:
            await asyncio.to_thread(self._ch.insert_by_table, table, rows)
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._total_rows += len(rows)
            self._total_flushes += 1
            self._total_flush_ms += elapsed_ms
        except Exception:
            logger.exception(
                "ch_buffer_insert_error table=%s rows=%d", table, len(rows)
            )
            async with self._lock:
                existing = self._buffers[table]
                # R-CEN-002 — previous behaviour silently fell through to
                # an empty re-buffer when the merged total exceeded the
                # cap, dropping every row of the failed batch with a
                # debug-level warning. Now: keep the newest rows up to
                # the cap (newer rows are usually more useful) and log
                # the actual drop count so operators see what we lost.
                merged = rows + existing
                if len(merged) <= _MAX_BUFFER_ROWS:
                    self._buffers[table] = merged
                else:
                    keep = merged[-_MAX_BUFFER_ROWS:]
                    self._buffers[table] = keep
                    logger.warning(
                        "ch_buffer_overflow table=%s dropped=%d kept=%d",
                        table, len(merged) - len(keep), len(keep),
                    )

    def stats(self) -> dict:
        return {
            "total_rows_flushed": self._total_rows,
            "total_flushes": self._total_flushes,
            "avg_flush_ms": round(
                self._total_flush_ms / max(self._total_flushes, 1), 2
            ),
            "pending_tables": {
                t: len(rows) for t, rows in self._buffers.items() if rows
            },
        }
