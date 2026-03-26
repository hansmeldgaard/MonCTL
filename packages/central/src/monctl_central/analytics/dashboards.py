"""Custom analytics dashboards CRUD."""

from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import AnalyticsDashboard, AnalyticsWidget, User
from monctl_common.utils import utc_now

router = APIRouter()


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _fmt_widget(w: AnalyticsWidget) -> dict:
    return {
        "id": str(w.id),
        "dashboard_id": str(w.dashboard_id),
        "title": w.title,
        "config": w.config,
        "layout": w.layout,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


def _fmt_dashboard(d: AnalyticsDashboard, *, include_widgets: bool = False) -> dict:
    out: dict = {
        "id": str(d.id),
        "name": d.name,
        "description": d.description,
        "owner_id": str(d.owner_id) if d.owner_id else None,
        "variables": d.variables or [],
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }
    if include_widgets:
        out["widgets"] = [_fmt_widget(w) for w in d.widgets]
    return out


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class WidgetPayload(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    config: dict = Field(default_factory=dict)
    layout: dict = Field(default_factory=dict)


class CreateDashboardRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    widgets: list[WidgetPayload] = Field(default_factory=list)


class UpdateDashboardRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    widgets: list[WidgetPayload] | None = None
    variables: list[dict] | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/dashboards")
async def list_dashboards(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all analytics dashboards (summary view)."""
    stmt = (
        select(
            AnalyticsDashboard.id,
            AnalyticsDashboard.name,
            AnalyticsDashboard.description,
            AnalyticsDashboard.owner_id,
            AnalyticsDashboard.created_at,
            AnalyticsDashboard.updated_at,
            User.display_name.label("owner_name"),
            func.count(AnalyticsWidget.id).label("widget_count"),
        )
        .outerjoin(User, AnalyticsDashboard.owner_id == User.id)
        .outerjoin(AnalyticsWidget, AnalyticsDashboard.id == AnalyticsWidget.dashboard_id)
        .group_by(
            AnalyticsDashboard.id,
            AnalyticsDashboard.name,
            AnalyticsDashboard.description,
            AnalyticsDashboard.owner_id,
            AnalyticsDashboard.created_at,
            AnalyticsDashboard.updated_at,
            User.display_name,
        )
        .order_by(AnalyticsDashboard.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    data = []
    for r in rows:
        data.append({
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "owner_id": str(r.owner_id) if r.owner_id else None,
            "owner_name": r.owner_name,
            "widget_count": r.widget_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })

    return {"status": "success", "data": data}


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(
    dashboard_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get a single dashboard with all its widgets."""
    stmt = (
        select(AnalyticsDashboard)
        .options(selectinload(AnalyticsDashboard.widgets))
        .where(AnalyticsDashboard.id == dashboard_id)
    )
    dash = (await db.execute(stmt)).scalar_one_or_none()
    if not dash:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    return {"status": "success", "data": _fmt_dashboard(dash, include_widgets=True)}


@router.post("/dashboards", status_code=201)
async def create_dashboard(
    body: CreateDashboardRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new analytics dashboard."""
    dash = AnalyticsDashboard(
        name=body.name,
        description=body.description,
        owner_id=_uuid.UUID(auth["user_id"]) if auth.get("user_id") else None,
    )
    db.add(dash)
    await db.flush()

    for wp in body.widgets:
        widget = AnalyticsWidget(
            dashboard_id=dash.id,
            title=wp.title,
            config=wp.config,
            layout=wp.layout,
        )
        db.add(widget)

    await db.commit()
    await db.refresh(dash)

    # Reload with widgets
    stmt = (
        select(AnalyticsDashboard)
        .options(selectinload(AnalyticsDashboard.widgets))
        .where(AnalyticsDashboard.id == dash.id)
    )
    dash = (await db.execute(stmt)).scalar_one()

    return {"status": "success", "data": _fmt_dashboard(dash, include_widgets=True)}


@router.put("/dashboards/{dashboard_id}")
async def update_dashboard(
    dashboard_id: _uuid.UUID,
    body: UpdateDashboardRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a dashboard (name, description, and/or full widget replacement)."""
    stmt = (
        select(AnalyticsDashboard)
        .options(selectinload(AnalyticsDashboard.widgets))
        .where(AnalyticsDashboard.id == dashboard_id)
    )
    dash = (await db.execute(stmt)).scalar_one_or_none()
    if not dash:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    if body.name is not None:
        dash.name = body.name
    if body.description is not None:
        dash.description = body.description
    if body.variables is not None:
        dash.variables = body.variables
    dash.updated_at = utc_now()

    # Full widget replacement if provided
    if body.widgets is not None:
        # Delete existing widgets
        for w in list(dash.widgets):
            await db.delete(w)
        await db.flush()

        # Create new widgets
        for wp in body.widgets:
            widget = AnalyticsWidget(
                dashboard_id=dash.id,
                title=wp.title,
                config=wp.config,
                layout=wp.layout,
            )
            db.add(widget)

    await db.commit()

    # Reload
    stmt = (
        select(AnalyticsDashboard)
        .options(selectinload(AnalyticsDashboard.widgets))
        .where(AnalyticsDashboard.id == dash.id)
    )
    dash = (await db.execute(stmt)).scalar_one()

    return {"status": "success", "data": _fmt_dashboard(dash, include_widgets=True)}


class AppendWidgetRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    config: dict = Field(default_factory=dict)
    layout: dict = Field(default_factory=dict)


@router.post("/dashboards/{dashboard_id}/widgets", status_code=201)
async def append_widget(
    dashboard_id: _uuid.UUID,
    body: AppendWidgetRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Append a single widget to an existing dashboard (does not replace)."""
    stmt = select(AnalyticsDashboard).where(AnalyticsDashboard.id == dashboard_id)
    dash = (await db.execute(stmt)).scalar_one_or_none()
    if not dash:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    widget = AnalyticsWidget(
        dashboard_id=dash.id,
        title=body.title,
        config=body.config,
        layout=body.layout,
    )
    db.add(widget)
    dash.updated_at = utc_now()
    await db.commit()

    # Reload with widgets
    stmt = (
        select(AnalyticsDashboard)
        .options(selectinload(AnalyticsDashboard.widgets))
        .where(AnalyticsDashboard.id == dash.id)
    )
    dash = (await db.execute(stmt)).scalar_one()

    return {"status": "success", "data": _fmt_dashboard(dash, include_widgets=True)}


@router.delete("/dashboards/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a dashboard and all its widgets."""
    stmt = select(AnalyticsDashboard).where(AnalyticsDashboard.id == dashboard_id)
    dash = (await db.execute(stmt)).scalar_one_or_none()
    if not dash:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    await db.delete(dash)
    await db.commit()

    return {"status": "success", "data": None}
