"""Poll engine for the poll-worker process.

The engine runs on a poll-worker and:
  1. Registers itself with the local cache-node (via gRPC RegisterWorker).
  2. Pulls job assignments from the cache-node (via gRPC GetMyJobs).
  3. Maintains a min-heap deadline queue (earliest-due job first).
  4. Runs jobs using two semaphores:
       - light_sem: max 45 concurrent light jobs (avg < 30s)
       - heavy_sem: max 5  concurrent heavy jobs  (avg ≥ 30s)
  5. Reports results back to cache-node (via gRPC SubmitResult).
  6. Reports execution time to cache-node (via gRPC ReportExecution).
  7. Refreshes job list from cache-node every `refresh_interval` seconds.
"""

from __future__ import annotations

import asyncio
import heapq
import time
import traceback
from dataclasses import dataclass, field

import ctypes
import gc

import structlog

from monctl_collector.apps.manager import AppManager

# glibc malloc_trim — returns freed memory to OS
try:
    _libc = ctypes.CDLL("libc.so.6")
    _malloc_trim = _libc.malloc_trim
except Exception:
    _malloc_trim = None
from monctl_collector.central.credentials import CredentialManager
from monctl_collector.config import SchedulingConfig
from monctl_collector.jobs.models import (
    ConnectorBinding,
    JobDefinition,
    JobProfile,
    PollContext,
    PollResult,
    ScheduledJob,
)
from monctl_collector.cache.app_cache_accessor import AppCacheAccessor
from monctl_collector.peer.client import PeerChannelPool

logger = structlog.get_logger()

_REFRESH_INTERVAL = 10.0  # seconds between job-list refresh from cache-node


@dataclass
class _RunningJob:
    job_id: str
    started_at: float = field(default_factory=time.time)


