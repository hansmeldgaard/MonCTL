"""Local SQLite cache for the collector cache-node.

Seven tables:
  cache        — monitoring data with TTL (cleaned periodically)
  jobs         — job definitions, permanent (no TTL)
  job_profiles — execution profiles, permanent (EMA updated in-place)
  apps         — app source code + venv info, permanent
  credentials  — encrypted credentials, permanent (never deleted)
  results      — result buffer for forwarder
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

import aiosqlite

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;

-- 1. Cache data — HAS TTL, cleaned every cleanup_interval seconds
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    value       BLOB NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    created_at  REAL NOT NULL,
    origin_node TEXT NOT NULL,
    is_primary  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cache_expiry ON cache(created_at);

-- 2. Jobs — permanent, no TTL
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    definition_json TEXT NOT NULL,
    home_node     TEXT,
    executing_node TEXT,
    is_mine       INTEGER DEFAULT 0,
    last_synced   REAL NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted       INTEGER DEFAULT 0
);

-- 3. Job profiles — permanent, EMA-updated
CREATE TABLE IF NOT EXISTS job_profiles (
    job_id              TEXT PRIMARY KEY,
    avg_execution_time  REAL DEFAULT 5.0,
    last_execution_time REAL DEFAULT 0.0,
    max_execution_time  REAL DEFAULT 0.0,
    execution_count     INTEGER DEFAULT 0,
    error_count         INTEGER DEFAULT 0,
    last_run            REAL DEFAULT 0.0,
    is_heavy            INTEGER DEFAULT 0
);

-- 4. Apps — permanent, versioned
CREATE TABLE IF NOT EXISTS apps (
    app_id       TEXT NOT NULL,
    version      TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    code_path    TEXT,
    venv_hash    TEXT,
    checksum     TEXT NOT NULL,
    fetched_at   REAL NOT NULL,
    PRIMARY KEY (app_id, version)
);

-- 5. Credentials — encrypted at rest, never deleted
CREATE TABLE IF NOT EXISTS credentials (
    credential_name TEXT PRIMARY KEY,
    credential_type TEXT NOT NULL,
    encrypted_data  BLOB NOT NULL,
    refresh_after   REAL NOT NULL,
    fetched_at      REAL NOT NULL
);

-- 6. Results buffer — for the forwarder
CREATE TABLE IF NOT EXISTS results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    result_json TEXT NOT NULL,
    created_at  REAL NOT NULL,
    sent        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_results_unsent ON results(sent, created_at);

-- 7. App cache — shared data between apps, synced to/from central
CREATE TABLE IF NOT EXISTS app_cache (
    app_id      TEXT NOT NULL,
    device_id   TEXT NOT NULL,
    cache_key   TEXT NOT NULL,
    cache_value TEXT NOT NULL,
    ttl_seconds INTEGER,
    updated_at  REAL NOT NULL,
    dirty       INTEGER DEFAULT 0,
    PRIMARY KEY (app_id, device_id, cache_key)
);
CREATE INDEX IF NOT EXISTS idx_app_cache_dirty ON app_cache(dirty) WHERE dirty = 1;
"""


