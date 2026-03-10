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


def _fmt(g: CollectorGroup, collector_count: int = 0, health: dict | None = None) -> dict:
    return {
        "id": str(g.id),
        "name": g.name,
        "description": g.description,
        "collector_count": collector_count,
        "health": health or {"status": "empty", "message": "No collectors"},
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


@router.get("")
async def list_collector_groups(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all collector groups with collector count and health status."""
    # Load groups with their collectors for health calculation
    stmt = (
        select(CollectorGroup)
        .options(selectinload(CollectorGroup.collectors))
        .order_by(CollectorGroup.name)
    )
    groups = (await db.execute(stmt)).scalars().all()

    result = []
    for g in groups:
        collectors = [c for c in g.collectors if c.status not in ("PENDING", "REJECTED")]
        total = len(collectors)
        health = _compute_group_health(collectors, total)
        result.append(_fmt(g, total, health))

    return {"status": "success", "data": result}


def _compute_group_health(collectors: list, total: int) -> dict:
    """Compute health status for a collector group based on member statuses.

    Uses central's own status tracking (ACTIVE/DOWN) as the primary source,
    and gossip-reported peer_states as supplementary info for SUSPECTED peers.
    """
    if total == 0:
        return {"status": "empty", "message": "No collectors"}

    active = [c for c in collectors if c.status == "ACTIVE"]
    down = [c for c in collectors if c.status == "DOWN"]

    # Check gossip for SUSPECTED peers (not yet DOWN in central but flaky)
    suspected_names: set[str] = set()
    for c in active:
        peer_states = getattr(c, "reported_peer_states", None) or {}
        for peer_id, state in peer_states.items():
            if state == "SUSPECTED":
                suspected_names.add(peer_id)

    issues: list[str] = []
    if down:
        down_names = ", ".join(c.hostname or c.name for c in down)
        issues.append(f"{len(down)} DOWN: {down_names}")
    if suspected_names:
        issues.append(f"{len(suspected_names)} SUSPECTED: {', '.join(sorted(suspected_names))}")

    if len(down) == total:
        return {
            "status": "critical",
            "message": f"All {total} collectors are DOWN",
        }

    if issues:
        return {
            "status": "degraded",
            "message": "; ".join(issues),
        }

    return {"status": "healthy", "message": f"All {total} collectors online"}


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
