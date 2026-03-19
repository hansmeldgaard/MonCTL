"""App management endpoints."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import apply_tenant_filter, get_db, require_auth
from monctl_central.storage.models import (
    App,
    AppAssignment,
    AppConnectorBinding,
    AppVersion,
    AssignmentConnectorBinding,
    Connector,
    ConnectorVersion,
)

router = APIRouter()


VALID_TARGET_TABLES = {"availability_latency", "performance", "interface", "config"}


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
                        "target_table": "availability_latency",
                    },
                },
                {
                    "summary": "HTTP check app",
                    "value": {
                        "name": "http_check",
                        "description": "HTTP/HTTPS reachability and response time check",
                        "app_type": "script",
                        "target_table": "availability_latency",
                    },
                },
            ]
        }
    }

    name: str
    description: str | None = None
    app_type: str = Field(description="'script' or 'sdk'")
    config_schema: dict | None = None
    target_table: str = Field(default="availability_latency", description="ClickHouse target table")


class ConnectorBindingInput(BaseModel):
    connector_id: str
    connector_version_id: str | None = None
    credential_id: str | None = None
    alias: str
    use_latest: bool = False
    settings: dict = Field(default_factory=dict)


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
    use_latest: bool = Field(default=False, description="Follow latest app version dynamically")
    connector_bindings: list[ConnectorBindingInput] = Field(
        default_factory=list,
        description="Optional connector bindings to attach to this assignment",
    )


@router.get("")
async def list_apps(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all apps with connector bindings."""
    from sqlalchemy.orm import selectinload
    from monctl_central.storage.models import AppConnectorBinding

    stmt = select(App).options(selectinload(App.connector_bindings))
    result = await db.execute(stmt)
    apps = result.scalars().all()

    # Batch-fetch connector names
    all_connector_ids: set[uuid.UUID] = set()
    for a in apps:
        for b in a.connector_bindings:
            all_connector_ids.add(b.connector_id)
    connector_names: dict[uuid.UUID, str] = {}
    if all_connector_ids:
        cn_rows = (await db.execute(
            select(Connector.id, Connector.name).where(Connector.id.in_(all_connector_ids))
        )).all()
        connector_names = {r.id: r.name for r in cn_rows}

    return {
        "status": "success",
        "data": [
            {
                "id": str(a.id),
                "name": a.name,
                "description": a.description,
                "app_type": a.app_type,
                "target_table": a.target_table,
                "connector_bindings": [
                    {
                        "alias": b.alias,
                        "connector_id": str(b.connector_id),
                        "connector_name": connector_names.get(b.connector_id, ""),
                    }
                    for b in a.connector_bindings
                ],
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
    if request.target_table not in VALID_TARGET_TABLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target_table. Must be one of: {', '.join(sorted(VALID_TARGET_TABLES))}",
        )
    app = App(
        name=request.name,
        description=request.description,
        app_type=request.app_type,
        config_schema=request.config_schema,
        target_table=request.target_table,
    )
    db.add(app)
    await db.flush()
    return {
        "status": "success",
        "data": {"id": str(app.id), "name": app.name},
    }


class UpdateAppRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    app_type: str | None = None
    config_schema: dict | None = None
    target_table: str | None = None


class CreateVersionRequest(BaseModel):
    version: str
    source_code: str
    requirements: list[str] = Field(default_factory=list)
    entry_class: str | None = None
    set_latest: bool = False
    display_template: dict | None = None


# --- Assignment routes must be registered BEFORE /{app_id} to avoid path conflict ---

@router.get("/assignments")
async def list_assignments(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
    collector_id: str | None = None,
    device_id: str | None = None,
    app_id_filter: str | None = None,
):
    """List all app assignments with app, device, and schedule details."""
    from sqlalchemy.orm import selectinload
    from monctl_central.storage.models import App, AppVersion, Device

    from monctl_central.storage.models import Device as DeviceModel

    stmt = (
        select(AppAssignment, App, AppVersion)
        .join(App, AppAssignment.app_id == App.id)
        .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
        .outerjoin(DeviceModel, AppAssignment.device_id == DeviceModel.id)
        .options(selectinload(AppAssignment.connector_bindings))
        .options(selectinload(App.connector_bindings))
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

    # ── Resolve credential names for display ──────────────────────────
    from monctl_central.storage.models import Credential, AssignmentCredentialOverride

    all_cred_ids: set[uuid.UUID] = set()
    for row in rows:
        a = row.AppAssignment
        if a.credential_id:
            all_cred_ids.add(a.credential_id)
        if a.device_id and a.device_id in devices:
            dev = devices[a.device_id]
            if dev.default_credential_id:
                all_cred_ids.add(dev.default_credential_id)

    # Load credential overrides for all assignments
    assignment_ids = [row.AppAssignment.id for row in rows]
    overrides_map: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    if assignment_ids:
        override_stmt = select(AssignmentCredentialOverride).where(
            AssignmentCredentialOverride.assignment_id.in_(assignment_ids)
        )
        override_result = await db.execute(override_stmt)
        for ov in override_result.scalars().all():
            overrides_map.setdefault(ov.assignment_id, {})[ov.alias] = ov.credential_id
            all_cred_ids.add(ov.credential_id)

    # Fetch all credential names in one query
    cred_name_map: dict[uuid.UUID, str] = {}
    if all_cred_ids:
        cred_stmt = select(Credential.id, Credential.name).where(Credential.id.in_(all_cred_ids))
        cred_rows = (await db.execute(cred_stmt)).all()
        cred_name_map = {r.id: r.name for r in cred_rows}

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
                "app_version_id": str(row.AppAssignment.app_version_id),
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
                "use_latest": row.AppAssignment.use_latest,
                "role": row.AppAssignment.role,
                "credential_id": str(row.AppAssignment.credential_id) if row.AppAssignment.credential_id else None,
                "credential_name": cred_name_map.get(row.AppAssignment.credential_id) if row.AppAssignment.credential_id else None,
                "credential_overrides": [
                    {
                        "alias": alias,
                        "credential_id": str(cred_id),
                        "credential_name": cred_name_map.get(cred_id, ""),
                    }
                    for alias, cred_id in overrides_map.get(row.AppAssignment.id, {}).items()
                ],
                "device_default_credential_name": (
                    cred_name_map.get(devices[row.AppAssignment.device_id].default_credential_id)
                    if (
                        row.AppAssignment.device_id
                        and row.AppAssignment.device_id in devices
                        and devices[row.AppAssignment.device_id].default_credential_id
                        and row.App.connector_bindings
                    )
                    else None
                ),
                "connector_bindings": [
                    {
                        "id": str(b.id),
                        "connector_id": str(b.connector_id),
                        "connector_version_id": str(b.connector_version_id),
                        "credential_id": str(b.credential_id) if b.credential_id else None,
                        "alias": b.alias,
                        "use_latest": b.use_latest,
                        "settings": b.settings,
                    }
                    for b in row.AppAssignment.connector_bindings
                ],
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
    stmt = (
        select(App)
        .options(selectinload(App.versions), selectinload(App.connector_bindings))
        .where(App.id == uuid.UUID(app_id))
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")

    # Load connector names for display
    connector_ids = {b.connector_id for b in app.connector_bindings}
    connector_names: dict[uuid.UUID, str] = {}
    if connector_ids:
        from monctl_central.storage.models import Connector as ConnectorModel
        cn_rows = (await db.execute(
            select(ConnectorModel.id, ConnectorModel.name).where(ConnectorModel.id.in_(connector_ids))
        )).all()
        connector_names = {r.id: r.name for r in cn_rows}

    return {
        "status": "success",
        "data": {
            "id": str(app.id),
            "name": app.name,
            "description": app.description,
            "app_type": app.app_type,
            "target_table": app.target_table,
            "config_schema": app.config_schema,
            "versions": [
                {"id": str(v.id), "version": v.version, "is_latest": v.is_latest}
                for v in sorted(app.versions, key=lambda v: v.published_at, reverse=True)
            ],
            "connector_bindings": [
                {
                    "alias": b.alias,
                    "connector_id": str(b.connector_id),
                    "connector_name": connector_names.get(b.connector_id, ""),
                    "use_latest": b.use_latest,
                    "connector_version_id": str(b.connector_version_id) if b.connector_version_id else None,
                    "settings": b.settings or {},
                }
                for b in app.connector_bindings
            ],
        },
    }


# ── App connector binding CRUD ─────────────────────────────────────────────


class AppConnectorBindingInput(BaseModel):
    alias: str
    connector_id: str
    use_latest: bool = True
    connector_version_id: str | None = None
    settings: dict = Field(default_factory=dict)


@router.get("/{app_id}/connectors")
async def list_app_connectors(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List connector bindings for an app."""
    stmt = select(AppConnectorBinding).where(AppConnectorBinding.app_id == uuid.UUID(app_id))
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "status": "success",
        "data": [
            {
                "alias": b.alias,
                "connector_id": str(b.connector_id),
                "use_latest": b.use_latest,
                "connector_version_id": str(b.connector_version_id) if b.connector_version_id else None,
                "settings": b.settings or {},
            }
            for b in rows
        ],
    }


@router.post("/{app_id}/connectors", status_code=status.HTTP_201_CREATED)
async def add_app_connector(
    app_id: str,
    request: AppConnectorBindingInput,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Add a connector binding to an app."""
    app = await db.get(App, uuid.UUID(app_id))
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    # Check for duplicate alias
    existing = (await db.execute(
        select(AppConnectorBinding).where(
            AppConnectorBinding.app_id == app.id,
            AppConnectorBinding.alias == request.alias,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Alias '{request.alias}' already exists on this app")

    # Resolve version_id if use_latest
    version_id = None
    if request.connector_version_id:
        version_id = uuid.UUID(request.connector_version_id)
    elif not request.use_latest:
        latest = (await db.execute(
            select(ConnectorVersion).where(
                ConnectorVersion.connector_id == uuid.UUID(request.connector_id),
                ConnectorVersion.is_latest == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if latest:
            version_id = latest.id

    binding = AppConnectorBinding(
        app_id=app.id,
        connector_id=uuid.UUID(request.connector_id),
        alias=request.alias,
        use_latest=request.use_latest,
        connector_version_id=version_id,
        settings=request.settings,
    )
    db.add(binding)
    await db.flush()
    return {"status": "success", "data": {"alias": binding.alias}}


@router.put("/{app_id}/connectors/{alias}")
async def update_app_connector(
    app_id: str,
    alias: str,
    request: AppConnectorBindingInput,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a connector binding on an app."""
    binding = (await db.execute(
        select(AppConnectorBinding).where(
            AppConnectorBinding.app_id == uuid.UUID(app_id),
            AppConnectorBinding.alias == alias,
        )
    )).scalar_one_or_none()
    if not binding:
        raise HTTPException(status_code=404, detail="Connector binding not found")

    binding.connector_id = uuid.UUID(request.connector_id)
    binding.use_latest = request.use_latest
    binding.connector_version_id = uuid.UUID(request.connector_version_id) if request.connector_version_id else None
    binding.settings = request.settings
    return {"status": "success", "data": {"alias": binding.alias}}


@router.delete("/{app_id}/connectors/{alias}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_connector(
    app_id: str,
    alias: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Remove a connector binding from an app."""
    binding = (await db.execute(
        select(AppConnectorBinding).where(
            AppConnectorBinding.app_id == uuid.UUID(app_id),
            AppConnectorBinding.alias == alias,
        )
    )).scalar_one_or_none()
    if not binding:
        raise HTTPException(status_code=404, detail="Connector binding not found")
    await db.delete(binding)


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
        use_latest=request.use_latest,
    )
    db.add(assignment)
    await db.flush()

    # Auto-create alert instances for this new assignment
    from monctl_central.alerting.instance_sync import sync_instances_for_assignment
    await sync_instances_for_assignment(db, assignment)
    await db.flush()

    # Create connector bindings if provided
    for binding in request.connector_bindings:
        version_id = binding.connector_version_id
        if not version_id:
            # Resolve latest version for this connector
            latest = (await db.execute(
                select(ConnectorVersion).where(
                    ConnectorVersion.connector_id == uuid.UUID(binding.connector_id),
                    ConnectorVersion.is_latest == True,  # noqa: E712
                )
            )).scalar_one_or_none()
            if not latest:
                raise HTTPException(status_code=400, detail=f"No latest version for connector {binding.connector_id}")
            version_id = str(latest.id)
        acb = AssignmentConnectorBinding(
            assignment_id=assignment.id,
            connector_id=uuid.UUID(binding.connector_id),
            connector_version_id=uuid.UUID(version_id),
            credential_id=uuid.UUID(binding.credential_id) if binding.credential_id else None,
            alias=binding.alias,
            use_latest=binding.use_latest,
            settings=binding.settings,
        )
        db.add(acb)
    if request.connector_bindings:
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


class UpdateAssignmentRequest(BaseModel):
    schedule_type: str | None = None
    schedule_value: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    app_version_id: str | None = None
    use_latest: bool | None = None
    connector_bindings: list[ConnectorBindingInput] | None = None


@router.put("/assignments/{assignment_id}")
async def update_assignment(
    assignment_id: str,
    request: UpdateAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update an app assignment. Bumps collector config_version so it re-fetches."""
    from sqlalchemy import update
    from monctl_central.storage.models import Collector, Device
    from monctl_common.utils import utc_now

    assignment = await db.get(AppAssignment, uuid.UUID(assignment_id))
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    if request.schedule_type is not None:
        assignment.schedule_type = request.schedule_type
    if request.schedule_value is not None:
        assignment.schedule_value = request.schedule_value
    if request.config is not None:
        assignment.config = request.config
    if request.enabled is not None:
        assignment.enabled = request.enabled
    if request.app_version_id is not None:
        assignment.app_version_id = uuid.UUID(request.app_version_id)
    if request.use_latest is not None:
        assignment.use_latest = request.use_latest
    assignment.updated_at = utc_now()

    # Replace connector bindings if provided
    if request.connector_bindings is not None:
        from sqlalchemy import delete as sa_delete
        await db.execute(
            sa_delete(AssignmentConnectorBinding).where(
                AssignmentConnectorBinding.assignment_id == assignment.id
            )
        )
        for binding in request.connector_bindings:
            version_id = binding.connector_version_id
            if not version_id:
                latest = (await db.execute(
                    select(ConnectorVersion).where(
                        ConnectorVersion.connector_id == uuid.UUID(binding.connector_id),
                        ConnectorVersion.is_latest == True,  # noqa: E712
                    )
                )).scalar_one_or_none()
                if not latest:
                    raise HTTPException(status_code=400, detail=f"No latest version for connector {binding.connector_id}")
                version_id = str(latest.id)
            acb = AssignmentConnectorBinding(
                assignment_id=assignment.id,
                connector_id=uuid.UUID(binding.connector_id),
                connector_version_id=uuid.UUID(version_id),
                credential_id=uuid.UUID(binding.credential_id) if binding.credential_id else None,
                alias=binding.alias,
                use_latest=binding.use_latest,
                settings=binding.settings,
            )
            db.add(acb)

    await db.flush()

    # Bump config_version so the relevant collector(s) re-fetch on next heartbeat
    if assignment.collector_id:
        await db.execute(
            update(Collector)
            .where(Collector.id == assignment.collector_id)
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )
    elif assignment.device_id:
        device = await db.get(Device, assignment.device_id)
        if device and device.collector_group_id:
            await db.execute(
                update(Collector)
                .where(Collector.group_id == device.collector_group_id)
                .values(config_version=Collector.config_version + 1, updated_at=utc_now())
            )

    return {
        "status": "success",
        "data": {"id": str(assignment.id)},
    }


# --- Parameterized /{app_id} routes AFTER literal routes to avoid path conflicts ---


@router.put("/{app_id}")
async def update_app(
    app_id: str,
    request: UpdateAppRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update app metadata."""
    app = await db.get(App, uuid.UUID(app_id))
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")
    if request.name is not None:
        app.name = request.name
    if request.description is not None:
        app.description = request.description
    if request.app_type is not None:
        app.app_type = request.app_type
    if request.config_schema is not None:
        app.config_schema = request.config_schema
    if request.target_table is not None:
        if request.target_table not in VALID_TARGET_TABLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target_table. Must be one of: {', '.join(sorted(VALID_TARGET_TABLES))}",
            )
        app.target_table = request.target_table
    await db.flush()
    return {
        "status": "success",
        "data": {"id": str(app.id), "name": app.name},
    }


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete an app. Rejected if any assignments reference it."""
    app = await db.get(App, uuid.UUID(app_id))
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")

    # Check if app is in use
    from sqlalchemy import func
    count = (await db.execute(
        select(func.count()).select_from(AppAssignment).where(AppAssignment.app_id == app.id)
    )).scalar_one()
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"App is in use by {count} assignment(s). Remove them first.",
        )

    await db.delete(app)
    await db.flush()


@router.put("/{app_id}/versions/{version_id}/set-latest")
async def set_latest_version(
    app_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Mark a version as the latest. Clears is_latest on all other versions and bumps collector config."""
    from sqlalchemy import update
    from sqlalchemy.orm import selectinload as _sil
    from monctl_central.storage.models import Collector
    from monctl_common.utils import utc_now

    stmt = select(App).options(_sil(App.versions)).where(App.id == uuid.UUID(app_id))
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")

    target = None
    for v in app.versions:
        if str(v.id) == version_id:
            target = v
        v.is_latest = False

    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    target.is_latest = True

    # Bump config_version on all collectors that have use_latest assignments for this app
    collector_ids_stmt = (
        select(AppAssignment.collector_id)
        .where(AppAssignment.app_id == uuid.UUID(app_id))
        .where(AppAssignment.use_latest == True)  # noqa: E712
        .where(AppAssignment.collector_id.isnot(None))
    )
    coll_rows = await db.execute(collector_ids_stmt)
    coll_ids = {row[0] for row in coll_rows.all() if row[0]}
    if coll_ids:
        await db.execute(
            update(Collector)
            .where(Collector.id.in_(coll_ids))
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )

    await db.flush()
    return {
        "status": "success",
        "data": {"id": str(target.id), "version": target.version, "is_latest": True},
    }


@router.get("/{app_id}/versions/{version_id}")
async def get_app_version(
    app_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Get version details including source code."""
    stmt = select(AppVersion).where(
        AppVersion.id == uuid.UUID(version_id),
        AppVersion.app_id == uuid.UUID(app_id),
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return {
        "status": "success",
        "data": {
            "id": str(version.id),
            "version": version.version,
            "source_code": version.source_code,
            "requirements": version.requirements or [],
            "entry_class": version.entry_class,
            "checksum": version.checksum_sha256,
            "is_latest": version.is_latest,
            "published_at": version.published_at.isoformat() if version.published_at else None,
            "display_template": version.display_template,
        },
    }


class UpdateVersionRequest(BaseModel):
    source_code: str | None = None
    requirements: list[str] | None = None
    entry_class: str | None = None
    display_template: dict | None = None


@router.put("/{app_id}/versions/{version_id}")
async def update_app_version(
    app_id: str,
    version_id: str,
    request: UpdateVersionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update an app version's source code, requirements, or entry class."""
    import hashlib

    stmt = select(AppVersion).where(
        AppVersion.id == uuid.UUID(version_id),
        AppVersion.app_id == uuid.UUID(app_id),
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    if request.source_code is not None:
        version.source_code = request.source_code
        version.checksum_sha256 = hashlib.sha256(request.source_code.encode()).hexdigest()
    if request.requirements is not None:
        version.requirements = request.requirements
    if request.entry_class is not None:
        version.entry_class = request.entry_class
    if request.display_template is not None:
        version.display_template = request.display_template

    await db.flush()
    return {
        "status": "success",
        "data": {
            "id": str(version.id),
            "version": version.version,
            "checksum": version.checksum_sha256,
            "is_latest": version.is_latest,
        },
    }


@router.delete("/{app_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_version(
    app_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete an app version. Rejected if any assignments reference it."""
    from sqlalchemy import func

    stmt = select(AppVersion).where(
        AppVersion.id == uuid.UUID(version_id),
        AppVersion.app_id == uuid.UUID(app_id),
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    # Check if version is in use
    count = (await db.execute(
        select(func.count()).select_from(AppAssignment).where(AppAssignment.app_version_id == version.id)
    )).scalar_one()
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version is in use by {count} assignment(s). Remove them first.",
        )

    await db.delete(version)
    await db.flush()


@router.post("/{app_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_app_version(
    app_id: str,
    request: CreateVersionRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Upload a new version of an app."""
    import hashlib
    from sqlalchemy.orm import selectinload as _sil

    stmt = select(App).options(_sil(App.versions)).where(App.id == uuid.UUID(app_id))
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")

    # First version is automatically latest
    is_first = len(app.versions) == 0
    should_be_latest = request.set_latest or is_first

    checksum = hashlib.sha256(request.source_code.encode()).hexdigest()
    version = AppVersion(
        app_id=app.id,
        version=request.version,
        source_code=request.source_code,
        requirements=request.requirements,
        entry_class=request.entry_class,
        checksum_sha256=checksum,
        is_latest=should_be_latest,
        display_template=request.display_template,
    )
    db.add(version)

    # If setting as latest, clear is_latest on all other versions
    if should_be_latest:
        for v in app.versions:
            v.is_latest = False

    await db.flush()
    return {
        "status": "success",
        "data": {"id": str(version.id), "version": version.version, "checksum": checksum, "is_latest": version.is_latest},
    }


@router.get("/{app_id}/config-keys")
async def get_app_config_keys(
    app_id: str,
    version_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return detected config_key values for a config app."""
    app = await db.get(App, uuid.UUID(app_id))
    if app is None:
        raise HTTPException(status_code=404, detail="App not found")
    if app.target_table != "config":
        return {"status": "success", "data": {"source_code_keys": [], "clickhouse_keys": [], "all_keys": []}}

    # 1. Parse source code
    source_code_keys: list[str] = []
    if version_id:
        stmt = select(AppVersion).where(
            AppVersion.id == uuid.UUID(version_id),
            AppVersion.app_id == app.id,
        )
    else:
        stmt = (
            select(AppVersion)
            .where(AppVersion.app_id == app.id, AppVersion.is_latest == True)  # noqa: E712
            .limit(1)
        )
    version = (await db.execute(stmt)).scalar_one_or_none()

    if version and version.source_code:
        source_code_keys = _extract_config_keys_from_source(version.source_code)

    # 2. ClickHouse lookup (supplement)
    clickhouse_keys: list[str] = []
    try:
        from monctl_central.dependencies import get_clickhouse

        ch = get_clickhouse()
        rows = ch._get_client().query(
            "SELECT DISTINCT config_key FROM config WHERE app_id = %(app_id)s ORDER BY config_key",
            parameters={"app_id": str(app_id)},
        )
        clickhouse_keys = [row[0] for row in rows.result_rows if row[0]]
    except Exception:
        pass

    return {
        "status": "success",
        "data": {
            "source_code_keys": source_code_keys,
            "clickhouse_keys": clickhouse_keys,
            "all_keys": sorted(set(source_code_keys + clickhouse_keys)),
        },
    }


def _extract_config_keys_from_source(source_code: str) -> list[str]:
    """Extract likely config_key string values from Python source code."""
    keys: set[str] = set()

    # Pattern 1: config_key="some_key" or config_key='some_key'
    for m in re.finditer(r'config_key\s*[=:]\s*["\']([a-zA-Z_][a-zA-Z0-9_.-]*)["\']', source_code):
        keys.add(m.group(1))

    # Pattern 2: "config_key": "some_key" (dict literal)
    for m in re.finditer(
        r'["\']config_key["\']\s*:\s*["\']([a-zA-Z_][a-zA-Z0-9_.-]*)["\']', source_code
    ):
        keys.add(m.group(1))

    # Pattern 3: String arrays that may be key lists
    for m in re.finditer(
        r'\[(["\'][a-zA-Z_][a-zA-Z0-9_."-]*["\']'
        r'(?:\s*,\s*["\'][a-zA-Z_][a-zA-Z0-9_."-]*["\'])*)\]',
        source_code,
    ):
        block = m.group(1)
        for s in re.finditer(r'["\']([a-zA-Z_][a-zA-Z0-9_.-]*)["\']', block):
            candidate = s.group(1)
            if "_" in candidate or len(candidate) > 4:
                keys.add(candidate)

    return sorted(keys)


# ── Alert Metrics Discovery ──────────────────────────────

@router.get("/{app_id}/alert-metrics")
async def get_alert_metrics(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Discover available metrics for alert expressions based on app's target_table."""
    import asyncio
    from monctl_central.dependencies import get_clickhouse

    app = await db.get(App, uuid.UUID(app_id))
    if app is None:
        raise HTTPException(status_code=404, detail="App not found")

    target_table = app.target_table

    if target_table == "availability_latency":
        metrics = [
            {"name": "rtt_ms", "type": "numeric", "description": "Round-trip time in ms"},
            {"name": "response_time_ms", "type": "numeric", "description": "Response time in ms"},
            {"name": "reachable", "type": "numeric", "description": "1 if reachable, 0 if not"},
            {"name": "state", "type": "numeric", "description": "Check state (0=OK, 1=WARN, 2=CRIT)"},
            {"name": "status_code", "type": "numeric", "description": "HTTP status code"},
        ]

    elif target_table == "interface":
        metrics = [
            {"name": "in_rate_bps", "type": "numeric", "description": "Inbound rate (bits/sec)"},
            {"name": "out_rate_bps", "type": "numeric", "description": "Outbound rate (bits/sec)"},
            {"name": "in_utilization_pct", "type": "numeric", "description": "Inbound utilization %"},
            {"name": "out_utilization_pct", "type": "numeric", "description": "Outbound utilization %"},
            {"name": "in_errors", "type": "numeric", "description": "Inbound errors"},
            {"name": "out_errors", "type": "numeric", "description": "Outbound errors"},
            {"name": "in_discards", "type": "numeric", "description": "Inbound discards"},
            {"name": "out_discards", "type": "numeric", "description": "Outbound discards"},
            {"name": "if_oper_status", "type": "numeric", "description": "Interface operational status"},
        ]

    elif target_table == "performance":
        ch = get_clickhouse()
        if ch:
            try:
                rows = await asyncio.to_thread(
                    ch._get_client().query,
                    "SELECT DISTINCT arrayJoin(metric_names) AS metric_name "
                    "FROM performance "
                    "WHERE app_id = {app_id:String} "
                    "ORDER BY metric_name",
                    parameters={"app_id": str(app_id)},
                )
                metrics = [
                    {"name": row[0], "type": "numeric", "description": f"Discovered metric: {row[0]}"}
                    for row in rows.result_rows
                    if row[0]
                ]
            except Exception:
                metrics = []
        else:
            metrics = []

    elif target_table == "config":
        ch = get_clickhouse()
        if ch:
            try:
                rows = await asyncio.to_thread(
                    ch._get_client().query,
                    "SELECT DISTINCT config_key "
                    "FROM config "
                    "WHERE app_id = {app_id:String} "
                    "ORDER BY config_key",
                    parameters={"app_id": str(app_id)},
                )
                metrics = [
                    {"name": row[0], "type": "string", "description": f"Config key: {row[0]}"}
                    for row in rows.result_rows
                    if row[0]
                ]
            except Exception:
                metrics = []
        else:
            metrics = []
    else:
        metrics = []

    return {"status": "success", "data": metrics}
