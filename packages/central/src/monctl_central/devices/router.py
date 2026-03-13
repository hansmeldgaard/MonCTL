"""Device management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

import sqlalchemy as sa
from monctl_central.dependencies import apply_tenant_filter, check_tenant_access, get_db, require_auth
from sqlalchemy.orm import selectinload
from monctl_central.storage.models import Credential, CollectorGroup, Device, Tenant
from monctl_common.utils import utc_now

router = APIRouter()


class CreateDeviceRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Linux server",
                    "value": {
                        "name": "prod-web-01",
                        "address": "10.0.1.10",
                        "device_type": "host",
                        "labels": {"env": "production", "role": "web"},
                    },
                },
            ]
        }
    }

    name: str = Field(description="Human-readable device name, e.g. 'prod-db-01'")
    address: str = Field(description="IP address, hostname, or URL")
    device_type: str = Field(default="host", description="'host', 'network', 'api', 'database', etc.")
    collector_id: str | None = Field(default=None, description="UUID of the owning collector")
    tenant_id: str | None = Field(default=None, description="UUID of the owning tenant")
    collector_group_id: str | None = Field(default=None, description="UUID of the collector group")
    default_credential_id: str | None = Field(default=None, description="UUID of the default credential")
    labels: dict[str, str] = Field(default_factory=dict, description="Key-value labels")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class UpdateDeviceRequest(BaseModel):
    name: str | None = None
    address: str | None = None
    device_type: str | None = None
    collector_id: str | None = None
    tenant_id: str | None = None
    collector_group_id: str | None = None
    default_credential_id: str | None = None
    labels: dict[str, str] | None = None
    metadata: dict | None = None


def _format_device(d: Device) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "address": d.address,
        "device_type": d.device_type,
        "collector_id": str(d.collector_id) if d.collector_id else None,
        "tenant_id": str(d.tenant_id) if d.tenant_id else None,
        "tenant_name": d.tenant.name if d.tenant else None,
        "collector_group_id": str(d.collector_group_id) if d.collector_group_id else None,
        "collector_group_name": d.collector_group.name if d.collector_group else None,
        "default_credential_id": str(d.default_credential_id) if d.default_credential_id else None,
        "default_credential_name": d.default_credential.name if d.default_credential else None,
        "labels": d.labels,
        "metadata": d.metadata_,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


@router.get("")
async def list_devices(
    collector_id: Optional[str] = Query(default=None, description="Filter by collector UUID"),
    device_type: Optional[str] = Query(default=None, description="Filter by device type"),
    name: Optional[str] = Query(default=None, description="Filter by name (ilike)"),
    address: Optional[str] = Query(default=None, description="Filter by address (ilike)"),
    tenant_name: Optional[str] = Query(default=None, description="Filter by tenant name"),
    collector_group_name: Optional[str] = Query(default=None, description="Filter by collector group name"),
    label_key: Optional[str] = Query(default=None, description="Filter by label key"),
    label_value: Optional[str] = Query(default=None, description="Filter by label value (requires label_key)"),
    sort_by: str = Query(default="name", description="Sort field"),
    sort_dir: str = Query(default="asc", description="Sort direction: asc or desc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List devices with filtering, sorting, and pagination."""
    # Base query with eager loads
    stmt = select(Device).options(
        selectinload(Device.tenant),
        selectinload(Device.collector_group),
        selectinload(Device.default_credential),
    )

    # Apply filters
    if collector_id:
        stmt = stmt.where(Device.collector_id == uuid.UUID(collector_id))
    if device_type:
        stmt = stmt.where(Device.device_type == device_type)
    if name:
        stmt = stmt.where(Device.name.ilike(f"%{name}%"))
    if address:
        stmt = stmt.where(Device.address.ilike(f"%{address}%"))
    if tenant_name:
        stmt = stmt.outerjoin(Tenant, Device.tenant_id == Tenant.id)
        stmt = stmt.where(Tenant.name == tenant_name)
    if collector_group_name:
        if not tenant_name:  # avoid double outerjoin issues
            stmt = stmt.outerjoin(CollectorGroup, Device.collector_group_id == CollectorGroup.id)
        else:
            stmt = stmt.outerjoin(CollectorGroup, Device.collector_group_id == CollectorGroup.id)
        stmt = stmt.where(CollectorGroup.name == collector_group_name)
    if label_key:
        stmt = stmt.where(Device.labels.has_key(label_key))
        if label_value:
            stmt = stmt.where(Device.labels[label_key].astext == label_value)

    stmt = apply_tenant_filter(stmt, auth, Device.tenant_id)

    # Count query (same WHERE clause)
    count_stmt = select(sa.func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Sorting
    sort_column = {
        "name": Device.name,
        "address": Device.address,
        "device_type": Device.device_type,
        "created_at": Device.created_at,
    }.get(sort_by)

    if sort_by == "tenant_name" and not tenant_name:
        stmt = stmt.outerjoin(Tenant, Device.tenant_id == Tenant.id)
        sort_column = Tenant.name
    elif sort_by == "tenant_name":
        sort_column = Tenant.name
    elif sort_by == "collector_group_name" and not collector_group_name:
        stmt = stmt.outerjoin(CollectorGroup, Device.collector_group_id == CollectorGroup.id)
        sort_column = CollectorGroup.name
    elif sort_by == "collector_group_name":
        sort_column = CollectorGroup.name

    if sort_column is not None:
        if sort_dir == "desc":
            stmt = stmt.order_by(sa.desc(sort_column))
        else:
            stmt = stmt.order_by(sa.asc(sort_column))
    else:
        stmt = stmt.order_by(Device.name)

    stmt = stmt.offset(offset).limit(limit)
    devices = (await db.execute(stmt)).scalars().unique().all()
    return {
        "status": "success",
        "data": [_format_device(d) for d in devices],
        "meta": {"limit": limit, "offset": offset, "count": len(devices), "total": total},
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_device(
    request: CreateDeviceRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new device."""
    device = Device(
        name=request.name,
        address=request.address,
        device_type=request.device_type,
        collector_id=uuid.UUID(request.collector_id) if request.collector_id else None,
        tenant_id=uuid.UUID(request.tenant_id) if request.tenant_id else None,
        collector_group_id=uuid.UUID(request.collector_group_id) if request.collector_group_id else None,
        default_credential_id=uuid.UUID(request.default_credential_id) if request.default_credential_id else None,
        labels=request.labels,
        metadata_=request.metadata,
    )
    db.add(device)
    await db.flush()
    await db.refresh(device, ["tenant", "collector_group", "default_credential"])
    return {
        "status": "success",
        "data": _format_device(device),
    }


@router.get("/{device_id}")
async def get_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get a device by ID."""
    stmt = (
        select(Device)
        .options(selectinload(Device.tenant), selectinload(Device.collector_group), selectinload(Device.default_credential))
        .where(Device.id == uuid.UUID(device_id))
    )
    device = (await db.execute(stmt)).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return {"status": "success", "data": _format_device(device)}


@router.put("/{device_id}")
async def update_device(
    device_id: str,
    request: UpdateDeviceRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a device."""
    stmt = (
        select(Device)
        .options(selectinload(Device.tenant), selectinload(Device.collector_group), selectinload(Device.default_credential))
        .where(Device.id == uuid.UUID(device_id))
    )
    device = (await db.execute(stmt)).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if request.name is not None:
        device.name = request.name
    if request.address is not None:
        device.address = request.address
    if request.device_type is not None:
        device.device_type = request.device_type
    if request.collector_id is not None:
        device.collector_id = uuid.UUID(request.collector_id) if request.collector_id else None
    if request.tenant_id is not None:
        device.tenant_id = uuid.UUID(request.tenant_id) if request.tenant_id != "" else None

    # Track whether collector_group_id is changing (and what it's changing to)
    new_group_id: uuid.UUID | None = device.collector_group_id
    if request.collector_group_id is not None:
        new_group_id = uuid.UUID(request.collector_group_id) if request.collector_group_id != "" else None
        device.collector_group_id = new_group_id

    if request.default_credential_id is not None:
        device.default_credential_id = uuid.UUID(request.default_credential_id) if request.default_credential_id != "" else None
    if request.labels is not None:
        device.labels = request.labels
    if request.metadata is not None:
        device.metadata_ = request.metadata
    device.updated_at = utc_now()
    await db.flush()

    # When a device is placed into a collector group, migrate all its existing
    # explicit-collector assignments to group-level (collector_id = NULL) so that
    # the group's collectors pick them up via round-robin.
    if new_group_id is not None:
        from sqlalchemy import update
        from monctl_central.storage.models import AppAssignment, Collector
        from monctl_common.utils import utc_now as _utc_now

        # Null out collector_id on all assignments that still point to a specific collector
        await db.execute(
            update(AppAssignment)
            .where(
                AppAssignment.device_id == device.id,
                AppAssignment.collector_id.is_not(None),
            )
            .values(collector_id=None)
        )

        # Bump all collectors in the new group so they re-fetch their config
        await db.execute(
            update(Collector)
            .where(Collector.group_id == new_group_id)
            .values(config_version=Collector.config_version + 1, updated_at=_utc_now())
        )

    await db.refresh(device, ["tenant", "collector_group", "default_credential"])
    return {"status": "success", "data": _format_device(device)}


class MonitoringCheckConfig(BaseModel):
    """Configuration for a single monitoring check (availability or latency)."""
    app_name: str | None = None
    config: dict = Field(default_factory=dict)
    interval_seconds: int = 60


class UpdateMonitoringRequest(BaseModel):
    availability: MonitoringCheckConfig | None = None
    latency: MonitoringCheckConfig | None = None
    interface: MonitoringCheckConfig | None = None


def _monitoring_config_from_assignment(assignment, app_name: str) -> dict:
    """Convert an AppAssignment back into a MonitoringCheckConfig dict."""
    return {
        "app_name": app_name,
        "config": assignment.config or {},
        "interval_seconds": int(assignment.schedule_value),
    }


@router.get("/{device_id}/monitoring")
async def get_device_monitoring(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get current availability and latency monitoring configuration for a device."""
    from sqlalchemy import select as sa_select
    from monctl_central.storage.models import App, AppAssignment

    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    rows = (
        await db.execute(
            sa_select(AppAssignment, App)
            .join(App, AppAssignment.app_id == App.id)
            .where(
                AppAssignment.device_id == uuid.UUID(device_id),
                AppAssignment.role.in_(["availability", "latency", "interface"]),
            )
        )
    ).all()

    result: dict = {"availability": None, "latency": None, "interface": None}
    for assignment, app in rows:
        if assignment.role in result:
            result[assignment.role] = _monitoring_config_from_assignment(assignment, app.name)

    return {"status": "success", "data": result}


@router.put("/{device_id}/monitoring")
async def update_device_monitoring(
    device_id: str,
    request: UpdateMonitoringRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Set availability and latency monitoring apps for a device."""
    from sqlalchemy import delete as sa_delete, select as sa_select, update as sa_update, desc as sa_desc
    from monctl_central.storage.models import App, AppAssignment, AppVersion, Collector
    from monctl_common.utils import utc_now as _utc_now

    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if not device.collector_group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device must be assigned to a collector group before enabling monitoring.",
        )

    # Remove all existing monitoring assignments for this device
    await db.execute(
        sa_delete(AppAssignment).where(
            AppAssignment.device_id == uuid.UUID(device_id),
            AppAssignment.role.in_(["availability", "latency", "interface"]),
        )
    )

    # Map role → allowed target_table
    _ROLE_TARGET_TABLE = {
        "availability": "availability_latency",
        "latency": "availability_latency",
        "interface": "interface",
    }

    new_assignments: dict = {}
    for role_name, check_config in [
        ("availability", request.availability),
        ("latency", request.latency),
        ("interface", request.interface),
    ]:
        if check_config is None or check_config.app_name is None:
            continue

        # Look up the app by name
        app = (
            await db.execute(sa_select(App).where(App.name == check_config.app_name))
        ).scalar_one_or_none()
        if app is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"App '{check_config.app_name}' not found",
            )

        # Validate app targets the correct table for this role
        expected_table = _ROLE_TARGET_TABLE.get(role_name, "availability_latency")
        if app.target_table != expected_table:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"App '{check_config.app_name}' targets '{app.target_table}', not '{expected_table}'",
            )

        # Get the latest published version
        app_version = (
            await db.execute(
                sa_select(AppVersion)
                .where(AppVersion.app_id == app.id)
                .order_by(sa_desc(AppVersion.published_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if app_version is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No version found for app '{check_config.app_name}'",
            )

        # For interface role, resolve system default if interval not set
        interval = check_config.interval_seconds
        if role_name == "interface" and interval <= 0:
            from monctl_central.storage.models import SystemSetting
            setting = await db.get(SystemSetting, "interface_poll_interval_seconds")
            interval = int(setting.value) if setting else 300

        assignment = AppAssignment(
            app_id=app.id,
            app_version_id=app_version.id,
            device_id=uuid.UUID(device_id),
            collector_id=None,
            config=check_config.config,
            schedule_type="interval",
            schedule_value=str(interval),
            resource_limits={"timeout_seconds": 30, "memory_mb": 256},
            role=role_name,
            enabled=True,
        )
        db.add(assignment)
        new_assignments[role_name] = (assignment, app.name)

    await db.flush()

    # Bump all collectors in the device's group so they re-fetch config
    await db.execute(
        sa_update(Collector)
        .where(Collector.group_id == device.collector_group_id)
        .values(config_version=Collector.config_version + 1, updated_at=_utc_now())
    )

    # Return the updated monitoring config
    result: dict = {"availability": None, "latency": None, "interface": None}
    for role_name, (assignment, app_name) in new_assignments.items():
        result[role_name] = _monitoring_config_from_assignment(assignment, app_name)

    return {"status": "success", "data": result}


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a device."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    await db.delete(device)


class BulkDeleteRequest(BaseModel):
    device_ids: list[str]


@router.post("/bulk-delete", status_code=status.HTTP_200_OK)
async def bulk_delete_devices(
    request: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Bulk delete devices."""
    deleted = 0
    for did in request.device_ids:
        device = await db.get(Device, uuid.UUID(did))
        if device and check_tenant_access(auth, device.tenant_id):
            await db.delete(device)
            deleted += 1
    return {"status": "success", "data": {"deleted": deleted}}
