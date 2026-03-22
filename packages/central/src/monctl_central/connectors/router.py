"""Connector management endpoints."""

from __future__ import annotations

import hashlib
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from monctl_common.validators import validate_semver
import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import (
    AssignmentConnectorBinding,
    Connector,
    ConnectorVersion,
)
from monctl_common.utils import utc_now

router = APIRouter()


def _next_patch_version(source_version: str, existing_versions: set[str]) -> str:
    """Auto-increment patch version from source."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", source_version)
    if match:
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        candidate_patch = patch + 1
        while f"{major}.{minor}.{candidate_patch}" in existing_versions:
            candidate_patch += 1
        return f"{major}.{minor}.{candidate_patch}"

    counter = 1
    while f"{source_version}.{counter}" in existing_versions:
        counter += 1
    return f"{source_version}.{counter}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_connector(c: Connector, *, version_count: int = 0, latest_version: str | None = None) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "description": c.description,
        "connector_type": c.connector_type,
        "requirements": c.requirements,
        "is_builtin": c.is_builtin,
        "version_count": version_count,
        "latest_version": latest_version,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _fmt_version(v: ConnectorVersion) -> dict:
    return {
        "id": str(v.id),
        "connector_id": str(v.connector_id),
        "version": v.version,
        "requirements": v.requirements,
        "entry_class": v.entry_class,
        "is_latest": v.is_latest,
        "checksum": v.checksum,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def _fmt_version_detail(v: ConnectorVersion) -> dict:
    d = _fmt_version(v)
    d["source_code"] = v.source_code
    return d


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateConnectorRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    connector_type: str = Field(min_length=1, max_length=64)
    requirements: dict | None = None


class UpdateConnectorRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    connector_type: str | None = Field(default=None, min_length=1, max_length=64)


class CreateVersionRequest(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    source_code: str = Field(min_length=1)
    requirements: dict | None = None
    entry_class: str = Field(default="Connector", max_length=255)
    set_latest: bool = False

    @field_validator("version")
    @classmethod
    def check_version(cls, v: str) -> str:
        return validate_semver(v)


class UpdateVersionRequest(BaseModel):
    source_code: str | None = Field(default=None, min_length=1)
    requirements: dict | None = None
    entry_class: str | None = Field(default=None, max_length=255)


# ---------------------------------------------------------------------------
# Connector CRUD
# ---------------------------------------------------------------------------

SORT_MAP = {
    "name": Connector.name,
    "connector_type": Connector.connector_type,
    "created_at": Connector.created_at,
}


@router.get("")
async def list_connectors(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
    name: str | None = Query(default=None),
    connector_type: str | None = Query(default=None),
    description: str | None = Query(default=None),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all connectors with version_count and latest_version."""
    base_stmt = select(Connector)

    if name:
        base_stmt = base_stmt.where(Connector.name.ilike(f"%{name}%"))
    if connector_type:
        base_stmt = base_stmt.where(Connector.connector_type.ilike(f"%{connector_type}%"))
    if description:
        base_stmt = base_stmt.where(Connector.description.ilike(f"%{description}%"))

    sort_col = SORT_MAP.get(sort_by, Connector.name)
    base_stmt = base_stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    count_stmt = select(sa.func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = base_stmt.options(selectinload(Connector.versions)).offset(offset).limit(limit)
    result = await db.execute(stmt)
    connectors = result.scalars().all()

    data = []
    for c in connectors:
        version_count = len(c.versions)
        latest = next((v for v in c.versions if v.is_latest), None)
        latest_version = latest.version if latest else None
        latest_version_id = str(latest.id) if latest else None
        entry = _fmt_connector(c, version_count=version_count, latest_version=latest_version)
        entry["latest_version_id"] = latest_version_id
        data.append(entry)

    return {
        "status": "success",
        "data": data,
        "meta": {"limit": limit, "offset": offset, "count": len(data), "total": total},
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connector(
    request: CreateConnectorRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new connector."""
    connector = Connector(
        name=request.name,
        description=request.description,
        connector_type=request.connector_type,
        requirements=request.requirements,
    )
    db.add(connector)
    await db.flush()
    return {
        "status": "success",
        "data": _fmt_connector(connector),
    }


@router.get("/{connector_id}")
async def get_connector(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get connector details including all versions (sorted newest first)."""
    stmt = (
        select(Connector)
        .options(selectinload(Connector.versions))
        .where(Connector.id == uuid.UUID(connector_id))
    )
    result = await db.execute(stmt)
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    versions = sorted(connector.versions, key=lambda v: v.created_at, reverse=True)
    data = _fmt_connector(
        connector,
        version_count=len(versions),
        latest_version=next((v.version for v in versions if v.is_latest), None),
    )
    data["versions"] = [_fmt_version(v) for v in versions]
    return {"status": "success", "data": data}


@router.put("/{connector_id}")
async def update_connector(
    connector_id: str,
    request: UpdateConnectorRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update connector name, description, or type."""
    connector = await db.get(Connector, uuid.UUID(connector_id))
    if connector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    if request.name is not None:
        connector.name = request.name
    if request.description is not None:
        connector.description = request.description
    if request.connector_type is not None:
        connector.connector_type = request.connector_type
    connector.updated_at = utc_now()

    await db.flush()
    return {"status": "success", "data": _fmt_connector(connector)}


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a connector. Rejected if any assignment bindings reference it."""
    connector = await db.get(Connector, uuid.UUID(connector_id))
    if connector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    count = (await db.execute(
        select(func.count())
        .select_from(AssignmentConnectorBinding)
        .where(AssignmentConnectorBinding.connector_id == connector.id)
    )).scalar_one()
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Connector is in use by {count} binding(s). Remove them first.",
        )

    await db.delete(connector)
    await db.flush()


# ---------------------------------------------------------------------------
# Version CRUD
# ---------------------------------------------------------------------------

@router.post("/{connector_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_connector_version(
    connector_id: str,
    request: CreateVersionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Upload a new version of a connector."""
    stmt = (
        select(Connector)
        .options(selectinload(Connector.versions))
        .where(Connector.id == uuid.UUID(connector_id))
    )
    result = await db.execute(stmt)
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    is_first = len(connector.versions) == 0
    should_be_latest = request.set_latest or is_first

    checksum = hashlib.sha256(request.source_code.encode()).hexdigest()
    version = ConnectorVersion(
        connector_id=connector.id,
        version=request.version,
        source_code=request.source_code,
        requirements=request.requirements,
        entry_class=request.entry_class,
        checksum=checksum,
        is_latest=should_be_latest,
    )
    db.add(version)

    if should_be_latest:
        for v in connector.versions:
            v.is_latest = False

    await db.flush()
    return {
        "status": "success",
        "data": _fmt_version(version),
    }


@router.get("/{connector_id}/versions/{version_id}")
async def get_connector_version(
    connector_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get version details including source code."""
    stmt = select(ConnectorVersion).where(
        ConnectorVersion.id == uuid.UUID(version_id),
        ConnectorVersion.connector_id == uuid.UUID(connector_id),
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return {"status": "success", "data": _fmt_version_detail(version)}


@router.put("/{connector_id}/versions/{version_id}")
async def update_connector_version(
    connector_id: str,
    version_id: str,
    request: UpdateVersionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a connector version's source code, requirements, or entry class."""
    stmt = select(ConnectorVersion).where(
        ConnectorVersion.id == uuid.UUID(version_id),
        ConnectorVersion.connector_id == uuid.UUID(connector_id),
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    if request.source_code is not None:
        version.source_code = request.source_code
        version.checksum = hashlib.sha256(request.source_code.encode()).hexdigest()
    if request.requirements is not None:
        version.requirements = request.requirements
    if request.entry_class is not None:
        version.entry_class = request.entry_class

    await db.flush()
    return {"status": "success", "data": _fmt_version(version)}


@router.delete("/{connector_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector_version(
    connector_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a connector version. Rejected if any bindings reference it."""
    stmt = select(ConnectorVersion).where(
        ConnectorVersion.id == uuid.UUID(version_id),
        ConnectorVersion.connector_id == uuid.UUID(connector_id),
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    count = (await db.execute(
        select(func.count())
        .select_from(AssignmentConnectorBinding)
        .where(AssignmentConnectorBinding.connector_version_id == version.id)
    )).scalar_one()
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version is in use by {count} binding(s). Remove them first.",
        )

    await db.delete(version)
    await db.flush()


@router.put("/{connector_id}/versions/{version_id}/set-latest")
async def set_latest_version(
    connector_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Mark a version as the latest. Clears is_latest on all other versions."""
    stmt = (
        select(Connector)
        .options(selectinload(Connector.versions))
        .where(Connector.id == uuid.UUID(connector_id))
    )
    result = await db.execute(stmt)
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    target = None
    for v in connector.versions:
        if str(v.id) == version_id:
            target = v
        v.is_latest = False

    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    target.is_latest = True
    await db.flush()
    return {
        "status": "success",
        "data": _fmt_version(target),
    }


@router.post("/{connector_id}/versions/{version_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_connector_version(
    connector_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Clone an existing connector version into a new draft version.

    Copies source_code, requirements, entry_class. The new version is NOT
    set as is_latest.
    """
    stmt = select(ConnectorVersion).where(
        ConnectorVersion.id == uuid.UUID(version_id),
        ConnectorVersion.connector_id == uuid.UUID(connector_id),
    )
    source = (await db.execute(stmt)).scalar_one_or_none()
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source version not found",
        )

    all_versions = (await db.execute(
        select(ConnectorVersion.version).where(
            ConnectorVersion.connector_id == uuid.UUID(connector_id),
        )
    )).scalars().all()
    new_version = _next_patch_version(source.version, set(all_versions))

    checksum = hashlib.sha256((source.source_code or "").encode()).hexdigest()
    cloned = ConnectorVersion(
        connector_id=source.connector_id,
        version=new_version,
        source_code=source.source_code,
        requirements=source.requirements,
        entry_class=source.entry_class,
        checksum=checksum,
        is_latest=False,
    )
    db.add(cloned)
    await db.flush()

    return {
        "status": "success",
        "data": {
            "id": str(cloned.id),
            "version": cloned.version,
            "checksum": cloned.checksum,
            "is_latest": cloned.is_latest,
            "cloned_from": {
                "version_id": str(source.id),
                "version": source.version,
            },
        },
    }