class PollEngine:
    """Min-heap deadline scheduler with light/heavy semaphore lanes."""

    def __init__(
        self,
        *,
        worker_id: str,
        cache_node_address: str,
        app_manager: AppManager,
        credential_manager: CredentialManager,
        config: SchedulingConfig,
        channel_pool: PeerChannelPool,
        refresh_interval: float = _REFRESH_INTERVAL,
    ) -> None:
        self._worker_id = worker_id
        self._cache_address = cache_node_address
        self._apps = app_manager
        self._creds = credential_manager
        self._cfg = config
        self._pool = channel_pool
        self._refresh_interval = refresh_interval

        # Min-heap: sorted by next_deadline (ScheduledJob is dataclass(order=True))
        self._heap: list[ScheduledJob] = []
        # Semaphores for light/heavy concurrency control
        self._light_sem = asyncio.Semaphore(config.light_slots)
        self._heavy_sem = asyncio.Semaphore(config.heavy_slots)
        # Currently loaded app types (for affinity reporting)
        self._loaded_apps: set[tuple[str, str]] = set()
        # Set of job_ids currently running (prevent double-scheduling)
        self._running: set[str] = set()

        self._running_flag = False
        self._task: asyncio.Task | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> asyncio.Task:
        """Register with cache-node and start the polling loop."""
        self._running_flag = True
        self._task = asyncio.create_task(self._run(), name="poll_engine")
        logger.info("poll_engine_started", worker_id=self._worker_id)
        return self._task

    async def stop(self) -> None:
        self._running_flag = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("poll_engine_stopped")

    # ── Main loop ────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        """Interleave job refresh and deadline dispatch."""
        last_refresh = 0.0
        while self._running_flag:
            now = time.time()

            # Refresh job list periodically
            if now - last_refresh >= self._refresh_interval:
                await self._refresh_jobs()
                last_refresh = time.time()

            # Dispatch overdue jobs
            await self._dispatch_ready()

            # Sleep until next deadline or refresh, whichever comes first
            next_deadline = self._heap[0].next_deadline if self._heap else now + 1.0
            next_refresh = last_refresh + self._refresh_interval
            sleep_until = min(next_deadline, next_refresh)
            sleep_time = max(0.0, sleep_until - time.time())
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    async def _refresh_jobs(self) -> None:
        """Pull updated job list from cache-node via gRPC."""
        try:
            client = await self._pool.get(self._cache_address)
            await client.register_worker(self._worker_id, list(self._loaded_apps))
            raw_jobs, immediate_ids = await client.get_my_jobs(self._worker_id, list(self._loaded_apps))
        except Exception as exc:
            logger.warning("job_refresh_failed", error=str(exc))
            return

        if not raw_jobs:
            # Cache-node returned no jobs — clear the heap so we stop executing
            if self._heap:
                logger.info("jobs_cleared", previous=len(self._heap))
                self._heap.clear()
                self._loaded_apps.clear()
            logger.debug("job_list_refreshed", total=0)
            return

        # Convert flat dicts from gRPC to (JobDefinition, JobProfile) pairs
        job_pairs: list[tuple[JobDefinition, JobProfile]] = []
        for j in raw_jobs:
            bindings = [
                ConnectorBinding(
                    alias=b["alias"],
                    connector_id=b["connector_id"],
                    connector_version_id=b["connector_version_id"],
                    credential_name=b.get("credential_name"),
                    use_latest=b.get("use_latest", False),
                    settings=b.get("settings", {}),
                    connector_checksum=b.get("connector_checksum", ""),
                )
                for b in j.get("connector_bindings", [])
            ]
            job_def = JobDefinition(
                job_id=j["job_id"],
                device_id=j.get("device_id") or None,
                device_host=j.get("device_host") or None,
                app_id=j["app_id"],
                app_version=j.get("app_version", "1.0.0"),
                credential_names=j.get("credential_names", []),
                interval=j.get("interval", 60),
                parameters=j.get("parameters", {}),
                role=j.get("role") or None,
                max_execution_time=j.get("max_execution_time", 120),
                app_checksum=j.get("app_checksum", ""),
                connector_bindings=bindings,
            )
            profile = JobProfile(
                job_id=j["job_id"],
                avg_execution_time=j.get("avg_execution_time", 5.0),
                is_heavy=j.get("is_heavy", False),
            )
            job_pairs.append((job_def, profile))

        # Rebuild heap (keeping in-progress jobs)
        # Track previous (deadline, interval) so we can detect interval changes
        # and reset the deadline — otherwise shortening an interval wouldn't take
        # effect until the stale (longer) deadline fires.
        existing: dict[str, tuple[float, int]] = {
            sj.job_id: (sj.next_deadline, sj.job.interval) for sj in self._heap
        }
        self._heap.clear()

        now = time.time()
        for job_def, profile in job_pairs:
            prev = existing.get(job_def.job_id)
            if prev is None:
                # Brand-new job — jittered first deadline
                deadline = now + (hash(job_def.job_id) % max(1, job_def.interval))
            elif prev[1] != job_def.interval:
                # Interval changed — re-jitter on the new cadence so the change
                # takes effect immediately instead of waiting out the old deadline.
                deadline = now + (hash(job_def.job_id) % max(1, job_def.interval))
                logger.info(
                    "job_interval_changed",
                    job_id=job_def.job_id,
                    old_interval=prev[1],
                    new_interval=job_def.interval,
                )
            else:
                # Unchanged — keep existing deadline
                deadline = prev[0]
            heapq.heappush(
                self._heap,
                ScheduledJob(
                    next_deadline=deadline,
                    job_id=job_def.job_id,
                    job=job_def,
                    profile=profile,
                ),
            )

        # Update loaded_apps from current heap
        self._loaded_apps = {(sj.job.app_id, sj.job.app_version) for sj in self._heap}

        # Apply immediate triggers — set deadline to 0 for flagged jobs
        if immediate_ids:
            trigger_set = set(immediate_ids)
            for i, sj in enumerate(self._heap):
                if sj.job_id in trigger_set:
                    self._heap[i] = ScheduledJob(
                        next_deadline=0.0, job_id=sj.job_id,
                        job=sj.job, profile=sj.profile,
                    )
                    logger.info("job_triggered_immediate", job_id=sj.job_id)
            if trigger_set:
                heapq.heapify(self._heap)

        logger.debug("job_list_refreshed", total=len(self._heap))

    async def _dispatch_ready(self) -> None:
        """Launch tasks for all jobs whose deadline has passed."""
        now = time.time()
        while self._heap and self._heap[0].next_deadline <= now:
            sj = heapq.heappop(self._heap)
            if sj.job_id in self._running:
                # Still running from previous cycle — reschedule without counting as miss
                logger.debug(
                    "job_still_running", job_id=sj.job_id,
                    app=sj.job.app_id, running=list(self._running),
                )
                heapq.heappush(
                    self._heap,
                    ScheduledJob(
                        next_deadline=now + sj.job.interval * 0.1,  # retry in 10% of interval
                        job_id=sj.job_id,
                        job=sj.job,
                        profile=sj.profile,
                    ),
                )
                continue

            logger.info("job_dispatching", job_id=sj.job_id, app=sj.job.app_id)
            asyncio.create_task(
                self._run_job(sj),
                name=f"poll_{sj.job_id}",
            )

    # ── Job execution ─────────────────────────────────────────────────────────

    async def _run_job(self, sj: ScheduledJob) -> None:
        """Execute one job, report result, reschedule."""
        job = sj.job
        is_heavy = sj.profile.is_heavy
        sem = self._heavy_sem if is_heavy else self._light_sem

        self._running.add(job.job_id)
        start = time.time()
        result: PollResult | None = None

        async with sem:
            connectors: dict = {}
            # Tracks where a failure occurred, so the catch-all can classify it.
            # Values: "setup" (app/cred load), "connect" (connector handshake),
            # "poll" (inside app.poll()). Defaults to "poll" — if the exception
            # fires after connectors are ready it's almost certainly app-side.
            fail_phase = "setup"
            try:
                # Ensure app is loaded (may trigger download + venv create)
                cls = await self._apps.ensure_app(
                    job.app_id, job.app_version, job.app_checksum,
                )

                # Resolve credentials
                cred_data: dict = {}
                if job.credential_names:
                    for cred_name in job.credential_names:
                        data = await self._creds.get_credential(cred_name)
                        if data:
                            cred_data.update(data)

                # Load and instantiate connectors
                for binding in job.connector_bindings:
                    conn_cls = await self._apps.ensure_connector(
                        binding.connector_id, binding.connector_version_id,
                        expected_checksum=binding.connector_checksum,
                    )
                    conn_cred: dict = {}
                    if binding.credential_name:
                        conn_cred = await self._creds.get_credential(binding.credential_name)
                    connector = conn_cls(
                        settings=binding.settings,
                        credential=conn_cred,
                    )
                    fail_phase = "connect"
                    await connector.connect(job.device_host or "")
                    connectors[binding.alias] = connector
                fail_phase = "poll"

                # Build app cache accessor via gRPC to cache-node
                cache_client = await self._pool.get(self._cache_address)
                cache_accessor = AppCacheAccessor(
                    peer_client=cache_client,
                    app_id=job.app_id,
                    device_id=job.device_id or "",
                )

                ctx = PollContext(
                    job=job,
                    credential=cred_data,
                    node_id=self._worker_id,
                    device_host=job.device_host or "",
                    parameters=job.parameters,
                    connectors=connectors,
                    cache=cache_accessor,
                )

                # Instantiate (or reuse) poller
                poller = cls()
                await poller.setup()

                poll_task = asyncio.create_task(poller.poll(ctx))
                timeout_secs = float(job.max_execution_time)
                try:
                    result = await asyncio.wait_for(
                        asyncio.shield(poll_task),
                        timeout=timeout_secs,
                    )
                except asyncio.TimeoutError:
                    # wait_for timed out — force-cancel the shielded task
                    poll_task.cancel()
                    try:
                        await asyncio.wait_for(poll_task, timeout=5.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass
                    raise  # re-raise TimeoutError

                # Auto-fill error_category for apps that return an error result
                # without classifying it. Most uploaded apps catch connector
                # exceptions and build their own PollResult with error_message
                # only — default those to "device" since that is overwhelmingly
                # the real cause (target timeout / unreachable).
                if result is not None and result.status != "ok" and not result.error_category:
                    result.error_category = "device"

            except asyncio.TimeoutError:
                execution_ms = int((time.time() - start) * 1000)
                result = _error_result(job, self._worker_id, "timeout", execution_ms, error_category="device")
            except Exception as exc:  # noqa: BLE001
                execution_ms = int((time.time() - start) * 1000)
                # Classify based on where the failure occurred:
                #   setup   → config (missing app, credential, or connector code)
                #   connect → device (target unreachable or auth handshake failed)
                #   poll    → app    (crash inside app.poll() after setup succeeded)
                category = {"setup": "config", "connect": "device", "poll": "app"}[fail_phase]
                result = _error_result(
                    job, self._worker_id,
                    f"{type(exc).__name__}: {exc}",
                    execution_ms,
                    error_category=category,
                )
                logger.warning(
                    "job_execution_error",
                    job_id=job.job_id,
                    phase=fail_phase,
                    category=category,
                    error=str(exc),
                    tb=traceback.format_exc(),
                )
            finally:
                # Close all connectors
                for conn in connectors.values():
                    try:
                        await conn.close()
                    except Exception:
                        pass
                # Release memory back to OS
                gc.collect()
                if _malloc_trim is not None:
                    _malloc_trim(0)

                # Log RSS for memory leak tracking
                try:
                    with open("/proc/self/status") as _f:
                        for _line in _f:
                            if _line.startswith("VmRSS"):
                                logger.debug("job_memory", job_id=job.job_id,
                                             app=job.app_id, rss_kb=int(_line.split()[1]))
                                break
                except Exception:
                    pass

        execution_time = time.time() - start
        self._running.discard(job.job_id)

        # Attach started_at to the result for central ingestion
        if result and result.started_at is None:
            result.started_at = start

        # Reschedule (skip for one-shot jobs like discovery)
        if job.interval > 0:
            next_deadline = start + job.interval
            heapq.heappush(
                self._heap,
                ScheduledJob(
                    next_deadline=next_deadline,
                    job_id=job.job_id,
                    job=job,
                    profile=sj.profile,
                ),
            )
        else:
            logger.info("one_shot_job_complete", job_id=job.job_id)

        if result:
            await self._submit_result(result)
            await self._report_execution(
                job.job_id,
                execution_time,
                error=result.status == "error",
            )

    async def trigger_immediate(self, job_id: str) -> bool:
        """Move a scheduled job to the front of the heap so it runs at the next dispatch cycle."""
        for i, sj in enumerate(self._heap):
            if sj.job_id == job_id:
                self._heap[i] = ScheduledJob(
                    next_deadline=0.0,
                    job_id=sj.job_id,
                    job=sj.job,
                    profile=sj.profile,
                )
                heapq.heapify(self._heap)
                logger.info("job_triggered_immediate", job_id=job_id)
                return True
        return False

    async def _submit_result(self, result: PollResult) -> None:
        """Send poll result to cache-node for forwarding to central."""
        try:
            client = await self._pool.get(self._cache_address)
            await client.submit_result({
                "job_id": result.job_id,
                "device_id": result.device_id,
                "collector_node": result.collector_node,
                "timestamp": result.timestamp,
                "started_at": result.started_at,
                "metrics": result.metrics,
                "config_data": result.config_data,
                "status": result.status,
                "reachable": result.reachable,
                "error_message": result.error_message,
                "error_category": result.error_category,
                "execution_time_ms": result.execution_time_ms,
                "rtt_ms": result.rtt_ms,
                "response_time_ms": result.response_time_ms,
                "interface_rows": result.interface_rows,
            })
        except Exception as exc:
            logger.warning("submit_result_failed", job_id=result.job_id, error=str(exc))

    async def _report_execution(
        self, job_id: str, execution_time: float, error: bool
    ) -> None:
        """Report execution timing back to scheduler (EMA update)."""
        try:
            client = await self._pool.get(self._cache_address)
            await client.report_execution(job_id, execution_time, error)
        except Exception as exc:
            logger.debug("report_execution_failed", job_id=job_id, error=str(exc))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _error_result(
    job: JobDefinition, node_id: str, error_message: str, execution_ms: int,
    error_category: str = "app",
) -> PollResult:
    return PollResult(
        job_id=job.job_id,
        device_id=job.device_id,
        collector_node=node_id,
        timestamp=time.time(),
        metrics=[],
        config_data=None,
        status="error",
        reachable=False,
        error_message=error_message,
        error_category=error_category,
        execution_time_ms=execution_ms,
    )
