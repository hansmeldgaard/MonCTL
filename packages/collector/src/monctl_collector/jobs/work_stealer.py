"""Work-stealing coordinator for overloaded cache-nodes.

Flow (overloaded node perspective):
  Every `check_interval` seconds (default 30):
    1. Collect load scores for all alive nodes from the membership table.
    2. Compute the median load score.
    3. If our load > median * overload_factor (default 1.5):
       a. Find the least-loaded peer that is not in cooldown.
       b. Pick one "movable" job from our home jobs (largest load contribution,
          longest interval — i.e. easy to reschedule).
       c. Call peer.offer_job(job_id, job_dict, from_node=us) via gRPC.
       d. If peer accepts: remove from our active jobs + start cooldown timer.
    4. Max 1 job stolen per round to prevent oscillation.
    5. 300-second cooldown per target node (config.cooldown).

Acceptor perspective (called via gRPC OfferJob RPC):
  - accept_offered_job() checks if we have capacity (below median load).
  - If yes: add to scheduler as a stolen job, record origin for reclaim.

Reclaim perspective (called via gRPC ReclaimJob RPC):
  - handle_reclaim() removes the job from stolen jobs so the original node
    can take it back after recovering.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import structlog

from monctl_collector.cluster.membership import MembershipTable, MemberStatus
from monctl_collector.config import WorkStealingConfig
from monctl_collector.jobs.models import JobDefinition
from monctl_collector.jobs.scheduler import JobScheduler
from monctl_collector.peer.client import PeerChannelPool

logger = structlog.get_logger()


def _job_to_dict(job: JobDefinition) -> dict:
    return {
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
    }


def _dict_to_job(d: dict) -> JobDefinition:
    return JobDefinition(
        job_id=d.get("job_id", ""),
        device_id=d.get("device_id"),
        device_host=d.get("device_host"),
        app_id=d.get("app_id", ""),
        app_version=d.get("app_version", "1.0.0"),
        credential_names=d.get("credential_names", []),
        interval=d.get("interval", 60),
        parameters=d.get("parameters", {}),
        role=d.get("role"),
        max_execution_time=d.get("max_execution_time", 120),
        enabled=d.get("enabled", True),
        updated_at=d.get("updated_at", ""),
    )


class WorkStealer:
    """Detects load imbalance and redistributes jobs across cluster nodes."""

    def __init__(
        self,
        *,
        node_id: str,
        scheduler: JobScheduler,
        membership: MembershipTable,
        channel_pool: PeerChannelPool,
        config: WorkStealingConfig,
    ) -> None:
        self._node_id = node_id
        self._scheduler = scheduler
        self._membership = membership
        self._pool = channel_pool
        self._config = config

        # {node_id → Unix timestamp of last steal attempt to that node}
        self._cooldowns: dict[str, float] = {}
        # {job_id → original_node_id} — tracks jobs we've received
        self._stolen_from: dict[str, str] = {}

        self._task: asyncio.Task | None = None
        self._running = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> asyncio.Task:
        """Start the background work-stealing check loop."""
        if not self._config.enabled:
            logger.info("work_stealing_disabled")
            # Return a dummy completed task
            self._task = asyncio.create_task(asyncio.sleep(0))
            return self._task
        self._running = True
        self._task = asyncio.create_task(self._run(), name="work_stealer")
        logger.info(
            "work_stealer_started",
            interval=self._config.check_interval,
            overload_factor=self._config.overload_factor,
        )
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("work_stealer_stopped")

    # ── Background loop ──────────────────────────────────────────────────────

    async def _run(self) -> None:
        while self._running:
            await asyncio.sleep(self._config.check_interval)
            try:
                await self._check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("work_stealer_check_error", error=str(exc))

    async def _check(self) -> None:
        """One work-stealing check round."""
        load_infos = self._membership.get_all_load_info()
        if len(load_infos) < 2:
            return  # Nothing to steal from in a single-node cluster

        scores = [info.get("load_score", 0.0) for info in load_infos]
        median_load = statistics.median(scores)
        if median_load <= 0.0:
            return  # Everyone is idle

        our_load = self._scheduler.get_current_load_info().load_score
        if our_load <= median_load * self._config.overload_factor:
            return  # We're not overloaded

        # We are overloaded — find the least-loaded peer to offer a job to
        now = time.time()
        candidates = [
            info for info in load_infos
            if info["node_id"] != self._node_id
            and self._membership.get(info["node_id"]) is not None
            and self._membership.get(info["node_id"]).status == MemberStatus.ALIVE
            and now - self._cooldowns.get(info["node_id"], 0.0) > self._config.cooldown
        ]
        if not candidates:
            return

        # Pick the least-loaded candidate
        target_info = min(candidates, key=lambda x: x.get("load_score", 0.0))
        target_id = target_info["node_id"]
        target_member = self._membership.get(target_id)
        if target_member is None:
            return

        # Pick the best job to offer (largest load contribution — gives us most relief)
        home_jobs = self._scheduler.get_home_jobs()
        if not home_jobs:
            return

        job_to_offer = self._pick_job_to_offer(home_jobs)
        if job_to_offer is None:
            return

        logger.info(
            "offering_job",
            job_id=job_to_offer.job_id,
            to_node=target_id,
            our_load=our_load,
            median_load=median_load,
        )

        try:
            client = await self._pool.get(target_member.address)
            accepted = await client.offer_job(
                job_to_offer.job_id,
                _job_to_dict(job_to_offer),
                from_node=self._node_id,
            )
        except Exception as exc:
            logger.warning("offer_job_failed", target=target_id, error=str(exc))
            return

        if accepted:
            self._scheduler.remove_home_job(job_to_offer.job_id)
            self._cooldowns[target_id] = time.time()
            logger.info(
                "job_offer_accepted",
                job_id=job_to_offer.job_id,
                target_node=target_id,
            )
        else:
            logger.debug("job_offer_rejected", job_id=job_to_offer.job_id, target=target_id)

    def _pick_job_to_offer(
        self, home_jobs: dict[str, JobDefinition]
    ) -> JobDefinition | None:
        """Pick the best job to offer to another node.

        Selection criteria (in order):
          - Not already stolen from elsewhere (avoid ping-pong)
          - Longest interval (least time-sensitive)
          - Any job as a fallback
        """
        load_info = self._scheduler.get_current_load_info()
        # Prefer long-interval jobs (easiest to hand off without deadline pressure)
        candidates = [
            job for job in home_jobs.values()
            if job.job_id not in self._stolen_from  # don't re-offer stolen jobs
        ]
        if not candidates:
            return None
        # Sort descending by interval: longest interval = least time-sensitive
        candidates.sort(key=lambda j: j.interval, reverse=True)
        return candidates[0]

    # ── Called from gRPC server (OfferJob RPC) ───────────────────────────────

    async def accept_offered_job(
        self, job_id: str, job: dict, from_node: str
    ) -> bool:
        """Decide whether to accept a job offered by an overloaded node.

        Returns True if we accept (and have added the job to our scheduler).
        """
        if not self._config.enabled:
            return False

        # Don't accept if we're already in cooldown with this node
        now = time.time()
        if now - self._cooldowns.get(from_node, 0.0) < self._config.cooldown:
            logger.debug("accept_offer_cooldown", from_node=from_node)
            return False

        # Don't accept if we have no workers
        our_load = self._scheduler.get_current_load_info()
        if our_load.worker_count == 0:
            logger.debug("accept_offer_no_workers")
            return False

        # Check if we're already loaded too
        load_infos = self._membership.get_all_load_info()
        if len(load_infos) >= 2:
            scores = [i.get("load_score", 0.0) for i in load_infos]
            median_load = statistics.median(scores)
            if our_load.load_score >= median_load:
                logger.debug(
                    "accept_offer_too_loaded",
                    our=our_load.load_score,
                    median=median_load,
                )
                return False

        # Accept the job
        try:
            job_def = _dict_to_job(job)
            job_def.job_id = job_id  # ensure the ID is authoritative
        except Exception as exc:
            logger.warning("accept_offer_parse_error", error=str(exc))
            return False

        self._scheduler.add_stolen_job(job_def)
        self._stolen_from[job_id] = from_node
        logger.info(
            "job_offer_accepted_local",
            job_id=job_id,
            from_node=from_node,
        )
        return True

    # ── Called from gRPC server (ReclaimJob RPC) ─────────────────────────────

    async def handle_reclaim(self, job_id: str, from_node: str) -> bool:
        """Remove a previously stolen job so the original node can reclaim it.

        Returns True if the job was found and removed.
        """
        original_node = self._stolen_from.get(job_id)
        if original_node != from_node:
            logger.warning(
                "reclaim_rejected",
                job_id=job_id,
                from_node=from_node,
                expected_node=original_node,
            )
            return False

        self._scheduler.remove_stolen_job(job_id)
        self._stolen_from.pop(job_id, None)
        logger.info("job_reclaimed", job_id=job_id, by=from_node)
        return True
