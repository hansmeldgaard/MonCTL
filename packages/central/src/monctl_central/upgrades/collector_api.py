"""Collector-facing upgrade endpoints.

Mounted at /api/v1/upgrade/ (see main.py).
Collectors poll these to check for available upgrades and download images.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.config import settings
from monctl_central.dependencies import get_db, require_collector_auth
from monctl_central.storage.models import (
    Collector,
    OsUpdatePackage,
    UpgradeJob,
    UpgradeJobStep,
    UpgradePackage,
)
from monctl_central.upgrades.schemas import CollectorUpgradeReport

router = APIRouter()
logger = structlog.get_logger()


async def _resolve_collector(
    db: AsyncSession, auth: dict, collector_id: str | None = None, node_id: str | None = None,
) -> Collector | None:
    """Resolve the collector from auth context or query params."""
    cid = collector_id or auth.get("collector_id") or node_id
    if not cid:
        return None
    try:
        stmt = select(Collector).where(Collector.id == uuid.UUID(cid))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except (ValueError, TypeError):
        # Try by hostname
        stmt = select(Collector).where(Collector.hostname == cid)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


@router.get("/available")
async def check_available_upgrade(
    collector_id: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    """Check if an upgrade is available for this collector."""
    collector = await _resolve_collector(db, auth, collector_id, node_id)

    # Find the latest package that contains collector images
    stmt = (
        select(UpgradePackage)
        .where(UpgradePackage.contains_collector == True)  # noqa: E712
        .order_by(UpgradePackage.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    package = result.scalar_one_or_none()

    if not package:
        return {"status": "success", "data": {"available": False}}

    # Check if there's an active upgrade job with a step for this collector
    upgrade_step = None
    if collector:
        hostname = collector.hostname or collector.name
        stmt = (
            select(UpgradeJobStep)
            .join(UpgradeJob)
            .where(
                UpgradeJob.status.in_(["running", "pending"]),
                UpgradeJobStep.node_hostname == hostname,
                UpgradeJobStep.status.in_(["pending", "waiting"]),
            )
        )
        result = await db.execute(stmt)
        upgrade_step = result.scalar_one_or_none()

    return {
        "status": "success",
        "data": {
            "available": True,
            "version": package.version,
            "filename": package.filename,
            "sha256_hash": package.sha256_hash,
            "changelog": package.changelog,
            "assigned": upgrade_step is not None,
            "step_id": str(upgrade_step.id) if upgrade_step else None,
        },
    }


@router.get("/package/{filename}")
async def download_package(
    filename: str,
    version: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    """Download a docker image tarball from an upgrade bundle."""
    if ".." in filename or "/" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename",
        )

    upgrade_dir = Path(settings.upgrade_storage_dir)

    if version:
        # Look in the specific version directory
        search_dir = upgrade_dir / version
    else:
        # Find the latest package
        stmt = (
            select(UpgradePackage)
            .where(UpgradePackage.contains_collector == True)  # noqa: E712
            .order_by(UpgradePackage.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        package = result.scalar_one_or_none()
        if not package:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No packages available")
        search_dir = upgrade_dir / package.version

    # Search for the file in the version directory
    file_path = None
    for p in search_dir.rglob(filename):
        file_path = p
        break

    if not file_path or not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    return FileResponse(
        str(file_path),
        media_type="application/x-tar",
        filename=filename,
    )


@router.get("/os-package/{filename}")
async def download_os_package(
    filename: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    """Download a cached .deb OS package."""
    if ".." in filename or "/" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename",
        )

    os_dir = Path(settings.upgrade_storage_dir) / "os-packages"
    file_path = os_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    return FileResponse(
        str(file_path),
        media_type="application/vnd.debian.binary-package",
        filename=filename,
    )


@router.post("/report")
async def report_upgrade_result(
    report: CollectorUpgradeReport,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    """Collector reports the result of an upgrade."""
    # Resolve the collector
    collector = await _resolve_collector(db, auth, report.collector_id)
    if not collector:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collector not found",
        )

    hostname = collector.hostname or collector.name

    # Find the active step for this collector
    stmt = (
        select(UpgradeJobStep)
        .join(UpgradeJob)
        .where(
            UpgradeJob.status == "running",
            UpgradeJobStep.node_hostname == hostname,
            UpgradeJobStep.status.in_(["waiting", "running"]),
        )
    )
    result = await db.execute(stmt)
    step = result.scalar_one_or_none()

    if step:
        step.status = report.status
        step.completed_at = datetime.now(timezone.utc)
        step.output_log = report.output_log
        step.error_message = report.error_message
        await db.flush()

        # Check if all steps in this job are done
        job = await db.get(UpgradeJob, step.job_id)
        if job:
            all_steps = (await db.execute(
                select(UpgradeJobStep).where(UpgradeJobStep.job_id == job.id)
            )).scalars().all()

            all_done = all(s.status in ("completed", "failed", "skipped", "cancelled") for s in all_steps)
            if all_done:
                has_failure = any(s.status == "failed" for s in all_steps)
                job.status = "failed" if has_failure else "completed"
                job.completed_at = datetime.now(timezone.utc)
                if has_failure:
                    failed_nodes = [s.node_hostname for s in all_steps if s.status == "failed"]
                    job.error_message = f"Failed on nodes: {', '.join(failed_nodes)}"
                await db.flush()

    logger.info(
        "collector_upgrade_report",
        collector=hostname,
        status=report.status,
        version=report.target_version,
    )

    return {"status": "success", "data": {"received": True}}
