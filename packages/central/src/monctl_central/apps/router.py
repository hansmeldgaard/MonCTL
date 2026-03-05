"""App management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import apply_tenant_filter, get_db, require_auth
from monctl_central.storage.models import App, AppAssignment, AppVersion

router = APIRouter()


class CreateAppRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Script-based app",
                    "value": {
                        "name": "ping_check",
                        "description": "ICMP ping reachability check",
                        "app_type": "script",
                    },
                },
                {
                    "summary": "HTTP check app",
                    "value": {
                        "name": "http_check",
                        "description": "HTTP/HTTPS reachability and response time check",
                        "app_type": "script",
                    },
                },
            ]
        }
    }

    name: str
    description: str | None = None
    app_type: str = Field(description="'script' or 'sdk'")
    config_schema: dict | None = None


class CreateAssignmentRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Ping check — device-linked (address auto-injected)",
                    "description": (
                        "Link a ping_check assignment to a device. "
                        "The device's address is automatically injected as `host` in the app config. "
                        "Schedule: every 60 seconds."
                    ),
                    "value": {
                        "app_id": "<ping_check app UUID>",
                        "app_version_id": "<app version UUID>",
                        "collector_id": "<collector UUID>",
                        "device_id": "<device UUID>",
                        "config": {"count": 3, "timeout": 2},
                        "schedule_type": "interval",
                        "schedule_value": "60",
                    },
                },
                {
                    "summary": "HTTP check — device-linked with credential",
                    "description": (
                        "HTTP check where the device address is used as the URL. "
                        "`$credential:` references are resolved server-side before the config "
                        "is sent to the collector — the collector receives the plaintext value."
                    ),
                    "value": {
                        "app_id": "<http_check app UUID>",
                        "app_version_id": "<app version UUID>",
                        "collector_id": "<collector UUID>",
                        "device_id": "<device UUID>",
                        "config": {
                            "timeout": 10,
                            "expected_status": [200, 201],
                            "api_key": "$credential:my-api-key",
                        },
                        "schedule_type": "interval",
                        "schedule_value": "120",
                    },
                },
                {
                    "summary": "Ping check — inline host (no device)",
                    "description": "Direct assignment without a device record — target is embedded in config.",
                    "value": {
                        "app_id": "<ping_check app UUID>",
                        "app_version_id": "<app version UUID>",
                        "collector_id": "<collector UUID>",
                        "config": {"host": "localhost", "count": 3, "timeout": 2},
                        "schedule_type": "interval",
                        "schedule_value": "30",
                    },
                },
                {
                    "summary": "Cron schedule",
                    "description": "Run every 5 minutes using a cron expression.",
                    "value": {
                        "app_id": "<app UUID>",
                        "app_version_id": "<version UUID>",
                        "collector_id": "<collector UUID>",
                        "device_id": "<device UUID>",
                        "config": {},
                        "schedule_type": "cron",
                        "schedule_value": "*/5 * * * *",
                    },
                },
            ]
        }
    }

    app_id: str
    app_version_id: str
    collector_id: str | None = None
    cluster_id: str | None = None
    device_id: str | None = Field(
        default=None,
        description="Optional device UUID. The device's address is auto-injected as `host` in the app config.",
    )
    config: dict = Field(
        default_factory=dict,
        description=(
            "App-specific config. Values starting with `$credential:<name>` are resolved to "
            "the decrypted secret before the config is sent to the collector."
        ),
    )
    schedule_type: str = Field(description="'interval' (seconds) or 'cron' (cron expression)")
    schedule_value: str = Field(description="Seconds for interval (e.g. '60') or cron expression (e.g. '*/5 * * * *')")
    resource_limits: dict = Field(default_factory=lambda: {"timeout_seconds": 30, "memory_mb": 256})
    role: str | None = Field(default=None, description="Optional role: 'availability' or 'latency'")


@router.get("")
async def list_apps(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all apps."""
    stmt = select(App)
    result = await db.execute(stmt)
    apps = result.scalars().all()
    return {
        "status": "success",
        "data": [
            {
                "id": str(a.id),
                "name": a.name,
                "description": a.description,
                "app_type": a.app_type,
            }
            for a in apps
        ],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_app(
    request: CreateAppRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Register a new monitoring app."""
    app = App(
        name=request.name,
        description=request.description,
        app_type=request.app_type,
        config_schema=request.config_schema,
    )
    db.add(app)
    await db.flush()
    return {
        "status": "success",
        "data": {"id": str(app.id), "name": app.name},
    }


@router.get("/assignments")
async def list_assignments(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
    collector_id: str | None = None,
    device_id: str | None = None,
    app_id_filter: str | None = None,
):
    """List all app assignments with app, device, and schedule details."""
    from monctl_central.storage.models import App, AppVersion, Device

    from monctl_central.storage.models import Device as DeviceModel

    stmt = (
        select(AppAssignment, App, AppVersion)
        .join(App, AppAssignment.app_id == App.id)
        .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
        .outerjoin(DeviceModel, AppAssignment.device_id == DeviceModel.id)
    )
    if collector_id:
        stmt = stmt.where(AppAssignment.collector_id == uuid.UUID(collector_id))
    if device_id:
        stmt = stmt.where(AppAssignment.device_id == uuid.UUID(device_id))
    if app_id_filter:
        stmt = stmt.where(AppAssignment.app_id == uuid.UUID(app_id_filter))
    stmt = apply_tenant_filter(stmt, auth, DeviceModel.tenant_id)

    result = await db.execute(stmt)
    rows = result.all()

    # Load devices for assignments that have a device_id
    device_ids = {row.AppAssignment.device_id for row in rows if row.AppAssignment.device_id}
    devices = {}
    if device_ids:
        dev_result = await db.execute(select(Device).where(Device.id.in_(device_ids)))
        devices = {d.id: d for d in dev_result.scalars().all()}

    return {
        "status": "success",
        "data": [
            {
                "id": str(row.AppAssignment.id),
                "app": {
                    "id": str(row.App.id),
                    "name": row.App.name,
                    "version": row.AppVersion.version,
                },
                "device": (
                    {
                        "id": str(devices[row.AppAssignment.device_id].id),
                        "name": devices[row.AppAssignment.device_id].name,
                        "address": devices[row.AppAssignment.device_id].address,
                        "device_type": devices[row.AppAssignment.device_id].device_type,
                    }
                    if row.AppAssignment.device_id and row.AppAssignment.device_id in devices
                    else None
                ),
                "collector_id": str(row.AppAssignment.collector_id) if row.AppAssignment.collector_id else None,
                "schedule_type": row.AppAssignment.schedule_type,
                "schedule_value": row.AppAssignment.schedule_value,
                "schedule_human": (
                    f"every {row.AppAssignment.schedule_value}s"
                    if row.AppAssignment.schedule_type == "interval"
                    else row.AppAssignment.schedule_value
                ),
                "config": row.AppAssignment.config,
                "enabled": row.AppAssignment.enabled,
                "role": row.AppAssignment.role,
                "created_at": row.AppAssignment.created_at.isoformat() if row.AppAssignment.created_at else None,
            }
            for row in rows
        ],
        "meta": {"count": len(rows)},
    }


@router.get("/{app_id}")
async def get_app(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get app details including all versions (sorted newest first)."""
    from sqlalchemy.orm import selectinload
    stmt = select(App).options(selectinload(App.versions)).where(App.id == uuid.UUID(app_id))
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")
    return {
        "status": "success",
        "data": {
            "id": str(app.id),
            "name": app.name,
            "description": app.description,
            "app_type": app.app_type,
            "config_schema": app.config_schema,
            "versions": [
                {"id": str(v.id), "version": v.version}
                for v in sorted(app.versions, key=lambda v: v.published_at, reverse=True)
            ],
        },
    }


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
async def create_assignment(
    request: CreateAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create an app assignment (assign an app to a collector, cluster, or collector group)."""
    from sqlalchemy import update
    from monctl_central.storage.models import Collector, Device
    from monctl_common.utils import utc_now

    # Determine routing: specific collector, cluster, or group-level (collector_id=None)
    device_group_id: uuid.UUID | None = None
    if not request.collector_id and not request.cluster_id:
        # Group-level assignment: device must belong to a collector group
        if not request.device_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="collector_id or cluster_id is required, or the device must be in a collector group",
            )
        device = await db.get(Device, uuid.UUID(request.device_id))
        if not device or not device.collector_group_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="collector_id or cluster_id is required, or the device must be assigned to a collector group",
            )
        device_group_id = device.collector_group_id

    assignment = AppAssignment(
        app_id=uuid.UUID(request.app_id),
        app_version_id=uuid.UUID(request.app_version_id),
        collector_id=uuid.UUID(request.collector_id) if request.collector_id else None,
        cluster_id=uuid.UUID(request.cluster_id) if request.cluster_id else None,
        device_id=uuid.UUID(request.device_id) if request.device_id else None,
        config=request.config,
        schedule_type=request.schedule_type,
        schedule_value=request.schedule_value,
        resource_limits=request.resource_limits,
        role=request.role,
    )
    db.add(assignment)
    await db.flush()

    # Bump config_version so collectors re-fetch on next heartbeat
    if request.collector_id:
        # Direct assignment — only bump the specific collector
        await db.execute(
            update(Collector)
            .where(Collector.id == uuid.UUID(request.collector_id))
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )
    elif device_group_id:
        # Group-level assignment — bump all collectors in the group
        await db.execute(
            update(Collector)
            .where(Collector.group_id == device_group_id)
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )

    return {
        "status": "success",
        "data": {"id": str(assignment.id)},
    }


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment(
    assignment_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete an app assignment. Bumps collector config_version so it re-fetches."""
    from sqlalchemy import update
    from monctl_central.storage.models import Collector, Device
    from monctl_common.utils import utc_now

    assignment = await db.get(AppAssignment, uuid.UUID(assignment_id))
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    collector_id = assignment.collector_id
    device_id = assignment.device_id
    await db.delete(assignment)
    await db.flush()

    # Bump config_version so the relevant collector(s) re-fetch on next heartbeat
    if collector_id:
        await db.execute(
            update(Collector)
            .where(Collector.id == collector_id)
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )
    elif device_id:
        # Group-level assignment — bump all collectors in the device's group
        device = await db.get(Device, device_id)
        if device and device.collector_group_id:
            await db.execute(
                update(Collector)
                .where(Collector.group_id == device.collector_group_id)
                .values(config_version=Collector.config_version + 1, updated_at=utc_now())
            )
