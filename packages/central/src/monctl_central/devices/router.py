"""Device management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

import sqlalchemy as sa
from monctl_central.dependencies import apply_tenant_filter, check_tenant_access, get_clickhouse, get_db, require_permission
from monctl_central.storage.clickhouse import ClickHouseClient
from sqlalchemy.orm import selectinload
from monctl_central.storage.models import Credential, CollectorGroup, Device, DeviceType, InterfaceMetadata, LabelKey, Tenant, Collector
from monctl_common.utils import utc_now
from monctl_common.validators import validate_address, validate_labels, validate_metadata, validate_uuid

router = APIRouter()


async def _auto_register_label_keys(labels: dict[str, str], db: AsyncSession) -> None:
    """Auto-register any unknown label keys from a device's labels dict."""
    if not labels:
        return
    keys = list(labels.keys())
    existing = (await db.execute(
        select(LabelKey.key).where(LabelKey.key.in_(keys))
    )).scalars().all()
    existing_set = set(existing)
    for key in keys:
        if key not in existing_set:
            db.add(LabelKey(key=key))


class CreateDeviceRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Linux server",
                    "value": {
                        "name": "prod-web-01",
                        "address": "10.0.1.10",
                        "device_category": "host",
                        "labels": {"env": "production", "role": "web"},
                    },
                },
            ]
        }
    }

    name: str = Field(min_length=1, max_length=255, description="Human-readable device name, e.g. 'prod-db-01'")
    address: str = Field(min_length=1, max_length=500, description="IP address, hostname, or URL")
    device_category: str = Field(default="host", min_length=1, max_length=64, description="'host', 'network', 'api', 'database', etc.")
    collector_id: str | None = Field(default=None, description="UUID of the owning collector")
    tenant_id: str | None = Field(default=None, description="UUID of the owning tenant")
    collector_group_id: str | None = Field(default=None, description="UUID of the collector group")
    device_type_id: str | None = Field(default=None, description="UUID of the device type (optional, auto-detected via SNMP if not set)")
    credentials: dict[str, str] = Field(default_factory=dict, description="Per-protocol credential mapping: {credential_type: credential_id}")
    labels: dict[str, str] = Field(default_factory=dict, description="Key-value labels")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")

    @field_validator("address")
    @classmethod
    def check_address(cls, v: str) -> str:
        return validate_address(v)

    @field_validator("labels")
    @classmethod
    def check_labels(cls, v: dict[str, str]) -> dict[str, str]:
        return validate_labels(v)

    @field_validator("metadata")
    @classmethod
    def check_metadata(cls, v: dict) -> dict:
        return validate_metadata(v)

    @field_validator("collector_id", "tenant_id", "collector_group_id", "device_type_id")
    @classmethod
    def check_uuids(cls, v: str | None, info) -> str | None:
        if v is not None:
            validate_uuid(v, info.field_name)
        return v


class UpdateDeviceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    device_category: str | None = Field(default=None, min_length=1, max_length=64)
    collector_id: str | None = None
    tenant_id: str | None = None
    collector_group_id: str | None = None
    device_type_id: str | None = None
    credentials: dict[str, str] | None = None
    labels: dict[str, str] | None = None
    metadata: dict | None = None
    retention_overrides: dict[str, str] | None = None

    @field_validator("address")
    @classmethod
    def check_address(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_address(v)
        return v

    @field_validator("labels")
    @classmethod
    def check_labels(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is not None:
            return validate_labels(v)
        return v

    @field_validator("metadata")
    @classmethod
    def check_metadata(cls, v: dict | None) -> dict | None:
        if v is not None:
            return validate_metadata(v)
        return v

    @field_validator("collector_id", "tenant_id", "collector_group_id", "device_type_id")
    @classmethod
    def check_uuids(cls, v: str | None, info) -> str | None:
        if v is not None and v != "":
            validate_uuid(v, info.field_name)
        return v


def _format_device(d: Device, resolved_credentials: dict | None = None) -> dict:
    dt = d.device_type if hasattr(d, "device_type") else None
    return {
        "id": str(d.id),
        "name": d.name,
        "address": d.address,
        "device_category": d.device_category,
        "device_type_id": str(d.device_type_id) if d.device_type_id else None,
        "device_type_name": dt.name if dt else None,
        "device_type_vendor": dt.vendor if dt else None,
        "device_type_model": dt.model if dt else None,
        "device_type_os_family": dt.os_family if dt else None,
        "collector_id": str(d.collector_id) if d.collector_id else None,
        "tenant_id": str(d.tenant_id) if d.tenant_id else None,
        "tenant_name": d.tenant.name if d.tenant else None,
        "collector_group_id": str(d.collector_group_id) if d.collector_group_id else None,
        "collector_group_name": d.collector_group.name if d.collector_group else None,
        "is_enabled": d.is_enabled,
        "credentials": resolved_credentials if resolved_credentials is not None else {},
        "labels": d.labels,
        "metadata": d.metadata_,
        "retention_overrides": d.retention_overrides or {},
        "interface_rules": d.interface_rules,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


async def _resolve_device_credentials(device: Device, db) -> dict:
    """Resolve device credentials JSONB to {type: {id, name, credential_type}} for API response."""
    from monctl_central.storage.models import Credential
    cred_map = device.credentials or {}
    if not cred_map:
        return {}
    cred_ids = []
    for v in cred_map.values():
        if v:
            try:
                cred_ids.append(uuid.UUID(v))
            except ValueError:
                pass
    if not cred_ids:
        return {}
    rows = (await db.execute(
        select(Credential.id, Credential.name, Credential.credential_type)
        .where(Credential.id.in_(cred_ids))
    )).all()
    name_map = {str(r.id): {"id": str(r.id), "name": r.name, "credential_type": r.credential_type} for r in rows}
    result = {}
    for ctype, cid in cred_map.items():
        if cid in name_map:
            result[ctype] = name_map[cid]
    return result


@router.get("")
async def list_devices(
    collector_id: Optional[str] = Query(default=None, description="Filter by collector UUID"),
    device_category: Optional[str] = Query(default=None, description="Filter by device category"),
    device_type_name: Optional[str] = Query(default=None, description="Filter by device type name"),
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
    auth: dict = Depends(require_permission("device", "view")),
):
    """List devices with filtering, sorting, and pagination."""
    # Base query with eager loads
    stmt = select(Device).options(
        selectinload(Device.tenant),
        selectinload(Device.collector_group),
        selectinload(Device.device_type),
    )

    # Apply filters
    if collector_id:
        stmt = stmt.where(Device.collector_id == uuid.UUID(collector_id))
    if device_category:
        stmt = stmt.where(Device.device_category.ilike(f"%{device_category}%"))
    if device_type_name:
        stmt = stmt.outerjoin(DeviceType, Device.device_type_id == DeviceType.id)
        stmt = stmt.where(DeviceType.name.ilike(f"%{device_type_name}%"))
    if name:
        stmt = stmt.where(Device.name.ilike(f"%{name}%"))
    if address:
        stmt = stmt.where(Device.address.ilike(f"%{address}%"))
    if tenant_name:
        stmt = stmt.outerjoin(Tenant, Device.tenant_id == Tenant.id)
        stmt = stmt.where(Tenant.name.ilike(f"%{tenant_name}%"))
    if collector_group_name:
        if not tenant_name:  # avoid double outerjoin issues
            stmt = stmt.outerjoin(CollectorGroup, Device.collector_group_id == CollectorGroup.id)
        else:
            stmt = stmt.outerjoin(CollectorGroup, Device.collector_group_id == CollectorGroup.id)
        stmt = stmt.where(CollectorGroup.name.ilike(f"%{collector_group_name}%"))
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
        "device_category": Device.device_category,
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
    elif sort_by == "device_type_name" and not device_type_name:
        stmt = stmt.outerjoin(DeviceType, Device.device_type_id == DeviceType.id)
        sort_column = DeviceType.name
    elif sort_by == "device_type_name":
        sort_column = DeviceType.name

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
    auth: dict = Depends(require_permission("device", "create")),
):
    """Create a new device."""
    device = Device(
        name=request.name,
        address=request.address,
        device_category=request.device_category,
        collector_id=uuid.UUID(request.collector_id) if request.collector_id else None,
        tenant_id=uuid.UUID(request.tenant_id) if request.tenant_id else None,
        collector_group_id=uuid.UUID(request.collector_group_id) if request.collector_group_id else None,
        device_type_id=uuid.UUID(request.device_type_id) if request.device_type_id else None,
        credentials=request.credentials,
        labels=request.labels,
        metadata_=request.metadata,
    )
    db.add(device)
    await _auto_register_label_keys(request.labels, db)
    await db.flush()
    await db.refresh(device, ["tenant", "collector_group", "device_type"])

    # Auto-discover if device has an SNMP credential and a collector group
    discovery_queued = False
    has_snmp = False
    if device.credentials:
        has_snmp = any("snmp" in k.lower() for k in device.credentials)
    if has_snmp and device.collector_group_id:
        try:
            from monctl_central.cache import set_discovery_flag
            await set_discovery_flag(str(device.id))
            discovery_queued = True
        except Exception:
            pass

    resolved_creds = await _resolve_device_credentials(device, db)
    data = _format_device(device, resolved_creds)
    if discovery_queued:
        data["discovery_queued"] = True
    return {
        "status": "success",
        "data": data,
    }


class DeviceBulkPatchRequest(BaseModel):
    device_ids: list[uuid.UUID]
    is_enabled: bool | None = None
    collector_group_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None

    model_config = ConfigDict(extra="forbid")


class BulkImportDevicesRequest(BaseModel):
    addresses: list[str] = Field(min_length=1, max_length=500)
    tenant_id: str | None = None
    collector_group_id: str | None = None
    credentials: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    device_category: str = Field(default="host", max_length=64)

    @field_validator("addresses")
    @classmethod
    def check_addresses(cls, v: list[str]) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        validated: list[str] = []
        for raw in v:
            addr = raw.strip()
            if not addr or addr in seen:
                continue
            seen.add(addr)
            try:
                validated.append(validate_address(addr))
            except ValueError as e:
                errors.append(str(e))
        if errors:
            raise ValueError(errors)
        return validated

    @field_validator("labels")
    @classmethod
    def check_labels(cls, v: dict[str, str]) -> dict[str, str]:
        return validate_labels(v)


@router.post("/bulk-patch")
async def bulk_patch_devices(
    body: DeviceBulkPatchRequest,
    auth: dict = Depends(require_permission("device", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk patch devices: enable/disable, move to collector group, move to tenant."""
    if not body.device_ids:
        raise HTTPException(status_code=400, detail="device_ids must not be empty")

    if body.collector_group_id is not None:
        grp = await db.get(CollectorGroup, body.collector_group_id)
        if grp is None:
            raise HTTPException(status_code=404, detail="Collector group not found")

    if body.tenant_id is not None:
        tenant = await db.get(Tenant, body.tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")

    # Fetch visible devices (tenant-scoped)
    stmt = select(Device.id).where(Device.id.in_(body.device_ids))
    stmt = apply_tenant_filter(stmt, auth, Device.tenant_id)
    result = await db.execute(stmt)
    visible_ids = {row[0] for row in result.all()}
    skipped = len(body.device_ids) - len(visible_ids)

    # Build update values
    updates: dict = {}
    if body.is_enabled is not None:
        updates["is_enabled"] = body.is_enabled
    if body.collector_group_id is not None:
        updates["collector_group_id"] = body.collector_group_id
    if body.tenant_id is not None:
        updates["tenant_id"] = body.tenant_id

    if updates and visible_ids:
        updates["updated_at"] = sa.func.now()
        await db.execute(
            update(Device).where(Device.id.in_(visible_ids)).values(**updates)
        )

        # When moving to a collector group, migrate assignments and bump collectors
        if body.collector_group_id is not None:
            from monctl_central.storage.models import AppAssignment
            await db.execute(
                update(AppAssignment)
                .where(
                    AppAssignment.device_id.in_(visible_ids),
                    AppAssignment.collector_id.is_not(None),
                )
                .values(collector_id=None)
            )
            await db.execute(
                update(Collector)
                .where(Collector.group_id == body.collector_group_id)
                .values(config_version=Collector.config_version + 1, updated_at=utc_now())
            )

        await db.commit()

    return {
        "status": "success",
        "data": {"updated": len(visible_ids), "skipped": skipped},
    }


@router.post("/bulk-import", status_code=status.HTTP_201_CREATED)
async def bulk_import_devices(
    request: BulkImportDevicesRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "create")),
):
    """Import multiple devices from a list of IP addresses.

    Devices are created immediately with the IP as their initial name. If an
    SNMP credential is provided and a collector group is set, SNMP discovery
    is queued for each device. Discovery will auto-rename the device to sysName
    once it completes (if the name still equals the address).
    """
    tenant_id_uuid = uuid.UUID(request.tenant_id) if request.tenant_id else None
    cgroup_id_uuid = uuid.UUID(request.collector_group_id) if request.collector_group_id else None

    devices_to_create = [
        Device(
            name=addr,
            address=addr,
            device_category=request.device_category,
            tenant_id=tenant_id_uuid,
            collector_group_id=cgroup_id_uuid,
            credentials=request.credentials,
            labels=request.labels,
            metadata_={},
        )
        for addr in request.addresses
    ]

    db.add_all(devices_to_create)
    await _auto_register_label_keys(request.labels, db)
    await db.flush()

    device_ids = [d.id for d in devices_to_create]
    stmt = (
        select(Device)
        .options(
            selectinload(Device.tenant),
            selectinload(Device.collector_group),
            selectinload(Device.device_type),
        )
        .where(Device.id.in_(device_ids))
    )
    created_devices = (await db.execute(stmt)).scalars().all()

    has_snmp = any("snmp" in k.lower() for k in request.credentials)
    discovery_queued = 0
    if has_snmp and cgroup_id_uuid:
        from monctl_central.cache import set_discovery_flag
        for device in created_devices:
            try:
                await set_discovery_flag(str(device.id))
                discovery_queued += 1
            except Exception:
                pass

    return {
        "status": "success",
        "data": {
            "created": len(created_devices),
            "discovery_queued": discovery_queued,
            "devices": [_format_device(d) for d in created_devices],
        },
    }


@router.get("/{device_id}")
async def get_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Get a device by ID."""
    stmt = (
        select(Device)
        .options(selectinload(Device.tenant), selectinload(Device.collector_group), selectinload(Device.device_type))
        .where(Device.id == uuid.UUID(device_id))
    )
    device = (await db.execute(stmt)).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    resolved_creds = await _resolve_device_credentials(device, db)
    return {"status": "success", "data": _format_device(device, resolved_creds)}


@router.put("/{device_id}")
async def update_device(
    device_id: str,
    request: UpdateDeviceRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "edit")),
):
    """Update a device."""
    stmt = (
        select(Device)
        .options(selectinload(Device.tenant), selectinload(Device.collector_group), selectinload(Device.device_type))
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
    if request.device_category is not None:
        device.device_category = request.device_category
    if request.collector_id is not None:
        device.collector_id = uuid.UUID(request.collector_id) if request.collector_id else None
    if request.tenant_id is not None:
        device.tenant_id = uuid.UUID(request.tenant_id) if request.tenant_id != "" else None

    # Track whether collector_group_id is actually changing
    old_group_id = device.collector_group_id
    group_changed = False
    if request.collector_group_id is not None:
        new_group_id = uuid.UUID(request.collector_group_id) if request.collector_group_id != "" else None
        if new_group_id != old_group_id:
            group_changed = True
        device.collector_group_id = new_group_id

    if request.device_type_id is not None:
        device.device_type_id = uuid.UUID(request.device_type_id) if request.device_type_id != "" else None
    if request.credentials is not None:
        device.credentials = request.credentials
    if request.labels is not None:
        device.labels = request.labels
        await _auto_register_label_keys(request.labels, db)
    if request.metadata is not None:
        device.metadata_ = request.metadata
    if request.retention_overrides is not None:
        _VALID_RETENTION_KEYS = {
            "interface_raw_retention_days", "interface_hourly_retention_days", "interface_daily_retention_days",
            "perf_raw_retention_days", "perf_hourly_retention_days", "perf_daily_retention_days",
        }
        invalid_keys = set(request.retention_overrides.keys()) - _VALID_RETENTION_KEYS
        if invalid_keys:
            raise HTTPException(status_code=422, detail=f"Invalid retention keys: {invalid_keys}")
        for k, v in request.retention_overrides.items():
            try:
                val = int(v)
                if val < 1:
                    raise ValueError()
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail=f"Invalid value for {k}: must be a positive integer")
        device.retention_overrides = request.retention_overrides
    device.updated_at = utc_now()
    await db.flush()

    # When a device is moved to a DIFFERENT collector group, migrate all its
    # existing explicit-collector assignments to group-level (collector_id = NULL)
    # so that the group's collectors pick them up via round-robin.
    # Only do this when the group actually changes — not on unrelated edits (name, etc.).
    if group_changed and device.collector_group_id is not None:
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

    await db.refresh(device, ["tenant", "collector_group", "device_type"])
    resolved_creds = await _resolve_device_credentials(device, db)
    return {"status": "success", "data": _format_device(device, resolved_creds)}


class MonitoringCheckConfig(BaseModel):
    """Configuration for a single monitoring check (availability or latency)."""
    app_name: str | None = Field(default=None, max_length=255)
    config: dict = Field(default_factory=dict)
    interval_seconds: int = Field(default=60, ge=10, le=86400)


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
    auth: dict = Depends(require_permission("device", "view")),
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
    auth: dict = Depends(require_permission("device", "edit")),
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


# ---------------------------------------------------------------------------
# Interface Metadata endpoints
# ---------------------------------------------------------------------------

def _fmt_iface_meta(m: InterfaceMetadata) -> dict:
    return {
        "id": str(m.id),
        "device_id": str(m.device_id),
        "if_name": m.if_name,
        "current_if_index": m.current_if_index,
        "if_descr": m.if_descr,
        "if_alias": m.if_alias,
        "if_speed_mbps": m.if_speed_mbps,
        "polling_enabled": m.polling_enabled,
        "alerting_enabled": m.alerting_enabled,
        "poll_metrics": m.poll_metrics,
        "rules_managed": m.rules_managed,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.get("/{device_id}/interface-metadata")
async def get_interface_metadata(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Get cached interface metadata for a device."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    stmt = select(InterfaceMetadata).where(
        InterfaceMetadata.device_id == uuid.UUID(device_id),
    ).order_by(InterfaceMetadata.current_if_index)
    rows = (await db.execute(stmt)).scalars().all()
    return {"status": "success", "data": [_fmt_iface_meta(m) for m in rows]}


_VALID_POLL_METRICS_PARTS = {"all", "none", "traffic", "errors", "discards", "status"}


def _validate_poll_metrics(value: str) -> bool:
    """Validate poll_metrics: 'all' or comma-separated subset of traffic,errors,discards,status."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return all(p in _VALID_POLL_METRICS_PARTS for p in parts) and len(parts) > 0


class UpdateInterfaceSettingsRequest(BaseModel):
    polling_enabled: Optional[bool] = None
    alerting_enabled: Optional[bool] = None
    poll_metrics: Optional[str] = Field(default=None, max_length=100)


@router.patch("/{device_id}/interface-metadata/{interface_id}")
async def update_interface_settings(
    device_id: str,
    interface_id: str,
    req: UpdateInterfaceSettingsRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "edit")),
):
    """Toggle polling/alerting for a single interface."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    meta = await db.get(InterfaceMetadata, uuid.UUID(interface_id))
    if meta is None or str(meta.device_id) != device_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interface not found")

    if req.polling_enabled is not None:
        meta.polling_enabled = req.polling_enabled
    if req.alerting_enabled is not None:
        meta.alerting_enabled = req.alerting_enabled
    if req.poll_metrics is not None:
        if not _validate_poll_metrics(req.poll_metrics):
            raise HTTPException(status_code=400, detail=f"Invalid poll_metrics: must be 'all' or comma-separated list of {_VALID_POLL_METRICS_PARTS - {'all'}}")
        meta.poll_metrics = req.poll_metrics
    # Manual change → opt out of automatic rule management
    meta.rules_managed = False
    meta.updated_at = utc_now()
    await db.flush()

    # Invalidate Redis cache so ingestion/jobs see the change immediately
    if req.polling_enabled is not None or req.poll_metrics is not None:
        from monctl_central.cache import invalidate_cached_interface
        await invalidate_cached_interface(device_id, meta.if_name)

    return {"status": "success", "data": _fmt_iface_meta(meta)}


class BulkInterfaceSettingsRequest(BaseModel):
    interface_ids: list[str] = Field(min_length=1, max_length=500)
    polling_enabled: Optional[bool] = None
    alerting_enabled: Optional[bool] = None
    poll_metrics: Optional[str] = Field(default=None, max_length=100)


@router.patch("/{device_id}/interface-metadata")
async def bulk_update_interface_settings(
    device_id: str,
    req: BulkInterfaceSettingsRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "edit")),
):
    """Bulk toggle polling/alerting for multiple interfaces."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    updated = []
    invalidate_names = []
    for iid in req.interface_ids:
        meta = await db.get(InterfaceMetadata, uuid.UUID(iid))
        if meta and str(meta.device_id) == device_id:
            if req.polling_enabled is not None:
                meta.polling_enabled = req.polling_enabled
                invalidate_names.append(meta.if_name)
            if req.alerting_enabled is not None:
                meta.alerting_enabled = req.alerting_enabled
            if req.poll_metrics is not None:
                if req.poll_metrics not in _VALID_POLL_METRICS:
                    raise HTTPException(status_code=400, detail=f"Invalid poll_metrics: must be one of {_VALID_POLL_METRICS}")
                meta.poll_metrics = req.poll_metrics
                if meta.if_name not in invalidate_names:
                    invalidate_names.append(meta.if_name)
            # Manual change → opt out of automatic rule management
            meta.rules_managed = False
            meta.updated_at = utc_now()
            updated.append(_fmt_iface_meta(meta))
    await db.flush()

    # Invalidate Redis cache for affected interfaces
    if invalidate_names:
        from monctl_central.cache import invalidate_cached_interface
        for name in invalidate_names:
            await invalidate_cached_interface(device_id, name)

    return {"status": "success", "data": updated}


@router.post("/{device_id}/interface-metadata/refresh")
async def refresh_interface_metadata(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "edit")),
):
    """Queue a metadata refresh — the next interface poll will do a full SNMP walk
    instead of targeted GETs, rediscovering all interfaces and updating metadata.
    """
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    from monctl_central.cache import set_interface_refresh_flag
    await set_interface_refresh_flag(device_id)

    # Notify collectors via WebSocket to sync jobs immediately (same pattern as discovery)
    ws_notified = 0
    try:
        from monctl_central.ws.router import manager as ws_manager
        if device.collector_group_id:
            result = await db.execute(
                select(Collector.id).where(
                    Collector.group_id == device.collector_group_id,
                    Collector.status == "APPROVED",
                )
            )
            for cid in result.scalars().all():
                if ws_manager.is_connected_local(cid):
                    try:
                        await ws_manager.send_command(cid, "config_reload", {}, timeout=5)
                        ws_notified += 1
                    except Exception:
                        pass
    except Exception:
        pass

    return {"status": "success", "data": {"message": "Interface metadata refresh queued.", "ws_notified": ws_notified}}


class PollNowRequest(BaseModel):
    assignment_id: str


@router.post("/{device_id}/poll-now")
async def poll_device_now(
    device_id: str,
    body: PollNowRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "edit")),
):
    """Send an adhoc poll_device command to the collector(s) running this assignment."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    from monctl_central.ws.router import manager as ws_manager
    from monctl_central.storage.models import AppAssignment
    ws_notified = 0
    payload = {"assignment_id": body.assignment_id, "device_id": device_id}

    # Collect collector IDs to try
    collector_ids: list[uuid.UUID] = []

    # Pinned assignment → try that specific collector first
    assignment = await db.get(AppAssignment, uuid.UUID(body.assignment_id))
    if assignment and assignment.collector_id:
        collector_ids.append(assignment.collector_id)

    # Group-level → try all approved collectors in the group
    if device.collector_group_id:
        result = await db.execute(
            select(Collector.id).where(
                Collector.group_id == device.collector_group_id,
                Collector.status == "APPROVED",
            )
        )
        for cid in result.scalars().all():
            if cid not in collector_ids:
                collector_ids.append(cid)

    # Try sending to each — skip non-local connections (KeyError)
    for cid in collector_ids:
        try:
            await ws_manager.send_command(cid, "poll_device", payload, timeout=10)
            ws_notified += 1
        except (KeyError, Exception):
            pass

    return {"status": "success", "data": {"ws_notified": ws_notified}}


# ── Interface Rules ─────────────────────────────────────────


@router.get("/{device_id}/interface-rules")
async def get_interface_rules(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Get interface rules for a device."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return {"status": "success", "data": device.interface_rules or []}


class SetInterfaceRulesRequest(BaseModel):
    interface_rules: list[dict]
    apply_now: bool = Field(default=True, description="Immediately evaluate rules against existing interfaces")


@router.put("/{device_id}/interface-rules")
async def set_interface_rules(
    device_id: str,
    req: SetInterfaceRulesRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "edit")),
):
    """Set interface rules on a device (directly, not via template)."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    from monctl_central.templates.interface_rules import validate_interface_rules
    errors = validate_interface_rules(req.interface_rules)
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    device.interface_rules = req.interface_rules
    device.updated_at = utc_now()

    summary = None
    if req.apply_now and req.interface_rules:
        from monctl_central.templates.interface_rules import apply_rules_to_all_interfaces
        summary = await apply_rules_to_all_interfaces(device.id, req.interface_rules, db, force=False)

    return {"status": "success", "data": {"rules": device.interface_rules, "applied": summary}}


class EvaluateRulesRequest(BaseModel):
    force: bool = Field(default=False, description="Re-evaluate even manually-overridden interfaces")


@router.post("/{device_id}/interface-rules/evaluate")
async def evaluate_interface_rules(
    device_id: str,
    req: EvaluateRulesRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Re-evaluate interface rules against all interfaces on a device."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if not device.interface_rules:
        return {"status": "success", "data": {"total": 0, "matched": 0, "changed": 0, "skipped_manual": 0, "unmatched": 0}}

    from monctl_central.templates.interface_rules import apply_rules_to_all_interfaces
    summary = await apply_rules_to_all_interfaces(device.id, device.interface_rules, db, force=req.force)
    return {"status": "success", "data": summary}


@router.post("/{device_id}/interface-rules/preview")
async def preview_interface_rules(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Dry-run: show what rules would match without applying."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if not device.interface_rules:
        return {"status": "success", "data": []}

    from monctl_central.templates.interface_rules import preview_rules
    results = await preview_rules(device.id, device.interface_rules, db)
    return {"status": "success", "data": results}


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_permission("device", "delete")),
):
    """Delete a device."""
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not check_tenant_access(auth, device.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    await db.delete(device)
    ch.delete_devices_data([device_id])


class BulkDeleteRequest(BaseModel):
    device_ids: list[str] = Field(min_length=1, max_length=500)


@router.post("/bulk-delete", status_code=status.HTTP_200_OK)
async def bulk_delete_devices(
    request: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    ch: ClickHouseClient = Depends(get_clickhouse),
    auth: dict = Depends(require_permission("device", "delete")),
):
    """Bulk delete devices."""
    deleted_ids: list[str] = []
    for did in request.device_ids:
        device = await db.get(Device, uuid.UUID(did))
        if device and check_tenant_access(auth, device.tenant_id):
            await db.delete(device)
            deleted_ids.append(did)
    if deleted_ids:
        ch.delete_devices_data(deleted_ids)
    return {"status": "success", "data": {"deleted": len(deleted_ids)}}


# ── Device Thresholds ────────────────────────────────────

@router.get("/{device_id}/thresholds")
async def get_device_thresholds(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "view")),
):
    """Get flat list of threshold variables for this device with override hierarchy."""
    from monctl_central.storage.models import (
        AlertDefinition,
        AppAssignment,
        ThresholdOverride,
        ThresholdVariable,
    )

    device_uuid = uuid.UUID(device_id)

    # Find all assignments for this device
    assignments = (
        await db.execute(
            select(AppAssignment)
            .where(AppAssignment.device_id == device_uuid)
            .options(selectinload(AppAssignment.app))
        )
    ).scalars().all()

    # Collect unique app IDs
    app_ids = list({a.app_id for a in assignments})
    if not app_ids:
        return {"status": "success", "data": []}

    # Load all threshold variables for these apps
    threshold_vars = (
        await db.execute(
            select(ThresholdVariable)
            .where(ThresholdVariable.app_id.in_(app_ids))
            .order_by(ThresholdVariable.name)
        )
    ).scalars().all()
    if not threshold_vars:
        return {"status": "success", "data": []}

    # Load device-level overrides for these variables
    var_ids = [v.id for v in threshold_vars]
    device_overrides: dict[str, ThresholdOverride] = {}
    overrides = (
        await db.execute(
            select(ThresholdOverride)
            .where(
                ThresholdOverride.variable_id.in_(var_ids),
                ThresholdOverride.device_id == device_uuid,
                sa.or_(ThresholdOverride.entity_key.is_(None), ThresholdOverride.entity_key == ""),
            )
        )
    ).scalars().all()
    for ov in overrides:
        device_overrides[str(ov.variable_id)] = ov

    # Load entity-level overrides
    entity_overrides: dict[str, list] = {}
    e_overrides = (
        await db.execute(
            select(ThresholdOverride)
            .where(
                ThresholdOverride.variable_id.in_(var_ids),
                ThresholdOverride.device_id == device_uuid,
                ThresholdOverride.entity_key.is_not(None),
                ThresholdOverride.entity_key != "",
            )
        )
    ).scalars().all()
    for ov in e_overrides:
        key = str(ov.variable_id)
        if key not in entity_overrides:
            entity_overrides[key] = []
        entity_overrides[key].append({
            "override_id": str(ov.id),
            "entity_key": ov.entity_key,
            "entity_labels": {},
            "value": ov.value,
        })

    # Load alert definitions to build used_by mapping
    alert_defs = (
        await db.execute(
            select(AlertDefinition)
            .where(AlertDefinition.app_id.in_(app_ids))
        )
    ).scalars().all()

    # Build app_id -> app_name mapping
    app_name_map: dict[str, str] = {}
    for a in assignments:
        if a.app:
            app_name_map[str(a.app_id)] = a.app.name

    # Build variable usage: which definitions reference each variable
    var_usage: dict[str, list] = {}
    import re as _re
    for var in threshold_vars:
        refs = []
        for d in alert_defs:
            if d.expression and str(d.app_id) == str(var.app_id):
                pattern = _re.compile(rf"(?:>|<|>=|<=|==|!=)\s*{_re.escape(var.name)}\b")
                if pattern.search(d.expression):
                    refs.append({"definition_id": str(d.id), "definition_name": d.name})
        var_usage[str(var.id)] = refs

    # Build flat rows
    results = []
    for var in threshold_vars:
        override = device_overrides.get(str(var.id))
        device_value = override.value if override else None
        effective = (
            device_value if device_value is not None
            else var.app_value if var.app_value is not None
            else var.default_value
        )
        results.append({
            "variable_id": str(var.id),
            "name": var.name,
            "display_name": var.display_name,
            "unit": var.unit,
            "app_name": app_name_map.get(str(var.app_id), ""),
            "expression_default": var.default_value,
            "app_value": var.app_value,
            "device_value": device_value,
            "effective_value": effective,
            "device_override_id": str(override.id) if override else None,
            "entity_overrides": entity_overrides.get(str(var.id), []),
            "used_by_definitions": var_usage.get(str(var.id), []),
        })

    return {"status": "success", "data": results}
