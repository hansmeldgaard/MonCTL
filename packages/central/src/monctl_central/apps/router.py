"""App management endpoints."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import apply_tenant_filter, get_db, require_auth
from monctl_common.validators import validate_semver, validate_uuid
from monctl_central.storage.models import (
    AlertDefinition,
    App,
    AppAssignment,
    AppConnectorBinding,
    AppVersion,
    AssignmentConnectorBinding,
    Connector,
    ConnectorVersion,
    ThresholdVariable,
)

router = APIRouter()


VALID_TARGET_TABLES = {"availability_latency", "performance", "interface", "config"}


def _next_patch_version(source_version: str, existing_versions: set[str]) -> str:
    """Auto-increment patch version from source.

    '1.0.0' -> '1.0.1', or '1.0.2' if '1.0.1' already exists.
    Falls back to appending '.1' for non-semver strings.
    """
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", source_version)
    if match:
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        candidate_patch = patch + 1
        while f"{major}.{minor}.{candidate_patch}" in existing_versions:
            candidate_patch += 1
        return f"{major}.{minor}.{candidate_patch}"

    counter = 1
    while f"{source_version}.{counter}" in existing_versions:
        counter += 1
    return f"{source_version}.{counter}"


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

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    app_type: str = Field(min_length=1, max_length=32, description="'script' or 'sdk'")
    config_schema: dict | None = None
    target_table: str = Field(default="availability_latency", max_length=64, description="ClickHouse target table")

    @field_validator("app_type")
    @classmethod
    def check_app_type(cls, v: str) -> str:
        if v not in {"script", "sdk"}:
            raise ValueError("app_type must be 'script' or 'sdk'")
        return v

    @field_validator("target_table")
    @classmethod
    def check_target_table(cls, v: str) -> str:
        if v not in {"availability_latency", "performance", "interface", "config"}:
            raise ValueError("target_table must be one of: availability_latency, performance, interface, config")
        return v


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
    schedule_type: str = Field(default="interval", max_length=32, description="'interval' (seconds) or 'cron' (cron expression)")
    schedule_value: str = Field(min_length=1, max_length=32, description="Seconds for interval (e.g. '60') or cron expression (e.g. '*/5 * * * *')")
    resource_limits: dict = Field(default_factory=lambda: {"timeout_seconds": 30, "memory_mb": 256})
    role: str | None = Field(default=None, description="Optional role: 'availability' or 'latency'")
    use_latest: bool = Field(default=False, description="Follow latest app version dynamically")
    credential_id: str | None = Field(default=None, description="Optional credential UUID for this assignment")
    connector_bindings: list[ConnectorBindingInput] = Field(
        default_factory=list,
        description="Optional connector bindings to attach to this assignment",
    )

    @field_validator("app_id", "app_version_id")
    @classmethod
    def check_required_uuids(cls, v: str, info) -> str:
        validate_uuid(v, info.field_name)
        return v

    @field_validator("collector_id", "device_id", "cluster_id", "credential_id")
    @classmethod
    def check_optional_uuids(cls, v: str | None, info) -> str | None:
        if v is not None:
            validate_uuid(v, info.field_name)
        return v

    @field_validator("schedule_type")
    @classmethod
    def check_schedule_type(cls, v: str) -> str:
        if v not in {"interval", "cron"}:
            raise ValueError("schedule_type must be 'interval' or 'cron'")
        return v


@router.get("")
async def list_apps(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
    name: str | None = Query(default=None),
    app_type: str | None = Query(default=None),
    target_table: str | None = Query(default=None),
    description: str | None = Query(default=None),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all apps with connector bindings."""
    from sqlalchemy.orm import selectinload
    from monctl_central.storage.models import AppConnectorBinding

    stmt = select(App).options(selectinload(App.connector_bindings))

    if name:
        stmt = stmt.where(App.name.ilike(f"%{name}%"))
    if app_type:
        stmt = stmt.where(App.app_type.ilike(f"%{app_type}%"))
    if target_table:
        stmt = stmt.where(App.target_table.ilike(f"%{target_table}%"))
    if description:
        stmt = stmt.where(App.description.ilike(f"%{description}%"))

    APPS_SORT_MAP = {
        "name": App.name,
        "app_type": App.app_type,
        "target_table": App.target_table,
        "created_at": App.created_at,
    }
    sort_col = APPS_SORT_MAP.get(sort_by, App.name)
    stmt = stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    count_stmt = select(sa.func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.limit(limit).offset(offset)

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

    apps_list = [
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
    ]

    return {
        "status": "success",
        "data": apps_list,
        "meta": {"limit": limit, "offset": offset, "count": len(apps_list), "total": total},
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
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    app_type: str | None = Field(default=None, min_length=1, max_length=32)
    config_schema: dict | None = None
    target_table: str | None = Field(default=None, max_length=64)

    @field_validator("app_type")
    @classmethod
    def check_app_type(cls, v: str | None) -> str | None:
        if v is not None and v not in {"script", "sdk"}:
            raise ValueError("app_type must be 'script' or 'sdk'")
        return v

    @field_validator("target_table")
    @classmethod
    def check_target_table(cls, v: str | None) -> str | None:
        if v is not None and v not in {"availability_latency", "performance", "interface", "config"}:
            raise ValueError("target_table must be one of: availability_latency, performance, interface, config")
        return v


class CreateVersionRequest(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    source_code: str = Field(min_length=1)
    requirements: list[str] = Field(default_factory=list)
    entry_class: str | None = None
    set_latest: bool = False
    display_template: dict | None = None
    volatile_keys: list[str] | None = None

    @field_validator("version")
    @classmethod
    def check_version(cls, v: str) -> str:
        return validate_semver(v)


# --- These routes must be registered BEFORE /{app_id} to avoid path conflict ---


@router.get("/config-templates")
async def get_config_templates(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return display templates for all config apps assigned to a device."""
    stmt = (
        select(AppAssignment, App, AppVersion)
        .join(App, AppAssignment.app_id == App.id)
        .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
        .where(
            AppAssignment.device_id == uuid.UUID(device_id),
            App.target_table == "config",
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Pre-load latest versions for use_latest assignments
    latest_version_map: dict[uuid.UUID, AppVersion] = {}
    use_latest_app_ids = {
        row.AppAssignment.app_id for row in rows if row.AppAssignment.use_latest
    }
    if use_latest_app_ids:
        latest_stmt = select(AppVersion).where(
            AppVersion.app_id.in_(use_latest_app_ids),
            AppVersion.is_latest == True,  # noqa: E712
        )
        latest_result = await db.execute(latest_stmt)
        for lv in latest_result.scalars().all():
            latest_version_map[lv.app_id] = lv

    templates = {}
    for row in rows:
        a = row.AppAssignment
        app = row.App
        stored_version = row.AppVersion

        if a.use_latest and a.app_id in latest_version_map:
            effective_version = latest_version_map[a.app_id]
        else:
            effective_version = stored_version

        templates[str(app.id)] = {
            "app_name": app.name,
            "version": effective_version.version,
            "display_template": effective_version.display_template,
        }

    return {"status": "success", "data": templates}


@router.get("/assignments")
async def list_assignments(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
    collector_id: str | None = None,
    device_id: str | None = None,
    app_id_filter: str | None = None,
    app_name: str | None = Query(default=None),
    device_name: str | None = Query(default=None),
    device_address: str | None = Query(default=None),
    device_type: str | None = Query(default=None),
    sort_by: str = Query(default="app_name"),
    sort_dir: str = Query(default="asc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all app assignments with app, device, and schedule details."""
    from sqlalchemy.orm import selectinload
    from monctl_central.storage.models import App, AppVersion, Collector, Device

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

    if app_name:
        stmt = stmt.where(App.name.ilike(f"%{app_name}%"))
    if device_name:
        stmt = stmt.where(DeviceModel.name.ilike(f"%{device_name}%"))
    if device_address:
        stmt = stmt.where(DeviceModel.address.ilike(f"%{device_address}%"))
    if device_type:
        stmt = stmt.where(DeviceModel.device_category.ilike(f"%{device_type}%"))

    ASSIGNMENTS_SORT_MAP = {
        "app_name": App.name,
        "device_name": DeviceModel.name,
        "device_address": DeviceModel.address,
        "device_category": DeviceModel.device_category,
        "schedule": AppAssignment.schedule_value,
        "enabled": AppAssignment.enabled,
        "created_at": AppAssignment.created_at,
    }
    sort_col = ASSIGNMENTS_SORT_MAP.get(sort_by, App.name)
    stmt = stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    count_stmt = select(sa.func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.limit(limit).offset(offset)

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
            # Per-protocol credentials from device.credentials JSONB
            if dev.credentials:
                for cred_val in dev.credentials.values():
                    try:
                        all_cred_ids.add(uuid.UUID(str(cred_val)))
                    except (ValueError, TypeError):
                        pass

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

    # Pre-load latest versions for use_latest resolution
    latest_version_map: dict[uuid.UUID, AppVersion] = {}
    use_latest_app_ids = {
        row.AppAssignment.app_id for row in rows if row.AppAssignment.use_latest
    }
    if use_latest_app_ids:
        latest_stmt = select(AppVersion).where(
            AppVersion.app_id.in_(use_latest_app_ids),
            AppVersion.is_latest == True,  # noqa: E712
        )
        latest_result = await db.execute(latest_stmt)
        for lv in latest_result.scalars().all():
            latest_version_map[lv.app_id] = lv

    # Resolve collector names for pinned assignments
    collector_ids = {row.AppAssignment.collector_id for row in rows if row.AppAssignment.collector_id}
    collector_name_map: dict[uuid.UUID, str] = {}
    if collector_ids:
        coll_stmt = select(Collector.id, Collector.name).where(Collector.id.in_(collector_ids))
        coll_rows = (await db.execute(coll_stmt)).all()
        collector_name_map = {r.id: r.name for r in coll_rows}

    def _resolve_device_credential_name(
        assignment, app, devs: dict, cred_names: dict,
    ) -> str | None:
        """Resolve effective device-level credential name for display.

        Priority: device.default_credential_id → device.credentials[connector_alias]
        """
        if not assignment.device_id or assignment.device_id not in devs:
            return None
        dev = devs[assignment.device_id]
        # 1. Explicit default credential
        if dev.default_credential_id:
            name = cred_names.get(dev.default_credential_id)
            if name:
                return name
        # 2. Per-protocol credential matching connector alias
        if dev.credentials and app.connector_bindings:
            for cb in app.connector_bindings:
                alias = cb.alias
                if alias in dev.credentials:
                    try:
                        cred_id = uuid.UUID(str(dev.credentials[alias]))
                        name = cred_names.get(cred_id)
                        if name:
                            return name
                    except (ValueError, TypeError):
                        pass
        return None

    return {
        "status": "success",
        "data": [
            {
                "id": str(row.AppAssignment.id),
                "app": {
                    "id": str(row.App.id),
                    "name": row.App.name,
                    "version": (
                        latest_version_map[row.AppAssignment.app_id].version
                        if row.AppAssignment.use_latest
                        and row.AppAssignment.app_id in latest_version_map
                        else row.AppVersion.version
                    ),
                },
                "app_version_id": str(row.AppAssignment.app_version_id),
                "device": (
                    {
                        "id": str(devices[row.AppAssignment.device_id].id),
                        "name": devices[row.AppAssignment.device_id].name,
                        "address": devices[row.AppAssignment.device_id].address,
                        "device_category": devices[row.AppAssignment.device_id].device_category,
                    }
                    if row.AppAssignment.device_id and row.AppAssignment.device_id in devices
                    else None
                ),
                "collector_id": str(row.AppAssignment.collector_id) if row.AppAssignment.collector_id else None,
                "collector_name": collector_name_map.get(row.AppAssignment.collector_id) if row.AppAssignment.collector_id else None,
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
                "device_default_credential_name": _resolve_device_credential_name(
                    row.AppAssignment, row.App, devices, cred_name_map,
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
        "meta": {"limit": limit, "offset": offset, "count": len(rows), "total": total},
    }


class BulkUpdateAssignmentsRequest(BaseModel):
    assignment_ids: list[str]
    schedule_type: str | None = None
    schedule_value: str | None = None
    credential_id: str | None = None
    enabled: bool | None = None
    app_version_id: str | None = None
    use_latest: bool | None = None

    @field_validator("app_version_id")
    @classmethod
    def _validate_app_version_id(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            try:
                uuid.UUID(v)
            except ValueError:
                raise ValueError(f"Invalid UUID for app_version_id: '{v}'")
        return v


@router.put("/assignments/bulk-update")
async def bulk_update_assignments(
    request: BulkUpdateAssignmentsRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Bulk update schedule, credential, and/or enabled state for multiple assignments."""
    from monctl_central.storage.models import Collector, Device
    from sqlalchemy import update as sa_update
    from monctl_common.utils import utc_now

    if not request.assignment_ids:
        raise HTTPException(status_code=400, detail="No assignment IDs provided")
    if len(request.assignment_ids) > 200:
        raise HTTPException(status_code=400, detail="Max 200 assignments per bulk update")

    uuids = [uuid.UUID(aid) for aid in request.assignment_ids]
    stmt = select(AppAssignment).where(AppAssignment.id.in_(uuids))
    assignments = (await db.execute(stmt)).scalars().all()

    if len(assignments) != len(uuids):
        raise HTTPException(status_code=404, detail="One or more assignments not found")

    collector_ids_to_bump: set[uuid.UUID] = set()
    group_ids_to_bump: set[uuid.UUID] = set()

    for a in assignments:
        if request.schedule_type is not None:
            a.schedule_type = request.schedule_type
        if request.schedule_value is not None:
            a.schedule_value = request.schedule_value
        if request.credential_id is not None:
            a.credential_id = uuid.UUID(request.credential_id) if request.credential_id else None
        if request.enabled is not None:
            a.enabled = request.enabled
        if request.use_latest is not None:
            a.use_latest = request.use_latest
        if request.app_version_id is not None:
            new_version_id = uuid.UUID(request.app_version_id)
            version = await db.get(AppVersion, new_version_id)
            if version is None or version.app_id != a.app_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Version {request.app_version_id} does not belong to app of assignment {a.id}",
                )
            a.app_version_id = new_version_id
            a.use_latest = False

        if a.collector_id:
            collector_ids_to_bump.add(a.collector_id)
        elif a.device_id:
            device = await db.get(Device, a.device_id)
            if device and device.collector_group_id:
                group_ids_to_bump.add(device.collector_group_id)

    await db.flush()

    if collector_ids_to_bump:
        await db.execute(
            sa_update(Collector)
            .where(Collector.id.in_(collector_ids_to_bump))
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )
    if group_ids_to_bump:
        await db.execute(
            sa_update(Collector)
            .where(Collector.group_id.in_(group_ids_to_bump))
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )

    return {"status": "success", "data": {"updated": len(assignments)}}


class BulkDeleteAssignmentsRequest(BaseModel):
    assignment_ids: list[str]


@router.post("/assignments/bulk-delete")
async def bulk_delete_assignments(
    request: BulkDeleteAssignmentsRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Bulk delete multiple assignments. Bumps collector config_version."""
    from monctl_central.storage.models import Collector, Device
    from sqlalchemy import update as sa_update
    from monctl_common.utils import utc_now

    if not request.assignment_ids:
        raise HTTPException(status_code=400, detail="No assignment IDs provided")
    if len(request.assignment_ids) > 200:
        raise HTTPException(status_code=400, detail="Max 200 assignments per bulk delete")

    uuids = [uuid.UUID(aid) for aid in request.assignment_ids]
    stmt = select(AppAssignment).where(AppAssignment.id.in_(uuids))
    assignments = (await db.execute(stmt)).scalars().all()

    if not assignments:
        raise HTTPException(status_code=404, detail="No assignments found")

    collector_ids_to_bump: set[uuid.UUID] = set()
    group_ids_to_bump: set[uuid.UUID] = set()

    for a in assignments:
        if a.collector_id:
            collector_ids_to_bump.add(a.collector_id)
        elif a.device_id:
            device = await db.get(Device, a.device_id)
            if device and device.collector_group_id:
                group_ids_to_bump.add(device.collector_group_id)
        await db.delete(a)

    await db.flush()

    if collector_ids_to_bump:
        await db.execute(
            sa_update(Collector)
            .where(Collector.id.in_(collector_ids_to_bump))
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )
    if group_ids_to_bump:
        await db.execute(
            sa_update(Collector)
            .where(Collector.group_id.in_(group_ids_to_bump))
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )

    return {"status": "success", "data": {"deleted": len(assignments)}}


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
                {"id": str(v.id), "version": v.version, "is_latest": v.is_latest, "volatile_keys": v.volatile_keys or []}
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
    alias: str = Field(min_length=1, max_length=64)
    connector_id: str = Field(min_length=1)
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

    # Validate pinned collector belongs to the device's collector group
    if request.collector_id and request.device_id:
        pinned = await db.get(Collector, uuid.UUID(request.collector_id))
        if not pinned:
            raise HTTPException(status_code=404, detail=f"Collector {request.collector_id} not found")
        dev = await db.get(Device, uuid.UUID(request.device_id))
        if dev and dev.collector_group_id and pinned.group_id != dev.collector_group_id:
            raise HTTPException(status_code=400, detail="Pinned collector must be a member of the device's collector group")

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
        credential_id=uuid.UUID(request.credential_id) if request.credential_id else None,
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
    schedule_type: str | None = Field(default=None, max_length=32)
    schedule_value: str | None = Field(default=None, min_length=1, max_length=32)
    config: dict | None = None
    enabled: bool | None = None
    app_version_id: str | None = None
    use_latest: bool | None = None
    collector_id: str | None = None  # "" = unpin, UUID = pin, None = don't change
    credential_id: str | None = None
    connector_bindings: list[ConnectorBindingInput] | None = None

    @field_validator("schedule_type")
    @classmethod
    def check_schedule_type(cls, v: str | None) -> str | None:
        if v is not None and v not in {"interval", "cron"}:
            raise ValueError("schedule_type must be 'interval' or 'cron'")
        return v

    @field_validator("app_version_id", "credential_id")
    @classmethod
    def check_optional_uuids(cls, v: str | None, info) -> str | None:
        if v is not None and v != "":
            validate_uuid(v, info.field_name)
        return v

    @field_validator("collector_id")
    @classmethod
    def check_collector_id(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            validate_uuid(v, "collector_id")
        return v


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
    if request.credential_id is not None:
        assignment.credential_id = uuid.UUID(request.credential_id) if request.credential_id else None
    if request.collector_id is not None:
        old_collector_id = assignment.collector_id
        if request.collector_id == "":
            # Explicit unpin
            assignment.collector_id = None
        else:
            pinned = await db.get(Collector, uuid.UUID(request.collector_id))
            if not pinned:
                raise HTTPException(status_code=404, detail=f"Collector {request.collector_id} not found")
            if assignment.device_id:
                device = await db.get(Device, assignment.device_id)
                if device and device.collector_group_id and pinned.group_id != device.collector_group_id:
                    raise HTTPException(status_code=400, detail="Pinned collector must be in the device's collector group")
            assignment.collector_id = pinned.id
        # Bump old and new collectors on pin change
        if old_collector_id != assignment.collector_id:
            if old_collector_id:
                await db.execute(
                    update(Collector).where(Collector.id == old_collector_id)
                    .values(config_version=Collector.config_version + 1, updated_at=utc_now())
                )
            if assignment.collector_id:
                await db.execute(
                    update(Collector).where(Collector.id == assignment.collector_id)
                    .values(config_version=Collector.config_version + 1, updated_at=utc_now())
                )
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
            "volatile_keys": version.volatile_keys or [],
        },
    }


class UpdateVersionRequest(BaseModel):
    source_code: str | None = None
    requirements: list[str] | None = None
    entry_class: str | None = None
    display_template: dict | None = None
    volatile_keys: list[str] | None = None


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
    if request.volatile_keys is not None:
        version.volatile_keys = request.volatile_keys

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
        volatile_keys=request.volatile_keys or [],
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


@router.post("/{app_id}/versions/{version_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_app_version(
    app_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Clone an existing app version into a new draft version.

    Copies source_code, requirements, entry_class, display_template.
    The new version is NOT set as is_latest.
    """
    import hashlib

    stmt = select(AppVersion).where(
        AppVersion.id == uuid.UUID(version_id),
        AppVersion.app_id == uuid.UUID(app_id),
    )
    source = (await db.execute(stmt)).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source version not found")

    all_versions = (await db.execute(
        select(AppVersion.version).where(AppVersion.app_id == uuid.UUID(app_id))
    )).scalars().all()
    new_version = _next_patch_version(source.version, set(all_versions))

    checksum = hashlib.sha256((source.source_code or "").encode()).hexdigest()
    cloned = AppVersion(
        app_id=source.app_id,
        version=new_version,
        source_code=source.source_code,
        requirements=source.requirements or [],
        entry_class=source.entry_class,
        checksum_sha256=checksum,
        is_latest=False,
        display_template=source.display_template,
        volatile_keys=source.volatile_keys or [],
    )
    db.add(cloned)
    await db.flush()

    return {
        "status": "success",
        "data": {
            "id": str(cloned.id),
            "version": cloned.version,
            "checksum": cloned.checksum_sha256,
            "is_latest": cloned.is_latest,
            "cloned_from": {
                "version_id": str(source.id),
                "version": source.version,
            },
        },
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


# ── App Threshold Variables ──────────────────────────────


def _fmt_threshold_variable(v: ThresholdVariable) -> dict:
    return {
        "id": str(v.id),
        "app_id": str(v.app_id),
        "name": v.name,
        "display_name": v.display_name,
        "description": v.description,
        "default_value": v.default_value,
        "app_value": v.app_value,
        "unit": v.unit,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


class CreateThresholdVariableRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    default_value: float
    display_name: str | None = Field(default=None, max_length=255)
    unit: str | None = None
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        if not re.match(r"^[a-z_][a-z0-9_]*$", v):
            raise ValueError("name must be lowercase letters, digits, and underscores only")
        return v

    @field_validator("unit")
    @classmethod
    def check_unit(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                return None
            if len(v) > 50:
                raise ValueError("unit must be at most 50 characters")
        return v


class UpdateThresholdVariableRequest(BaseModel):
    default_value: float | None = None
    app_value: float | None = None
    clear_app_value: bool = False
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=50)


@router.get("/{app_id}/thresholds")
async def list_app_thresholds(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all threshold variables for an app."""
    app = await db.get(App, uuid.UUID(app_id))
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    stmt = (
        select(ThresholdVariable)
        .where(ThresholdVariable.app_id == uuid.UUID(app_id))
        .order_by(ThresholdVariable.name)
    )
    variables = (await db.execute(stmt)).scalars().all()
    return {"status": "success", "data": [_fmt_threshold_variable(v) for v in variables]}


@router.post("/{app_id}/thresholds", status_code=201)
async def create_app_threshold(
    app_id: str,
    request: CreateThresholdVariableRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Create a new threshold variable for an app."""
    app = await db.get(App, uuid.UUID(app_id))
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    # Check uniqueness
    existing = (await db.execute(
        select(ThresholdVariable).where(
            ThresholdVariable.app_id == uuid.UUID(app_id),
            ThresholdVariable.name == request.name,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Threshold variable '{request.name}' already exists on this app",
        )

    var = ThresholdVariable(
        app_id=uuid.UUID(app_id),
        name=request.name,
        default_value=request.default_value,
        display_name=request.display_name,
        unit=request.unit,
        description=request.description,
    )
    db.add(var)
    await db.flush()
    return {"status": "success", "data": _fmt_threshold_variable(var)}


@router.delete("/{app_id}/thresholds/{var_id}")
async def delete_app_threshold(
    app_id: str,
    var_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a threshold variable. Fails if referenced by alert definitions."""
    app = await db.get(App, uuid.UUID(app_id))
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    variable = await db.get(ThresholdVariable, uuid.UUID(var_id))
    if not variable or str(variable.app_id) != app_id:
        raise HTTPException(status_code=404, detail="Threshold variable not found")

    # Check if any alert definitions reference the variable (by name on right side
    # of comparison, or via auto-generated threshold param name)
    from monctl_central.alerting.dsl import validate_expression
    alert_defs = (await db.execute(
        select(AlertDefinition).where(AlertDefinition.app_id == uuid.UUID(app_id))
    )).scalars().all()
    for ad in alert_defs:
        validation = validate_expression(ad.expression, app.target_table)
        for ref in validation.threshold_refs:
            if ref.name == variable.name:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete: alert definition '{ad.name}' references "
                           f"'{variable.name}' in its expression",
                )
        for tp in validation.threshold_params:
            if tp.name == variable.name:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete: alert definition '{ad.name}' references "
                           f"'{variable.name}' in its expression",
                )

    await db.delete(variable)
    await db.flush()
    return {"status": "success", "data": None}


@router.put("/{app_id}/thresholds/{var_id}")
async def update_app_threshold(
    app_id: str,
    var_id: str,
    request: UpdateThresholdVariableRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a threshold variable."""
    app = await db.get(App, uuid.UUID(app_id))
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    variable = await db.get(ThresholdVariable, uuid.UUID(var_id))
    if not variable or str(variable.app_id) != app_id:
        raise HTTPException(status_code=404, detail="Threshold variable not found")

    if request.default_value is not None:
        variable.default_value = request.default_value
    if request.clear_app_value:
        variable.app_value = None
    elif request.app_value is not None:
        variable.app_value = request.app_value
    if request.display_name is not None:
        variable.display_name = request.display_name
    if request.description is not None:
        variable.description = request.description
    if request.unit is not None:
        variable.unit = request.unit.strip() or None

    from monctl_common.utils import utc_now
    variable.updated_at = utc_now()
    await db.flush()
    return {"status": "success", "data": _fmt_threshold_variable(variable)}
