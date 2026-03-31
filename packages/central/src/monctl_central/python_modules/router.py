"""Python Module Registry endpoints."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from monctl_common.validators import validate_uuid
import sqlalchemy as sa
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

from .resolver import ResolverResult, check_conflicts
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


def _pick_best_wheel(urls: list[dict]) -> tuple[str | None, str | None]:
    """Pick the best wheel for Linux amd64 collectors (Python 3.12).

    Preference order:
      1. pure-python (py3-none-any)
      2. manylinux x86_64 cp312
      3. manylinux x86_64 cp311
      4. manylinux x86_64 (any cpython)
      5. any linux x86_64
      6. first available wheel (fallback)
    """
    wheels = [u for u in urls if u.get("packagetype") == "bdist_wheel"]
    if not wheels:
        return None, None

    def score(u: dict) -> tuple[int, str]:
        fn = u.get("filename", "")
        fl = fn.lower()
        # Pure python — best
        if "py3-none-any" in fl or "py2.py3-none-any" in fl:
            return (0, fn)
        # manylinux x86_64 with matching cpython
        if "manylinux" in fl and "x86_64" in fl:
            if "cp312" in fl:
                return (1, fn)
            if "cp311" in fl:
                return (2, fn)
            return (3, fn)
        # any linux x86_64
        if "linux" in fl and "x86_64" in fl:
            return (4, fn)
        # Fallback
        return (5, fn)

    best = min(wheels, key=score)
    return best["url"], best["filename"]


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
    name: str | None = Query(default=None),
    description: str | None = Query(default=None),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all registered Python modules with version/wheel counts and dep status."""
    # Count total matching modules
    count_stmt = select(sa.func.count()).select_from(PythonModule)
    if name:
        count_stmt = count_stmt.where(PythonModule.name.ilike(f"%{name}%"))
    if description:
        count_stmt = count_stmt.where(PythonModule.description.ilike(f"%{description}%"))
    total = (await db.execute(count_stmt)).scalar() or 0

    # Main query
    stmt = (
        select(
            PythonModule,
            func.count(PythonModuleVersion.id.distinct()).label("version_count"),
            func.count(WheelFile.id).label("wheel_count"),
        )
        .outerjoin(PythonModuleVersion, PythonModule.id == PythonModuleVersion.module_id)
        .outerjoin(WheelFile, PythonModuleVersion.id == WheelFile.module_version_id)
    )
    if name:
        stmt = stmt.where(PythonModule.name.ilike(f"%{name}%"))
    if description:
        stmt = stmt.where(PythonModule.description.ilike(f"%{description}%"))

    SORT_MAP = {
        "name": PythonModule.name,
        "is_approved": PythonModule.is_approved,
        "created_at": PythonModule.created_at,
    }
    sort_col = SORT_MAP.get(sort_by, PythonModule.name)
    stmt = stmt.group_by(PythonModule.id).order_by(
        sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    )
    stmt = stmt.limit(limit).offset(offset)

    result = await db.execute(stmt)
    rows = result.all()

    # Build dep status: collect all deps from all versions, check against registry
    available = await _get_available_packages(db)
    all_deps_by_module: dict[str, list[str]] = {}
    dep_stmt = (
        select(PythonModuleVersion.module_id, PythonModuleVersion.dependencies)
        .where(PythonModuleVersion.dependencies != None)  # noqa: E711
    )
    dep_rows = (await db.execute(dep_stmt)).all()
    for mid, deps in dep_rows:
        mid_str = str(mid)
        all_deps_by_module.setdefault(mid_str, [])
        if deps:
            all_deps_by_module[mid_str].extend(deps)

    # Build name→id map and figure out which modules are deps of others
    name_to_id: dict[str, str] = {}
    id_to_name: dict[str, str] = {}
    for row in rows:
        norm = normalize_package_name(row.PythonModule.name)
        name_to_id[norm] = str(row.PythonModule.id)
        id_to_name[str(row.PythonModule.id)] = row.PythonModule.name

    # For each module, parse its dep names (normalized)
    dep_names_by_module: dict[str, set[str]] = {}
    for mid_str, deps_list in all_deps_by_module.items():
        parsed: set[str] = set()
        for d in deps_list:
            from .resolver import _parse_dep
            name, _ = _parse_dep(d)
            if name:
                parsed.add(name)
        dep_names_by_module[mid_str] = parsed

    # Compute is_dependency_of: which parent modules depend on this one
    is_dep_of: dict[str, list[str]] = {}  # module_id -> list of parent module names
    for parent_id, dep_set in dep_names_by_module.items():
        parent_name = id_to_name.get(parent_id, "")
        for dep_norm in dep_set:
            child_id = name_to_id.get(dep_norm)
            if child_id and child_id != parent_id:
                is_dep_of.setdefault(child_id, []).append(parent_name)

    data = []
    for row in rows:
        d = _fmt_module(row.PythonModule, version_count=row.version_count, wheel_count=row.wheel_count)
        mid_str = str(row.PythonModule.id)
        deps = all_deps_by_module.get(mid_str, [])
        if deps:
            res = check_conflicts(deps, available)
            d["dep_total"] = len(deps)
            d["dep_missing"] = len(res.missing)
            d["dep_missing_names"] = res.missing
        else:
            d["dep_total"] = 0
            d["dep_missing"] = 0
            d["dep_missing_names"] = []
        d["is_dependency_of"] = is_dep_of.get(mid_str, [])
        data.append(d)

    return {
        "status": "success",
        "data": data,
        "meta": {"limit": limit, "offset": offset, "count": len(data), "total": total},
    }


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

    # Add dependency status per version
    available = await _get_available_packages(db)
    all_deps: list[str] = []
    for v in data["versions"]:
        deps = v.get("dependencies") or []
        if deps:
            res = check_conflicts(deps, available)
            v["dep_missing"] = res.missing
            v["dep_resolved"] = res.resolved
            all_deps.extend(deps)
        else:
            v["dep_missing"] = []
            v["dep_resolved"] = []

    # Aggregate dep status for the module
    if all_deps:
        agg = check_conflicts(all_deps, available)
        data["dep_total"] = len(all_deps)
        data["dep_missing"] = len(agg.missing)
        data["dep_missing_names"] = agg.missing
    else:
        data["dep_total"] = 0
        data["dep_missing"] = 0
        data["dep_missing_names"] = []

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
        file_data=data,
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
                file_data=data,
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
    package_name: str = Field(min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=32)


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

    # Find the best wheel for Linux amd64 collectors
    urls = info.get("urls", [])
    wheel_url, wheel_filename = _pick_best_wheel(urls)

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
        file_data=wheel_data,
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
    dependencies: list[str] = Field(min_length=1, max_length=100)


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
# POST /python-modules/auto-resolve — import all missing deps from PyPI
# ---------------------------------------------------------------------------

