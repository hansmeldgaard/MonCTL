"""Python Module Registry endpoints."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.config import settings
from monctl_central.dependencies import get_db, require_admin, require_auth
from monctl_central.storage.models import (
    PythonModule,
    PythonModuleVersion,
    SystemSetting,
    WheelFile,
)
from monctl_common.utils import utc_now

from .resolver import check_conflicts
from .wheel_parser import WheelMetadata, normalize_package_name, parse_wheel, parse_wheel_filename

router = APIRouter()
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wheel_dir() -> Path:
    return Path(settings.wheel_storage_dir)


def _fmt_module(m: PythonModule, version_count: int = 0, wheel_count: int = 0) -> dict:
    return {
        "id": str(m.id),
        "name": m.name,
        "description": m.description,
        "homepage_url": m.homepage_url,
        "is_approved": m.is_approved,
        "version_count": version_count,
        "wheel_count": wheel_count,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _fmt_version(v: PythonModuleVersion) -> dict:
    return {
        "id": str(v.id),
        "module_id": str(v.module_id),
        "version": v.version,
        "dependencies": v.dependencies,
        "python_requires": v.python_requires,
        "is_verified": v.is_verified,
        "metadata": v.metadata_,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "wheel_files": [_fmt_wheel(w) for w in v.wheel_files] if v.wheel_files else [],
    }


def _fmt_wheel(w: WheelFile) -> dict:
    return {
        "id": str(w.id),
        "filename": w.filename,
        "sha256_hash": w.sha256_hash,
        "file_size": w.file_size,
        "python_tag": w.python_tag,
        "abi_tag": w.abi_tag,
        "platform_tag": w.platform_tag,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


async def _get_network_mode(db: AsyncSession) -> tuple[str, str]:
    """Return (network_mode, proxy_url) from system settings."""
    mode = "direct"
    proxy_url = ""
    for key in ("pypi_network_mode", "pypi_proxy_url"):
        row = await db.get(SystemSetting, key)
        if row:
            if key == "pypi_network_mode":
                mode = row.value
            else:
                proxy_url = row.value
    return mode, proxy_url


def _store_wheel_file(normalized_name: str, filename: str, data: bytes) -> Path:
    """Write a wheel file to disk. Returns the full path."""
    pkg_dir = _wheel_dir() / normalized_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    dest = pkg_dir / filename
    dest.write_bytes(data)
    return dest


def _delete_wheel_file(normalized_name: str, filename: str) -> None:
    """Remove a wheel file from disk (ignore if missing)."""
    path = _wheel_dir() / normalized_name / filename
    path.unlink(missing_ok=True)


async def _find_or_create_module(
    db: AsyncSession,
    meta: WheelMetadata,
) -> PythonModule:
    """Find an existing module by name or create a new one."""
    normalized = normalize_package_name(meta.name)
    stmt = select(PythonModule).where(PythonModule.name == normalized)
    result = await db.execute(stmt)
    module = result.scalar_one_or_none()
    if module is None:
        module = PythonModule(
            name=normalized,
            description=meta.summary or None,
            homepage_url=meta.homepage_url or None,
        )
        db.add(module)
        await db.flush()
    return module


async def _find_or_create_version(
    db: AsyncSession,
    module: PythonModule,
    meta: WheelMetadata,
) -> PythonModuleVersion:
    """Find an existing version or create a new one."""
    stmt = select(PythonModuleVersion).where(
        PythonModuleVersion.module_id == module.id,
        PythonModuleVersion.version == meta.version,
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if version is None:
        version = PythonModuleVersion(
            module_id=module.id,
            version=meta.version,
            dependencies=meta.dependencies,
            python_requires=meta.python_requires or None,
        )
        db.add(version)
        await db.flush()
    return version


async def _get_available_packages(db: AsyncSession) -> dict[str, list[str]]:
    """Build a dict of all registered packages and their versions."""
    stmt = (
        select(PythonModule.name, PythonModuleVersion.version)
        .join(PythonModuleVersion, PythonModule.id == PythonModuleVersion.module_id)
    )
    result = await db.execute(stmt)
    packages: dict[str, list[str]] = {}
    for name, ver in result.all():
        packages.setdefault(name, []).append(ver)
    return packages


# ---------------------------------------------------------------------------
# GET /python-modules — list all modules
# ---------------------------------------------------------------------------

@router.get("")
async def list_modules(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all registered Python modules with version and wheel counts."""
    stmt = (
        select(
            PythonModule,
            func.count(PythonModuleVersion.id.distinct()).label("version_count"),
            func.count(WheelFile.id).label("wheel_count"),
        )
        .outerjoin(PythonModuleVersion, PythonModule.id == PythonModuleVersion.module_id)
        .outerjoin(WheelFile, PythonModuleVersion.id == WheelFile.module_version_id)
        .group_by(PythonModule.id)
        .order_by(PythonModule.name)
    )
    result = await db.execute(stmt)
    rows = result.all()
    data = [
        _fmt_module(row.PythonModule, version_count=row.version_count, wheel_count=row.wheel_count)
        for row in rows
    ]
    return {"status": "success", "data": data}


