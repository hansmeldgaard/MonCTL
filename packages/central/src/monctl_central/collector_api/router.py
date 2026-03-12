"""Collector API — endpoints used by the distributed collector system.

These endpoints replace the old /v1/collectors/{id}/config + /v1/ingest model
with a job-pull model where collectors fetch jobs, app code, and credentials
independently and push results in a collector-native format.

All endpoints are mounted at /api/v1/  (see main.py).
Authentication: Bearer token (API key) in Authorization header — same as existing /v1/.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.credentials.crypto import decrypt_dict
from monctl_central.dependencies import get_clickhouse, get_db, require_collector_auth as require_auth
from monctl_central.storage.models import (
    App,
    AppAssignment,
    AppVersion,
    Collector,
    Credential,
    Device,
)

router = APIRouter()
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# ACTIVE-status gate for collector endpoints
# ---------------------------------------------------------------------------

async def _require_active_collector(auth: dict, db: AsyncSession) -> None:
    """Raise 403 if the collector is not in ACTIVE status.

    Used by endpoints that should be blocked for PENDING/REJECTED collectors
    (jobs, app metadata/code, credentials).
    """
    collector_id = auth.get("collector_id")
    if not collector_id:
        return  # Non-collector auth (management key, JWT) — skip check

    stmt = select(Collector).where(Collector.id == uuid.UUID(collector_id))
    result = await db.execute(stmt)
    collector = result.scalar_one_or_none()
    if collector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")

    if collector.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Collector is {collector.status} — approval required before accessing this endpoint",
        )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _compute_capacity_weights(
    collectors: list[Collector], stale_threshold: float = 120.0,
) -> dict[str, float]:
    """Compute capacity weights for each collector based on load metrics.

    Returns {collector.hostname: weight} where higher weight = more capacity.
    """
    now_ts = time.time()
    weights: dict[str, float] = {}
    for c in collectors:
        # Stale or missing load data → fallback to equal weight
        if c.load_updated_at is None:
            weights[c.hostname] = 1.0
            continue
        age = now_ts - c.load_updated_at.timestamp()
        if age > stale_threshold:
            weights[c.hostname] = 1.0
            continue

        capacity = max(0.05, 1.0 - c.effective_load)
        # Penalty for high deadline miss rate
        if c.deadline_miss_rate > 0.1:
            capacity *= 0.5
        weights[c.hostname] = capacity
    return weights


def _weighted_job_owner(
    assignment_id: str,
    weights: dict[str, float],
    vnodes_base: int = 100,
) -> str:
    """Weighted consistent hashing — returns the hostname that owns this job.

    Each collector gets `vnodes_base * normalized_weight` virtual nodes on a
    SHA256 hash ring. More capacity → more vnodes → more jobs.
    """
    if not weights:
        return ""
    if len(weights) == 1:
        return next(iter(weights))

    # Normalize weights so the max is 1.0
    max_w = max(weights.values()) or 1.0

    # Build ring: list of (hash_value, hostname) sorted by hash_value
    ring_hashes: list[int] = []
    ring_nodes: list[str] = []
    for hostname, w in sorted(weights.items()):
        n_vnodes = max(1, int(vnodes_base * (w / max_w)))
        for i in range(n_vnodes):
            h = int(hashlib.sha256(f"{hostname}:{i}".encode()).hexdigest(), 16)
            idx = bisect.bisect_left(ring_hashes, h)
            ring_hashes.insert(idx, h)
            ring_nodes.insert(idx, hostname)

    # Hash the assignment and find its position on the ring
    key_hash = int(hashlib.sha256(assignment_id.encode()).hexdigest(), 16)
    idx = bisect.bisect_left(ring_hashes, key_hash)
    if idx >= len(ring_hashes):
        idx = 0
    return ring_nodes[idx]


_CRED_REF_RE = re.compile(r"\$credential:([^\"}\s]+)")


def _extract_credential_names(config: dict) -> list[str]:
    """Return all $credential:<name> references found anywhere in config."""
    raw = json.dumps(config)
    return list({m for m in _CRED_REF_RE.findall(raw)})


# ---------------------------------------------------------------------------
# GET /api/v1/jobs
# ---------------------------------------------------------------------------

@router.get("/jobs", tags=["collector-api"])
async def get_jobs(
    since: str | None = Query(
        default=None,
        description="ISO-8601 timestamp for delta-sync. Only return jobs updated after this time.",
    ),
    collector_id: str | None = Query(
        default=None,
        description="Collector UUID — filters jobs to only devices in the collector's group.",
    ),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return active jobs (assignments) for a collector.

    If collector_id is provided and the collector belongs to a group,
    only assignments for devices in that group are returned.
    Jobs are partitioned server-side across active collectors in the group
    using consistent hashing so each job is executed by exactly one collector.
    """
    await _require_active_collector(auth, db)

    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid 'since' timestamp: {since!r}. Use ISO-8601 format.",
            )

    # Resolve collector's group for filtering and partitioning
    group_id: uuid.UUID | None = None
    coll: Collector | None = None
    if collector_id:
        try:
            coll = await db.get(Collector, uuid.UUID(collector_id))
        except ValueError:
            coll = None
        if coll and coll.group_id:
            group_id = coll.group_id

    # Fetch enabled assignments with their app, app_version, and device
    stmt = (
        select(AppAssignment, App, AppVersion, Device)
        .join(App, AppAssignment.app_id == App.id)
        .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
        .outerjoin(Device, AppAssignment.device_id == Device.id)
        .where(AppAssignment.enabled == True)  # noqa: E712
    )

    # Filter by collector group: only jobs for devices in this group
    if group_id is not None:
        stmt = stmt.where(Device.collector_group_id == group_id)

    if since_dt is not None:
        stmt = stmt.where(AppAssignment.updated_at > since_dt)

    result = await db.execute(stmt)
    rows = result.all()

    # ── Server-side weighted job partitioning ────────────────────────────
    # When a collector belongs to a group with multiple active members,
    # partition jobs using weighted consistent hashing so collectors with
    # more available capacity receive proportionally more jobs.
    if group_id is not None and coll is not None:
        group_stmt = (
            select(Collector)
            .where(Collector.group_id == group_id, Collector.status == "ACTIVE")
            .order_by(Collector.hostname)  # deterministic ordering
        )
        group_result = await db.execute(group_stmt)
        group_collectors = group_result.scalars().all()

        if len(group_collectors) > 1:
            my_hostname = coll.hostname
            weights = _compute_capacity_weights(group_collectors)

            if my_hostname in weights:
                total_before = len(rows)
                rows = [
                    r for r in rows
                    if _weighted_job_owner(str(r.AppAssignment.id), weights) == my_hostname
                ]
                logger.info(
                    "job_partitioning_weighted",
                    collector=my_hostname,
                    weights=weights,
                    group_size=len(group_collectors),
                    total_jobs=total_before,
                    assigned_jobs=len(rows),
                )

    # Pre-load latest versions for apps that have use_latest assignments
    latest_versions: dict[uuid.UUID, AppVersion] = {}
    use_latest_app_ids = {
        row.AppAssignment.app_id for row in rows if row.AppAssignment.use_latest
    }
    if use_latest_app_ids:
        latest_stmt = select(AppVersion).where(
            AppVersion.app_id.in_(use_latest_app_ids),
            AppVersion.is_latest == True,  # noqa: E712
        )
        latest_result = await db.execute(latest_stmt)
        for lv in latest_result.scalars().all():
            latest_versions[lv.app_id] = lv

    jobs = []
    for row in rows:
        assignment: AppAssignment = row.AppAssignment
        app: App = row.App
        app_version: AppVersion = row.AppVersion
        device: Device | None = row.Device

        # Resolve version: use_latest overrides the pinned version
        if assignment.use_latest and assignment.app_id in latest_versions:
            app_version = latest_versions[assignment.app_id]

        # Derive device_host: use device.address if linked, else try config["host"]
        device_host: str | None = None
        if device is not None:
            device_host = device.address
        elif "host" in assignment.config:
            device_host = str(assignment.config["host"])

        # interval in seconds (schedule_type == "interval")
        interval = 60
        if assignment.schedule_type == "interval":
            try:
                interval = int(assignment.schedule_value)
            except ValueError:
                pass

        # max_execution_time from resource_limits
        max_exec = 30
        if assignment.resource_limits and "timeout_seconds" in assignment.resource_limits:
            max_exec = int(assignment.resource_limits["timeout_seconds"])

        # credential names referenced in config
        credential_names = _extract_credential_names(assignment.config)

        jobs.append({
            "job_id": str(assignment.id),
            "device_id": str(assignment.device_id) if assignment.device_id else None,
            "device_host": device_host,
            "app_id": app.name,
            "app_version": app_version.version,
            "credential_names": credential_names,  # collector fetches each via /credentials/{name}
            "interval": interval,
            "parameters": assignment.config,
            "role": assignment.role,
            "max_execution_time": max_exec,
            "enabled": assignment.enabled,
            "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None,
        })

    return {
        "jobs": jobs,
        "deleted_ids": [],  # soft-delete support: future work
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /api/v1/apps/{app_name}/metadata
# ---------------------------------------------------------------------------

@router.get("/apps/{app_name}/metadata", tags=["collector-api"])
async def get_app_metadata(
    app_name: str,
    version: str | None = Query(default=None, description="Version string. Defaults to latest."),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return app metadata (requirements, entry_class, checksum) for a given app name."""
    await _require_active_collector(auth, db)

    from sqlalchemy.orm import selectinload

    stmt = (
        select(App)
        .options(selectinload(App.versions))
        .where(App.name == app_name)
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"App '{app_name}' not found")

    # Pick version: explicit > is_latest > newest
    versions = sorted(app.versions, key=lambda v: v.published_at, reverse=True)
    if version:
        av = next((v for v in versions if v.version == version), None)
        if av is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"App '{app_name}' version '{version}' not found",
            )
    else:
        av = next((v for v in versions if v.is_latest), None) or (versions[0] if versions else None)
        if av is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"App '{app_name}' has no versions",
            )

    return {
        "app_id": app.name,
        "version": av.version,
        "description": app.description,
        "requirements": av.requirements or [],
        "entry_class": av.entry_class,
        "checksum": av.checksum_sha256,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/apps/{app_name}/code
# ---------------------------------------------------------------------------

@router.get("/apps/{app_name}/code", tags=["collector-api"])
async def get_app_code(
    app_name: str,
    version: str | None = Query(default=None, description="Version string. Defaults to latest."),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return Python source code for a poll app."""
    await _require_active_collector(auth, db)

    from sqlalchemy.orm import selectinload

    stmt = (
        select(App)
        .options(selectinload(App.versions))
        .where(App.name == app_name)
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"App '{app_name}' not found")

    versions = sorted(app.versions, key=lambda v: v.published_at, reverse=True)
    if version:
        av = next((v for v in versions if v.version == version), None)
        if av is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"App '{app_name}' version '{version}' not found",
            )
    else:
        av = next((v for v in versions if v.is_latest), None) or (versions[0] if versions else None)
        if av is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"App '{app_name}' has no versions",
            )

    if not av.source_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"App '{app_name}' v{av.version} has no source code uploaded yet.",
        )

    # Recompute checksum so collectors can verify integrity
    checksum = hashlib.sha256(av.source_code.encode()).hexdigest()

    return {
        "app_id": app.name,
        "version": av.version,
        "code": av.source_code,
        "checksum": checksum,
        "requirements": av.requirements or [],
        "entry_class": av.entry_class,
    }