class AutoResolveRequest(BaseModel):
    module_id: str | None = None  # resolve for a specific module, or all if None
    max_depth: int = Field(default=5, ge=1, le=20)  # max recursion depth to prevent infinite loops

    @field_validator("module_id")
    @classmethod
    def check_module_id(cls, v: str | None) -> str | None:
        if v is not None:
            validate_uuid(v, "module_id")
        return v


@router.post("/auto-resolve")
async def auto_resolve(
    req: AutoResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Automatically import all missing dependencies from PyPI (recursive).

    Walks the dependency tree up to max_depth levels, importing each missing
    package and its transitive dependencies.
    """
    from .pypi_client import download_wheel, fetch_package_info

    network_mode, proxy_url = await _get_network_mode(db)
    if network_mode == "offline":
        raise HTTPException(status_code=400, detail="Cannot auto-resolve in offline mode")

    proxy = proxy_url if network_mode == "proxy" else None

    # Collect all dependencies to resolve
    if req.module_id:
        stmt = (
            select(PythonModuleVersion.dependencies)
            .join(PythonModule, PythonModule.id == PythonModuleVersion.module_id)
            .where(PythonModule.id == uuid.UUID(req.module_id))
        )
    else:
        stmt = select(PythonModuleVersion.dependencies)

    dep_rows = (await db.execute(stmt)).scalars().all()
    all_deps: list[str] = []
    for deps in dep_rows:
        if deps:
            all_deps.extend(deps)

    imported: list[dict] = []
    failed: list[dict] = []
    already_available: set[str] = set()

    for depth in range(req.max_depth):
        available = await _get_available_packages(db)
        already_available = set(available.keys())
        result = check_conflicts(all_deps, available)

        if not result.missing:
            break

        # Parse missing dep names
        new_deps: list[str] = []
        for dep_str in result.missing:
            dep_name = _parse_dep_name(dep_str)
            if not dep_name or dep_name in already_available:
                continue

            try:
                info = await fetch_package_info(dep_name, proxy_url=proxy)
                pkg_info = info.get("info", {})
                version_str = pkg_info.get("version", "")
                if not version_str:
                    failed.append({"name": dep_name, "error": "No version found"})
                    continue

                # Find the best wheel for Linux amd64 collectors
                urls = info.get("urls", [])
                wheel_url, wheel_filename = _pick_best_wheel(urls)

                if not wheel_url:
                    # Try the specific version's releases
                    releases = info.get("releases", {})
                    ver_files = releases.get(version_str, [])
                    wheel_url, wheel_filename = _pick_best_wheel(ver_files)

                if not wheel_url:
                    failed.append({"name": dep_name, "error": "No wheel available"})
                    continue

                # Check if wheel already exists
                existing_wheel = (await db.execute(
                    select(WheelFile).where(WheelFile.filename == wheel_filename)
                )).scalar_one_or_none()
                if existing_wheel:
                    already_available.add(normalize_package_name(dep_name))
                    continue

                wheel_data = await download_wheel(wheel_url, proxy_url=proxy)
                meta = parse_wheel(wheel_data)
                try:
                    fn_parts = parse_wheel_filename(wheel_filename)
                    meta.python_tag = meta.python_tag or fn_parts["python_tag"]
                    meta.abi_tag = meta.abi_tag or fn_parts["abi_tag"]
                    meta.platform_tag = meta.platform_tag or fn_parts["platform_tag"]
                except ValueError:
                    pass

                module = await _find_or_create_module(db, meta)
                version = await _find_or_create_version(db, module, meta)

                wheel = WheelFile(
                    module_version_id=version.id,
                    filename=wheel_filename,
                    sha256_hash=meta.sha256_hash,
                    file_size=meta.file_size,
                    python_tag=meta.python_tag,
                    abi_tag=meta.abi_tag,
                    platform_tag=meta.platform_tag,
                    file_data=wheel_data,
                )
                normalized = normalize_package_name(meta.name)
                _store_wheel_file(normalized, wheel_filename, wheel_data)
                db.add(wheel)
                await db.flush()

                imported.append({
                    "name": meta.name,
                    "version": meta.version,
                    "filename": wheel_filename,
                })

                # Add this package's deps for next iteration
                if meta.dependencies:
                    new_deps.extend(meta.dependencies)

            except Exception as exc:
                failed.append({"name": dep_name, "error": str(exc)})

        if not new_deps:
            break
        all_deps = new_deps

    # Final check
    available = await _get_available_packages(db)
    final_deps: list[str] = []
    if req.module_id:
        for deps in dep_rows:
            if deps:
                final_deps.extend(deps)
    else:
        final_deps = all_deps
    final_result = check_conflicts(final_deps, available) if final_deps else ResolverResult()

    return {
        "status": "success",
        "data": {
            "imported": imported,
            "failed": failed,
            "still_missing": final_result.missing,
        },
    }


def _parse_dep_name(dep_str: str) -> str:
    """Extract just the package name from a dependency string."""
    import re as _re
    cleaned = _re.sub(r"\[.*?\]", "", dep_str).strip().split(";")[0].strip()
    m = _re.match(r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)", cleaned)
    return _re.sub(r"[-_.]+", "-", m.group(1)).lower() if m else ""


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
