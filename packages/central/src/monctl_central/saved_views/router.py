"""Per-user saved views (named filter sets) for list pages.

Currently used by `/devices-beta`; the `page` column is a free-text key so
future list pages (apps, assignments, alerts, ...) can adopt the same
table without a schema change.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth, require_permission
from monctl_central.storage.models import SavedView

router = APIRouter()


# Built-in starter views seeded for a new user on first GET. Hard-coded names
# come from the design handoff; filter contents are intentionally light so the
# user can edit each one to suit their fleet.
DEFAULT_VIEWS: dict[str, list[dict]] = {
    "devices-beta": [
        {
            "name": "All devices",
            "filter_json": {"statusFilter": "all", "q": "", "columnFilters": {}, "sort": {"key": "name", "dir": "asc"}},
        },
        {
            "name": "Down right now",
            "filter_json": {"statusFilter": "down", "q": "", "columnFilters": {}, "sort": {"key": "name", "dir": "asc"}},
        },
        {
            "name": "Never polled",
            "filter_json": {"statusFilter": "unknown", "q": "", "columnFilters": {}, "sort": {"key": "name", "dir": "asc"}},
        },
        {
            "name": "Disabled",
            "filter_json": {"statusFilter": "disabled", "q": "", "columnFilters": {}, "sort": {"key": "name", "dir": "asc"}},
        },
    ],
}


def _format(v: SavedView) -> dict:
    return {
        "id": str(v.id),
        "page": v.page,
        "name": v.name,
        "filter_json": v.filter_json,
        "position": v.position,
        "is_pinned": v.is_pinned,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


class SavedViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    filter_json: dict = Field(default_factory=dict)
    is_pinned: bool = False


class SavedViewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    filter_json: Optional[dict] = None
    is_pinned: Optional[bool] = None


class SavedViewReorder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordered_ids: list[uuid.UUID] = Field(min_length=1)


async def _seed_defaults_if_empty(
    db: AsyncSession, user_id: uuid.UUID, page: str
) -> list[SavedView]:
    """Insert the page's default view set for `user_id` and return them.

    Caller must ensure the user has zero views for `page` before calling.
    """
    defaults = DEFAULT_VIEWS.get(page, [])
    created: list[SavedView] = []
    for i, d in enumerate(defaults):
        v = SavedView(
            user_id=user_id,
            page=page,
            name=d["name"],
            filter_json=d.get("filter_json", {}),
            position=i,
            is_pinned=False,
        )
        db.add(v)
        created.append(v)
    if created:
        await db.commit()
        for v in created:
            await db.refresh(v)
    return created


@router.get("")
async def list_saved_views(
    page: str = Query(..., min_length=1, max_length=64, description="Page key (e.g. 'devices-beta')"),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("saved_view", "view")),
):
    """List the current user's saved views for the given page.

    On first call (zero rows), seeds the page-specific default view set
    so the UI is non-empty out of the box.
    """
    user_id = uuid.UUID(str(auth["user_id"]))
    stmt = (
        select(SavedView)
        .where(SavedView.user_id == user_id, SavedView.page == page)
        .order_by(SavedView.position.asc(), SavedView.created_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        rows = await _seed_defaults_if_empty(db, user_id, page)
    return {
        "status": "success",
        "data": [_format(v) for v in rows],
        "meta": {"count": len(rows)},
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_saved_view(
    body: SavedViewCreate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("saved_view", "create")),
):
    user_id = uuid.UUID(str(auth["user_id"]))
    # Append at end: max(position)+1
    max_pos_stmt = select(SavedView.position).where(
        SavedView.user_id == user_id, SavedView.page == body.page
    ).order_by(SavedView.position.desc()).limit(1)
    max_pos = (await db.execute(max_pos_stmt)).scalar()
    next_pos = (max_pos + 1) if max_pos is not None else 0
    v = SavedView(
        user_id=user_id,
        page=body.page,
        name=body.name,
        filter_json=body.filter_json,
        position=next_pos,
        is_pinned=body.is_pinned,
    )
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return {"status": "success", "data": _format(v)}


@router.patch("/{view_id}")
async def update_saved_view(
    view_id: uuid.UUID,
    body: SavedViewUpdate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("saved_view", "edit")),
):
    user_id = uuid.UUID(str(auth["user_id"]))
    v = (
        await db.execute(
            select(SavedView).where(
                SavedView.id == view_id, SavedView.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Saved view not found")
    if body.name is not None:
        v.name = body.name
    if body.filter_json is not None:
        v.filter_json = body.filter_json
    if body.is_pinned is not None:
        v.is_pinned = body.is_pinned
    await db.commit()
    await db.refresh(v)
    return {"status": "success", "data": _format(v)}


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_view(
    view_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("saved_view", "delete")),
):
    user_id = uuid.UUID(str(auth["user_id"]))
    res = await db.execute(
        delete(SavedView).where(
            SavedView.id == view_id, SavedView.user_id == user_id
        )
    )
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Saved view not found")
    await db.commit()


@router.post("/reorder")
async def reorder_saved_views(
    body: SavedViewReorder,
    page: str = Query(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("saved_view", "edit")),
):
    """Reorder this user's views for `page` to match the supplied id list.

    Any view ids that belong to the user+page but aren't in the list keep
    their current relative order, appended after the supplied set.
    """
    user_id = uuid.UUID(str(auth["user_id"]))
    rows = (
        await db.execute(
            select(SavedView).where(
                SavedView.user_id == user_id, SavedView.page == page
            )
        )
    ).scalars().all()
    by_id = {v.id: v for v in rows}
    seen: set[uuid.UUID] = set()
    pos = 0
    for vid in body.ordered_ids:
        v = by_id.get(vid)
        if v is None:
            continue  # silently skip unknown ids; idempotent reorder
        v.position = pos
        seen.add(vid)
        pos += 1
    # Append unseen views in their existing order
    leftover = sorted(
        (v for v in rows if v.id not in seen),
        key=lambda v: (v.position, v.created_at),
    )
    for v in leftover:
        v.position = pos
        pos += 1
    await db.commit()
    return {"status": "success", "data": {"reordered": len(seen)}}
