"""Collector-facing OS package distribution endpoints.
Mounted at /api/v1/os-packages/.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
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


@router.get("/archive")
async def download_archive(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    """Serve the prepared apt cache archive (tar.gz of .deb files)."""
    import httpx
    from starlette.responses import StreamingResponse

    # Try local sidecar first
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get("http://127.0.0.1:9100/os/archive")
            if resp.status_code == 200 and len(resp.content) > 100:
                return StreamingResponse(
                    iter([resp.content]),
                    media_type="application/gzip",
                    headers={"Content-Disposition": 'attachment; filename="apt-archive.tar.gz"'},
                )
    except Exception:
        pass

    # Local doesn't have it — try peer centrals via their sidecars
    if request.headers.get("x-no-proxy"):
        raise HTTPException(status_code=404, detail="No archive on this node")

    from monctl_central.storage.models import SystemVersion
    nodes = (await db.execute(
        select(SystemVersion).where(SystemVersion.node_role == "central")
    )).scalars().all()

    for node in nodes:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.get(
                    f"http://{node.node_ip}:9100/os/archive",
                )
                if resp.status_code == 200 and len(resp.content) > 100:
                    # Cache locally for next request
                    import os as _os
                    archive_dir = "/host_root/opt/monctl/os-packages" if _os.path.exists("/host_root") else "/data/upgrades/os-packages"
                    _os.makedirs(archive_dir, exist_ok=True)
                    with open(f"{archive_dir}/apt-archive.tar.gz", "wb") as f:
                        f.write(resp.content)
                    return StreamingResponse(
                        iter([resp.content]),
                        media_type="application/gzip",
                        headers={"Content-Disposition": 'attachment; filename="apt-archive.tar.gz"'},
                    )
        except Exception:
            continue

    raise HTTPException(status_code=404, detail="No archive prepared on any central node")


@router.get("/download/{filename}")
async def download_os_package(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_collector_auth),
):
    from urllib.parse import quote, unquote

    # Try both URL-encoded and decoded variants of the filename
    # (apt names files with %3a but FastAPI decodes %3a to : in the path)
    candidates = list({filename, quote(filename, safe=""), unquote(filename)})

    pkg = None
    for candidate in candidates:
        pkg = (await db.execute(
            select(OsCachedPackage).where(OsCachedPackage.filename == candidate)
        )).scalar_one_or_none()
        if pkg:
            break
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    # Try finding the file with any filename variant
    os_dir = Path(settings.upgrade_storage_dir) / "os-packages"
    for candidate in candidates:
        file_path = os_dir / candidate
        if file_path.exists():
            return FileResponse(path=str(file_path), filename=pkg.filename, media_type="application/octet-stream")

    # File not on this central node — try to fetch from a peer
    # X-No-Proxy header prevents infinite recursion between central nodes
    if request.headers.get("x-no-proxy"):
        raise HTTPException(status_code=404, detail="File not found on this node")

    import os as _os
    import httpx
    from monctl_central.storage.models import SystemVersion
    api_key = _os.environ.get("MONCTL_COLLECTOR_API_KEY", "")
    nodes = (await db.execute(
        select(SystemVersion).where(SystemVersion.node_role == "central")
    )).scalars().all()
    for node in nodes:
        peer_url = f"http://{node.node_ip}:8443/api/v1/os-packages/download/{quote(pkg.filename, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(peer_url, headers={
                    "Authorization": f"Bearer {api_key}",
                    "X-No-Proxy": "1",
                })
                if resp.status_code == 200:
                    save_path = os_dir / pkg.filename
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    save_path.write_bytes(resp.content)
                    logger.info("os_package_fetched_from_peer", filename=pkg.filename, peer=node.node_hostname)
                    return FileResponse(path=str(save_path), filename=pkg.filename, media_type="application/octet-stream")
        except Exception:
            continue
    raise HTTPException(status_code=404, detail="File not found on any central node")


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
