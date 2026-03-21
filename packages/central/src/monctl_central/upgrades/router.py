"""Upgrade management admin API router.

Mounted at /v1/upgrades (see api/router.py).
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, func, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import httpx

from monctl_central.config import settings
from monctl_central.dependencies import get_db, get_session_factory, require_admin, require_auth
from monctl_central.storage.models import (
    Collector,
    OsAvailableUpdate,
    OsCachedPackage,
    OsUpdatePackage,
    SystemVersion,
    UpgradeJob,
    UpgradeJobStep,
    UpgradePackage,
)
from monctl_central.upgrades.bundle_parser import parse_bundle
from monctl_central.upgrades.os_updates import (
    check_os_updates_via_ssh,
    compute_file_hash as compute_file_hash_ssh,
    download_os_packages_via_ssh,
)
from monctl_central.upgrades.os_service import (
    check_node_updates,
    install_packages_on_node,
    fetch_deb_from_sidecar,
    compute_file_hash,
    download_packages_via_sidecar,
)
from monctl_central.upgrades.schemas import (
    DownloadOsPackagesRequest,
    DownloadOsUpdatesRequest,
    InstallOsOnNodeRequest,
    StartUpgradeRequest,
)
from monctl_central.upgrades.service import create_upgrade_job, execute_upgrade_job

router = APIRouter()
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _fmt_version(v: SystemVersion) -> dict:
    return {
        "id": str(v.id),
        "node_hostname": v.node_hostname,
        "node_role": v.node_role,
        "node_ip": v.node_ip,
        "monctl_version": v.monctl_version,
        "docker_image_id": v.docker_image_id,
        "os_version": v.os_version,
        "kernel_version": v.kernel_version,
        "python_version": v.python_version,
        "last_reported_at": v.last_reported_at.isoformat() if v.last_reported_at else None,
    }


def _fmt_package(p: UpgradePackage) -> dict:
    return {
        "id": str(p.id),
        "version": p.version,
        "package_type": p.package_type,
        "filename": p.filename,
        "file_size": p.file_size,
        "sha256_hash": p.sha256_hash,
        "changelog": p.changelog,
        "contains_central": p.contains_central,
        "contains_collector": p.contains_collector,
        "uploaded_by": p.uploaded_by,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _fmt_step(s: UpgradeJobStep) -> dict:
    return {
        "id": str(s.id),
        "step_order": s.step_order,
        "node_hostname": s.node_hostname,
        "node_role": s.node_role,
        "node_ip": s.node_ip,
        "action": s.action,
        "status": s.status,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        "output_log": s.output_log,
        "error_message": s.error_message,
    }


def _fmt_job(j: UpgradeJob) -> dict:
    return {
        "id": str(j.id),
        "upgrade_package_id": str(j.upgrade_package_id),
        "target_version": j.target_version,
        "scope": j.scope,
        "strategy": j.strategy,
        "status": j.status,
        "started_by": j.started_by,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "error_message": j.error_message,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "steps": [_fmt_step(s) for s in j.steps] if j.steps else [],
    }


def _fmt_os_pkg(p: OsUpdatePackage) -> dict:
    return {
        "id": str(p.id),
        "package_name": p.package_name,
        "version": p.version,
        "architecture": p.architecture,
        "filename": p.filename,
        "file_size": p.file_size,
        "sha256_hash": p.sha256_hash,
        "severity": p.severity,
        "source": p.source,
        "is_downloaded": p.is_downloaded,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_upgrade_status(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """System version info + available packages."""
    # System versions
    result = await db.execute(select(SystemVersion).order_by(SystemVersion.node_hostname))
    versions = [_fmt_version(v) for v in result.scalars().all()]

    # Available packages
    result = await db.execute(select(UpgradePackage).order_by(UpgradePackage.created_at.desc()))
    packages = [_fmt_package(p) for p in result.scalars().all()]

    return {
        "status": "success",
        "data": {
            "versions": versions,
            "packages": packages,
        },
    }


@router.post("/upload")
async def upload_package(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Upload a .tar.gz upgrade bundle."""
    if not file.filename or not file.filename.endswith((".tar.gz", ".tgz")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .tar.gz bundle",
        )

    upgrade_dir = Path(settings.upgrade_storage_dir)
    upgrade_dir.mkdir(parents=True, exist_ok=True)

    # Save to temp location, then parse
    temp_path = upgrade_dir / f"_upload_{uuid.uuid4().hex}.tar.gz"
    try:
        with open(temp_path, "wb") as f:
            while chunk := await file.read(8192):
                f.write(chunk)

        with open(temp_path, "rb") as f:
            bundle_dir = upgrade_dir / f"_parse_{uuid.uuid4().hex}"
            info = parse_bundle(f, bundle_dir)

        # Check for duplicate version
        existing = (await db.execute(
            select(UpgradePackage).where(UpgradePackage.version == info.version)
        )).scalar_one_or_none()
        if existing:
            shutil.rmtree(bundle_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Package version {info.version} already exists",
            )

        # Move to final location
        final_dir = upgrade_dir / info.version
        if final_dir.exists():
            shutil.rmtree(final_dir)
        bundle_dir.rename(final_dir)

        # Also keep the original tarball
        final_tar = upgrade_dir / file.filename
        temp_path.rename(final_tar)

        package = UpgradePackage(
            version=info.version,
            package_type="bundle",
            filename=file.filename,
            file_size=info.file_size,
            sha256_hash=info.sha256_hash,
            changelog=info.changelog,
            metadata_={"min_version": info.min_version} if info.min_version else {},
            contains_central=info.contains_central,
            contains_collector=info.contains_collector,
            uploaded_by=auth.get("username", "unknown"),
        )
        db.add(package)
        await db.flush()

        return {"status": "success", "data": _fmt_package(package)}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("upload_package_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid bundle: {exc}",
        )
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


