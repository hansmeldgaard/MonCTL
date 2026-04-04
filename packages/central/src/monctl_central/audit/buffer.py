"""Async batch buffer for audit mutation rows → ClickHouse.

Non-blocking: rows are appended from request handlers, flushed periodically
by a background task. If ClickHouse is unavailable, rows are dropped with a
warning — the audit system must never block the application.
"""

from __future__ import annotations

import asyncio
import threading

import structlog

logger = structlog.get_logger()

_MAX_BUFFER = 5000  # hard cap to prevent unbounded memory growth
_FLUSH_BATCH = 500
_FLUSH_INTERVAL_SEC = 5.0


class AuditBuffer:
    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._lock = threading.Lock()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def extend(self, rows: list[dict]) -> None:
        """Append rows to the buffer. Safe to call from sync or async code."""
        if not rows:
            return
        with self._lock:
            if len(self._rows) >= _MAX_BUFFER:
                # Drop oldest to make room — audit should not OOM the process
                drop = len(self._rows) + len(rows) - _MAX_BUFFER
                self._rows = self._rows[drop:]
                logger.warning("audit_buffer_overflow", dropped=drop)
            self._rows.extend(rows)

    def _drain(self, max_rows: int) -> list[dict]:
        with self._lock:
            if not self._rows:
                return []
            batch = self._rows[:max_rows]
            self._rows = self._rows[max_rows:]
            return batch

    async def _run(self) -> None:
        from monctl_central.dependencies import get_clickhouse

        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_FLUSH_INTERVAL_SEC)
            except TimeoutError:
                pass

            batch = self._drain(_FLUSH_BATCH)
            if not batch:
                continue
            try:
                ch = get_clickhouse()
                # Run blocking insert in thread
                await asyncio.to_thread(ch.insert_audit_mutations, batch)
            except Exception as exc:  # noqa: BLE001
                logger.warning("audit_flush_failed", error=str(exc), rows=len(batch))
                # Drop batch — prefer availability over completeness

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="audit-buffer-flush")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await self._task
            except Exception:  # noqa: BLE001
                pass


audit_buffer = AuditBuffer()
