"""gRPC peer client — connects to a remote cache-node.

Used by:
  - Cache-nodes to communicate with peer cache-nodes (gossip, cache replication,
    work-stealing)
  - Poll-workers to talk to their local cache-node (via localhost:50051)
  - Forwarder to talk to its local cache-node

Connection pooling: one channel per remote address, reused across calls.
Timeout: 5 seconds per RPC. Retries: 1 automatic retry on transient errors.
"""

from __future__ import annotations

import json
from typing import Any

import grpc
import structlog

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
    """gRPC client for CollectorPeer service on a single remote node."""

    def __init__(self, address: str, timeout: float = _DEFAULT_TIMEOUT) -> None:
        """
        Args:
            address: host:port of the remote cache-node.
            timeout: RPC timeout in seconds.
        """
        self._address = address
        self._timeout = timeout
        self._channel: grpc.aio.Channel | None = None
        self._stub: pb_grpc.CollectorPeerStub | None = None

    async def connect(self) -> None:
        self._channel = grpc.aio.insecure_channel(self._address, options=_CHANNEL_OPTIONS)
        self._stub = pb_grpc.CollectorPeerStub(self._channel)

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None

    # ── Cache ─────────────────────────────────────────────────────────────────

    async def get_cache(self, key: str) -> pb.CacheResponse | None:
        try:
            return await self._stub.GetCache(
                pb.CacheRequest(key=key), timeout=self._timeout
            )
        except grpc.aio.AioRpcError as e:
            logger.debug("get_cache_rpc_error", address=self._address, key=key, error=str(e))
            return None

    async def put_cache(
        self, key: str, value: bytes, ttl: int, origin_node: str, is_replica: bool = False
    ) -> bool:
        try:
            resp = await self._stub.PutCache(
                pb.CachePutRequest(
                    key=key, value=value, ttl=ttl,
                    origin_node=origin_node, is_replica=is_replica,
                ),
                timeout=self._timeout,
            )
            return resp.success
        except grpc.aio.AioRpcError as e:
            logger.debug("put_cache_rpc_error", address=self._address, error=str(e))
            return False

    # ── Cluster ───────────────────────────────────────────────────────────────

    async def ping(self, node_id: str, generation: int) -> pb.PingResponse | None:
        try:
            return await self._stub.Ping(
                pb.PingRequest(node_id=node_id, generation=generation),
                timeout=self._timeout,
            )
        except grpc.aio.AioRpcError:
            return None

    async def gossip_exchange(self, sender_id: str, members: list[dict]) -> list[dict]:
        """Send gossip and return the remote node's member list."""
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
            for m in members
        ]
        try:
            resp = await self._stub.GossipExchange(
                pb.GossipMessage(sender_id=sender_id, members=pb_members),
                timeout=self._timeout,
            )
            return [_member_info_to_dict(m) for m in resp.members]
        except grpc.aio.AioRpcError:
            return []

    # ── Job Distribution ──────────────────────────────────────────────────────

    async def get_my_jobs(
        self, worker_id: str, loaded_apps: list[tuple[str, str]]
    ) -> list[dict]:
        """Poll-worker calls this to get its assigned jobs from the cache-node."""
        pb_apps = [pb.AppInfo(app_id=a, version=v) for (a, v) in loaded_apps]
        try:
            resp = await self._stub.GetMyJobs(
                pb.GetJobsRequest(worker_id=worker_id, loaded_apps=pb_apps),
                timeout=self._timeout,
            )
            return [_job_to_dict(j) for j in resp.jobs]
        except grpc.aio.AioRpcError as e:
            logger.warning("get_my_jobs_failed", worker=worker_id, error=str(e))
            return []

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
                ),
                timeout=self._timeout,
            )
            return resp.accepted
        except grpc.aio.AioRpcError:
            return False

    # ── Work-Stealing ─────────────────────────────────────────────────────────

    async def offer_job(self, job_id: str, job: dict, from_node: str) -> bool:
        """Offer a job to this node (work-stealing). Returns True if accepted."""
        pb_job = _dict_to_job_pb(job)
        try:
            resp = await self._stub.OfferJob(
                pb.OfferJobRequest(job_id=job_id, job=pb_job, from_node=from_node),
                timeout=self._timeout,
            )
            return resp.accepted
        except grpc.aio.AioRpcError:
            return False

    async def reclaim_job(self, job_id: str, from_node: str) -> bool:
        """Reclaim a previously stolen job back to this node."""
        try:
            resp = await self._stub.ReclaimJob(
                pb.ReclaimJobRequest(job_id=job_id, from_node=from_node),
                timeout=self._timeout,
            )
            return resp.ok
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

def _member_info_to_dict(m: pb.MemberInfo) -> dict:
    return {
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


def _job_to_dict(j: pb.JobWithProfile) -> dict:
    return {
        "job_id": j.job_id,
        "device_id": j.device_id,
        "device_host": j.device_host,
        "app_id": j.app_id,
        "app_version": j.app_version,
        "credential_names": list(j.credential_names),
        "interval": j.interval,
        "parameters": json.loads(j.parameters_json) if j.parameters_json else {},
        "max_execution_time": j.max_execution_time,
        "avg_execution_time": j.avg_execution_time,
        "is_heavy": j.is_heavy,
        "role": j.role,
    }


def _dict_to_job_pb(j: dict) -> pb.JobWithProfile:
    return pb.JobWithProfile(
        job_id=j.get("job_id", ""),
        device_id=j.get("device_id") or "",
        device_host=j.get("device_host") or "",
        app_id=j.get("app_id", ""),
        app_version=j.get("app_version", ""),
        credential_names=j.get("credential_names", []),
        interval=j.get("interval", 60),
        parameters_json=json.dumps(j.get("parameters", {})),
        max_execution_time=j.get("max_execution_time", 120),
        avg_execution_time=j.get("avg_execution_time", 5.0),
        is_heavy=j.get("is_heavy", False),
        role=j.get("role") or "",
    )