@router.delete("/packages/{package_id}")
async def delete_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Delete an upgrade package."""
    package = await db.get(UpgradePackage, package_id)
    if not package:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    # Remove files
    upgrade_dir = Path(settings.upgrade_storage_dir)
    version_dir = upgrade_dir / package.version
    if version_dir.exists():
        shutil.rmtree(version_dir, ignore_errors=True)
    tarball = upgrade_dir / package.filename
    if tarball.exists():
        tarball.unlink(missing_ok=True)

    await db.delete(package)
    await db.flush()

    return {"status": "success", "data": None}


@router.post("/execute")
async def start_upgrade(
    request: StartUpgradeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
    session_factory=Depends(get_session_factory),
):
    """Start an upgrade job."""
    package = await db.get(UpgradePackage, uuid.UUID(request.upgrade_package_id))
    if not package:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    # Check no running jobs
    running = (await db.execute(
        select(UpgradeJob).where(UpgradeJob.status.in_(["pending", "running"]))
    )).scalar_one_or_none()
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another upgrade job is already running",
        )

    job = await create_upgrade_job(
        db, package, request.scope, request.strategy,
        started_by=auth.get("username", "unknown"),
    )
    await db.commit()

    # Reload with steps
    stmt = select(UpgradeJob).where(UpgradeJob.id == job.id).options(selectinload(UpgradeJob.steps))
    result = await db.execute(stmt)
    job = result.scalar_one()

    background_tasks.add_task(execute_upgrade_job, session_factory, job.id)

    return {"status": "success", "data": _fmt_job(job)}


@router.get("/jobs")
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """List all upgrade jobs."""
    stmt = (
        select(UpgradeJob)
        .options(selectinload(UpgradeJob.steps))
        .order_by(UpgradeJob.created_at.desc())
    )
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {"status": "success", "data": [_fmt_job(j) for j in jobs]}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Get a single upgrade job with steps."""
    stmt = (
        select(UpgradeJob)
        .where(UpgradeJob.id == job_id)
        .options(selectinload(UpgradeJob.steps))
    )
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return {"status": "success", "data": _fmt_job(job)}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Cancel a pending or running upgrade job."""
    job = await db.get(UpgradeJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status not in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel job in '{job.status}' state",
        )
    job.status = "cancelled"
    await db.flush()

    # Cancel pending steps
    stmt = select(UpgradeJobStep).where(
        UpgradeJobStep.job_id == job_id,
        UpgradeJobStep.status.in_(["pending", "waiting"]),
    )
    result = await db.execute(stmt)
    for step in result.scalars().all():
        step.status = "cancelled"
    await db.flush()

    # Reload with steps
    stmt = select(UpgradeJob).where(UpgradeJob.id == job_id).options(selectinload(UpgradeJob.steps))
    result = await db.execute(stmt)
    job = result.scalar_one()

    return {"status": "success", "data": _fmt_job(job)}


@router.post("/os/check")
async def check_os_updates(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Check OS updates on all known nodes via SSH."""
    # Gather all node IPs
    result = await db.execute(select(SystemVersion))
    nodes = result.scalars().all()

    all_updates = {}
    for node in nodes:
        updates = await check_os_updates_via_ssh(node.node_ip)
        all_updates[node.node_hostname] = [
            {
                "package_name": u.package_name,
                "current_version": u.current_version,
                "new_version": u.new_version,
                "severity": u.severity,
                "architecture": u.architecture,
            }
            for u in updates
        ]

    return {"status": "success", "data": all_updates}