# ---------------------------------------------------------------------------
# PUT /api/v1/apps/{app_name}/code  (upload source code — management op)
# ---------------------------------------------------------------------------

class UploadCodeRequest(BaseModel):
    version: str
    source_code: str
    requirements: list[str] = []
    entry_class: str


@router.put("/apps/{app_name}/code", tags=["collector-api"])
async def upload_app_code(
    app_name: str,
    request: UploadCodeRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Upload Python source code for an app version.

    Creates the app and version if they don't exist yet.
    The checksum is computed server-side from the uploaded source_code.
    """
    from sqlalchemy.orm import selectinload

    stmt = select(App).options(selectinload(App.versions)).where(App.name == app_name)
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()

    if app is None:
        app = App(
            name=app_name,
            description=f"Poll app: {app_name}",
            app_type="poller",
        )
        db.add(app)
        await db.flush()

    # Find or create the version
    av = next((v for v in app.versions if v.version == request.version), None)
    checksum = hashlib.sha256(request.source_code.encode()).hexdigest()

    if av is None:
        av = AppVersion(
            app_id=app.id,
            version=request.version,
            checksum_sha256=checksum,
            source_code=request.source_code,
            requirements=request.requirements,
            entry_class=request.entry_class,
        )
        db.add(av)
    else:
        av.source_code = request.source_code
        av.requirements = request.requirements
        av.entry_class = request.entry_class
        av.checksum_sha256 = checksum

    await db.flush()
    return {
        "app_id": app_name,
        "version": request.version,
        "checksum": checksum,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/credentials/{credential_name}
# ---------------------------------------------------------------------------

@router.get("/credentials/{credential_name}", tags=["collector-api"])
async def get_credential(
    credential_name: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return decrypted credential data for a named credential."""
    await _require_active_collector(auth, db)

    stmt = select(Credential).where(Credential.name == credential_name)
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential '{credential_name}' not found",
        )

    try:
        data = decrypt_dict(cred.secret_data)
    except Exception as exc:
        logger.error("credential_decrypt_error", name=credential_name, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt credential",
        ) from exc

    return {
        "name": cred.name,
        "type": cred.credential_type,
        "data": data,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/results
# ---------------------------------------------------------------------------

class CollectorResult(BaseModel):
    job_id: str                       # = assignment_id UUID
    device_id: str | None = None
    timestamp: float                  # Unix timestamp
    metrics: list[dict] = []
    status: str = "ok"               # "ok" | "warning" | "critical" | "unknown" | "error"
    reachable: bool = True
    error_message: str | None = None
    execution_time_ms: int | None = None
    rtt_ms: float | None = None
    response_time_ms: float | None = None
    started_at: float | None = None


class SubmitResultsRequest(BaseModel):
    collector_node: str               # hostname of the cache-node
    results: list[CollectorResult]


_STATUS_TO_STATE = {
    "ok": 0,
    "warning": 1,
    "critical": 2,
    "unknown": 3,
    "error": 2,
}


@router.post("/results", status_code=status.HTTP_202_ACCEPTED, tags=["collector-api"])
async def submit_results(
    request: SubmitResultsRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Receive monitoring results from a collector node.

    Results are inserted into ClickHouse for time-series storage.
    Denormalized fields (device_name, app_name, role, tenant_id) are resolved
    from PostgreSQL and cached in Redis.
    """
    ch = get_clickhouse()

    # Try to find a matching collector record by hostname
    collector_stmt = select(Collector).where(Collector.hostname == request.collector_node)
    collector_row = await db.execute(collector_stmt)
    collector = collector_row.scalar_one_or_none()
    collector_uuid = str(collector.id) if collector else "00000000-0000-0000-0000-000000000000"

    ch_rows = []
    skipped = 0
    for r in request.results:
        try:
            assignment_id = uuid.UUID(r.job_id)
        except ValueError:
            skipped += 1
            continue

        # Map status string to integer state
        state = _STATUS_TO_STATE.get(r.status.lower(), 3)
        if not r.reachable and state == 0:
            state = 2

        # Build output string
        if r.error_message:
            output = r.error_message
        elif r.reachable:
            rtt = r.rtt_ms or r.response_time_ms
            output = f"OK — {rtt:.1f}ms" if rtt else "OK"
        else:
            output = "CRITICAL — unreachable"

        executed_at = datetime.fromtimestamp(r.timestamp, tz=timezone.utc)

        # Resolve denormalized fields via cache
        enrichment = await _enrich_assignment(db, str(assignment_id))

        # Extract metric arrays from the metrics list
        metric_names = []
        metric_values = []
        for m in (r.metrics or []):
            if isinstance(m, dict) and "name" in m and "value" in m:
                metric_names.append(str(m["name"]))
                metric_values.append(float(m["value"]))

        ch_rows.append({
            "_target_table": enrichment.get("target_table", "availability_latency"),
            "assignment_id": str(assignment_id),
            "collector_id": collector_uuid,
            "app_id": enrichment.get("app_id", str(assignment_id)),
            "device_id": r.device_id or enrichment.get("device_id", "00000000-0000-0000-0000-000000000000"),
            "state": state,
            "output": output,
            "error_message": r.error_message or "",
            "rtt_ms": r.rtt_ms or 0.0,
            "response_time_ms": r.response_time_ms or 0.0,
            "reachable": 1 if r.reachable else 0,
            "status_code": 0,
            "metric_names": metric_names,
            "metric_values": metric_values,
            "executed_at": executed_at,
            "execution_time": (r.execution_time_ms / 1000.0) if r.execution_time_ms else 0.0,
            "started_at": datetime.fromtimestamp(r.started_at, tz=timezone.utc) if r.started_at else executed_at,
            "collector_name": request.collector_node,
            "device_name": enrichment.get("device_name", ""),
            "app_name": enrichment.get("app_name", ""),
            "role": enrichment.get("role", ""),
            "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
        })

    # Route results to the correct ClickHouse table based on target_table
    if ch_rows:
        # Group by target_table
        by_table: dict[str, list[dict]] = {}
        for row in ch_rows:
            tt = row.pop("_target_table", "availability_latency")
            by_table.setdefault(tt, []).append(row)

        for table, rows in by_table.items():
            try:
                ch.insert_by_table(table, rows)
            except Exception:
                logger.exception("clickhouse_insert_error", node=request.collector_node, table=table)

    return {
        "accepted": len(ch_rows),
        "skipped": skipped,
    }


async def _enrich_assignment(db: AsyncSession, assignment_id: str) -> dict:
    """Resolve denormalized fields for a given assignment_id, with Redis caching."""
    from monctl_central.cache import get_or_load_enrichment

    async def _load(aid: str) -> dict:
        try:
            stmt = (
                select(AppAssignment, App, Device)
                .join(App, AppAssignment.app_id == App.id)
                .outerjoin(Device, AppAssignment.device_id == Device.id)
                .where(AppAssignment.id == uuid.UUID(aid))
            )
            row = (await db.execute(stmt)).first()
            if row is None:
                return {}
            assignment, app, device = row.AppAssignment, row.App, row.Device
            return {
                "app_id": str(app.id),
                "app_name": app.name,
                "target_table": app.target_table,
                "device_id": str(device.id) if device else "00000000-0000-0000-0000-000000000000",
                "device_name": device.name if device else "",
                "role": assignment.role or "",
                "tenant_id": str(device.tenant_id) if device and device.tenant_id else "00000000-0000-0000-0000-000000000000",
            }
        except Exception:
            return {}

    return await get_or_load_enrichment(assignment_id, _load)


# ---------------------------------------------------------------------------
# POST /api/v1/heartbeat
# ---------------------------------------------------------------------------

class HeartbeatRequest(BaseModel):
    node_id: str                # hostname or unique node identifier
    load_score: float = 0.0    # sum(avg_time/interval) for active jobs
    worker_count: int = 0
    effective_load: float = 0.0
    deadline_miss_rate: float = 0.0
    total_jobs: int = 0
    stolen_job_count: int = 0
    peer_address: str | None = None  # gRPC address for peer discovery (e.g. 192.168.1.31:50051)
    peer_states: dict[str, str] | None = None  # {node_id: "ALIVE"|"SUSPECTED"|"DEAD"}


@router.post("/heartbeat", tags=["collector-api"])
async def collector_heartbeat(
    request: HeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Receive heartbeat from a cache-node.

    Updates last_seen_at on the matching Collector record (matched by hostname).
    If no matching Collector record exists, the heartbeat is acknowledged but not stored
    (in the new design, collectors are not pre-registered).
    """
    from monctl_common.utils import utc_now

    stmt = select(Collector).where(Collector.hostname == request.node_id)
    result = await db.execute(stmt)
    collector = result.scalar_one_or_none()

    if collector is not None:
        collector.last_seen_at = utc_now()
        # Don't flip PENDING or REJECTED to ACTIVE via heartbeat
        if collector.status not in ("PENDING", "REJECTED"):
            collector.status = "ACTIVE"
        if request.peer_address:
            collector.peer_address = request.peer_address
        # Store gossip peer states reported by this collector
        if request.peer_states:
            collector.reported_peer_states = request.peer_states
        # Persist load metrics for weighted job partitioning
        collector.load_score = request.load_score
        collector.effective_load = request.effective_load
        collector.total_jobs = request.total_jobs
        collector.worker_count = request.worker_count
        collector.deadline_miss_rate = request.deadline_miss_rate
        collector.load_updated_at = utc_now()
        await db.flush()

    return {
        "ok": True,
        "node_id": request.node_id,
        "known": collector is not None,
    }
