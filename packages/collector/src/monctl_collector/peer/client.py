"""gRPC peer client — connects to the local cache-node.

Used by:
  - Poll-workers to talk to their local cache-node (via localhost:50051)
  - Forwarder to talk to its local cache-node

Connection pooling: one channel per remote address, reused across calls.
Timeout: 5 seconds per RPC. Retries: 1 automatic retry on transient errors.
"""

from __future__ import annotations

import json

import grpc
import structlog

from monctl_collector.peer.auth import PeerAuthClientInterceptor, get_peer_token
from monctl_collector.proto import collector_pb2 as pb
from monctl_collector.proto import collector_pb2_grpc as pb_grpc

logger = structlog.get_logger()

_DEFAULT_TIMEOUT = 5.0  # seconds
_CHANNEL_OPTIONS = [
    ("grpc.max_receive_message_length", 64 * 1024 * 1024),  # 64 MB
    ("grpc.keepalive_time_ms", 30_000),
    ("grpc.keepalive_timeout_ms", 10_000),
]


class PeerClient:
    """gRPC client for CollectorPeer service on the local cache-node."""

    def __init__(self, address: str, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._address = address
        self._timeout = timeout
        self._channel: grpc.aio.Channel | None = None
        self._stub: pb_grpc.CollectorPeerStub | None = None

    async def connect(self) -> None:
        token = get_peer_token()
        interceptors = [PeerAuthClientInterceptor(token)] if token else []
        self._channel = grpc.aio.insecure_channel(
            self._address, options=_CHANNEL_OPTIONS, interceptors=interceptors,
        )
        self._stub = pb_grpc.CollectorPeerStub(self._channel)

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None

    # ── Job Distribution ──────────────────────────────────────────────────────

    async def get_my_jobs(
        self, worker_id: str, loaded_apps: list[tuple[str, str]]
    ) -> tuple[list[dict], list[str]]:
        """Poll-worker calls this to get its assigned jobs from the cache-node.

        Returns (jobs, immediate_job_ids).
        """
        pb_apps = [pb.AppInfo(app_id=a, version=v) for (a, v) in loaded_apps]
        try:
            resp = await self._stub.GetMyJobs(
                pb.GetJobsRequest(worker_id=worker_id, loaded_apps=pb_apps),
                timeout=self._timeout,
            )
            return [_job_to_dict(j) for j in resp.jobs], list(resp.immediate_job_ids)
        except grpc.aio.AioRpcError as e:
            logger.warning("get_my_jobs_failed", worker=worker_id, error=str(e))
            return [], []

    async def register_worker(self, worker_id: str, loaded_apps: list[tuple[str, str]]) -> bool:
        pb_apps = [pb.AppInfo(app_id=a, version=v) for (a, v) in loaded_apps]
        try:
            resp = await self._stub.RegisterWorker(
                pb.RegisterWorkerReq(worker_id=worker_id, loaded_apps=pb_apps),
                timeout=self._timeout,
            )
            return resp.ok
        except grpc.aio.AioRpcError:
            return False

    async def report_execution(
        self, job_id: str, execution_time: float, error: bool = False, error_message: str = ""
    ) -> bool:
        try:
            resp = await self._stub.ReportExecution(
                pb.ReportExecutionReq(
                    job_id=job_id,
                    execution_time=execution_time,
                    error=error,
                    error_message=error_message,
                ),
                timeout=self._timeout,
            )
            return resp.ok
        except grpc.aio.AioRpcError:
            return False

    # ── Credentials + App Code ────────────────────────────────────────────────

    async def get_credential(self, credential_name: str) -> dict | None:
        try:
            resp = await self._stub.GetCredential(
                pb.CredentialRequest(credential_name=credential_name),
                timeout=self._timeout,
            )
            if not resp.found:
                return None
            return {"type": resp.type, "data": json.loads(resp.data_json)}
        except grpc.aio.AioRpcError:
            return None

    async def get_app_code(self, app_id: str, version: str) -> dict | None:
        try:
            resp = await self._stub.GetAppCode(
                pb.AppCodeRequest(app_id=app_id, version=version),
                timeout=self._timeout,
            )
            if not resp.found:
                return None
            return {
                "code": resp.code,
                "checksum": resp.checksum,
                "requirements": json.loads(resp.requirements_json),
                "entry_class": resp.entry_class,
            }
        except grpc.aio.AioRpcError:
            return None

    # ── App Cache ──────────────────────────────────────────────────────────────

    async def app_cache_get(self, app_id: str, device_id: str, key: str) -> dict | None:
        try:
            resp = await self._stub.AppCacheGet(
                pb.AppCacheGetRequest(app_id=app_id, device_id=device_id, cache_key=key),
                timeout=self._timeout,
            )
            if not resp.found:
                return None
            return json.loads(resp.cache_value)
        except grpc.aio.AioRpcError:
            return None

    async def app_cache_set(
        self, app_id: str, device_id: str, key: str, value: dict,
        ttl_seconds: int = 0,
    ) -> bool:
        try:
            resp = await self._stub.AppCacheSet(
                pb.AppCacheSetRequest(
                    app_id=app_id, device_id=device_id, cache_key=key,
                    cache_value=json.dumps(value), ttl_seconds=ttl_seconds,
                ),
                timeout=self._timeout,
            )
            return resp.ok
        except grpc.aio.AioRpcError:
            return False

    async def app_cache_delete(self, app_id: str, device_id: str, key: str) -> bool:
        try:
            resp = await self._stub.AppCacheDelete(
                pb.AppCacheDeleteRequest(app_id=app_id, device_id=device_id, cache_key=key),
                timeout=self._timeout,
            )
            return resp.ok
        except grpc.aio.AioRpcError:
            return False

    # ── Result Submission ─────────────────────────────────────────────────────

    async def submit_result(self, result: dict) -> bool:
        try:
            resp = await self._stub.SubmitResult(
                pb.SubmitResultRequest(
                    job_id=result.get("job_id", ""),
                    device_id=result.get("device_id") or "",
                    timestamp=result.get("timestamp", 0.0),
                    metrics_json=json.dumps(result.get("metrics", [])),
                    config_data_json=json.dumps(result.get("config_data") or {}),
                    status=result.get("status", "unknown"),
                    reachable=result.get("reachable", False),
                    error_message=result.get("error_message") or "",
                    execution_time_ms=result.get("execution_time_ms", 0),
                    rtt_ms=result.get("rtt_ms") or 0.0,
                    response_time_ms=result.get("response_time_ms") or 0.0,
                    started_at=result.get("started_at") or 0.0,
                    collector_node=result.get("collector_node") or "",
                    interface_rows_json=json.dumps(result.get("interface_rows") or []),
                    error_category=result.get("error_category") or "",
                ),
                timeout=self._timeout,
            )
            return resp.accepted
        except grpc.aio.AioRpcError:
            return False


# ── Channel pool (one channel per address) ────────────────────────────────────

class PeerChannelPool:
    """Maintains a pool of PeerClient instances keyed by address."""

    def __init__(self, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._pool: dict[str, PeerClient] = {}

    async def get(self, address: str) -> PeerClient:
        if address not in self._pool:
            client = PeerClient(address, timeout=self._timeout)
            await client.connect()
            self._pool[address] = client
        return self._pool[address]

    async def close_all(self) -> None:
        for client in self._pool.values():
            await client.close()
        self._pool.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _job_to_dict(j: pb.JobWithProfile) -> dict:
    bindings = [
        {
            "connector_type": b.connector_type,
            "connector_id": b.connector_id,
            "connector_version_id": b.connector_version_id,
            "credential_name": b.credential_name or None,
            "settings": json.loads(b.settings_json) if b.settings_json else {},
        }
        for b in j.connector_bindings
    ]
    return {
        "job_id": j.job_id,
        "device_id": j.device_id,
        "device_host": j.device_host,
        "app_id": j.app_id,
        "app_version": j.app_version,
        "app_checksum": j.app_checksum,
        "credential_names": list(j.credential_names),
        "interval": j.interval,
        "parameters": json.loads(j.parameters_json) if j.parameters_json else {},
        "max_execution_time": j.max_execution_time,
        "avg_execution_time": j.avg_execution_time,
        "is_heavy": j.is_heavy,
        "role": j.role,
        "connector_bindings": bindings,
    }
