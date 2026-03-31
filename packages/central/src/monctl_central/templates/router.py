"""Template management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from monctl_common.validators import validate_uuid
import sqlalchemy as sa
from sqlalchemy import select, desc, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import (
    App,
    AppAssignment,
    AppVersion,
    Device,
    DeviceCategory,
    DeviceCategoryTemplateBinding,
    DeviceType,
    DeviceTypeTemplateBinding,
    Template,
)
from monctl_central.templates.resolver import resolve_templates_for_devices
from monctl_common.utils import utc_now

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_template(t: Template) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "description": t.description,
        "config": t.config,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _fmt_category_binding(b: DeviceCategoryTemplateBinding) -> dict:
    return {
        "id": str(b.id),
        "device_category_id": str(b.device_category_id),
        "device_category_name": b.device_category.name if b.device_category else None,
        "template_id": str(b.template_id),
        "template_name": b.template.name if b.template else None,
        "step": b.priority,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


def _fmt_type_binding(b: DeviceTypeTemplateBinding) -> dict:
    return {
        "id": str(b.id),
        "device_type_id": str(b.device_type_id),
        "device_type_name": b.device_type.name if b.device_type else None,
        "template_id": str(b.template_id),
        "template_name": b.template.name if b.template else None,
        "step": b.priority,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


_ROLE_TARGET_TABLE = {
    "availability": "availability_latency",
    "latency": "availability_latency",
    "interface": "interface",
}
_MONITORING_ROLES = {"availability", "latency", "interface"}


def _resolve_credential_id(cred_value: str | None) -> uuid.UUID | None:
    """Resolve credential_id from template config value.

    - None / empty: no credential
    - UUID string: use as-is
    - Invalid UUID: return None (gracefully ignore)
    """
    if not cred_value:
        return None
    try:
        return uuid.UUID(cred_value)
    except (ValueError, AttributeError):
        return None


async def apply_config_to_device(
    device: Device, config: dict, db: AsyncSession
) -> None:
    """Apply a template config dict to a device. Shared by manual apply and auto-apply."""
    # Apply labels (merge)
    template_labels = config.get("labels", {})
    if template_labels:
        merged = dict(device.labels or {})
        merged.update(template_labels)
        device.labels = merged

    # Apply credentials (merge into device.credentials JSONB)
    template_creds = config.get("credentials", {})
    if template_creds:
        merged = dict(device.credentials or {})
        merged.update(template_creds)
        device.credentials = merged

    # Apply collector group
    cg_id = config.get("default_collector_group_id")
    if cg_id:
        device.collector_group_id = uuid.UUID(cg_id)

    # Apply monitoring configuration (availability / latency / interface)
    monitoring_config = config.get("monitoring", {})
    if monitoring_config:
        for role_name in ["availability", "latency", "interface"]:
            check_config = monitoring_config.get(role_name)
            if not check_config or not check_config.get("app_name"):
                continue

            app = (await db.execute(
                select(App).where(App.name == check_config["app_name"])
            )).scalar_one_or_none()
            if app is None:
                continue

            expected_table = _ROLE_TARGET_TABLE.get(role_name)
            if app.target_table != expected_table:
                continue

            app_version = (await db.execute(
                select(AppVersion)
                .where(AppVersion.app_id == app.id)
                .order_by(desc(AppVersion.published_at))
                .limit(1)
            )).scalar_one_or_none()
            if app_version is None:
                continue

            interval = check_config.get("interval_seconds", 60)

            # Upsert: check for existing assignment with same (app_id, device_id)
            existing = (await db.execute(
                select(AppAssignment).where(
                    AppAssignment.app_id == app.id,
                    AppAssignment.device_id == device.id,
                )
            )).scalar_one_or_none()

            if existing:
                existing.app_version_id = app_version.id
                existing.config = check_config.get("config", {})
                existing.schedule_type = "interval"
                existing.schedule_value = str(interval)
                existing.role = role_name
                existing.credential_id = _resolve_credential_id(check_config.get("credential_id"))
                existing.enabled = True
                existing.use_latest = True
                existing.updated_at = utc_now()
            else:
                assignment = AppAssignment(
                    app_id=app.id,
                    app_version_id=app_version.id,
                    device_id=device.id,
                    config=check_config.get("config", {}),
                    schedule_type="interval",
                    schedule_value=str(interval),
                    role=role_name,
                    credential_id=_resolve_credential_id(check_config.get("credential_id")),
                    enabled=True,
                    use_latest=True,
                )
                db.add(assignment)

    # Apply app assignments (generic — non-monitoring)
    for app_config in config.get("apps", []):
        if app_config.get("role") in _MONITORING_ROLES:
            continue
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

        # Upsert: update existing assignment if same app already assigned to this device
        existing = (await db.execute(
            select(AppAssignment).where(
                AppAssignment.app_id == app.id,
                AppAssignment.device_id == device.id,
            )
        )).scalar_one_or_none()

        if existing:
            existing.app_version_id = app_version.id
            existing.config = app_config.get("config", {})
            existing.schedule_type = app_config.get("schedule_type", "interval")
            existing.schedule_value = app_config.get("schedule_value", "60")
            existing.credential_id = _resolve_credential_id(app_config.get("credential_id"))
            existing.enabled = True
            existing.use_latest = True
            existing.updated_at = utc_now()
        else:
            assignment = AppAssignment(
                app_id=app.id,
                app_version_id=app_version.id,
                device_id=device.id,
                config=app_config.get("config", {}),
                schedule_type=app_config.get("schedule_type", "interval"),
                schedule_value=app_config.get("schedule_value", "60"),
                role=app_config.get("role"),
                credential_id=_resolve_credential_id(app_config.get("credential_id")),
                enabled=True,
                use_latest=True,
            )
            db.add(assignment)

    # Apply interface rules
    interface_rules = config.get("interface_rules")
    if interface_rules:
        from monctl_central.templates.interface_rules import apply_rules_to_all_interfaces
        device.interface_rules = interface_rules
        await apply_rules_to_all_interfaces(device.id, interface_rules, db, force=False)

    device.updated_at = utc_now()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

SORT_MAP = {"name": Template.name, "created_at": Template.created_at}


class CreateTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    config: dict = Field(default_factory=dict)


class UpdateTemplateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    config: dict | None = None


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


class BindCategoryRequest(BaseModel):
    device_category_id: str
    template_id: str
    step: int = 0

    @field_validator("device_category_id", "template_id")
    @classmethod
    def check_uuids(cls, v: str) -> str:
        validate_uuid(v, "id")
        return v


class BindDeviceTypeRequest(BaseModel):
    device_type_id: str
    template_id: str
    step: int = 0

    @field_validator("device_type_id", "template_id")
    @classmethod
    def check_uuids(cls, v: str) -> str:
        validate_uuid(v, "id")
        return v


class ResolveRequest(BaseModel):
    device_ids: list[str] = Field(min_length=1, max_length=500)

    @field_validator("device_ids")
    @classmethod
    def check_device_ids(cls, v: list[str]) -> list[str]:
        for did in v:
            validate_uuid(did, "device_ids")
        return v


# ---------------------------------------------------------------------------
# Routes — STATIC paths first (before /{template_id} catch-all)
# ---------------------------------------------------------------------------

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


# ── Bindings ──────────────────────────────────────────────

@router.post("/bindings/category", status_code=status.HTTP_201_CREATED)
async def bind_category_template(
    request: BindCategoryRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Link a template to a device category."""
    cat_id = uuid.UUID(request.device_category_id)
    tmpl_id = uuid.UUID(request.template_id)

    cat = await db.get(DeviceCategory, cat_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Device category not found")
    tmpl = await db.get(Template, tmpl_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")

    existing = (await db.execute(
        select(DeviceCategoryTemplateBinding).where(
            DeviceCategoryTemplateBinding.device_category_id == cat_id,
            DeviceCategoryTemplateBinding.template_id == tmpl_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.priority = request.step
        await db.flush()
        stmt = select(DeviceCategoryTemplateBinding).where(
            DeviceCategoryTemplateBinding.id == existing.id
        ).options(
            selectinload(DeviceCategoryTemplateBinding.device_category),
            selectinload(DeviceCategoryTemplateBinding.template),
        )
        existing = (await db.execute(stmt)).scalar_one()
        return {"status": "success", "data": _fmt_category_binding(existing)}

    binding = DeviceCategoryTemplateBinding(
        device_category_id=cat_id,
        template_id=tmpl_id,
        priority=request.step,
    )
    db.add(binding)
    await db.flush()
    stmt = select(DeviceCategoryTemplateBinding).where(
        DeviceCategoryTemplateBinding.id == binding.id
    ).options(
        selectinload(DeviceCategoryTemplateBinding.device_category),
        selectinload(DeviceCategoryTemplateBinding.template),
    )
    binding = (await db.execute(stmt)).scalar_one()
    return {"status": "success", "data": _fmt_category_binding(binding)}


@router.delete("/bindings/category/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unbind_category_template(
    binding_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Unlink a template from a device category."""
    binding = await db.get(DeviceCategoryTemplateBinding, uuid.UUID(binding_id))
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")
    await db.delete(binding)


@router.get("/bindings/category/{category_id}")
async def list_category_bindings(
    category_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List templates bound to a device category."""
    cat_id = uuid.UUID(category_id)
    stmt = (
        select(DeviceCategoryTemplateBinding)
        .where(DeviceCategoryTemplateBinding.device_category_id == cat_id)
        .options(
            selectinload(DeviceCategoryTemplateBinding.device_category),
            selectinload(DeviceCategoryTemplateBinding.template),
        )
        .order_by(DeviceCategoryTemplateBinding.priority.asc())
    )
    bindings = (await db.execute(stmt)).scalars().all()
    return {"status": "success", "data": [_fmt_category_binding(b) for b in bindings]}


@router.post("/bindings/device-type", status_code=status.HTTP_201_CREATED)
async def bind_device_type_template(
    request: BindDeviceTypeRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Link a template to a device type."""
    dt_id = uuid.UUID(request.device_type_id)
    tmpl_id = uuid.UUID(request.template_id)

    dt = await db.get(DeviceType, dt_id)
    if dt is None:
        raise HTTPException(status_code=404, detail="Device type not found")
    tmpl = await db.get(Template, tmpl_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")

    existing = (await db.execute(
        select(DeviceTypeTemplateBinding).where(
            DeviceTypeTemplateBinding.device_type_id == dt_id,
            DeviceTypeTemplateBinding.template_id == tmpl_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.priority = request.step
        await db.flush()
        stmt = select(DeviceTypeTemplateBinding).where(
            DeviceTypeTemplateBinding.id == existing.id
        ).options(
            selectinload(DeviceTypeTemplateBinding.device_type),
            selectinload(DeviceTypeTemplateBinding.template),
        )
        existing = (await db.execute(stmt)).scalar_one()
        return {"status": "success", "data": _fmt_type_binding(existing)}

    binding = DeviceTypeTemplateBinding(
        device_type_id=dt_id,
        template_id=tmpl_id,
        priority=request.step,
    )
    db.add(binding)
    await db.flush()
    stmt = select(DeviceTypeTemplateBinding).where(
        DeviceTypeTemplateBinding.id == binding.id
    ).options(
        selectinload(DeviceTypeTemplateBinding.device_type),
        selectinload(DeviceTypeTemplateBinding.template),
    )
    binding = (await db.execute(stmt)).scalar_one()
    return {"status": "success", "data": _fmt_type_binding(binding)}


@router.delete("/bindings/device-type/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unbind_device_type_template(
    binding_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Unlink a template from a device type."""
    binding = await db.get(DeviceTypeTemplateBinding, uuid.UUID(binding_id))
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")
    await db.delete(binding)


@router.get("/bindings/device-type/{device_type_id}")
async def list_device_type_bindings(
    device_type_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List templates bound to a device type."""
    dt_id = uuid.UUID(device_type_id)
    stmt = (
        select(DeviceTypeTemplateBinding)
        .where(DeviceTypeTemplateBinding.device_type_id == dt_id)
        .options(
            selectinload(DeviceTypeTemplateBinding.device_type),
            selectinload(DeviceTypeTemplateBinding.template),
        )
        .order_by(DeviceTypeTemplateBinding.priority.asc())
    )
    bindings = (await db.execute(stmt)).scalars().all()
    return {"status": "success", "data": [_fmt_type_binding(b) for b in bindings]}


# ── Resolve & Auto-Apply ─────────────────────────────────

@router.post("/resolve")
async def resolve_templates(
    request: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Preview resolved template config for devices (no side effects)."""
    devices = []
    for did in request.device_ids:
        device = await db.get(Device, uuid.UUID(did))
        if device:
            devices.append(device)

    results = await resolve_templates_for_devices(devices, db)
    return {"status": "success", "data": results}


@router.post("/auto-apply")
async def auto_apply_templates(
    request: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Resolve hierarchical templates and apply to devices."""
    devices = []
    for did in request.device_ids:
        device = await db.get(Device, uuid.UUID(did))
        if device:
            devices.append(device)

    results = await resolve_templates_for_devices(devices, db)

    applied = 0
    for result in results:
        config = result["resolved_config"]
        if not config:
            continue
        device = await db.get(Device, uuid.UUID(result["device_id"]))
        if device is None:
            continue
        await apply_config_to_device(device, config, db)
        applied += 1

    await db.flush()
    return {
        "status": "success",
        "data": {
            "applied": applied,
            "details": results,
        },
    }


# ---------------------------------------------------------------------------
# Routes — PARAMETERIZED paths (must come after static paths)
# ---------------------------------------------------------------------------

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
        stmt = select(Device).where(Device.device_category.in_(request.device_type_names))
        result = await db.execute(stmt)
        for d in result.scalars().all():
            device_ids.add(d.id)

    applied = 0
    for device_id in device_ids:
        device = await db.get(Device, device_id)
        if device is None:
            continue
        await apply_config_to_device(device, config, db)
        applied += 1

    await db.flush()
    return {"status": "success", "data": {"applied": applied}}
