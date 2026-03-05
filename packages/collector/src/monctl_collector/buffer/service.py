"""Local SQLite buffer for results when central is unreachable."""

from __future__ import annotations

import json
import time

import aiosqlite
import structlog

logger = structlog.get_logger()


class ResultBuffer:
    """SQLite-backed durable buffer for results."""

    def __init__(self, db_path: str, max_size_mb: int = 500):
        self.db_path = db_path
        self.max_size_mb = max_size_mb
        self._db: aiosqlite.Connection | None = None

    async def initialize(self):
        """Initialize the SQLite database."""
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS buffered_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                payload TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                sent INTEGER NOT NULL DEFAULT 0
            )
        """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_unsent ON buffered_results (sent, created_at)"
        )
        await self._db.commit()
        logger.info("buffer_initialized", path=self.db_path)

    async def enqueue(self, payload: dict) -> None:
        """Store a result payload in the buffer."""
        assert self._db is not None
        payload_json = json.dumps(payload, default=str)
        await self._db.execute(
            "INSERT INTO buffered_results (created_at, payload) VALUES (?, ?)",
            (time.time(), payload_json),
        )
        await self._db.commit()

    async def dequeue_batch(self, batch_size: int = 100) -> list[dict]:
        """Fetch the oldest unsent results."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, payload FROM buffered_results WHERE sent = 0 ORDER BY created_at ASC LIMIT ?",
            (batch_size,),
        )
        rows = await cursor.fetchall()
        return [{"id": row[0], "payload": json.loads(row[1])} for row in rows]

    async def mark_sent(self, ids: list[int]) -> None:
        """Mark results as successfully sent."""
        assert self._db is not None
        placeholders = ",".join("?" for _ in ids)
        await self._db.execute(
            f"UPDATE buffered_results SET sent = 1 WHERE id IN ({placeholders})",
            ids,
        )
        await self._db.commit()

    async def mark_failed(self, ids: list[int]) -> None:
        """Increment attempt counter for failed sends."""
        assert self._db is not None
        placeholders = ",".join("?" for _ in ids)
        await self._db.execute(
            f"UPDATE buffered_results SET attempts = attempts + 1 WHERE id IN ({placeholders})",
            ids,
        )
        await self._db.commit()

    async def cleanup(self, max_retries: int = 10) -> None:
        """Remove sent results and entries exceeding max retries."""
        assert self._db is not None
        await self._db.execute("DELETE FROM buffered_results WHERE sent = 1")
        await self._db.execute(
            "DELETE FROM buffered_results WHERE attempts >= ?", (max_retries,)
        )
        await self._db.commit()

    async def count_pending(self) -> int:
        """Count unsent results in the buffer."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM buffered_results WHERE sent = 0"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def close(self):
        """Close the database connection."""
        if self._db:
            await self._db.close()
