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
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.credentials.crypto import decrypt_dict
from monctl_central.dependencies import get_clickhouse, get_db, require_collector_auth as require_auth
from sqlalchemy.dialects.postgresql import insert as pg_insert

from monctl_central.storage.models import (
    App,
    AppAssignment,
    AppCache,
    AppConnectorBinding,
    AppVersion,
    AssignmentConnectorBinding,
    AssignmentCredentialOverride,
    Collector,
    Connector,
    ConnectorVersion,
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
    from sqlalchemy.orm import selectinload

    _base_opts = (
        selectinload(AppAssignment.connector_bindings),
    )
    _enabled_device_filter = [
        AppAssignment.enabled == True,  # noqa: E712
        or_(
            AppAssignment.device_id.is_(None),
            Device.is_enabled == True,  # noqa: E712
        ),
    ]

    # 1. Fetch assignments pinned to THIS collector (always included, no partitioning)
    pinned_rows = []
    if collector_id:
        pinned_stmt = (
            select(AppAssignment, App, AppVersion, Device)
            .join(App, AppAssignment.app_id == App.id)
            .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
            .outerjoin(Device, AppAssignment.device_id == Device.id)
            .options(*_base_opts)
            .where(AppAssignment.collector_id == uuid.UUID(collector_id), *_enabled_device_filter)
        )
        if since_dt is not None:
            pinned_stmt = pinned_stmt.where(AppAssignment.updated_at > since_dt)
        pinned_rows = list((await db.execute(pinned_stmt)).all())

    # 2. Fetch unpinned (group-level) assignments for partitioning
    stmt = (
        select(AppAssignment, App, AppVersion, Device)
        .join(App, AppAssignment.app_id == App.id)
        .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
        .outerjoin(Device, AppAssignment.device_id == Device.id)
        .options(*_base_opts)
        .where(AppAssignment.collector_id.is_(None), *_enabled_device_filter)
    )

    # Filter by collector group: only jobs for devices in this group
    if group_id is not None:
        stmt = stmt.where(Device.collector_group_id == group_id)

    if since_dt is not None:
        stmt = stmt.where(AppAssignment.updated_at > since_dt)

    result = await db.execute(stmt)
    rows = list(result.all())

    # ── Server-side weighted job partitioning ────────────────────────────
    # Partitioning applies ONLY to unpinned (group-level) assignments.
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

    # Combine: pinned always included + group-level after partitioning
    rows = pinned_rows + rows

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

    # Pre-load app-level connector bindings (batch)
    app_ids = {row.App.id for row in rows}
    acb_stmt = select(AppConnectorBinding).where(AppConnectorBinding.app_id.in_(app_ids))
    acb_result = await db.execute(acb_stmt)
    app_bindings_map: dict[uuid.UUID, list[AppConnectorBinding]] = {}
    for acb in acb_result.scalars().all():
        app_bindings_map.setdefault(acb.app_id, []).append(acb)

    # Pre-load assignment credential overrides (batch)
    assignment_ids = {row.AppAssignment.id for row in rows}
    override_stmt = select(AssignmentCredentialOverride).where(
        AssignmentCredentialOverride.assignment_id.in_(assignment_ids)
    )
    override_result = await db.execute(override_stmt)
    overrides_map: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    for ov in override_result.scalars().all():
        overrides_map.setdefault(ov.assignment_id, {})[ov.alias] = ov.credential_id

    # Pre-load latest connector versions for use_latest resolution
    latest_cv_stmt = select(ConnectorVersion).where(ConnectorVersion.is_latest == True)  # noqa: E712
    latest_cv_result = await db.execute(latest_cv_stmt)
    latest_connector_versions: dict[uuid.UUID, uuid.UUID] = {}
    for cv in latest_cv_result.scalars().all():
        latest_connector_versions[cv.connector_id] = cv.id

    # Pre-load connector version checksums for cache invalidation
    all_cv_ids: set[uuid.UUID] = set()
    for row in rows:
        for acb in app_bindings_map.get(row.App.id, []):
            vid = acb.connector_version_id
            if acb.use_latest:
                vid = latest_connector_versions.get(acb.connector_id, vid)
            if vid:
                all_cv_ids.add(vid)
        for b in (row.AppAssignment.connector_bindings or []):
            if b.connector_version_id:
                all_cv_ids.add(b.connector_version_id)
    cv_checksum_map: dict[uuid.UUID, str] = {}
    if all_cv_ids:
        cv_stmt = select(ConnectorVersion.id, ConnectorVersion.checksum).where(
            ConnectorVersion.id.in_(all_cv_ids)
        )
        cv_rows = (await db.execute(cv_stmt)).all()
        cv_checksum_map = {r.id: r.checksum or "" for r in cv_rows}

    # Collect all credential IDs we might need names for
    all_cred_ids: set[uuid.UUID] = set()
    for row in rows:
        # Legacy: assignment connector bindings
        for b in (row.AppAssignment.connector_bindings or []):
            if b.credential_id:
                all_cred_ids.add(b.credential_id)
        # New: assignment credential_id, device default_credential_id
        if row.AppAssignment.credential_id:
            all_cred_ids.add(row.AppAssignment.credential_id)
        if row.Device and row.Device.default_credential_id:
            all_cred_ids.add(row.Device.default_credential_id)
    for alias_map in overrides_map.values():
        all_cred_ids.update(alias_map.values())

    cred_name_map: dict[uuid.UUID, str] = {}
    if all_cred_ids:
        cred_stmt = select(Credential.id, Credential.name).where(Credential.id.in_(all_cred_ids))
        cred_rows = (await db.execute(cred_stmt)).all()
        cred_name_map = {r.id: r.name for r in cred_rows}

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
            # Check if a metadata refresh was requested (forces full walk)
            from monctl_central.cache import get_and_clear_interface_refresh_flag
            refresh_requested = await get_and_clear_interface_refresh_flag(dev_key)
            if refresh_requested:
                logger.info("interface_refresh_requested", device_id=dev_key)
                # Omit monitored_interfaces → poller will do a full walk
            elif dev_key in monitored_map:
                params["monitored_interfaces"] = monitored_map[dev_key]

        # Build connector bindings from APP-level bindings (new model)
        # with credential resolution: override > assignment > device default
        app_cbs = app_bindings_map.get(app.id, [])
        cred_overrides = overrides_map.get(assignment.id, {})

        bindings = []
        if app_cbs:
            # New path: read from app connector bindings
            for acb in app_cbs:
                # Resolve connector version
                version_id = acb.connector_version_id
                if acb.use_latest:
                    version_id = latest_connector_versions.get(acb.connector_id, version_id)

                # Resolve credential: override > assignment > device default
                cred_id: uuid.UUID | None = None
                if acb.alias in cred_overrides:
                    cred_id = cred_overrides[acb.alias]
                elif assignment.credential_id:
                    cred_id = assignment.credential_id
                elif device and device.default_credential_id:
                    cred_id = device.default_credential_id

                bindings.append({
                    "alias": acb.alias,
                    "connector_id": str(acb.connector_id),
                    "connector_version_id": str(version_id) if version_id else None,
                    "credential_name": cred_name_map.get(cred_id) if cred_id else None,
                    "use_latest": acb.use_latest,
                    "settings": acb.settings or {},
                    "connector_checksum": cv_checksum_map.get(version_id, "") if version_id else "",
                })
        else:
            # Fallback: legacy assignment connector bindings (for apps not yet migrated)
            for b in (assignment.connector_bindings or []):
                bindings.append({
                    "alias": b.alias,
                    "connector_id": str(b.connector_id),
                    "connector_version_id": str(b.connector_version_id),
                    "credential_name": cred_name_map.get(b.credential_id) if b.credential_id else None,
                    "use_latest": b.use_latest,
                    "settings": b.settings or {},
                    "connector_checksum": cv_checksum_map.get(b.connector_version_id, "") if b.connector_version_id else "",
                })

        jobs.append({
            "job_id": str(assignment.id),
            "device_id": str(assignment.device_id) if assignment.device_id else None,
            "device_host": device_host,
            "app_id": app.name,
            "app_version": app_version.version,
            "app_checksum": app_version.checksum_sha256 or "",
            "credential_names": credential_names,  # collector fetches each via /credentials/{name}
            "interval": interval,
            "parameters": params,
            "role": assignment.role,
            "max_execution_time": max_exec,
            "enabled": assignment.enabled,
            "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None,
            "connector_bindings": bindings,
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
    config_data: dict | None = None   # Key-value config/inventory data for config-table apps
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


# ── Performance counter normalization ────────────────────────

_PERF_PREV_PREFIX = "perf-prev:"
_PERF_PREV_TTL = 1200  # 20 minutes


def _calculate_perf_rate(
    current_value: float,
    previous_value: float,
    dt_seconds: float,
) -> float:
    """Calculate rate (per second) from counter delta.

    current < previous = always reset (no wrap detection).
    """
    if dt_seconds <= 0:
        return 0.0
    if current_value < previous_value:
        return 0.0
    if current_value == previous_value:
        return 0.0
    return (current_value - previous_value) / dt_seconds


async def _get_previous_perf_counters(
    device_id: str, component_type: str, component: str,
) -> dict | None:
    """Get previous counter values for a performance component.

    Returns dict like {"read_bytes": {"value": 123, "executed_at": "..."}, ...}
    Falls back to ClickHouse performance_latest if Redis cache expired.
    """
    from monctl_central.cache import _redis

    cache_key = f"{_PERF_PREV_PREFIX}{device_id}:{component_type}:{component}"

    if _redis:
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    # Fallback: ClickHouse performance_latest
    try:
        import asyncio
        from monctl_central.dependencies import get_clickhouse
        ch = get_clickhouse()
        if ch:
            rows = await asyncio.to_thread(
                ch._get_client().query,
                "SELECT metric_names, metric_values, metric_types, executed_at "
                "FROM performance_latest FINAL "
                "WHERE device_id = {device_id:UUID} "
                "  AND component_type = {component_type:String} "
                "  AND component = {component:String} "
                "LIMIT 1",
                parameters={
                    "device_id": device_id,
                    "component_type": component_type,
                    "component": component,
                },
            )
            named = list(rows.named_results())
            if named:
                row = named[0]
                names = row.get("metric_names", [])
                values = row.get("metric_values", [])
                types = row.get("metric_types", [])
                ea = row["executed_at"]
                ea_iso = ea.isoformat() if hasattr(ea, "isoformat") else str(ea)

                prev: dict = {}
                for i, name in enumerate(names):
                    mt = types[i] if i < len(types) else "gauge"
                    if mt == "counter":
                        prev[name] = {
                            "value": values[i] if i < len(values) else 0,
                            "executed_at": ea_iso,
                        }
                if prev:
                    if _redis:
                        await _redis.set(cache_key, json.dumps(prev), ex=_PERF_PREV_TTL)
                    return prev
    except Exception:
        pass

    return None


async def _cache_perf_counters(
    device_id: str, component_type: str, component: str,
    counter_data: dict, executed_at_iso: str,
) -> None:
    """Cache current counter values. ALWAYS called — even on reset."""
    from monctl_central.cache import _redis
    if not _redis:
        return
    cache_key = f"{_PERF_PREV_PREFIX}{device_id}:{component_type}:{component}"
    cache = {
        name: {"value": val, "executed_at": executed_at_iso}
        for name, val in counter_data.items()
    }
    if cache:
        try:
            await _redis.set(cache_key, json.dumps(cache), ex=_PERF_PREV_TTL)
        except Exception:
            pass


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

        # Performance-table apps: metrics may have component/component_type grouping
        # Each unique (component, component_type) becomes a separate ClickHouse row
        if target_table == "performance" and r.metrics:
            # Group metrics by (component, component_type)
            component_groups: dict[tuple[str, str], tuple[list[str], list[float], list[str]]] = {}
            for m in r.metrics:
                if not isinstance(m, dict):
                    continue
                comp = m.get("component", "")
                comp_type = m.get("component_type", "")
                key = (comp, comp_type)
                if key not in component_groups:
                    component_groups[key] = ([], [], [])
                raw_types = m.get("metric_types", [])
                for idx, (mn, mv) in enumerate(zip(m.get("metric_names", []), m.get("metric_values", []))):
                    component_groups[key][0].append(str(mn))
                    component_groups[key][1].append(float(mv))
                    component_groups[key][2].append(raw_types[idx] if idx < len(raw_types) else "gauge")
                # Also support flat name/value metrics (no metric_names array)
                if "name" in m and "value" in m and "metric_names" not in m:
                    component_groups[key][0].append(str(m["name"]))
                    component_groups[key][1].append(float(m["value"]))
                    component_groups[key][2].append("gauge")

            if component_groups:
                for (comp, comp_type), (mnames, mvalues, mtypes) in component_groups.items():
                    # Normalize counter metrics to rates
                    normalized_values = list(mvalues)
                    has_counters = any(t == "counter" for t in mtypes)
                    if has_counters:
                        previous = await _get_previous_perf_counters(
                            device_id_resolved, comp_type, comp,
                        )
                        counter_data: dict[str, float] = {}
                        for i, (name, value, mtype) in enumerate(zip(mnames, mvalues, mtypes)):
                            if mtype == "counter":
                                counter_data[name] = value
                                if previous and name in previous:
                                    try:
                                        prev_entry = previous[name]
                                        prev_ts_str = prev_entry["executed_at"]
                                        if isinstance(prev_ts_str, str):
                                            if prev_ts_str.endswith("Z"):
                                                prev_ts_str = prev_ts_str[:-1] + "+00:00"
                                            prev_ts = datetime.fromisoformat(prev_ts_str)
                                            if prev_ts.tzinfo is None:
                                                prev_ts = prev_ts.replace(tzinfo=timezone.utc)
                                        else:
                                            prev_ts = prev_ts_str
                                        dt = (executed_at - prev_ts).total_seconds()
                                        normalized_values[i] = _calculate_perf_rate(
                                            value, prev_entry["value"], dt,
                                        )
                                    except (ValueError, TypeError, KeyError):
                                        normalized_values[i] = 0.0
                                else:
                                    normalized_values[i] = 0.0
                        await _cache_perf_counters(
                            device_id_resolved, comp_type, comp,
                            counter_data, executed_at.isoformat(),
                        )

                    ch_rows.append({
                        "_target_table": "performance",
                        "assignment_id": str(assignment_id),
                        "collector_id": collector_uuid,
                        "app_id": enrichment.get("app_id", str(assignment_id)),
                        "device_id": device_id_resolved,
                        "component": comp,
                        "component_type": comp_type,
                        "state": state,
                        "output": "",
                        "error_message": r.error_message or "",
                        "metric_names": mnames,
                        "metric_values": normalized_values,
                        "metric_types": mtypes,
                        "executed_at": executed_at,
                        "execution_time": (r.execution_time_ms / 1000.0) if r.execution_time_ms else 0.0,
                        "started_at": started_at_dt,
                        "collector_name": request.collector_node,
                        "device_name": enrichment.get("device_name", ""),
                        "app_name": enrichment.get("app_name", ""),
                        "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
                        "tenant_name": enrichment.get("tenant_name", ""),
                    })
                continue  # Skip the default row builder below

        # Interface-table apps: if no interface_rows (e.g. SNMP timeout), skip
        # this result entirely. Interface poller failures should NOT be written
        # to availability_latency — they pollute the availability/latency chart.
        # The device's dedicated availability check already tracks reachability.
        if target_table == "interface" and not r.interface_rows:
            skipped += 1
            continue

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
                    prev_ts_str = prev["executed_at"]
                    if isinstance(prev_ts_str, str):
                        if prev_ts_str.endswith("Z"):
                            prev_ts_str = prev_ts_str[:-1] + "+00:00"
                        prev_ts = datetime.fromisoformat(prev_ts_str)
                        if prev_ts.tzinfo is None:
                            prev_ts = prev_ts.replace(tzinfo=timezone.utc)
                    else:
                        prev_ts = prev_ts_str
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
        elif target_table == "config" and r.config_data:
            # Config-table apps: each key-value pair becomes a separate ClickHouse row
            import hashlib as _hashlib
            _base = {
                "assignment_id": str(assignment_id),
                "collector_id": collector_uuid,
                "app_id": enrichment.get("app_id", str(assignment_id)),
                "device_id": device_id_resolved,
                "component": "",
                "component_type": enrichment.get("app_name", ""),
                "state": state,
                "executed_at": executed_at,
                "collector_name": request.collector_node,
                "device_name": enrichment.get("device_name", ""),
                "app_name": enrichment.get("app_name", ""),
                "tenant_id": enrichment.get("tenant_id", "00000000-0000-0000-0000-000000000000"),
                "tenant_name": enrichment.get("tenant_name", ""),
            }
            _config_rows = []
            for cfg_key, cfg_value in r.config_data.items():
                val_str = str(cfg_value) if cfg_value is not None else ""
                _config_rows.append({
                    **_base,
                    "_target_table": "config",
                    "config_key": cfg_key,
                    "config_value": val_str,
                    "config_hash": _hashlib.md5(val_str.encode()).hexdigest(),
                })
            # Suppress unchanged non-volatile keys
            _volatile = set(enrichment.get("volatile_keys") or [])
            _config_rows = _filter_config_rows(
                _config_rows,
                device_id=device_id_resolved,
                app_id=enrichment.get("app_id", str(assignment_id)),
                volatile_keys=_volatile,
                ch=ch,
            )
            ch_rows.extend(_config_rows)
            if _config_rows:
                _invalidate_config_hash_cache(
                    device_id_resolved,
                    enrichment.get("app_id", str(assignment_id)),
                )
            # Also insert an availability_latency row for status tracking
            ch_rows.append({
                "_target_table": "availability_latency",
                "assignment_id": str(assignment_id),
                "collector_id": collector_uuid,
                "app_id": enrichment.get("app_id", str(assignment_id)),
                "device_id": device_id_resolved,
                "state": state,
                "output": f"{len(r.config_data)} config keys collected",
                "error_message": r.error_message or "",
                "rtt_ms": 0.0,
                "response_time_ms": (r.execution_time_ms or 0) / 1.0,
                "reachable": 1 if r.reachable else 0,
                "status_code": 0,
                "metric_names": ["config_key_count"],
                "metric_values": [float(len(r.config_data))],
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
        else:
            row = {
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
            }
            # Performance table requires component/component_type
            if target_table == "performance":
                row["component"] = ""
                row["component_type"] = ""
            ch_rows.append(row)

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


# ---------------------------------------------------------------------------
# Config suppression: only write changed keys + volatile keys
# ---------------------------------------------------------------------------

import time as _time

_config_hash_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_CONFIG_HASH_CACHE_TTL = 60.0


def _get_cached_config_hashes(ch, device_id: str, app_id: str) -> dict[tuple[str, str, str], str]:
    cache_key = (device_id, app_id)
    now = _time.monotonic()
    cached = _config_hash_cache.get(cache_key)
    if cached and (now - cached[0]) < _CONFIG_HASH_CACHE_TTL:
        return cached[1]
    hashes = ch.get_config_hashes(device_id, app_id)
    _config_hash_cache[cache_key] = (now, hashes)
    return hashes


def _invalidate_config_hash_cache(device_id: str, app_id: str) -> None:
    _config_hash_cache.pop((device_id, app_id), None)


def _filter_config_rows(
    config_rows: list[dict],
    device_id: str,
    app_id: str,
    volatile_keys: set[str],
    ch,
) -> list[dict]:
    """Suppress unchanged non-volatile config keys. Volatile keys always written."""
    if not config_rows:
        return []

    existing_hashes = _get_cached_config_hashes(ch, device_id, app_id)

    # First-ever poll — write everything
    if not existing_hashes:
        return config_rows

    filtered = []
    for row in config_rows:
        key = row.get("config_key", "")
        if key in volatile_keys:
            filtered.append(row)
            continue
        lookup = (row.get("component_type", ""), row.get("component", ""), key)
        existing_hash = existing_hashes.get(lookup)
        if existing_hash is None or existing_hash != row.get("config_hash", ""):
            filtered.append(row)

    return filtered


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
            # Resolve volatile_keys from the assigned app version
            version_volatile_keys: list[str] = []
            if assignment.app_version_id:
                from monctl_central.storage.models import AppVersion
                ver = await db.get(AppVersion, assignment.app_version_id)
                if ver and ver.volatile_keys:
                    version_volatile_keys = ver.volatile_keys

            return {
                "app_id": str(app.id),
                "app_name": app.name,
                "target_table": app.target_table,
                "device_id": str(device.id) if device else "00000000-0000-0000-0000-000000000000",
                "device_name": device.name if device else "",
                "role": assignment.role or "",
                "tenant_id": str(device.tenant_id) if device and device.tenant_id else "00000000-0000-0000-0000-000000000000",
                "tenant_name": tenant.name if tenant else "",
                "volatile_keys": version_volatile_keys,
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
    container_states: dict[str, str] | None = None
    queue_stats: dict | None = None


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
        states = dict(collector.reported_peer_states or {})
        if request.peer_states:
            states.update(request.peer_states)
        if request.container_states:
            states["_container_states"] = request.container_states
        if request.queue_stats:
            states["_queue_stats"] = request.queue_stats
        collector.reported_peer_states = states
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


# ---------------------------------------------------------------------------
# PEP 503 Simple Repository API — serves wheels to collectors
# ---------------------------------------------------------------------------

@router.get("/pypi/simple/", tags=["collector-api"])
async def pypi_simple_index(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """PEP 503 simple index — list all approved packages as HTML links."""
    from fastapi.responses import HTMLResponse
    from monctl_central.storage.models import PythonModule

    stmt = (
        select(PythonModule)
        .where(PythonModule.is_approved == True)  # noqa: E712
        .order_by(PythonModule.name)
    )
    result = await db.execute(stmt)
    modules = result.scalars().all()

    links = []
    for m in modules:
        links.append(f'<a href="/api/v1/pypi/simple/{m.name}/">{m.name}</a>')

    html = (
        "<!DOCTYPE html>\n<html><head><title>Simple Index</title></head>\n"
        "<body>\n" + "\n".join(links) + "\n</body></html>"
    )
    return HTMLResponse(content=html, media_type="text/html")


@router.get("/pypi/simple/{package_name}/", tags=["collector-api"])
async def pypi_simple_package(
    package_name: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """PEP 503 package page — list wheel files with sha256 hashes."""
    from fastapi.responses import HTMLResponse
    from monctl_central.storage.models import PythonModule, PythonModuleVersion, WheelFile
    from monctl_central.python_modules.wheel_parser import normalize_package_name

    normalized = normalize_package_name(package_name)
    stmt = select(PythonModule).where(PythonModule.name == normalized)
    result = await db.execute(stmt)
    module = result.scalar_one_or_none()
    if not module:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Package not found")

    # Fetch all wheel files for this module
    wheel_stmt = (
        select(WheelFile)
        .join(PythonModuleVersion, WheelFile.module_version_id == PythonModuleVersion.id)
        .where(PythonModuleVersion.module_id == module.id)
        .order_by(WheelFile.filename)
    )
    wheel_result = await db.execute(wheel_stmt)
    wheels = wheel_result.scalars().all()

    links = []
    for w in wheels:
        links.append(
            f'<a href="/api/v1/pypi/wheels/{w.filename}#sha256={w.sha256_hash}">'
            f'{w.filename}</a>'
        )

    html = (
        f"<!DOCTYPE html>\n<html><head><title>Links for {normalized}</title></head>\n"
        f"<body>\n<h1>Links for {normalized}</h1>\n"
        + "\n".join(links)
        + "\n</body></html>"
    )
    return HTMLResponse(content=html, media_type="text/html")


@router.get("/pypi/wheels/{filename}", tags=["collector-api"])
async def pypi_serve_wheel(
    filename: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Serve a wheel file — first from disk, falling back to database."""
    from fastapi.responses import FileResponse, Response
    from monctl_central.config import settings
    from monctl_central.python_modules.wheel_parser import normalize_package_name, parse_wheel_filename
    from monctl_central.storage.models import WheelFile

    try:
        parts = parse_wheel_filename(filename)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid wheel filename",
        )

    # Try disk first
    normalized = normalize_package_name(parts["name"])
    wheel_path = Path(settings.wheel_storage_dir) / normalized / filename
    if wheel_path.exists():
        return FileResponse(
            path=str(wheel_path),
            media_type="application/octet-stream",
            filename=filename,
        )

    # Fall back to database
    stmt = select(WheelFile).where(WheelFile.filename == filename)
    wf = (await db.execute(stmt)).scalar_one_or_none()
    if wf is None or not wf.file_data:
        raise HTTPException(status_code=404, detail="Wheel file not found")

    return Response(
        content=wf.file_data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Connector endpoints for collectors
# ---------------------------------------------------------------------------

@router.get("/connectors/{connector_id}/metadata", tags=["collector-api"])
async def get_connector_metadata(
    connector_id: str,
    version_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return connector metadata (name, version, requirements, entry_class, checksum).

    By default returns the latest version. If version_id is provided, returns that
    specific version.
    """
    connector = await db.get(Connector, uuid.UUID(connector_id))
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    if version_id:
        stmt = select(ConnectorVersion).where(
            ConnectorVersion.id == uuid.UUID(version_id),
            ConnectorVersion.connector_id == connector.id,
        )
    else:
        stmt = select(ConnectorVersion).where(
            ConnectorVersion.connector_id == connector.id,
            ConnectorVersion.is_latest == True,  # noqa: E712
        )

    version = (await db.execute(stmt)).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Connector version not found")

    return {
        "name": connector.name,
        "connector_type": connector.connector_type,
        "version": version.version,
        "version_id": str(version.id),
        "requirements": version.requirements,
        "entry_class": version.entry_class,
        "checksum": version.checksum,
    }


@router.get("/connectors/{connector_id}/code", tags=["collector-api"])
async def get_connector_code(
    connector_id: str,
    version_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return the source code for a connector version.

    If version_id is provided, returns that specific version's code.
    Otherwise returns the latest version's code.
    """
    connector = await db.get(Connector, uuid.UUID(connector_id))
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    if version_id:
        stmt = select(ConnectorVersion).where(
            ConnectorVersion.id == uuid.UUID(version_id),
            ConnectorVersion.connector_id == connector.id,
        )
    else:
        stmt = select(ConnectorVersion).where(
            ConnectorVersion.connector_id == connector.id,
            ConnectorVersion.is_latest == True,  # noqa: E712
        )

    version = (await db.execute(stmt)).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Connector version not found")

    return {
        "connector_id": str(connector.id),
        "version_id": str(version.id),
        "version": version.version,
        "entry_class": version.entry_class,
        "checksum": version.checksum,
        "source_code": version.source_code,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/app-cache/push
# ---------------------------------------------------------------------------

class AppCachePushEntry(BaseModel):
    app_id: str
    device_id: str
    cache_key: str
    cache_value: dict
    ttl_seconds: int | None = None
    updated_at: str


class AppCachePushRequest(BaseModel):
    entries: list[AppCachePushEntry]


async def _resolve_collector_group(
    db: AsyncSession, auth: dict, collector_id_param: str | None, node_id_param: str | None,
) -> uuid.UUID:
    """Resolve the collector's group_id from auth, collector_id param, or node_id param."""
    # Try auth dict first (individual API key)
    cid = auth.get("collector_id")
    if not cid and collector_id_param:
        cid = collector_id_param
    if cid:
        collector = await db.get(Collector, uuid.UUID(cid))
        if collector and collector.group_id:
            return collector.group_id
    # Fallback: look up by hostname
    if node_id_param:
        stmt = select(Collector).where(Collector.hostname == node_id_param)
        collector = (await db.execute(stmt)).scalar_one_or_none()
        if collector and collector.group_id:
            return collector.group_id
    raise HTTPException(status_code=400, detail="Cannot resolve collector group")


@router.post("/app-cache/push", tags=["collector-api"])
async def push_app_cache(
    req: AppCachePushRequest,
    collector_id: str | None = Query(None),
    node_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Collectors push dirty cache entries to central."""
    group_id = await _resolve_collector_group(db, auth, collector_id, node_id)

    # Resolve app names → UUIDs (collectors use app name, DB uses UUID)
    app_names = {e.app_id for e in req.entries}
    app_name_to_id: dict[str, uuid.UUID] = {}
    if app_names:
        stmt = select(App.id, App.name).where(App.name.in_(app_names))
        rows = (await db.execute(stmt)).all()
        app_name_to_id = {r.name: r.id for r in rows}

    accepted = 0
    rejected = 0

    for entry in req.entries:
        try:
            entry_updated_at = datetime.fromisoformat(entry.updated_at)
        except (ValueError, TypeError):
            rejected += 1
            continue

        # Resolve app_id: try as name first, then as UUID
        resolved_app_id = app_name_to_id.get(entry.app_id)
        if resolved_app_id is None:
            try:
                resolved_app_id = uuid.UUID(entry.app_id)
            except ValueError:
                logger.warning("app_cache_push_unknown_app", app_id=entry.app_id)
                rejected += 1
                continue

        try:
            resolved_device_id = uuid.UUID(entry.device_id)
        except ValueError:
            rejected += 1
            continue

        ins = pg_insert(AppCache).values(
            collector_group_id=group_id,
            app_id=resolved_app_id,
            device_id=resolved_device_id,
            cache_key=entry.cache_key,
            cache_value=entry.cache_value,
            ttl_seconds=entry.ttl_seconds,
            updated_at=entry_updated_at,
        )
        upsert = ins.on_conflict_do_update(
            constraint="uq_app_cache_entry",
            set_={
                "cache_value": ins.excluded.cache_value,
                "ttl_seconds": ins.excluded.ttl_seconds,
                "updated_at": ins.excluded.updated_at,
            },
            where=AppCache.updated_at < ins.excluded.updated_at,
        )
        await db.execute(upsert)
        accepted += 1

    await db.flush()
    return {"status": "success", "data": {"accepted": accepted, "rejected": rejected}}


# ---------------------------------------------------------------------------
# GET /api/v1/app-cache/pull
# ---------------------------------------------------------------------------

@router.get("/app-cache/pull", tags=["collector-api"])
async def pull_app_cache(
    since: str | None = Query(None),
    limit: int = Query(1000, le=5000),
    collector_id: str | None = Query(None),
    node_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Collectors pull cache entries updated since their last sync."""
    group_id = await _resolve_collector_group(db, auth, collector_id, node_id)

    stmt = (
        select(AppCache)
        .where(AppCache.collector_group_id == group_id)
        .order_by(AppCache.updated_at.asc())
        .limit(limit + 1)
    )

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid 'since' timestamp")
        stmt = stmt.where(AppCache.updated_at > since_dt)

    rows = (await db.execute(stmt)).scalars().all()

    # Resolve app UUIDs → names (collectors use app name as key)
    app_ids = {row.app_id for row in rows}
    app_id_to_name: dict[uuid.UUID, str] = {}
    if app_ids:
        name_rows = (await db.execute(
            select(App.id, App.name).where(App.id.in_(app_ids))
        )).all()
        app_id_to_name = {r.id: r.name for r in name_rows}

    now = datetime.now(timezone.utc)
    entries = []
    for row in rows[:limit]:
        # Skip expired entries
        if row.ttl_seconds is not None:
            if row.updated_at.timestamp() + row.ttl_seconds < now.timestamp():
                continue
        # Use app name (not UUID) so collectors can match their local cache keys
        app_name = app_id_to_name.get(row.app_id)
        if app_name is None:
            continue  # Skip entries for deleted apps
        entries.append({
            "app_id": app_name,
            "device_id": str(row.device_id),
            "cache_key": row.cache_key,
            "cache_value": row.cache_value,
            "ttl_seconds": row.ttl_seconds,
            "updated_at": row.updated_at.isoformat(),
        })

    has_more = len(rows) > limit
    return {"status": "success", "data": {"entries": entries, "has_more": has_more}}


from monctl_central.upgrades.collector_api import router as upgrade_collector_router
router.include_router(upgrade_collector_router, prefix="/upgrade", tags=["upgrade"])
