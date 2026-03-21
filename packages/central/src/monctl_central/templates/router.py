"""Template management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from monctl_common.validators import validate_uuid
import sqlalchemy as sa
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import (
    App,
    AppAssignment,
    AppVersion,
    Device,
    Template,
)
from monctl_common.utils import utc_now

router = APIRouter()


def _format_template(t: Template) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "description": t.description,
        "config": t.config,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


SORT_MAP = {"name": Template.name, "created_at": Template.created_at}


@router.get("")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
    name: str | None = Query(default=None),
    description: str | None = Query(default=None),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all templates."""
    base_stmt = select(Template)

    if name:
        base_stmt = base_stmt.where(Template.name.ilike(f"%{name}%"))
    if description:
        base_stmt = base_stmt.where(Template.description.ilike(f"%{description}%"))

    sort_col = SORT_MAP.get(sort_by, Template.name)
    base_stmt = base_stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    count_stmt = select(sa.func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = base_stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    templates = result.scalars().all()
    data = [_format_template(t) for t in templates]

    return {
        "status": "success",
        "data": data,
        "meta": {"limit": limit, "offset": offset, "count": len(data), "total": total},
    }


class CreateTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    config: dict = Field(default_factory=dict)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(
    request: CreateTemplateRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new template."""
    template = Template(
        name=request.name,
        description=request.description,
        config=request.config,
    )
    db.add(template)
    await db.flush()
    return {"status": "success", "data": _format_template(template)}


@router.get("/{template_id}")
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get a template by ID."""
    template = await db.get(Template, uuid.UUID(template_id))
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"status": "success", "data": _format_template(template)}


class UpdateTemplateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    config: dict | None = None


@router.put("/{template_id}")
async def update_template(
    template_id: str,
    request: UpdateTemplateRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a template."""
    template = await db.get(Template, uuid.UUID(template_id))
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if request.name is not None:
        template.name = request.name
    if request.description is not None:
        template.description = request.description
    if request.config is not None:
        template.config = request.config
    template.updated_at = utc_now()
    await db.flush()
    return {"status": "success", "data": _format_template(template)}


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a template."""
    template = await db.get(Template, uuid.UUID(template_id))
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(template)


class ApplyTemplateRequest(BaseModel):
    device_ids: list[str] = Field(default_factory=list, max_length=500)
    device_type_names: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("device_ids")
    @classmethod
    def check_device_ids(cls, v: list[str]) -> list[str]:
        for did in v:
            validate_uuid(did, "device_ids")
        return v

    @model_validator(mode="after")
    def check_at_least_one_target(self) -> "ApplyTemplateRequest":
        if not self.device_ids and not self.device_type_names:
            raise ValueError("At least one of device_ids or device_type_names must be provided")
        return self


@router.post("/{template_id}/apply")
async def apply_template(
    template_id: str,
    request: ApplyTemplateRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Apply a template to devices."""
    template = await db.get(Template, uuid.UUID(template_id))
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    config = template.config or {}

    # Collect target devices
    device_ids = set()
    for did in request.device_ids:
        device_ids.add(uuid.UUID(did))

    if request.device_type_names:
        stmt = select(Device).where(Device.device_type.in_(request.device_type_names))
        result = await db.execute(stmt)
        for d in result.scalars().all():
            device_ids.add(d.id)

    applied = 0
    for device_id in device_ids:
        device = await db.get(Device, device_id)
        if device is None:
            continue

        # Apply labels (merge)
        template_labels = config.get("labels", {})
        if template_labels:
            merged = dict(device.labels or {})
            merged.update(template_labels)
            device.labels = merged

        # Apply default credential
        cred_id = config.get("default_credential_id")
        if cred_id:
            device.default_credential_id = uuid.UUID(cred_id)

        # Apply app assignments
        for app_config in config.get("apps", []):
            app_name = app_config.get("app_name") or app_config.get("app_id")
            if not app_name:
                continue

            app = (await db.execute(
                select(App).where(App.name == app_name)
            )).scalar_one_or_none()
            if app is None:
                continue

            app_version = (await db.execute(
                select(AppVersion)
                .where(AppVersion.app_id == app.id)
                .order_by(desc(AppVersion.published_at))
                .limit(1)
            )).scalar_one_or_none()
            if app_version is None:
                continue

            assignment = AppAssignment(
                app_id=app.id,
                app_version_id=app_version.id,
                device_id=device_id,
                config=app_config.get("config", {}),
                schedule_type=app_config.get("schedule_type", "interval"),
                schedule_value=app_config.get("schedule_value", "60"),
                role=app_config.get("role"),
                enabled=True,
            )
            db.add(assignment)

        device.updated_at = utc_now()
        applied += 1

    await db.flush()
    return {"status": "success", "data": {"applied": applied}}