# ---------------------------------------------------------------------------
# GET /python-modules/network-status — current network mode
# (must be before /{module_id} to avoid path conflict)
# ---------------------------------------------------------------------------

@router.get("/network-status")
async def get_network_status(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return the current PyPI network mode configuration."""
    mode, proxy_url = await _get_network_mode(db)
    return {
        "status": "success",
        "data": {
            "mode": mode,
            "proxy_configured": bool(proxy_url),
        },
    }


# ---------------------------------------------------------------------------
# GET /python-modules/search-pypi — search PyPI
# (must be before /{module_id} to avoid path conflict)
# ---------------------------------------------------------------------------

@router.get("/search-pypi")
async def search_pypi_endpoint(
    q: str = Query(..., min_length=1, description="Package name to search"),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Search PyPI for a package."""
    from .pypi_client import search_pypi

    network_mode, proxy_url = await _get_network_mode(db)
    if network_mode == "offline":
        raise HTTPException(status_code=400, detail="Network mode is 'offline'")

    proxy = proxy_url if network_mode == "proxy" else None

    try:
        results = await search_pypi(q, proxy_url=proxy)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PyPI search failed: {exc}") from exc

    # Check which packages are already registered locally
    if results:
        names = [normalize_package_name(r["name"]) for r in results]
        existing = (await db.execute(
            select(PythonModule.name).where(PythonModule.name.in_(names))
        )).scalars().all()
        existing_set = {normalize_package_name(n) for n in existing}
        for r in results:
            r["registered"] = normalize_package_name(r["name"]) in existing_set

    return {"status": "success", "data": results}


# ---------------------------------------------------------------------------
# GET /python-modules/{module_id} — module detail
# ---------------------------------------------------------------------------

@router.get("/{module_id}")
async def get_module(
    module_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get a module with all its versions and wheel files."""
    stmt = (
        select(PythonModule)
        .options(
            selectinload(PythonModule.versions).selectinload(PythonModuleVersion.wheel_files)
        )
        .where(PythonModule.id == uuid.UUID(module_id))
    )
    result = await db.execute(stmt)
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    data = _fmt_module(module)
    data["versions"] = [_fmt_version(v) for v in module.versions]
    return {"status": "success", "data": data}


# ---------------------------------------------------------------------------
# POST /python-modules/upload-wheel — upload a single .whl file
# ---------------------------------------------------------------------------

@router.post("/upload-wheel", status_code=status.HTTP_201_CREATED)
async def upload_wheel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Upload a .whl file, parse its metadata, and store it on disk."""
    if not file.filename or not file.filename.endswith(".whl"):
        raise HTTPException(status_code=400, detail="File must be a .whl file")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        meta = parse_wheel(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse wheel: {exc}") from exc

    # Also parse filename for tags (more reliable than WHEEL file)
    try:
        fn_parts = parse_wheel_filename(file.filename)
        meta.python_tag = meta.python_tag or fn_parts["python_tag"]
        meta.abi_tag = meta.abi_tag or fn_parts["abi_tag"]
        meta.platform_tag = meta.platform_tag or fn_parts["platform_tag"]
    except ValueError:
        pass  # Use what we got from the WHEEL file

    # Find or create module + version
    module = await _find_or_create_module(db, meta)
    version = await _find_or_create_version(db, module, meta)

    # Check for duplicate wheel filename
    existing = (await db.execute(
        select(WheelFile).where(WheelFile.filename == file.filename)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Wheel file '{file.filename}' already exists")

    # Store on disk
    normalized = normalize_package_name(meta.name)
    _store_wheel_file(normalized, file.filename, data)

    # Create DB record
    wheel = WheelFile(
        module_version_id=version.id,
        filename=file.filename,
        sha256_hash=meta.sha256_hash,
        file_size=meta.file_size,
        python_tag=meta.python_tag,
        abi_tag=meta.abi_tag,
        platform_tag=meta.platform_tag,
    )
    db.add(wheel)
    await db.flush()

    # Check for missing dependencies
    available = await _get_available_packages(db)
    resolver_result = check_conflicts(meta.dependencies, available)

    return {
        "status": "success",
        "data": {
            "module_id": str(module.id),
            "module_name": module.name,
            "version": version.version,
            "wheel_filename": wheel.filename,
            "file_size": wheel.file_size,
            "sha256": wheel.sha256_hash,
            "missing_dependencies": [
                {"name": m, "version_spec": "", "registered": False}
                for m in resolver_result.missing
            ],
        },
    }


# ---------------------------------------------------------------------------
# POST /python-modules/upload-wheels-batch — upload multiple .whl files
# ---------------------------------------------------------------------------

@router.post("/upload-wheels-batch", status_code=status.HTTP_201_CREATED)
async def upload_wheels_batch(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Upload multiple .whl files in a single request."""
    results = []
    errors = []

    for file in files:
        if not file.filename or not file.filename.endswith(".whl"):
            errors.append({"filename": file.filename or "unknown", "error": "Not a .whl file"})
            continue

        data = await file.read()
        if not data:
            errors.append({"filename": file.filename, "error": "Empty file"})
            continue

        try:
            meta = parse_wheel(data)
            try:
                fn_parts = parse_wheel_filename(file.filename)
                meta.python_tag = meta.python_tag or fn_parts["python_tag"]
                meta.abi_tag = meta.abi_tag or fn_parts["abi_tag"]
                meta.platform_tag = meta.platform_tag or fn_parts["platform_tag"]
            except ValueError:
                pass

            module = await _find_or_create_module(db, meta)
            version = await _find_or_create_version(db, module, meta)

            existing = (await db.execute(
                select(WheelFile).where(WheelFile.filename == file.filename)
            )).scalar_one_or_none()
            if existing:
                errors.append({"filename": file.filename, "error": "Already exists"})
                continue

            normalized = normalize_package_name(meta.name)
            _store_wheel_file(normalized, file.filename, data)

            wheel = WheelFile(
                module_version_id=version.id,
                filename=file.filename,
                sha256_hash=meta.sha256_hash,
                file_size=meta.file_size,
                python_tag=meta.python_tag,
                abi_tag=meta.abi_tag,
                platform_tag=meta.platform_tag,
            )
            db.add(wheel)
            await db.flush()

            results.append({
                "filename": file.filename,
                "module": meta.name,
                "version": meta.version,
            })
        except Exception as exc:
            errors.append({"filename": file.filename, "error": str(exc)})

    return {
        "status": "success",
        "data": {
            "uploaded": results,
            "errors": errors,
        },
    }


# ---------------------------------------------------------------------------
# POST /python-modules/import-pypi — import package from PyPI
# ---------------------------------------------------------------------------

class ImportPyPIRequest(BaseModel):
    package_name: str
    version: str | None = None


@router.post("/import-pypi", status_code=status.HTTP_201_CREATED)
async def import_from_pypi(
    req: ImportPyPIRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Import a package (and its wheel) from PyPI."""
    from .pypi_client import download_wheel, fetch_package_info, fetch_version_info

    network_mode, proxy_url = await _get_network_mode(db)
    if network_mode == "offline":
        raise HTTPException(
            status_code=400,
            detail="Network mode is 'offline' — PyPI imports are disabled",
        )

    proxy = proxy_url if network_mode == "proxy" else None

    try:
        if req.version:
            info = await fetch_version_info(req.package_name, req.version, proxy_url=proxy)
        else:
            info = await fetch_package_info(req.package_name, proxy_url=proxy)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from PyPI: {exc}") from exc

    pkg_info = info.get("info", {})
    version_str = req.version or pkg_info.get("version", "")
    if not version_str:
        raise HTTPException(status_code=400, detail="Could not determine version")

    # Find a wheel URL in the release files
    urls = info.get("urls", [])
    wheel_url = None
    wheel_filename = None
    for u in urls:
        if u.get("packagetype") == "bdist_wheel":
            wheel_url = u["url"]
            wheel_filename = u["filename"]
            break

    if not wheel_url:
        raise HTTPException(
            status_code=404,
            detail=f"No wheel file found for {req.package_name}=={version_str} on PyPI",
        )

    # Download the wheel
    try:
        wheel_data = await download_wheel(wheel_url, proxy_url=proxy)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to download wheel: {exc}") from exc

    # Parse the wheel
    meta = parse_wheel(wheel_data)
    try:
        fn_parts = parse_wheel_filename(wheel_filename)
        meta.python_tag = meta.python_tag or fn_parts["python_tag"]
        meta.abi_tag = meta.abi_tag or fn_parts["abi_tag"]
        meta.platform_tag = meta.platform_tag or fn_parts["platform_tag"]
    except ValueError:
        pass

    # Override with PyPI info
    meta.homepage_url = meta.homepage_url or pkg_info.get("home_page", "")
    meta.summary = meta.summary or pkg_info.get("summary", "")

    module = await _find_or_create_module(db, meta)
    version = await _find_or_create_version(db, module, meta)

    # Check for duplicate wheel filename
    existing = (await db.execute(
        select(WheelFile).where(WheelFile.filename == wheel_filename)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Wheel file '{wheel_filename}' already exists",
        )

    normalized = normalize_package_name(meta.name)
    _store_wheel_file(normalized, wheel_filename, wheel_data)

    wheel = WheelFile(
        module_version_id=version.id,
        filename=wheel_filename,
        sha256_hash=meta.sha256_hash,
        file_size=meta.file_size,
        python_tag=meta.python_tag,
        abi_tag=meta.abi_tag,
        platform_tag=meta.platform_tag,
    )
    db.add(wheel)
    await db.flush()

    available = await _get_available_packages(db)
    resolver_result = check_conflicts(meta.dependencies, available)

    return {
        "status": "success",
        "data": {
            "module_id": str(module.id),
            "module_name": module.name,
            "version": version.version,
            "wheel_filename": wheel.filename,
            "file_size": wheel.file_size,
            "sha256": wheel.sha256_hash,
            "missing_dependencies": [
                {"name": m, "version_spec": "", "registered": False}
                for m in resolver_result.missing
            ],
        },
    }


# ---------------------------------------------------------------------------
# POST /python-modules/resolve — check conflicts + missing deps
# ---------------------------------------------------------------------------

class ResolveRequest(BaseModel):
    dependencies: list[str]


@router.post("/resolve")
async def resolve_dependencies(
    req: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Check a list of dependencies against the registry."""
    available = await _get_available_packages(db)
    result = check_conflicts(req.dependencies, available)
    return {
        "status": "success",
        "data": {
            "conflicts": result.conflicts,
            "missing": result.missing,
            "resolved": result.resolved,
        },
    }


# ---------------------------------------------------------------------------
# PUT /python-modules/{module_id}/approve — toggle approval
# ---------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    is_approved: bool


@router.put("/{module_id}/approve")
async def approve_module(
    module_id: str,
    req: ApproveRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Toggle the approval status of a module."""
    module = await db.get(PythonModule, uuid.UUID(module_id))
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    module.is_approved = req.is_approved
    module.updated_at = utc_now()
    return {"status": "success", "data": _fmt_module(module)}


# ---------------------------------------------------------------------------
# PUT /python-modules/{module_id}/versions/{version_id}/verify
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    is_verified: bool


@router.put("/{module_id}/versions/{version_id}/verify")
async def verify_version(
    module_id: str,
    version_id: str,
    req: VerifyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Toggle the verified status of a module version."""
    version = await db.get(PythonModuleVersion, uuid.UUID(version_id))
    if not version or str(version.module_id) != module_id:
        raise HTTPException(status_code=404, detail="Version not found")
    version.is_verified = req.is_verified
    return {"status": "success", "data": _fmt_version(version)}


# ---------------------------------------------------------------------------
# DELETE /python-modules/{module_id} — delete module + all wheels
# ---------------------------------------------------------------------------

@router.delete("/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_module(
    module_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Delete a module and all its versions/wheels from the database and disk."""
    stmt = (
        select(PythonModule)
        .options(
            selectinload(PythonModule.versions).selectinload(PythonModuleVersion.wheel_files)
        )
        .where(PythonModule.id == uuid.UUID(module_id))
    )
    result = await db.execute(stmt)
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    normalized = normalize_package_name(module.name)

    # Remove wheel files from disk
    for version in module.versions:
        for wheel in version.wheel_files:
            _delete_wheel_file(normalized, wheel.filename)

    # Remove the entire package directory if empty
    pkg_dir = _wheel_dir() / normalized
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir, ignore_errors=True)

    await db.delete(module)


# ---------------------------------------------------------------------------
# DELETE /python-modules/{module_id}/versions/{version_id}
# ---------------------------------------------------------------------------

@router.delete("/{module_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_version(
    module_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Delete a module version and its wheels from the database and disk."""
    stmt = (
        select(PythonModuleVersion)
        .options(selectinload(PythonModuleVersion.wheel_files))
        .where(
            PythonModuleVersion.id == uuid.UUID(version_id),
            PythonModuleVersion.module_id == uuid.UUID(module_id),
        )
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    # Look up module name for disk path
    module = await db.get(PythonModule, uuid.UUID(module_id))
    normalized = normalize_package_name(module.name) if module else ""

    # Remove wheel files from disk
    for wheel in version.wheel_files:
        _delete_wheel_file(normalized, wheel.filename)

    await db.delete(version)
