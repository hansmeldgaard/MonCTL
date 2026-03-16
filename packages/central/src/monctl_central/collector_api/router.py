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
    InterfaceMetadata,
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


_CRED_REF_RE = re.compile(r"\$credential:([^\"}]+)")


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

    # Pre-load monitored interfaces for interface-type jobs (batch query)
    interface_device_ids = {
        row.Device.id for row in rows
        if row.App.target_table == "interface" and row.Device is not None
    }
    monitored_map: dict[str, list[dict]] = {}
    if interface_device_ids:
        iface_stmt = (
            select(InterfaceMetadata)
            .where(
                InterfaceMetadata.device_id.in_(interface_device_ids),
                InterfaceMetadata.polling_enabled == True,  # noqa: E712
            )
            .order_by(InterfaceMetadata.current_if_index)
        )
        iface_result = await db.execute(iface_stmt)
        for meta in iface_result.scalars().all():
            dev_key = str(meta.device_id)
            monitored_map.setdefault(dev_key, []).append({
                "if_index": meta.current_if_index,
                "if_name": meta.if_name,
                "poll_metrics": meta.poll_metrics,
            })

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

        # Inject monitored_interfaces for interface-type apps
        params = dict(assignment.config)
        if app.target_table == "interface" and device is not None:
            dev_key = str(device.id)
            if dev_key in monitored_map:
                params["monitored_interfaces"] = monitored_map[dev_key]
            # If not in monitored_map, no interfaces known yet → walk mode (no key injected)

        jobs.append({
            "job_id": str(assignment.id),
            "device_id": str(assignment.device_id) if assignment.device_id else None,
            "device_host": device_host,
            "app_id": app.name,
            "app_version": app_version.version,
            "credential_names": credential_names,  # collector fetches each via /credentials/{name}
            "interval": interval,
            "parameters": params,
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
    interface_rows: list[dict] | None = None  # Per-interface data for interface-table apps


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


def _calculate_rate(
    current_octets: int,
    previous_octets: int,
    dt_seconds: float,
    if_speed_mbps: int = 0,
) -> tuple[float, bool]:
    """Calculate rate in bps from counter delta.

    Returns (rate_bps, is_valid).
    current < previous = always reset (no wrap detection).
    Rejects rates > 110% of link speed as implausible.
    """
    if dt_seconds <= 0:
        return 0.0, False
    if current_octets < previous_octets:
        return 0.0, False
    if current_octets == previous_octets:
        return 0.0, True

    delta = current_octets - previous_octets
    rate_bps = (delta * 8) / dt_seconds

    # Reject implausible rates
    max_rate = (if_speed_mbps * 1_000_000 * 1.1) if if_speed_mbps > 0 else 110_000_000_000
    if rate_bps > max_rate:
        return 0.0, False

    return rate_bps, True


def _calculate_utilization(rate_bps: float, if_speed_mbps: int) -> float:
    """Returns utilization percentage, capped at 100%."""
    if if_speed_mbps <= 0 or rate_bps <= 0:
        return 0.0
    pct = (rate_bps / (if_speed_mbps * 1_000_000)) * 100
    return min(pct, 100.0)


async def _resolve_interface_id(
    db: AsyncSession,
    device_id: str,
    if_name: str,
    if_index: int,
    if_descr: str = "",
    if_alias: str = "",
    if_speed_mbps: int = 0,
) -> tuple[str, bool]:
    """Resolve or create stable interface_id from (device_id, if_name).

    Redis cached (1h). Auto-creates InterfaceMetadata on first discovery.
    Detects if_index changes and updates accordingly.

    Returns (interface_id, polling_enabled).
    """
    from monctl_central.cache import get_cached_interface_id, set_cached_interface_id

    # 1. Check Redis cache
    cached = await get_cached_interface_id(device_id, if_name)
    if cached:
        cached_id = cached["interface_id"]
        cached_if_index = cached.get("current_if_index")
        polling_enabled = cached.get("polling_enabled", True)
        if cached_if_index == if_index:
            return cached_id, polling_enabled
        # if_index changed — update PG and cache
        try:
            meta = await db.get(InterfaceMetadata, uuid.UUID(cached_id))
            if meta:
                meta.current_if_index = if_index
                if if_descr:
                    meta.if_descr = if_descr
                if if_alias:
                    meta.if_alias = if_alias
                if if_speed_mbps:
                    meta.if_speed_mbps = if_speed_mbps
                from monctl_common.utils import utc_now
                meta.updated_at = utc_now()
                await db.flush()
                polling_enabled = meta.polling_enabled
                logger.info(
                    "if_index_changed",
                    device_id=device_id,
                    if_name=if_name,
                    old_if_index=cached_if_index,
                    new_if_index=if_index,
                )
            cache_data = {
                "interface_id": cached_id,
                "current_if_index": if_index,
                "polling_enabled": polling_enabled,
            }
            await set_cached_interface_id(device_id, if_name, cache_data)
        except Exception:
            logger.debug("Failed to update if_index change", exc_info=True)
        return cached_id, polling_enabled

    # 2. PG lookup by (device_id, if_name)
    stmt = select(InterfaceMetadata).where(
        InterfaceMetadata.device_id == uuid.UUID(device_id),
        InterfaceMetadata.if_name == if_name,
    )
    result = await db.execute(stmt)
    meta = result.scalar_one_or_none()

    if meta is not None:
        # Update if_index if changed
        if meta.current_if_index != if_index:
            meta.current_if_index = if_index
            from monctl_common.utils import utc_now
            meta.updated_at = utc_now()
            await db.flush()
        interface_id = str(meta.id)
        polling_enabled = meta.polling_enabled
        cache_data = {
            "interface_id": interface_id,
            "current_if_index": if_index,
            "polling_enabled": polling_enabled,
        }
        await set_cached_interface_id(device_id, if_name, cache_data)
        return interface_id, polling_enabled

    # 3. Create new InterfaceMetadata (new interfaces default to polling_enabled=True)
    new_meta = InterfaceMetadata(
        device_id=uuid.UUID(device_id),
        if_name=if_name,
        current_if_index=if_index,
        if_descr=if_descr,
        if_alias=if_alias,
        if_speed_mbps=if_speed_mbps,
    )
    db.add(new_meta)
    await db.flush()
    interface_id = str(new_meta.id)
    cache_data = {
        "interface_id": interface_id,
        "current_if_index": if_index,
        "polling_enabled": True,
    }
    await set_cached_interface_id(device_id, if_name, cache_data)
    return interface_id, True


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

        target_table = enrichment.get("target_table", "availability_latency")
        device_id_resolved = r.device_id or enrichment.get("device_id", "00000000-0000-0000-0000-000000000000")
        started_at_dt = datetime.fromtimestamp(r.started_at, tz=timezone.utc) if r.started_at else executed_at

        # Interface-table apps: unpack interface_rows into one CH row per interface
        # If interface_rows is empty/None (e.g. SNMP timeout), fall through to
        # availability_latency so the error/status is still recorded.
        if target_table == "interface" and not r.interface_rows:
            target_table = "availability_latency"

        if target_table == "interface" and r.interface_rows:
            from monctl_central.cache import get_previous_counters, cache_current_counters

            for iface in r.interface_rows:
                iface_name = iface.get("if_name", "")
                iface_index = iface.get("if_index", 0)
                iface_alias = iface.get("if_alias", "")
                iface_speed = iface.get("if_speed_mbps", 0)
                in_octets = iface.get("in_octets", 0)
                out_octets = iface.get("out_octets", 0)

                # Resolve stable interface_id + polling_enabled flag
                interface_id, polling_enabled = await _resolve_interface_id(
                    db, device_id_resolved, iface_name, iface_index,
                    if_descr="", if_alias=iface_alias, if_speed_mbps=iface_speed,
                )

                # Skip interfaces where polling has been disabled
                if not polling_enabled:
                    continue

                # Central-side rate calculation
                in_rate = 0.0
                out_rate = 0.0
                in_util = 0.0
                out_util = 0.0
                prev = await get_previous_counters(interface_id)
                if prev:
                    prev_ts = datetime.fromisoformat(prev["executed_at"])
                    dt_sec = (executed_at - prev_ts).total_seconds()
                    in_rate, _ = _calculate_rate(in_octets, prev["in_octets"], dt_sec, iface_speed)
                    out_rate, _ = _calculate_rate(out_octets, prev["out_octets"], dt_sec, iface_speed)
                    in_util = _calculate_utilization(in_rate, iface_speed)
                    out_util = _calculate_utilization(out_rate, iface_speed)

                # Always cache current counters as new baseline
                await cache_current_counters(
                    interface_id, in_octets, out_octets, executed_at.isoformat(),
                )

                ch_rows.append({
                    "_target_table": "interface",
                    "assignment_id": str(assignment_id),
                    "collector_id": collector_uuid,
                    "app_id": enrichment.get("app_id", str(assignment_id)),
                    "device_id": device_id_resolved,
                    "interface_id": interface_id,
                    "if_index": iface_index,
                    "if_name": iface_name,
                    "if_alias": iface_alias,
                    "if_speed_mbps": iface_speed,
                    "if_admin_status": iface.get("if_admin_status", ""),
                    "if_oper_status": iface.get("if_oper_status", ""),
                    "in_octets": in_octets,
                    "out_octets": out_octets,
                    "in_errors": iface.get("in_errors", 0),
                    "out_errors": iface.get("out_errors", 0),
                    "in_discards": iface.get("in_discards", 0),
                    "out_discards": iface.get("out_discards", 0),
                    "in_unicast_pkts": iface.get("in_unicast_pkts", 0),
                    "out_unicast_pkts": iface.get("out_unicast_pkts", 0),
                    "in_rate_bps": in_rate,
                    "out_rate_bps": out_rate,
                    "in_utilization_pct": in_util,
                    "out_utilization_pct": out_util,
                    "poll_interval_sec": iface.get("poll_interval_sec", 0),
                    "state": iface.get("state", 0),
                    "executed_at": executed_at,
                    "collector_name": request.collector_node,
                    "device_name": enrichment.get("device_name", ""),
                    "app_name": enrichment.get("app_name", ""),
                    "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
                    "tenant_name": enrichment.get("tenant_name", ""),
                })
        else:
            ch_rows.append({
                "_target_table": target_table,
                "assignment_id": str(assignment_id),
                "collector_id": collector_uuid,
                "app_id": enrichment.get("app_id", str(assignment_id)),
                "device_id": device_id_resolved,
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
                "started_at": started_at_dt,
                "collector_name": request.collector_node,
                "device_name": enrichment.get("device_name", ""),
                "app_name": enrichment.get("app_name", ""),
                "role": enrichment.get("role", ""),
                "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
                "tenant_name": enrichment.get("tenant_name", ""),
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
            from monctl_central.storage.models import Tenant

            stmt = (
                select(AppAssignment, App, Device, Tenant)
                .join(App, AppAssignment.app_id == App.id)
                .outerjoin(Device, AppAssignment.device_id == Device.id)
                .outerjoin(Tenant, Device.tenant_id == Tenant.id)
                .where(AppAssignment.id == uuid.UUID(aid))
            )
            row = (await db.execute(stmt)).first()
            if row is None:
                return {}
            assignment, app, device, tenant = row.AppAssignment, row.App, row.Device, row.Tenant
            return {
                "app_id": str(app.id),
                "app_name": app.name,
                "target_table": app.target_table,
                "device_id": str(device.id) if device else "00000000-0000-0000-0000-000000000000",
                "device_name": device.name if device else "",
                "role": assignment.role or "",
                "tenant_id": str(device.tenant_id) if device and device.tenant_id else "00000000-0000-0000-0000-000000000000",
                "tenant_name": tenant.name if tenant else "",
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
