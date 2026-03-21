"""Collector-facing OS package distribution endpoints.
Mounted at /api/v1/os-packages/.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.config import settings
from monctl_central.dependencies import get_db, require_collector_auth
from monctl_central.storage.models import OsCachedPackage

logger = structlog.get_logger()
router = APIRouter()


@router.get("/available")
async def list_available_os_packages(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    pkgs = (await db.execute(
        select(OsCachedPackage).order_by(OsCachedPackage.package_name)
    )).scalars().all()
    return {
        "status": "success",
        "data": [
            {"filename": p.filename, "package": p.package_name, "version": p.version,
             "sha256": p.sha256_hash, "file_size": p.file_size}
            for p in pkgs
        ],
    }


@router.get("/download/{filename}")
async def download_os_package(
    filename: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    pkg = (await db.execute(
        select(OsCachedPackage).where(OsCachedPackage.filename == filename)
    )).scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    file_path = Path(settings.upgrade_storage_dir) / "os-packages" / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path=str(file_path), filename=filename, media_type="application/octet-stream")


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
