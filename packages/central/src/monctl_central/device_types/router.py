"""Device category catalogue endpoints — define what categories of devices exist."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import DeviceCategory, DeviceType

router = APIRouter()

MAX_ICON_SIZE = 256 * 1024  # 256 KB
ALLOWED_MIME_TYPES = {"image/png", "image/svg+xml", "image/jpeg", "image/webp"}


class CreateDeviceCategoryRequest(BaseModel):
    name: str = Field(description="Unique category name, e.g. 'host', 'network', 'api'")
    description: str | None = Field(default=None, description="Optional description")
    category: str = Field(default="other", description="Category: network, server, storage, printer, iot, service, database, other")
    icon: str | None = Field(default=None, max_length=64, description="Icon identifier: router, switch, server, firewall, etc.")


class UpdateDeviceCategoryRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    icon: str | None = None


def _fmt(dt: DeviceCategory) -> dict:
    return {
        "id": str(dt.id),
        "name": dt.name,
        "description": dt.description,
        "category": dt.category,
        "icon": dt.icon,
        "has_custom_icon": dt.icon_data is not None,
        "pack_id": str(dt.pack_id) if dt.pack_id else None,
        "created_at": dt.created_at.isoformat() if dt.created_at else None,
    }


@router.get("")
async def list_device_categories(
    name: str | None = Query(default=None, description="Filter by name (ilike)"),
    category: str | None = Query(default=None, description="Filter by category"),
    search: str | None = Query(default=None, description="Search name or description"),
    sort_by: str = Query(default="name", description="Sort field: name, category, created_at"),
    sort_dir: str = Query(default="asc", description="Sort direction: asc or desc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List device categories with filtering, sorting, and pagination."""
    stmt = select(DeviceCategory)

    if name:
        stmt = stmt.where(DeviceCategory.name.ilike(f"%{name}%"))
    if category:
        stmt = stmt.where(DeviceCategory.category == category)
    if search:
        stmt = stmt.where(
            sa.or_(
                DeviceCategory.name.ilike(f"%{search}%"),
                DeviceCategory.description.ilike(f"%{search}%"),
            )
        )

    # Count
    count_stmt = select(sa.func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Category summary (counts per category, always unfiltered by pagination)
    cat_count_stmt = (
        select(DeviceCategory.category, sa.func.count().label("cnt"))
        .where(
            DeviceCategory.id.in_(select(stmt.subquery().c.id))
        )
        .group_by(DeviceCategory.category)
    )
    cat_rows = (await db.execute(cat_count_stmt)).all()
    category_counts = {row[0]: row[1] for row in cat_rows}

    # Sorting
    sort_column = {
        "name": DeviceCategory.name,
        "category": DeviceCategory.category,
        "created_at": DeviceCategory.created_at,
    }.get(sort_by, DeviceCategory.name)

    if sort_dir == "desc":
        stmt = stmt.order_by(sa.desc(sort_column))
    else:
        stmt = stmt.order_by(sa.asc(sort_column))

    stmt = stmt.offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    # Count device types per category
    cat_ids = [dt.id for dt in rows]
    dt_count_map: dict[uuid.UUID, int] = {}
    if cat_ids:
        dt_count_stmt = (
            select(DeviceType.device_category_id, sa.func.count().label("cnt"))
            .where(DeviceType.device_category_id.in_(cat_ids))
            .group_by(DeviceType.device_category_id)
        )
        dt_count_rows = (await db.execute(dt_count_stmt)).all()
        dt_count_map = {row[0]: row[1] for row in dt_count_rows}

    def _fmt_with_count(dt: DeviceCategory) -> dict:
        d = _fmt(dt)
        d["device_type_count"] = dt_count_map.get(dt.id, 0)
        return d

    return {
        "status": "success",
        "data": [_fmt_with_count(dt) for dt in rows],
        "meta": {
            "limit": limit,
            "offset": offset,
            "count": len(rows),
            "total": total,
            "category_counts": category_counts,
        },
    }


@router.get("/categories")
async def list_category_counts(
    search: str | None = Query(default=None, description="Search name or description"),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get type counts per category, optionally filtered by search."""
    stmt = select(DeviceCategory)
    if search:
        stmt = stmt.where(
            sa.or_(
                DeviceCategory.name.ilike(f"%{search}%"),
                DeviceCategory.description.ilike(f"%{search}%"),
            )
        )
    cat_stmt = (
        select(DeviceCategory.category, sa.func.count().label("cnt"))
        .where(DeviceCategory.id.in_(select(stmt.subquery().c.id)))
        .group_by(DeviceCategory.category)
    )
    rows = (await db.execute(cat_stmt)).all()
    total_stmt = select(sa.func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar() or 0
    return {
        "status": "success",
        "data": {
            "categories": {row[0]: row[1] for row in rows},
            "total": total,
        },
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_device_category(
    request: CreateDeviceCategoryRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new device category."""
    # Check for duplicate name
    existing = (
        await db.execute(select(DeviceCategory).where(DeviceCategory.name == request.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Device category '{request.name}' already exists",
        )
    dt = DeviceCategory(
        name=request.name, description=request.description, category=request.category,
        icon=request.icon,
    )
    db.add(dt)
    await db.flush()
    return {"status": "success", "data": _fmt(dt)}


@router.put("/{type_id}")
async def update_device_category(
    type_id: str,
    request: UpdateDeviceCategoryRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a device category name or description."""
    dt = await db.get(DeviceCategory, uuid.UUID(type_id))
    if dt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device category not found")
    if request.name is not None:
        dt.name = request.name
    if request.description is not None:
        dt.description = request.description
    if request.category is not None:
        dt.category = request.category
    if request.icon is not None:
        dt.icon = request.icon
    return {"status": "success", "data": _fmt(dt)}


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_category(
    type_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a device category."""
    dt = await db.get(DeviceCategory, uuid.UUID(type_id))
    if dt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device category not found")
    await db.delete(dt)


# ── Custom icon endpoints ──────────────────────────────────


@router.post("/{type_id}/icon")
async def upload_device_category_icon(
    type_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Upload a custom icon for a device category. Accepts PNG, JPEG, WebP, or SVG up to 256 KB."""
    dt = await db.get(DeviceCategory, uuid.UUID(type_id))
    if dt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device category not found")

    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{content_type}'. Allowed: PNG, JPEG, WebP, SVG.",
        )

    data = await file.read()
    if len(data) > MAX_ICON_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Icon too large ({len(data)} bytes). Maximum size is 256 KB.",
        )

    dt.icon_data = data
    dt.icon_mime_type = content_type
    return {"status": "success", "data": _fmt(dt)}


@router.get("/{type_id}/icon")
async def get_device_category_icon(
    type_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve the custom icon image for a device category. No auth required (used in <img> tags)."""
    dt = await db.get(DeviceCategory, uuid.UUID(type_id))
    if dt is None or dt.icon_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No custom icon")
    return Response(
        content=dt.icon_data,
        media_type=dt.icon_mime_type or "image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.delete("/{type_id}/icon", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_category_icon(
    type_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Remove the custom icon from a device category."""
    dt = await db.get(DeviceCategory, uuid.UUID(type_id))
    if dt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device category not found")
    dt.icon_data = None
    dt.icon_mime_type = None
