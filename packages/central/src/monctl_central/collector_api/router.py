"""Collector API — endpoints used by the distributed collector system.

These endpoints replace the old /v1/collectors/{id}/config + /v1/ingest model
with a job-pull model where collectors fetch jobs, app code, and credentials
independently and push results in a collector-native format.

All endpoints are mounted at /api/v1/  (see main.py).
Authentication: Bearer token (API key) in Authorization header — same as existing /v1/.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.credentials.crypto import decrypt_dict
from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import (
    App,
    AppAssignment,
    AppVersion,
    CheckResultRecord,
    Collector,
    Credential,
    Device,
)

router = APIRouter()
logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

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
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return all active jobs (assignments) for the collector cluster.

    A "job" maps 1-to-1 to an AppAssignment. Collectors use consistent hashing
    on job_id to decide which node is responsible for each job.

    Supports delta-sync via ?since=<ISO timestamp>. Returns:
    - jobs: list of changed/new jobs since `since` (or all jobs if omitted)
    - deleted_ids: list of job IDs that were deleted since `since`
      (NOTE: current implementation always returns [] for deleted_ids — soft
       delete support can be added later)
    """
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid 'since' timestamp: {since!r}. Use ISO-8601 format.",
            )

    # Fetch all enabled assignments with their app, app_version, and device
    stmt = (
        select(AppAssignment, App, AppVersion, Device)
        .join(App, AppAssignment.app_id == App.id)
        .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
        .outerjoin(Device, AppAssignment.device_id == Device.id)
        .where(AppAssignment.enabled == True)  # noqa: E712
    )
    if since_dt is not None:
        stmt = stmt.where(AppAssignment.updated_at > since_dt)

    result = await db.execute(stmt)
    rows = result.all()

    jobs = []
    for row in rows:
        assignment: AppAssignment = row.AppAssignment
        app: App = row.App
        app_version: AppVersion = row.AppVersion
        device: Device | None = row.Device

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
    """Return app metadata (requirements, entry_class, checksum) for a given app name.

    Used by collectors to know what packages to install before downloading code.
    """
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

    # Pick version
    versions = sorted(app.versions, key=lambda v: v.published_at, reverse=True)
    if version:
        av = next((v for v in versions if v.version == version), None)
        if av is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"App '{app_name}' version '{version}' not found",
            )
    else:
        av = versions[0] if versions else None
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
    """Return Python source code for a poll app.

    The collector should:
    1. Verify the returned checksum matches sha256(code).
    2. Save code to /data/apps/{app_id}/{version}/module.py
    3. Create/reuse a virtualenv for the requirements set.
    """
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
        av = versions[0] if versions else None
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
    """Return decrypted credential data for a named credential.

    Used by collectors to resolve $credential:<name> references in job config.
    The response contains the raw (decrypted) credential data dict.

    NOTE: This endpoint should only be accessible over HTTPS in production.
    """
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

    Results are stored in the check_results table and forwarded to
    VictoriaMetrics for time-series storage (same as the legacy /v1/ingest).
    """
    from monctl_central.config import settings as central_settings

    # Try to find a matching collector record by hostname
    collector_stmt = select(Collector).where(Collector.hostname == request.collector_node)
    collector_row = await db.execute(collector_stmt)
    collector = collector_row.scalar_one_or_none()
    # Use collector UUID if found; fall back to nil UUID
    collector_uuid = collector.id if collector else uuid.UUID(int=0)

    records = []
    for r in request.results:
        try:
            assignment_id = uuid.UUID(r.job_id)
        except ValueError:
            continue  # Skip malformed job_ids

        # Map status string → integer state
        state = _STATUS_TO_STATE.get(r.status.lower(), 3)
        if not r.reachable and state == 0:
            state = 2  # treat unreachable as CRITICAL even if status says ok

        # Build output string
        if r.error_message:
            output = r.error_message
        elif r.reachable:
            rtt = r.rtt_ms or r.response_time_ms
            output = f"OK — {rtt:.1f}ms" if rtt else "OK"
        else:
            output = "CRITICAL — unreachable"

        # Performance data
        perf: dict = {}
        if r.rtt_ms is not None:
            perf["rtt_ms"] = r.rtt_ms
        if r.response_time_ms is not None:
            perf["response_time_ms"] = r.response_time_ms
        if r.metrics:
            perf["metrics"] = r.metrics

        executed_at = datetime.fromtimestamp(r.timestamp, tz=timezone.utc)

        record = CheckResultRecord(
            assignment_id=assignment_id,
            collector_id=collector_uuid,
            app_id=assignment_id,  # re-use assignment_id — will refine later
            state=state,
            output=output,
            performance_data=perf if perf else None,
            executed_at=executed_at,
            execution_time=r.execution_time_ms / 1000.0 if r.execution_time_ms else None,
        )
        records.append(record)

    if records:
        db.add_all(records)
        await db.flush()

        # Push to VictoriaMetrics (best-effort, same as /v1/ingest)
        try:
            await _push_to_victoriametrics(request, central_settings)
        except Exception:
            logger.warning("victoriametrics_push_failed", node=request.collector_node)

    return {
        "accepted": len(records),
        "skipped": len(request.results) - len(records),
    }


async def _push_to_victoriametrics(request: SubmitResultsRequest, settings) -> None:
    """Push results to VictoriaMetrics in Prometheus line protocol."""
    if not getattr(settings, "victoria_metrics_url", None):
        return

    import aiohttp
    lines = []
    for r in request.results:
        ts_ms = int(r.timestamp * 1000)
        safe_node = request.collector_node.replace('"', "")
        safe_job = r.job_id.replace('"', "")
        reachable_val = 1 if r.reachable else 0

        lines.append(
            f'monctl_reachable{{collector="{safe_node}",job_id="{safe_job}"}} '
            f"{reachable_val} {ts_ms}"
        )
        if r.rtt_ms is not None:
            lines.append(
                f'monctl_rtt_ms{{collector="{safe_node}",job_id="{safe_job}"}} '
                f"{r.rtt_ms} {ts_ms}"
            )
        if r.response_time_ms is not None:
            lines.append(
                f'monctl_response_time_ms{{collector="{safe_node}",job_id="{safe_job}"}} '
                f"{r.response_time_ms} {ts_ms}"
            )

    if not lines:
        return

    payload = "\n".join(lines) + "\n"
    async with aiohttp.ClientSession() as session:
        vm_url = settings.victoria_metrics_url.rstrip("/")
        async with session.post(
            f"{vm_url}/api/v1/import/prometheus",
            data=payload,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status >= 400:
                logger.warning("victoriametrics_error", status=resp.status)


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
        collector.status = "ACTIVE"
        await db.flush()

    return {
        "ok": True,
        "node_id": request.node_id,
        "known": collector is not None,
    }
