"""gRPC peer server — listens for connections from local poll-workers.

The server delegates each RPC to the appropriate component:
  Job RPCs            → JobScheduler
  Credential RPCs     → CredentialManager
  Result RPCs         → LocalCache (results buffer)
  App Code RPCs       → AppManager

Components are injected at construction time to keep the server thin.
"""

from __future__ import annotations

import json

import grpc
import structlog

from monctl_collector.peer.auth import PeerAuthServerInterceptor, get_peer_token
from monctl_collector.proto import collector_pb2 as pb
from monctl_collector.proto import collector_pb2_grpc as pb_grpc

logger = structlog.get_logger()


class CollectorPeerServicer(pb_grpc.CollectorPeerServicer):
    """gRPC servicer that delegates to collector components."""

    def __init__(
        self,
        *,
        local_cache=None,
        job_scheduler=None,
        credential_manager=None,
        app_manager=None,
        node_id: str = "",
    ) -> None:
        self._local_cache = local_cache
        self._scheduler = job_scheduler
        self._creds = credential_manager
        self._apps = app_manager
        self._node_id = node_id

    # ── Jobs ─────────────────────────────────────────────────────────────────

    async def GetMyJobs(self, request, context):
        if self._scheduler is None:
            return pb.GetJobsResponse(jobs=[])

        loaded_apps = [(a.app_id, a.version) for a in request.loaded_apps]
        jobs = self._scheduler.get_jobs_for_worker(request.worker_id, loaded_apps)

        pb_jobs = []
        for job_def, profile in jobs:
            pb_bindings = [
                pb.ConnectorBindingProto(
                    connector_type=b.connector_type,
                    connector_id=b.connector_id,
                    connector_version_id=b.connector_version_id,
                    credential_name=b.credential_name or "",
                    settings_json=json.dumps(b.settings) if b.settings else "{}",
                )
                for b in job_def.connector_bindings
            ]
            pb_jobs.append(pb.JobWithProfile(
                job_id=job_def.job_id,
                device_id=job_def.device_id or "",
                device_host=job_def.device_host or "",
                app_id=job_def.app_id,
                app_version=job_def.app_version,
                app_checksum=job_def.app_checksum,
                credential_names=job_def.credential_names,
                interval=job_def.interval,
                parameters_json=json.dumps(job_def.parameters),
                max_execution_time=job_def.max_execution_time,
                avg_execution_time=profile.avg_execution_time,
                is_heavy=profile.is_heavy,
                role=job_def.role or "",
                connector_bindings=pb_bindings,
            ))
        # Check for immediate trigger requests
        worker_job_ids = {j.job_id for j, _ in jobs}
        immediate = self._scheduler.pop_immediate_triggers(worker_job_ids) if jobs else []

        return pb.GetJobsResponse(jobs=pb_jobs, immediate_job_ids=immediate)

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
        iface_rows = None
        if request.interface_rows_json:
            parsed = json.loads(request.interface_rows_json)
            if parsed:
                iface_rows = parsed
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
            "interface_rows": iface_rows,
            "error_category": request.error_category or "",
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

    # ── App Cache ─────────────────────────────────────────────────────────────

    async def AppCacheGet(self, request, context):
        if self._local_cache is None:
            return pb.AppCacheGetResponse(found=False, cache_value="")
        value = await self._local_cache.app_cache_get(
            request.app_id, request.device_id, request.cache_key
        )
        if value is None:
            return pb.AppCacheGetResponse(found=False, cache_value="")
        return pb.AppCacheGetResponse(found=True, cache_value=json.dumps(value))

    async def AppCacheSet(self, request, context):
        if self._local_cache is None:
            return pb.AppCacheSetResponse(ok=False)
        ttl = request.ttl_seconds if request.ttl_seconds > 0 else None
        await self._local_cache.app_cache_set(
            request.app_id, request.device_id, request.cache_key,
            json.loads(request.cache_value), ttl_seconds=ttl,
        )
        return pb.AppCacheSetResponse(ok=True)

    async def AppCacheDelete(self, request, context):
        if self._local_cache is None:
            return pb.AppCacheDeleteResponse(ok=False)
        await self._local_cache.app_cache_delete(
            request.app_id, request.device_id, request.cache_key
        )
        return pb.AppCacheDeleteResponse(ok=True)


async def start_server(
    servicer: CollectorPeerServicer,
    address: str,
) -> grpc.aio.Server:
    """Start the gRPC server and return it.

    The caller is responsible for calling server.wait_for_termination().
    """
    interceptors: list = []
    token = get_peer_token()
    if token:
        interceptors.append(PeerAuthServerInterceptor(token))
        logger.info("peer_auth_enabled")
    else:
        # Grandfathered path — deployments that haven't provisioned the token
        # yet stay wide-open but surface a boot warning that audit can pick
        # up. Plan is to drop this branch once the fleet has rolled.
        logger.warning(
            "peer_auth_disabled",
            reason="MONCTL_PEER_TOKEN unset; gRPC channel is unauthenticated",
            finding="F-COL-026",
        )

    server = grpc.aio.server(interceptors=interceptors) if interceptors else grpc.aio.server()
    pb_grpc.add_CollectorPeerServicer_to_server(servicer, server)
    server.add_insecure_port(address)
    await server.start()
    logger.info("grpc_server_started", address=address, authenticated=bool(token))
    return server
