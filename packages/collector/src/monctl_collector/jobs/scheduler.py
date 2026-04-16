"""Job scheduler for the cache-node.

Responsibilities:
  1. Sync job definitions from central every `sync_interval` seconds
     (delta-sync using `since` timestamp after first full fetch).
  2. Assign jobs to workers using app-affinity: workers specialise in
     1-3 app types, minimising venv creation on poll-workers.
  3. Track execution profiles (EMA) per job for load calculation.
  4. Expose current load info for heartbeat reporting.

App-affinity assignment algorithm:
  - Sort all jobs deterministically by job_id.
  - Round-robin distribute across sorted worker list.
  - Each job goes to exactly one worker — no duplicates.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import structlog

from monctl_collector.cache.local_cache import LocalCache
from monctl_collector.central.api_client import CentralAPIClient
from monctl_collector.config import SchedulingConfig
from monctl_collector.jobs.models import (
    JobDefinition,
    JobProfile,
    NodeLoadInfo,
    WorkerRegistration,
)

logger = structlog.get_logger()


class JobScheduler:
    """Syncs jobs from central and assigns them to registered workers."""

    def __init__(
        self,
        *,
        node_id: str,
        local_cache: LocalCache,
        central_client: CentralAPIClient,
        config: SchedulingConfig,
        sync_interval: float = 60.0,
        collector_id: str = "",
    ) -> None:
        self._node_id = node_id
        self._cache = local_cache
        self._central = central_client
        self._config = config
        self._sync_interval = sync_interval
        self._collector_id = collector_id

        # All jobs assigned to this collector by central
        self._my_jobs: dict[str, JobDefinition] = {}
        # Registered poll-workers
        self._workers: dict[str, WorkerRegistration] = {}
        # In-memory EMA profiles (authoritative; synced to SQLite asynchronously)
        self._profiles: dict[str, JobProfile] = {}
        # Timestamp of the last successful central sync (for delta-sync)
        self._last_sync: datetime | None = None
        # Counter for periodic full sync (every N cycles, do a full reconciliation)
        self._sync_count: int = 0
        self._full_sync_every: int = 10  # full sync every 10 cycles (~10 minutes)
        # EMA of deadline miss rate for load calculation
        self._deadline_miss_ema: float = 0.0

        self._task: asyncio.Task | None = None
        self._running = False
        self._immediate_triggers: set[str] = set()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> asyncio.Task:
        """Start the background sync loop."""
        self._running = True
        # Do an initial full sync before returning
        await self._initial_load_from_db()
        self._task = asyncio.create_task(self._sync_loop(), name="job_sync")
        logger.info("job_scheduler_started", node_id=self._node_id)
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("job_scheduler_stopped")

    async def trigger_immediate(self, job_id: str) -> bool:
        """Mark a job for immediate execution by the next worker that pulls jobs."""
        if job_id in self._my_jobs:
            self._immediate_triggers.add(job_id)
            logger.info("trigger_immediate_queued", job_id=job_id)
            return True
        # Poll Now is a fleet-wide Redis pub/sub broadcast — every cache-node
        # hears every trigger, so non-owners will always see jobs they don't
        # have. Log at debug; only the owning node's `trigger_immediate_queued`
        # is interesting.
        logger.debug("trigger_immediate_unknown_job", job_id=job_id)
        return False

    def pop_immediate_triggers(self, job_ids: set[str]) -> list[str]:
        """Return and clear immediate triggers matching the given worker's job IDs."""
        matched = self._immediate_triggers & job_ids
        self._immediate_triggers -= matched
        return list(matched)

    async def force_sync(self) -> None:
        """Force an immediate full sync (called via WS config_reload handler).

        Resets _last_sync so the next sync is a full fetch (no delta),
        ensuring one-shot jobs like discovery are picked up.
        """
        self._last_sync = None
        logger.info("force_sync_triggered")
        await self._sync_jobs()

    # ── Background sync loop ─────────────────────────────────────────────────

    async def _initial_load_from_db(self) -> None:
        """Load jobs and profiles from local SQLite on startup.

        This ensures we can serve workers immediately even if central is down.
        """
        job_dicts = await self._cache.get_all_jobs()
        for d in job_dicts:
            try:
                job = _dict_to_job(d)
                self._my_jobs[job.job_id] = job
            except Exception as exc:
                logger.warning("job_load_error", job_id=d.get("job_id"), error=str(exc))

        # Load profiles
        for job_id in self._my_jobs:
            row = await self._cache.get_profile(job_id)
            if row:
                self._profiles[job_id] = _row_to_profile(job_id, row)

        logger.info(
            "scheduler_loaded_from_db",
            jobs=len(self._my_jobs),
            profiles=len(self._profiles),
        )

    async def _sync_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._sync_interval)
            try:
                await self._sync_jobs()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("job_sync_error", error=str(exc))

    async def _sync_jobs(self) -> None:
        """Delta-sync job definitions from central."""
        self._sync_count += 1
        # Periodically force a full sync to catch jobs with old updated_at
        if self._sync_count % self._full_sync_every == 0:
            self._last_sync = None
            logger.debug("forcing_full_sync", cycle=self._sync_count)

        is_full_sync = self._last_sync is None
        try:
            jobs, deleted_ids = await self._central.get_jobs(
                since=self._last_sync,
                collector_id=self._collector_id or None,
            )
        except Exception as exc:
            logger.warning("central_sync_failed", error=str(exc))
            return

        # Record sync time before processing so next call uses this window
        self._last_sync = datetime.now(timezone.utc)

        # Apply deletions
        for job_id in deleted_ids:
            self._my_jobs.pop(job_id, None)
            self._profiles.pop(job_id, None)
            await self._cache.delete_job(job_id)
            logger.debug("job_deleted", job_id=job_id)

        # On full sync (since=None), reconcile: remove jobs no longer in central's set
        if is_full_sync:
            valid_ids = {j.job_id for j in jobs}
            stale_ids = [jid for jid in list(self._my_jobs) if jid not in valid_ids]
            for jid in stale_ids:
                self._my_jobs.pop(jid, None)
                self._profiles.pop(jid, None)
                await self._cache.mark_job_deleted(jid)
                logger.info("job_removed_by_reconcile", job_id=jid)

        # Apply upserts
        for job in jobs:
            if not job.enabled:
                self._my_jobs.pop(job.job_id, None)
                continue

            await self._cache.upsert_job(job)
            self._my_jobs[job.job_id] = job

            # Ensure we have a profile
            if job.job_id not in self._profiles:
                row = await self._cache.get_profile(job.job_id)
                if row:
                    self._profiles[job.job_id] = _row_to_profile(job.job_id, row)
                else:
                    self._profiles[job.job_id] = JobProfile(job_id=job.job_id)

        logger.debug(
            "job_sync_complete",
            my_jobs=len(self._my_jobs),
            deleted=len(deleted_ids),
            changed=len(jobs),
        )

    # ── Worker API (called from gRPC server) ─────────────────────────────────

    def register_worker(self, worker_id: str, loaded_apps: set[tuple[str, str]]) -> None:
        """Register or refresh a poll-worker."""
        existing = self._workers.get(worker_id)
        if existing:
            existing.loaded_apps = loaded_apps
            existing.last_seen = time.time()
        else:
            self._workers[worker_id] = WorkerRegistration(
                worker_id=worker_id,
                loaded_apps=loaded_apps,
            )
            logger.info("worker_registered", worker_id=worker_id, apps=len(loaded_apps))

    def get_jobs_for_worker(
        self,
        worker_id: str,
        loaded_apps: list[tuple[str, str]],
    ) -> list[tuple[JobDefinition, JobProfile]]:
        """Return the jobs assigned to this worker, with their profiles."""
        # Refresh worker registration
        self.register_worker(worker_id, set(loaded_apps))

        if not self._my_jobs:
            return []

        assigned = self._assign_jobs_to_worker(worker_id)
        return [
            (job, self._get_or_create_profile(job.job_id))
            for job in assigned
        ]

    def get_registered_workers(self) -> dict[str, WorkerRegistration]:
        """Return currently registered workers (for status API)."""
        return dict(self._workers)

    def update_job_profile(
        self, job_id: str, execution_time: float, error: bool
    ) -> None:
        """Update the EMA profile after a job execution (called via ReportExecution RPC)."""
        profile = self._get_or_create_profile(job_id)
        profile.update_after_execution(
            actual_time=execution_time,
            alpha=self._config.ema_alpha,
            heavy_threshold=self._config.heavy_threshold,
        )
        if error:
            profile.error_count += 1
            profile.last_error_time = time.time()

        # Persist asynchronously (don't await in a sync method)
        asyncio.create_task(
            self._cache.upsert_profile(profile),
            name=f"persist_profile_{job_id}",
        )

    # ── Load info (for heartbeat reporting) ───────────────────────────────────

    def get_current_load_info(self) -> NodeLoadInfo:
        """Calculate and return the current load score for this node."""
        load_score = 0.0
        for job in self._my_jobs.values():
            profile = self._profiles.get(job.job_id)
            if profile:
                load_score += profile.load_contribution(job.interval)
            else:
                # Conservative estimate: 5s avg / interval
                load_score += 5.0 / max(job.interval, 1)

        worker_count = len(self._workers)
        effective_load = load_score / worker_count if worker_count > 0 else load_score

        return NodeLoadInfo(
            node_id=self._node_id,
            load_score=round(load_score, 4),
            worker_count=worker_count,
            effective_load=round(effective_load, 4),
            deadline_miss_rate=round(self._deadline_miss_ema, 4),
            total_jobs=len(self._my_jobs),
        )

    def get_job_costs(self) -> dict[str, float]:
        """Return {assignment_id: avg_execution_time} for stable profiles.

        Only includes jobs with 3+ executions so the EMA is meaningful.
        """
        costs: dict[str, float] = {}
        for job_id, profile in self._profiles.items():
            if profile.execution_count >= 3 and job_id in self._my_jobs:
                costs[job_id] = round(profile.avg_execution_time, 3)
        return costs

    # ── Private helpers ──────────────────────────────────────────────────────

    def _get_or_create_profile(self, job_id: str) -> JobProfile:
        if job_id not in self._profiles:
            self._profiles[job_id] = JobProfile(job_id=job_id)
        return self._profiles[job_id]

    def _assign_jobs_to_worker(self, worker_id: str) -> list[JobDefinition]:
        """Return the subset of jobs assigned to `worker_id`.

        Algorithm:
          1. Sort all jobs deterministically by job_id.
          2. Round-robin distribute across sorted worker list.
          3. Each job goes to exactly one worker — no duplicates.
        """
        active_workers = sorted(self._workers.keys())
        n_workers = len(active_workers) or 1

        if worker_id not in active_workers:
            # Unknown worker gets nothing until registered
            return []

        worker_pos = active_workers.index(worker_id)
        sorted_jobs = sorted(self._my_jobs.values(), key=lambda j: j.job_id)

        return [job for i, job in enumerate(sorted_jobs) if i % n_workers == worker_pos]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dict_to_job(d: dict) -> JobDefinition:
    return JobDefinition(
        job_id=d["job_id"],
        device_id=d.get("device_id"),
        device_host=d.get("device_host"),
        app_id=d["app_id"],
        app_version=d.get("app_version", "1.0.0"),
        credential_names=d.get("credential_names", []),
        interval=d.get("interval", 60),
        parameters=d.get("parameters", {}),
        role=d.get("role"),
        max_execution_time=d.get("max_execution_time", 120),
        enabled=d.get("enabled", True),
        updated_at=d.get("updated_at", ""),
    )


def _row_to_profile(job_id: str, row: dict) -> JobProfile:
    return JobProfile(
        job_id=job_id,
        avg_execution_time=row.get("avg_execution_time", 5.0),
        last_execution_time=row.get("last_execution_time", 0.0),
        max_execution_time=row.get("max_execution_time", 0.0),
        execution_count=row.get("execution_count", 0),
        error_count=row.get("error_count", 0),
        last_error_time=row.get("last_error_time", 0.0),
        last_run=row.get("last_run", 0.0),
        is_heavy=bool(row.get("is_heavy", 0)),
    )
