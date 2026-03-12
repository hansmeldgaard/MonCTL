"""gRPC peer server — listens for connections from peers and local workers.

The server delegates each RPC to the appropriate component:
  Cache RPCs          → DistributedCache (or LocalCache for simple ops)
  Gossip RPCs         → GossipProtocol + MembershipTable
  Job RPCs            → JobScheduler
  Credential RPCs     → CredentialManager
  Result RPCs         → LocalCache (results buffer)
  App Code RPCs       → AppManager
  Work-stealing RPCs  → WorkStealer

Components are injected at construction time to keep the server thin.
"""

from __future__ import annotations

import json

import grpc
import structlog

from monctl_collector.cluster.membership import MemberStatus
from monctl_collector.proto import collector_pb2 as pb
from monctl_collector.proto import collector_pb2_grpc as pb_grpc

logger = structlog.get_logger()


class CollectorPeerServicer(pb_grpc.CollectorPeerServicer):
    """gRPC servicer that delegates to collector components."""

    def __init__(
        self,
        *,
        local_cache=None,
        distributed_cache=None,
        membership=None,
        gossip=None,
        job_scheduler=None,
        credential_manager=None,
        app_manager=None,
        work_stealer=None,
        node_id: str = "",
    ) -> None:
        self._local_cache = local_cache
        self._dist_cache = distributed_cache
        self._membership = membership
        self._gossip = gossip
        self._scheduler = job_scheduler
        self._creds = credential_manager
        self._apps = app_manager
        self._stealer = work_stealer
        self._node_id = node_id

    # ── Cache ─────────────────────────────────────────────────────────────────

    async def GetCache(self, request, context):
        cache = self._dist_cache or self._local_cache
        if cache is None:
            return pb.CacheResponse(found=False)
        entry = await cache.get(request.key)
        if entry is None:
            return pb.CacheResponse(found=False)
        return pb.CacheResponse(
            found=True,
            value=entry.value if hasattr(entry, "value") else entry.get("value", b""),
            created_at=entry.created_at if hasattr(entry, "created_at") else 0.0,
            ttl=entry.ttl_seconds if hasattr(entry, "ttl_seconds") else 0,
            origin_node=entry.origin_node if hasattr(entry, "origin_node") else "",
        )

    async def PutCache(self, request, context):
        cache = self._dist_cache or self._local_cache
        if cache is None:
            return pb.CachePutResponse(success=False)
        await cache.put(
            request.key,
            request.value,
            request.ttl,
            request.origin_node,
            is_primary=not request.is_replica,
        )
        return pb.CachePutResponse(success=True)

    # ── Cluster ───────────────────────────────────────────────────────────────

    async def Ping(self, request, context):
        if self._membership:
            self._membership.mark_alive(request.node_id, generation=request.generation)
        return pb.PingResponse(node_id=self._node_id, generation=0)

    async def GossipExchange(self, request, context):
        if self._membership is None:
            return pb.GossipMessage(sender_id=self._node_id, members=[])

        # Merge incoming member list
        incoming = [
            {
                "node_id": m.node_id,
                "address": m.address,
                "status": m.status,
                "generation": m.generation,
                "last_seen": m.last_seen,
                "load_info": {
                    "load_score": m.load_score,
                    "worker_count": m.worker_count,
                    "effective_load": m.effective_load,
                    "deadline_miss_rate": m.deadline_miss_rate,
                    "total_jobs": m.total_jobs,
                    "stolen_job_count": m.stolen_job_count,
                },
            }
            for m in request.members
        ]
        events = self._membership.merge(incoming)

        # Process merge events: update hash ring for state transitions
        for ev in events:
            if self._gossip is not None:
                if ev.new_status == MemberStatus.ALIVE:
                    self._gossip._ring.add_node(ev.node_id)
                    if self._gossip._on_ring_changed:
                        self._gossip._on_ring_changed()
                elif ev.new_status == MemberStatus.DEAD:
                    self._gossip._ring.remove_node(ev.node_id)
                    if self._gossip._on_ring_changed:
                        self._gossip._on_ring_changed()

        # Return our own view
        local_members = self._membership.to_gossip_list()
        pb_members = [
            pb.MemberInfo(
                node_id=m["node_id"],
                address=m.get("address", ""),
                status=m.get("status", "ALIVE"),
                generation=m.get("generation", 0),
                last_seen=m.get("last_seen", 0.0),
                load_score=m.get("load_info", {}).get("load_score", 0.0),
                worker_count=m.get("load_info", {}).get("worker_count", 0),
                effective_load=m.get("load_info", {}).get("effective_load", 0.0),
                deadline_miss_rate=m.get("load_info", {}).get("deadline_miss_rate", 0.0),
                total_jobs=m.get("load_info", {}).get("total_jobs", 0),
                stolen_job_count=m.get("load_info", {}).get("stolen_job_count", 0),
            )
            for m in local_members
        ]
        return pb.GossipMessage(sender_id=self._node_id, members=pb_members)

    # ── Jobs ─────────────────────────────────────────────────────────────────

    async def GetMyJobs(self, request, context):
        if self._scheduler is None:
            return pb.GetJobsResponse(jobs=[])

        loaded_apps = [(a.app_id, a.version) for a in request.loaded_apps]
        jobs = self._scheduler.get_jobs_for_worker(request.worker_id, loaded_apps)

        pb_jobs = []
        for job_def, profile in jobs:
            pb_jobs.append(pb.JobWithProfile(
                job_id=job_def.job_id,
                device_id=job_def.device_id or "",
                device_host=job_def.device_host or "",
                app_id=job_def.app_id,
                app_version=job_def.app_version,
                credential_names=job_def.credential_names,
                interval=job_def.interval,
                parameters_json=json.dumps(job_def.parameters),
                max_execution_time=job_def.max_execution_time,
                avg_execution_time=profile.avg_execution_time,
                is_heavy=profile.is_heavy,
                role=job_def.role or "",
            ))
        return pb.GetJobsResponse(jobs=pb_jobs)

    async def RegisterWorker(self, request, context):
        if self._scheduler:
            loaded_apps = {(a.app_id, a.version) for a in request.loaded_apps}
            self._scheduler.register_worker(request.worker_id, loaded_apps)
        return pb.RegisterWorkerResp(ok=True)

    async def ReportExecution(self, request, context):
        if self._scheduler:
            self._scheduler.update_job_profile(
                request.job_id,
                request.execution_time,
                request.error,
            )
        return pb.ReportExecutionResp(ok=True)

    # ── Credentials ───────────────────────────────────────────────────────────

    async def GetCredential(self, request, context):
        if self._creds is None:
            return pb.CredentialResponse(found=False)
        try:
            data = await self._creds.get_credential(request.credential_name)
            if not data:
                return pb.CredentialResponse(found=False)
            return pb.CredentialResponse(
                found=True,
                type=data.get("type", "unknown") if isinstance(data, dict) and "type" in data else "unknown",
                data_json=json.dumps(data),
            )
        except Exception as exc:
            logger.error("get_credential_error", name=request.credential_name, error=str(exc))
            return pb.CredentialResponse(found=False)

    # ── Results ───────────────────────────────────────────────────────────────

    async def SubmitResult(self, request, context):
        if self._local_cache is None:
            return pb.SubmitResultResponse(accepted=False)
        result = {
            "job_id": request.job_id,
            "device_id": request.device_id or None,
            "timestamp": request.timestamp,
            "metrics": json.loads(request.metrics_json) if request.metrics_json else [],
            "config_data": json.loads(request.config_data_json) if request.config_data_json else None,
            "status": request.status,
            "reachable": request.reachable,
            "error_message": request.error_message or None,
            "execution_time_ms": request.execution_time_ms,
            "rtt_ms": request.rtt_ms if request.rtt_ms > 0 else None,
            "response_time_ms": request.response_time_ms if request.response_time_ms > 0 else None,
            "started_at": request.started_at if request.started_at > 0 else None,
            "collector_node": request.collector_node or None,
        }
        await self._local_cache.enqueue_result(result)
        return pb.SubmitResultResponse(accepted=True)

    # ── App Code ─────────────────────────────────────────────────────────────

    async def GetAppCode(self, request, context):
        # Check local SQLite first
        if self._local_cache:
            row = await self._local_cache.get_app(request.app_id, request.version)
            if row and row.get("code_path"):
                try:
                    import aiofiles
                    async with aiofiles.open(row["code_path"]) as f:
                        code = await f.read()
                    meta = json.loads(row["metadata_json"])
                    return pb.AppCodeResponse(
                        found=True,
                        code=code,
                        checksum=row["checksum"],
                        requirements_json=json.dumps(meta.get("requirements", [])),
                        entry_class=meta.get("entry_class", ""),
                    )
                except Exception:
                    pass  # Fall through to app_manager

        # Ask app_manager (it will fetch from central if needed)
        if self._apps:
            try:
                code_info = await self._apps.get_app_code(request.app_id, request.version)
                if code_info:
                    return pb.AppCodeResponse(
                        found=True,
                        code=code_info["code"],
                        checksum=code_info["checksum"],
                        requirements_json=json.dumps(code_info.get("requirements", [])),
                        entry_class=code_info.get("entry_class", ""),
                    )
            except Exception as exc:
                logger.error("get_app_code_error", app=request.app_id, error=str(exc))

        return pb.AppCodeResponse(found=False)

    # ── Work-Stealing ─────────────────────────────────────────────────────────

    async def OfferJob(self, request, context):
        if self._stealer is None:
            return pb.OfferJobResponse(accepted=False)
        accepted = await self._stealer.accept_offered_job(
            request.job_id, request.job, request.from_node
        )
        return pb.OfferJobResponse(accepted=accepted)

    async def ReclaimJob(self, request, context):
        if self._stealer is None:
            return pb.ReclaimJobResponse(ok=False)
        ok = await self._stealer.handle_reclaim(request.job_id, request.from_node)
        return pb.ReclaimJobResponse(ok=ok)


async def start_server(
    servicer: CollectorPeerServicer,
    address: str,
) -> grpc.aio.Server:
    """Start the gRPC server and return it.

    The caller is responsible for calling server.wait_for_termination().
    """
    server = grpc.aio.server()
    pb_grpc.add_CollectorPeerServicer_to_server(servicer, server)
    server.add_insecure_port(address)
    await server.start()
    logger.info("grpc_server_started", address=address)
    return server
