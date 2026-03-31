"""Tenant management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from monctl_common.validators import validate_metadata
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_permission
from monctl_central.storage.models import Tenant

router = APIRouter()


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Unique tenant name")
    metadata: dict = Field(default_factory=dict, description="Key-value metadata")

    @field_validator("metadata")
    @classmethod
    def check_metadata(cls, v: dict) -> dict:
        return validate_metadata(v)


class UpdateTenantRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict | None = None

    @field_validator("metadata")
    @classmethod
    def check_metadata(cls, v: dict | None) -> dict | None:
        if v is not None:
            return validate_metadata(v)
        return v


def _fmt(t: Tenant) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "metadata": t.metadata_ if t.metadata_ else {},
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("")
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("tenant", "view")),
):
    """List all tenants."""
    rows = (await db.execute(select(Tenant).order_by(Tenant.name))).scalars().all()
    return {"status": "success", "data": [_fmt(t) for t in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    request: CreateTenantRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("tenant", "manage")),
):
    """Create a new tenant."""
    existing = (
        await db.execute(select(Tenant).where(Tenant.name == request.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant '{request.name}' already exists",
        )
    tenant = Tenant(name=request.name, metadata_=request.metadata)
    db.add(tenant)
    await db.flush()
    return {"status": "success", "data": _fmt(tenant)}


@router.put("/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    request: UpdateTenantRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("tenant", "manage")),
):
    """Rename a tenant."""
    tenant = await db.get(Tenant, uuid.UUID(tenant_id))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    if request.name is not None:
        # Check uniqueness of new name
        existing = (
            await db.execute(select(Tenant).where(Tenant.name == request.name))
        ).scalar_one_or_none()
        if existing and str(existing.id) != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tenant '{request.name}' already exists",
            )
        tenant.name = request.name
    if request.metadata is not None:
        tenant.metadata_ = request.metadata
    await db.flush()
    return {"status": "success", "data": _fmt(tenant)}


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("tenant", "manage")),
):
    """Delete a tenant."""
    tenant = await db.get(Tenant, uuid.UUID(tenant_id))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    await db.delete(tenant)
