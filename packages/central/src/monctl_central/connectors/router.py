"""Connector management endpoints."""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
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
    name: str
    description: str | None = None
    connector_type: str
    requirements: dict | None = None


class UpdateConnectorRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    connector_type: str | None = None


class CreateVersionRequest(BaseModel):
    version: str
    source_code: str
    requirements: dict | None = None
    entry_class: str = "Connector"
    set_latest: bool = False


class UpdateVersionRequest(BaseModel):
    source_code: str | None = None
    requirements: dict | None = None
    entry_class: str | None = None


# ---------------------------------------------------------------------------
# Connector CRUD
# ---------------------------------------------------------------------------

@router.get("")
async def list_connectors(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all connectors with version_count and latest_version."""
    stmt = select(Connector).options(selectinload(Connector.versions)).order_by(Connector.name)
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

    return {"status": "success", "data": data}


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
