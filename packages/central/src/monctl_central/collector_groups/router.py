"""Collector group management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import Collector, CollectorGroup

router = APIRouter()


class CreateCollectorGroupRequest(BaseModel):
    name: str = Field(description="Unique group name")
    description: str | None = Field(default=None, description="Optional description")


class UpdateCollectorGroupRequest(BaseModel):
    name: str | None = Field(default=None, description="New group name")
    description: str | None = Field(default=None, description="New description")


def _fmt(g: CollectorGroup, collector_count: int = 0) -> dict:
    return {
        "id": str(g.id),
        "name": g.name,
        "description": g.description,
        "collector_count": collector_count,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


@router.get("")
async def list_collector_groups(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all collector groups with collector count."""
    # Subquery: count collectors per group
    count_sq = (
        select(Collector.group_id, func.count(Collector.id).label("cnt"))
        .where(Collector.group_id.is_not(None))
        .group_by(Collector.group_id)
        .subquery()
    )

    stmt = (
        select(CollectorGroup, func.coalesce(count_sq.c.cnt, 0).label("collector_count"))
        .outerjoin(count_sq, CollectorGroup.id == count_sq.c.group_id)
        .order_by(CollectorGroup.name)
    )
    rows = (await db.execute(stmt)).all()
    return {
        "status": "success",
        "data": [_fmt(g, int(cnt)) for g, cnt in rows],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_collector_group(
    request: CreateCollectorGroupRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new collector group."""
    existing = (
        await db.execute(select(CollectorGroup).where(CollectorGroup.name == request.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Collector group '{request.name}' already exists",
        )
    group = CollectorGroup(
        name=request.name,
        description=request.description,
        label_selector={},
    )
    db.add(group)
    await db.flush()
    return {"status": "success", "data": _fmt(group, 0)}


@router.put("/{group_id}")
async def update_collector_group(
    group_id: str,
    request: UpdateCollectorGroupRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a collector group's name or description."""
    group = await db.get(CollectorGroup, uuid.UUID(group_id))
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector group not found")

    if request.name is not None and request.name != group.name:
        # Check uniqueness
        existing = (
            await db.execute(select(CollectorGroup).where(CollectorGroup.name == request.name))
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Collector group '{request.name}' already exists",
            )
        group.name = request.name

    if request.description is not None:
        group.description = request.description

    await db.flush()

    # Get current collector count
    count_row = (
        await db.execute(
            select(func.count(Collector.id)).where(Collector.group_id == group.id)
        )
    ).scalar_one()

    return {"status": "success", "data": _fmt(group, int(count_row))}


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collector_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a collector group. Collectors and devices are unlinked (SET NULL)."""
    group = await db.get(CollectorGroup, uuid.UUID(group_id))
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector group not found")
    await db.delete(group)