@router.post("/os/download")
async def download_os_updates(
    request: DownloadOsUpdatesRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Download OS packages via SSH from the first available central node."""
    os_dir = Path(settings.upgrade_storage_dir) / "os-packages"
    os_dir.mkdir(parents=True, exist_ok=True)

    # Use the first central node to download packages
    result = await db.execute(
        select(SystemVersion).where(SystemVersion.node_role == "central").limit(1)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No central nodes registered",
        )

    downloaded = await download_os_packages_via_ssh(node.node_ip, request.package_names, os_dir)

    saved = []
    for path in downloaded:
        file_hash = compute_file_hash(path)
        file_size = path.stat().st_size
        filename = path.name

        # Parse package name and version from .deb filename
        parts = filename.replace(".deb", "").split("_")
        pkg_name = parts[0] if parts else filename
        pkg_version = parts[1] if len(parts) > 1 else "unknown"
        arch = parts[2] if len(parts) > 2 else "amd64"

        # Upsert into DB
        existing = (await db.execute(
            select(OsUpdatePackage).where(
                OsUpdatePackage.package_name == pkg_name,
                OsUpdatePackage.version == pkg_version,
                OsUpdatePackage.architecture == arch,
            )
        )).scalar_one_or_none()

        if existing:
            existing.filename = filename
            existing.file_size = file_size
            existing.sha256_hash = file_hash
            existing.is_downloaded = True
        else:
            pkg = OsUpdatePackage(
                package_name=pkg_name,
                version=pkg_version,
                architecture=arch,
                filename=filename,
                file_size=file_size,
                sha256_hash=file_hash,
                severity="normal",
                source=node.node_hostname,
                is_downloaded=True,
            )
            db.add(pkg)

        saved.append({"filename": filename, "size": file_size, "sha256": file_hash})

    await db.flush()

    return {"status": "success", "data": saved}


@router.get("/os/packages")
async def list_os_packages(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """List cached OS packages."""
    result = await db.execute(
        select(OsUpdatePackage).order_by(OsUpdatePackage.package_name, OsUpdatePackage.version)
    )
    packages = result.scalars().all()
    return {"status": "success", "data": [_fmt_os_pkg(p) for p in packages]}


# ---------------------------------------------------------------------------
# New sidecar-based OS update endpoints
# ---------------------------------------------------------------------------

@router.get("/badge")
async def get_upgrade_badge(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return pending update counts for sidebar badge."""
    from monctl_central.cache import _redis
    count = 0
    if _redis:
        raw = await _redis.get("monctl:os_updates:count")
        if raw:
            count = int(raw)
    else:
        result = await db.execute(
            select(func.count()).select_from(OsAvailableUpdate).where(
                OsAvailableUpdate.is_installed == False  # noqa: E712
            )
        )
        count = result.scalar() or 0
    return {"status": "success", "data": {"os_update_count": count}}


@router.post("/check-os")
async def check_os_updates_sidecar(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Check all nodes for OS updates via their sidecars."""
    result = await db.execute(select(SystemVersion))
    nodes = result.scalars().all()

    all_updates: dict[str, list[dict]] = {}
    for node in nodes:
        try:
            updates = await check_node_updates(node.node_ip)
        except Exception as exc:
            logger.warning("check_node_updates_failed", node=node.node_hostname, error=str(exc))
            all_updates[node.node_hostname] = []
            continue

        # Delete old entries for this node
        await db.execute(
            delete(OsAvailableUpdate).where(
                OsAvailableUpdate.node_hostname == node.node_hostname
            )
        )

        node_updates = []
        for u in updates:
            entry = OsAvailableUpdate(
                node_hostname=node.node_hostname,
                node_role=node.node_role,
                package_name=u.get("package_name", u.get("package", "")),
                current_version=u.get("current_version", ""),
                new_version=u.get("new_version", u.get("version", "")),
                severity=u.get("severity", "normal"),
            )
            db.add(entry)
            node_updates.append({
                "package_name": entry.package_name,
                "current_version": entry.current_version,
                "new_version": entry.new_version,
                "severity": entry.severity,
            })
        all_updates[node.node_hostname] = node_updates

    await db.flush()

    # Update Redis badge count
    from monctl_central.cache import _redis
    if _redis:
        count_result = await db.execute(
            select(func.count()).select_from(OsAvailableUpdate).where(
                OsAvailableUpdate.is_installed == False  # noqa: E712
            )
        )
        count = count_result.scalar() or 0
        await _redis.set("monctl:os_updates:count", str(count))

    return {"status": "success", "data": all_updates}


@router.get("/os-updates")
async def list_os_updates(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """List all available (not installed) updates grouped by node hostname."""
    result = await db.execute(
        select(OsAvailableUpdate)
        .where(OsAvailableUpdate.is_installed == False)  # noqa: E712
        .order_by(OsAvailableUpdate.node_hostname, OsAvailableUpdate.package_name)
    )
    rows = result.scalars().all()
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r.node_hostname, []).append({
            "id": str(r.id),
            "package_name": r.package_name,
            "current_version": r.current_version,
            "new_version": r.new_version,
            "severity": r.severity,
            "is_downloaded": r.is_downloaded,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        })
    return {"status": "success", "data": grouped}


@router.post("/os-download")
async def download_os_packages(
    request: DownloadOsPackagesRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Download .deb packages on a central node via sidecar."""
    # Find first central node
    result = await db.execute(
        select(SystemVersion).where(SystemVersion.node_role == "central").limit(1)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No central nodes registered")

    # Tell sidecar to download packages
    dl_result = await download_packages_via_sidecar(node.node_ip, request.package_names)
    filenames = dl_result.get("files", [])

    os_dir = Path(settings.upgrade_storage_dir) / "os-packages"
    os_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for fname in filenames:
        # Fetch each .deb from sidecar
        deb_data = await fetch_deb_from_sidecar(node.node_ip, fname)
        file_path = os_dir / fname
        file_path.write_bytes(deb_data)

        file_hash = compute_file_hash(file_path)
        file_size = file_path.stat().st_size

        # Parse package info from filename
        parts = fname.replace(".deb", "").split("_")
        pkg_name = parts[0] if parts else fname
        pkg_version = parts[1] if len(parts) > 1 else "unknown"
        arch = parts[2] if len(parts) > 2 else "amd64"

        # Upsert OsCachedPackage
        existing = (await db.execute(
            select(OsCachedPackage).where(OsCachedPackage.filename == fname)
        )).scalar_one_or_none()

        if existing:
            existing.file_size = file_size
            existing.sha256_hash = file_hash
        else:
            db.add(OsCachedPackage(
                package_name=pkg_name,
                version=pkg_version,
                architecture=arch,
                filename=fname,
                file_size=file_size,
                sha256_hash=file_hash,
                source=node.node_hostname,
            ))

        # Mark as downloaded in OsAvailableUpdate
        await db.execute(
            sql_update(OsAvailableUpdate)
            .where(OsAvailableUpdate.package_name == pkg_name)
            .values(is_downloaded=True)
        )

        saved.append({"filename": fname, "size": file_size, "sha256": file_hash})

    await db.flush()
    return {"status": "success", "data": saved}


@router.post("/os-upload")
async def upload_os_package(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Upload a .deb file for OS package distribution."""
    if not file.filename or not file.filename.endswith(".deb"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .deb package",
        )

    os_dir = Path(settings.upgrade_storage_dir) / "os-packages"
    os_dir.mkdir(parents=True, exist_ok=True)

    file_path = os_dir / file.filename
    with open(file_path, "wb") as f:
        while chunk := await file.read(8192):
            f.write(chunk)

    file_hash = compute_file_hash(file_path)
    file_size = file_path.stat().st_size

    parts = file.filename.replace(".deb", "").split("_")
    pkg_name = parts[0] if parts else file.filename
    pkg_version = parts[1] if len(parts) > 1 else "unknown"
    arch = parts[2] if len(parts) > 2 else "amd64"

    existing = (await db.execute(
        select(OsCachedPackage).where(OsCachedPackage.filename == file.filename)
    )).scalar_one_or_none()

    if existing:
        existing.file_size = file_size
        existing.sha256_hash = file_hash
        existing.source = "upload"
    else:
        db.add(OsCachedPackage(
            package_name=pkg_name,
            version=pkg_version,
            architecture=arch,
            filename=file.filename,
            file_size=file_size,
            sha256_hash=file_hash,
            source="upload",
        ))

    await db.flush()

    return {
        "status": "success",
        "data": {
            "filename": file.filename,
            "size": file_size,
            "sha256": file_hash,
            "package_name": pkg_name,
            "version": pkg_version,
        },
    }


@router.get("/os-packages")
async def list_cached_os_packages(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """List all cached .deb packages from OsCachedPackage table."""
    result = await db.execute(
        select(OsCachedPackage).order_by(OsCachedPackage.package_name)
    )
    pkgs = result.scalars().all()
    return {
        "status": "success",
        "data": [
            {
                "id": str(p.id),
                "package_name": p.package_name,
                "version": p.version,
                "architecture": p.architecture,
                "filename": p.filename,
                "file_size": p.file_size,
                "sha256_hash": p.sha256_hash,
                "source": p.source,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in pkgs
        ],
    }


@router.post("/os-install")
async def install_os_on_node(
    request: InstallOsOnNodeRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Install packages on a specific node via sidecar."""
    # Lookup node IP from SystemVersion
    result = await db.execute(
        select(SystemVersion).where(SystemVersion.node_hostname == request.node_hostname)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{request.node_hostname}' not found",
        )

    install_result = await install_packages_on_node(node.node_ip, request.package_names)

    # Mark as installed in OsAvailableUpdate
    for pkg_name in request.package_names:
        await db.execute(
            sql_update(OsAvailableUpdate)
            .where(
                OsAvailableUpdate.node_hostname == request.node_hostname,
                OsAvailableUpdate.package_name == pkg_name,
            )
            .values(is_installed=True)
        )

    await db.flush()

    # Update badge count
    from monctl_central.cache import _redis
    if _redis:
        count_result = await db.execute(
            select(func.count()).select_from(OsAvailableUpdate).where(
                OsAvailableUpdate.is_installed == False  # noqa: E712
            )
        )
        count = count_result.scalar() or 0
        await _redis.set("monctl:os_updates:count", str(count))

    return {"status": "success", "data": install_result}
