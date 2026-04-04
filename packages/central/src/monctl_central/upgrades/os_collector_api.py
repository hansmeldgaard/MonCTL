"""Collector-facing OS package distribution endpoints.
Mounted at /api/v1/os-packages/.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_collector_auth

logger = structlog.get_logger()
router = APIRouter()


class OsInstallReportRequest(BaseModel):
    collector_id: str = Field(default="")
    installed_packages: list[str] = Field(default_factory=list)
    success: bool = True
    output: str | None = None
    error: str | None = None


@router.post("/report-installed")
async def report_installed(
    request: OsInstallReportRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    from monctl_central.storage.models import OsAvailableUpdate, Collector
    from sqlalchemy import update as sql_update
    import uuid as _uuid

    hostname = "unknown"
    cid = auth.get("collector_id") or request.collector_id
    if cid:
        collector = await db.get(Collector, _uuid.UUID(cid))
        if collector:
            hostname = collector.hostname

    if request.success:
        for pkg in request.installed_packages:
            await db.execute(
                sql_update(OsAvailableUpdate)
                .where(OsAvailableUpdate.node_hostname == hostname, OsAvailableUpdate.package_name == pkg)
                .values(is_installed=True)
            )
        await db.commit()

    return {"status": "success"}


# ---------------------------------------------------------------------------
# Pull-based OS update endpoints for collectors
# ---------------------------------------------------------------------------

async def _resolve_node_hostnames(
    hostname: str, request: Request, db: AsyncSession,
) -> set[str]:
    """Resolve the caller to one or more SystemVersion node_hostnames.

    Matches by: (1) direct hostname, (2) Collector.ip_addresses → SystemVersion,
    (3) request's X-Forwarded-For IP → SystemVersion.
    """
    from monctl_central.storage.models import SystemVersion, Collector

    match_hostnames: set[str] = set()
    if hostname:
        match_hostnames.add(hostname)

    # Resolve via Collector table: collector hostname → ip_addresses → SystemVersion
    collector_record = (await db.execute(
        select(Collector).where(Collector.hostname == hostname)
    )).scalar_one_or_none() if hostname else None

    if collector_record and collector_record.ip_addresses:
        ips = collector_record.ip_addresses
        collector_ip = ""
        if isinstance(ips, list) and ips:
            collector_ip = ips[0]
        elif isinstance(ips, dict):
            collector_ip = next(iter(ips.values()), "")
        if collector_ip:
            sv = (await db.execute(
                select(SystemVersion).where(SystemVersion.node_ip == collector_ip)
            )).scalars().first()
            if sv:
                match_hostnames.add(sv.node_hostname)

    # Resolve via request IP (X-Forwarded-For or direct)
    caller_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not caller_ip:
        caller_ip = request.client.host if request.client else ""
    if caller_ip:
        sv = (await db.execute(
            select(SystemVersion).where(SystemVersion.node_ip == caller_ip)
        )).scalars().first()
        if sv:
            match_hostnames.add(sv.node_hostname)

    match_hostnames.discard("")
    return match_hostnames


@router.get("/my-tasks")
async def get_my_tasks(
    request: Request,
    hostname: str = "",
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    """Collector polls for pending OS install steps assigned to it."""
    from monctl_central.storage.models import OsInstallJob, OsInstallJobStep

    match_hostnames = await _resolve_node_hostnames(hostname, request, db)

    if not match_hostnames:
        return {"status": "success", "data": None}

    stmt = (
        select(OsInstallJobStep)
        .join(OsInstallJob)
        .where(
            OsInstallJobStep.node_hostname.in_(match_hostnames),
            OsInstallJobStep.status == "awaiting_collector",
            OsInstallJob.status.in_(["running"]),
        )
        .order_by(OsInstallJobStep.step_order)
        .limit(1)
    )
    result = await db.execute(stmt)
    step = result.scalar_one_or_none()

    if not step:
        return {"status": "success", "data": None}

    # Load the parent job for package_names
    job = await db.get(OsInstallJob, step.job_id)

    return {
        "status": "success",
        "data": {
            "job_id": str(step.job_id),
            "step_id": str(step.id),
            "action": step.action,
            "package_names": job.package_names if job else [],
        },
    }


class StepResultRequest(BaseModel):
    step_id: str = Field(min_length=1)
    status: str = Field(pattern="^(completed|failed)$")
    output_log: str | None = None
    error_message: str | None = None


@router.post("/step-result")
async def report_step_result(
    request: StepResultRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    """Collector reports the result of an OS install step.

    On success, advances the job to the next step (for rolling strategies).
    """
    import uuid as _uuid
    from monctl_central.storage.models import (
        OsInstallJob, OsInstallJobStep, OsAvailableUpdate, OsInstallAudit,
    )
    from monctl_central.dependencies import get_session_factory
    from sqlalchemy import update as sql_update

    step = await db.get(OsInstallJobStep, _uuid.UUID(request.step_id))
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    if step.status != "awaiting_collector":
        raise HTTPException(status_code=409, detail=f"Step not in awaiting_collector state (is {step.status})")

    job = await db.get(OsInstallJob, step.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    from datetime import datetime, timezone
    step.status = request.status
    step.output_log = request.output_log
    step.error_message = request.error_message
    step.completed_at = datetime.now(timezone.utc)
    await db.flush()

    # Mark packages as installed + audit log on success
    if request.status == "completed" and step.action == "install":
        for pkg in (job.package_names or []):
            await db.execute(
                sql_update(OsAvailableUpdate)
                .where(
                    OsAvailableUpdate.node_hostname == step.node_hostname,
                    OsAvailableUpdate.package_name == pkg,
                )
                .values(is_installed=True)
            )
            db.add(OsInstallAudit(
                node_hostname=step.node_hostname,
                node_role=step.node_role,
                package_name=pkg,
                action="install",
                job_id=job.id,
                installed_by=job.started_by or "system",
            ))

    await db.commit()

    # Advance the job to the next step in the background
    from monctl_central.upgrades.os_service import advance_collector_job
    background_tasks.add_task(advance_collector_job, get_session_factory(), job.id)

    return {"status": "success"}


class OsUpdateReport(BaseModel):
    hostname: str = Field(default="")
    updates: list[dict] = Field(default_factory=list)


@router.post("/report-updates")
async def report_updates(
    req: OsUpdateReport,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    """Collector reports its available OS updates (from `apt list --upgradable`)."""
    from sqlalchemy import delete as sql_delete
    from monctl_central.storage.models import OsAvailableUpdate, SystemVersion

    hostnames = await _resolve_node_hostnames(req.hostname, request, db)
    if not hostnames:
        raise HTTPException(404, "Node not found")

    # Pick the SystemVersion-matching hostname (prefer one that exists in DB)
    sv = None
    for h in hostnames:
        sv = (await db.execute(
            select(SystemVersion).where(SystemVersion.node_hostname == h)
        )).scalars().first()
        if sv:
            break
    if not sv:
        raise HTTPException(404, "Node not registered")

    # Replace this node's available-updates list
    await db.execute(sql_delete(OsAvailableUpdate).where(
        OsAvailableUpdate.node_hostname == sv.node_hostname
    ))
    for u in req.updates:
        db.add(OsAvailableUpdate(
            node_hostname=sv.node_hostname,
            node_role=sv.node_role,
            package_name=u.get("package_name", u.get("package", "")),
            current_version=u.get("current_version", u.get("current", "")),
            new_version=u.get("new_version", u.get("new", "")),
            severity=u.get("severity", "normal"),
        ))
    await db.commit()
    return {"status": "success", "count": len(req.updates)}