@dataclass
class CacheEntry:
    key: str
    value: bytes
    ttl_seconds: int
    created_at: float
    origin_node: str
    is_primary: bool = False

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl_seconds

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class LocalCache:
    """Async SQLite-backed local cache for a collector cache-node."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        """Open (or create) the SQLite database."""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ── Cache data ────────────────────────────────────────────────────────────

    async def get(self, key: str) -> CacheEntry | None:
        """Return a cache entry, or None if missing or expired."""
        async with self._db.execute(
            "SELECT * FROM cache WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        entry = CacheEntry(
            key=row["key"],
            value=row["value"],
            ttl_seconds=row["ttl_seconds"],
            created_at=row["created_at"],
            origin_node=row["origin_node"],
            is_primary=bool(row["is_primary"]),
        )
        if entry.is_expired:
            await self.delete(key)
            return None
        return entry

    async def put(
        self,
        key: str,
        value: bytes,
        ttl: int,
        origin_node: str,
        is_primary: bool = False,
    ) -> None:
        await self._db.execute(
            """INSERT INTO cache (key, value, ttl_seconds, created_at, origin_node, is_primary)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value=excluded.value, ttl_seconds=excluded.ttl_seconds,
                 created_at=excluded.created_at, origin_node=excluded.origin_node,
                 is_primary=excluded.is_primary""",
            (key, value, ttl, time.time(), origin_node, int(is_primary)),
        )
        await self._db.commit()

    async def delete(self, key: str) -> None:
        await self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
        await self._db.commit()

    async def cleanup_expired(self) -> int:
        """Delete expired cache rows. Returns number of rows deleted."""
        async with self._db.execute(
            "DELETE FROM cache WHERE (created_at + ttl_seconds) < ?", (time.time(),)
        ) as cur:
            count = cur.rowcount
        await self._db.commit()
        return count

    async def get_keys_for_range(self, start: int, end: int) -> list[str]:
        """Return cache keys whose SHA-256 hash falls in [start, end] on the ring.

        Used during node migration to find keys that need to move.
        """
        import hashlib
        all_keys: list[str] = []
        async with self._db.execute("SELECT key FROM cache") as cur:
            async for row in cur:
                k = row["key"]
                h = int(hashlib.sha256(k.encode()).hexdigest()[:8], 16)
                if start <= h <= end:
                    all_keys.append(k)
        return all_keys

    # ── Jobs ─────────────────────────────────────────────────────────────────

    async def upsert_job(self, job: Any, home_node: str | None = None) -> None:
        """Store or update a job definition."""
        from monctl_collector.jobs.models import JobDefinition
        if isinstance(job, JobDefinition):
            defn = json.dumps({
                "job_id": job.job_id,
                "device_id": job.device_id,
                "device_host": job.device_host,
                "app_id": job.app_id,
                "app_version": job.app_version,
                "credential_names": job.credential_names,
                "interval": job.interval,
                "parameters": job.parameters,
                "role": job.role,
                "max_execution_time": job.max_execution_time,
                "enabled": job.enabled,
                "updated_at": job.updated_at,
            })
            job_id = job.job_id
            updated_at = job.updated_at
        else:
            defn = json.dumps(job)
            job_id = job["job_id"]
            updated_at = job.get("updated_at", "")

        await self._db.execute(
            """INSERT INTO jobs (job_id, definition_json, home_node, last_synced, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(job_id) DO UPDATE SET
                 definition_json=excluded.definition_json,
                 home_node=COALESCE(excluded.home_node, jobs.home_node),
                 last_synced=excluded.last_synced,
                 updated_at=excluded.updated_at,
                 deleted=0""",
            (job_id, defn, home_node, time.time(), updated_at),
        )
        await self._db.commit()

    async def mark_job_deleted(self, job_id: str) -> None:
        await self._db.execute(
            "UPDATE jobs SET deleted=1 WHERE job_id=?", (job_id,)
        )
        await self._db.commit()

    async def delete_job(self, job_id: str) -> None:
        """Permanently remove a job from the database (called when central deletes it)."""
        await self._db.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
        await self._db.commit()

    async def get_all_jobs(self) -> list[dict]:
        """Return all non-deleted job definitions as dicts."""
        jobs = []
        async with self._db.execute(
            "SELECT definition_json, home_node, executing_node, is_mine FROM jobs WHERE deleted=0"
        ) as cur:
            async for row in cur:
                d = json.loads(row["definition_json"])
                d["_home_node"] = row["home_node"]
                d["_executing_node"] = row["executing_node"]
                d["_is_mine"] = bool(row["is_mine"])
                jobs.append(d)
        return jobs

    async def set_job_nodes(
        self, job_id: str, home_node: str | None, executing_node: str | None, is_mine: bool
    ) -> None:
        await self._db.execute(
            """UPDATE jobs SET home_node=?, executing_node=?, is_mine=? WHERE job_id=?""",
            (home_node, executing_node, int(is_mine), job_id),
        )
        await self._db.commit()

    # ── Job Profiles ──────────────────────────────────────────────────────────

    async def get_profile(self, job_id: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM job_profiles WHERE job_id=?", (job_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_profile(self, profile: Any) -> None:
        """Store or update a job profile."""
        from monctl_collector.jobs.models import JobProfile
        if isinstance(profile, JobProfile):
            p = profile
        else:
            return
        await self._db.execute(
            """INSERT INTO job_profiles
               (job_id, avg_execution_time, last_execution_time, max_execution_time,
                execution_count, error_count, last_run, is_heavy)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET
                 avg_execution_time=excluded.avg_execution_time,
                 last_execution_time=excluded.last_execution_time,
                 max_execution_time=excluded.max_execution_time,
                 execution_count=excluded.execution_count,
                 error_count=excluded.error_count,
                 last_run=excluded.last_run,
                 is_heavy=excluded.is_heavy""",
            (
                p.job_id, p.avg_execution_time, p.last_execution_time,
                p.max_execution_time, p.execution_count, p.error_count,
                p.last_run, int(p.is_heavy),
            ),
        )
        await self._db.commit()

    # ── Apps ─────────────────────────────────────────────────────────────────

    async def get_app(self, app_id: str, version: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM apps WHERE app_id=? AND version=?", (app_id, version)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_app(
        self,
        app_id: str,
        version: str,
        metadata: dict,
        code_path: str | None,
        venv_hash: str | None,
        checksum: str,
    ) -> None:
        await self._db.execute(
            """INSERT INTO apps (app_id, version, metadata_json, code_path, venv_hash, checksum, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(app_id, version) DO UPDATE SET
                 metadata_json=excluded.metadata_json,
                 code_path=excluded.code_path,
                 venv_hash=excluded.venv_hash,
                 checksum=excluded.checksum,
                 fetched_at=excluded.fetched_at""",
            (app_id, version, json.dumps(metadata), code_path, venv_hash, checksum, time.time()),
        )
        await self._db.commit()

    # ── Credentials ───────────────────────────────────────────────────────────

    async def get_credential(self, credential_name: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM credentials WHERE credential_name=?", (credential_name,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_credential(
        self,
        credential_name: str,
        credential_type: str,
        encrypted_data: bytes,
        refresh_after: float,
    ) -> None:
        await self._db.execute(
            """INSERT INTO credentials
               (credential_name, credential_type, encrypted_data, refresh_after, fetched_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(credential_name) DO UPDATE SET
                 credential_type=excluded.credential_type,
                 encrypted_data=excluded.encrypted_data,
                 refresh_after=excluded.refresh_after,
                 fetched_at=excluded.fetched_at""",
            (credential_name, credential_type, encrypted_data, refresh_after, time.time()),
        )
        await self._db.commit()

    # ── Results buffer ────────────────────────────────────────────────────────

    async def enqueue_result(self, result: dict) -> None:
        """Add a poll result to the forwarder buffer."""
        await self._db.execute(
            "INSERT INTO results (result_json, created_at) VALUES (?, ?)",
            (json.dumps(result), time.time()),
        )
        await self._db.commit()

    async def dequeue_results(self, limit: int = 100) -> list[tuple[int, dict]]:
        """Return up to `limit` unsent results as (id, result_dict) pairs."""
        rows = []
        async with self._db.execute(
            "SELECT id, result_json FROM results WHERE sent=0 ORDER BY created_at LIMIT ?",
            (limit,),
        ) as cur:
            async for row in cur:
                rows.append((row["id"], json.loads(row["result_json"])))
        return rows

    async def mark_results_sent(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        await self._db.execute(
            f"UPDATE results SET sent=1 WHERE id IN ({placeholders})", ids
        )
        await self._db.commit()

    async def cleanup_sent_results(self, older_than_seconds: int = 86400) -> int:
        """Delete sent results older than `older_than_seconds`. Returns count deleted."""
        cutoff = time.time() - older_than_seconds
        async with self._db.execute(
            "DELETE FROM results WHERE sent=1 AND created_at < ?", (cutoff,)
        ) as cur:
            count = cur.rowcount
        await self._db.commit()
        return count

    # ── App cache (shared across collector group) ─────────────────────────────

    async def app_cache_get(self, app_id: str, device_id: str, key: str) -> dict | None:
        """Read a cache entry. Returns parsed JSON value or None if missing/expired."""
        async with self._db.execute(
            "SELECT cache_value, ttl_seconds, updated_at FROM app_cache "
            "WHERE app_id = ? AND device_id = ? AND cache_key = ?",
            (app_id, device_id, key),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        if row["ttl_seconds"] is not None:
            if time.time() > row["updated_at"] + row["ttl_seconds"]:
                await self._db.execute(
                    "DELETE FROM app_cache WHERE app_id = ? AND device_id = ? AND cache_key = ?",
                    (app_id, device_id, key),
                )
                await self._db.commit()
                return None
        return json.loads(row["cache_value"])

    async def app_cache_set(
        self, app_id: str, device_id: str, key: str, value: dict,
        ttl_seconds: int | None = None,
    ) -> None:
        """Write a cache entry. Marks it dirty for sync to central."""
        now = time.time()
        await self._db.execute(
            """INSERT INTO app_cache (app_id, device_id, cache_key, cache_value, ttl_seconds, updated_at, dirty)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(app_id, device_id, cache_key) DO UPDATE SET
                 cache_value=excluded.cache_value,
                 ttl_seconds=excluded.ttl_seconds,
                 updated_at=excluded.updated_at,
                 dirty=1""",
            (app_id, device_id, key, json.dumps(value), ttl_seconds, now),
        )
        await self._db.commit()

    async def app_cache_delete(self, app_id: str, device_id: str, key: str) -> None:
        """Delete a cache entry locally."""
        await self._db.execute(
            "DELETE FROM app_cache WHERE app_id = ? AND device_id = ? AND cache_key = ?",
            (app_id, device_id, key),
        )
        await self._db.commit()

    async def app_cache_get_dirty(self, limit: int = 500) -> list[dict]:
        """Return dirty entries that need to be pushed to central."""
        rows = []
        async with self._db.execute(
            "SELECT app_id, device_id, cache_key, cache_value, ttl_seconds, updated_at "
            "FROM app_cache WHERE dirty = 1 LIMIT ?",
            (limit,),
        ) as cur:
            async for row in cur:
                rows.append(dict(row))
        return rows

    async def app_cache_mark_clean(self, keys: list[tuple[str, str, str]]) -> None:
        """Mark entries as synced. keys = list of (app_id, device_id, cache_key)."""
        if not keys:
            return
        for app_id, device_id, cache_key in keys:
            await self._db.execute(
                "UPDATE app_cache SET dirty = 0 "
                "WHERE app_id = ? AND device_id = ? AND cache_key = ?",
                (app_id, device_id, cache_key),
            )
        await self._db.commit()

    async def app_cache_upsert_from_central(self, entries: list[dict]) -> None:
        """Merge entries pulled from central into local cache."""
        for e in entries:
            cache_value = e["cache_value"] if isinstance(e["cache_value"], str) else json.dumps(e["cache_value"])
            updated_at = e["updated_at"]
            if isinstance(updated_at, str):
                from datetime import datetime, timezone
                updated_at = datetime.fromisoformat(updated_at).timestamp()
            await self._db.execute(
                """INSERT INTO app_cache (app_id, device_id, cache_key, cache_value, ttl_seconds, updated_at, dirty)
                   VALUES (?, ?, ?, ?, ?, ?, 0)
                   ON CONFLICT(app_id, device_id, cache_key) DO UPDATE SET
                     cache_value = CASE WHEN excluded.updated_at > app_cache.updated_at
                                        THEN excluded.cache_value ELSE app_cache.cache_value END,
                     ttl_seconds = CASE WHEN excluded.updated_at > app_cache.updated_at
                                        THEN excluded.ttl_seconds ELSE app_cache.ttl_seconds END,
                     updated_at = CASE WHEN excluded.updated_at > app_cache.updated_at
                                       THEN excluded.updated_at ELSE app_cache.updated_at END
                """,
                (e["app_id"], e["device_id"], e["cache_key"],
                 cache_value, e.get("ttl_seconds"), updated_at),
            )
        await self._db.commit()
