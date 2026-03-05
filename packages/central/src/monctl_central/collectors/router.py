"""Collector management endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_collector_key, require_auth
from monctl_central.storage.models import ApiKey, Collector, CollectorGroup, RegistrationToken
from monctl_common.utils import generate_api_key, hash_api_key, key_prefix_display, utc_now
from monctl_common.constants import COLLECTOR_KEY_PREFIX

router = APIRouter()


class RegisterRequest(BaseModel):
    hostname: str
    registration_token: str
    os_info: dict | None = None
    ip_addresses: list[str] | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    cluster_id: str | None = None
    peer_address: str | None = None


class RegisterResponse(BaseModel):
    collector_id: str
    api_key: str
    name: str


class HeartbeatRequest(BaseModel):
    collector_id: str
    timestamp: datetime
    config_version: int
    system_stats: dict | None = None
    app_statuses: dict | None = None
    peer_states: dict | None = None


class HeartbeatResponse(BaseModel):
    config_version: int
    config_changed: bool


class UpdateCollectorRequest(BaseModel):
    name: str | None = None
    group_id: str | None = None  # empty string = unassign, UUID string = assign


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_collector(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Register a new collector with the central server."""
    # Validate registration token
    token_hash = hash_api_key(request.registration_token)
    stmt = select(RegistrationToken).where(RegistrationToken.token_hash == token_hash)
    result = await db.execute(stmt)
    reg_token = result.scalar_one_or_none()

    if reg_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid registration token")

    if reg_token.one_time and reg_token.used:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Registration token already used")

    if reg_token.expires_at and reg_token.expires_at < utc_now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Registration token expired")

    # Create collector record
    collector = Collector(
        name=request.hostname,
        hostname=request.hostname,
        ip_addresses=request.ip_addresses,
        os_info=request.os_info,
        labels=request.labels,
        status="ACTIVE",
        cluster_id=uuid.UUID(request.cluster_id) if request.cluster_id else reg_token.cluster_id,
        peer_address=request.peer_address,
        last_seen_at=utc_now(),
    )
    db.add(collector)
    await db.flush()

    # Generate API key
    raw_key = generate_api_key(COLLECTOR_KEY_PREFIX)
    api_key = ApiKey(
        key_hash=hash_api_key(raw_key),
        key_prefix=key_prefix_display(raw_key),
        key_type="collector",
        collector_id=collector.id,
        scopes=["collector:*"],
    )
    db.add(api_key)

    # Mark token as used if one-time
    if reg_token.one_time:
        reg_token.used = True

    return RegisterResponse(
        collector_id=str(collector.id),
        api_key=raw_key,
        name=collector.name,
    )


@router.post("/{collector_id}/heartbeat")
async def heartbeat(
    collector_id: str,
    request: HeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    api_key: dict = Depends(require_collector_key),
) -> HeartbeatResponse:
    """Receive heartbeat from a collector, return config change status."""
    if api_key["collector_id"] != collector_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Collector ID mismatch")

    cid = uuid.UUID(collector_id)

    # Fetch collector to detect DOWN → ACTIVE recovery
    collector = (
        await db.execute(select(Collector).where(Collector.id == cid))
    ).scalar_one_or_none()
    if collector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")

    was_down = collector.status == "DOWN"

    collector.status = "ACTIVE"
    collector.last_seen_at = utc_now()
    collector.updated_at = utc_now()
    await db.flush()

    # Recovery: bump ALL group members (including this collector) so every node
    # re-fetches config and redistributes work with the updated group size.
    if was_down and collector.group_id:
        await db.execute(
            update(Collector)
            .where(Collector.group_id == collector.group_id)
            .values(config_version=Collector.config_version + 1, updated_at=utc_now())
        )
        # Re-read config_version after the bulk update
        await db.refresh(collector)

    current_version = collector.config_version
    config_changed = current_version != request.config_version

    return HeartbeatResponse(
        config_version=current_version,
        config_changed=config_changed,
    )


@router.get("/{collector_id}/config")
async def get_collector_config(
    collector_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: dict = Depends(require_collector_key),
):
    """Return the full configuration snapshot for a collector.

    - Device address is injected into app config when assignment has a device_id.
    - Credential references ($credential:name) are resolved to plaintext values.
    """
    if api_key["collector_id"] != collector_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Collector ID mismatch")

    from monctl_central.storage.models import App, AppAssignment, AppVersion, Device, Credential
    from monctl_central.credentials.crypto import decrypt_dict

    # Fetch the collector's current config_version
    stmt_c = select(Collector).where(Collector.id == uuid.UUID(collector_id))
    result_c = await db.execute(stmt_c)
    collector = result_c.scalar_one_or_none()
    if collector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")

    # Fetch enabled assignments for this collector (direct assignments)
    stmt_a = (
        select(AppAssignment, App, AppVersion)
        .join(App, AppAssignment.app_id == App.id)
        .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
        .where(
            AppAssignment.collector_id == uuid.UUID(collector_id),
            AppAssignment.enabled == True,
        )
    )
    rows = (await db.execute(stmt_a)).all()

    # Also fetch group-level assignments if this collector belongs to a group.
    # Group-level assignments have collector_id IS NULL; the workload is distributed
    # deterministically via round-robin (sorted collector IDs, index mod group size).
    group_rows: list[tuple] = []
    if collector.group_id:
        # Get all healthy collectors in this group (ACTIVE + seen within 90 s).
        # Using last_seen_at as the liveness gate means failover kicks in immediately
        # when a collector goes silent, even before the health-monitor background
        # task has had a chance to flip its status to DOWN.
        stale_cutoff = utc_now() - timedelta(seconds=90)
        stmt_gc = (
            select(Collector)
            .where(
                Collector.group_id == collector.group_id,
                Collector.status == "ACTIVE",
                Collector.last_seen_at >= stale_cutoff,
            )
            .order_by(Collector.id)
        )
        group_collectors = (await db.execute(stmt_gc)).scalars().all()
        group_size = len(group_collectors)
        my_position = next(
            (i for i, c in enumerate(group_collectors) if str(c.id) == collector_id), -1
        )

        if group_size > 0 and my_position >= 0:
            # Fetch all enabled assignments where collector_id IS NULL and the device
            # is in this collector group
            stmt_ga = (
                select(AppAssignment, App, AppVersion)
                .join(App, AppAssignment.app_id == App.id)
                .join(AppVersion, AppAssignment.app_version_id == AppVersion.id)
                .join(Device, AppAssignment.device_id == Device.id)
                .where(
                    AppAssignment.collector_id.is_(None),
                    AppAssignment.enabled == True,
                    Device.collector_group_id == collector.group_id,
                )
                .order_by(AppAssignment.id)  # stable ordering for deterministic split
            )
            ga_rows = (await db.execute(stmt_ga)).all()

            # Round-robin: this collector takes every group_size-th assignment
            group_rows = [
                row for idx, row in enumerate(ga_rows) if idx % group_size == my_position
            ]

    all_rows = list(rows) + group_rows

    # Cache for resolved credentials (avoid repeated DB queries for same credential)
    cred_cache: dict[str, dict] = {}

    async def _resolve_config(assignment: AppAssignment) -> dict:
        """Inject device address and resolve $credential: references."""
        resolved: dict = {}

        # Inject device address when a device is linked
        if assignment.device_id:
            device = await db.get(Device, assignment.device_id)
            if device:
                resolved["host"] = device.address
                resolved["device_name"] = device.name
                resolved["device_type"] = device.device_type

        # Assignment config can override / extend device defaults
        resolved.update(assignment.config or {})

        # Resolve $credential: references
        for key in list(resolved.keys()):
            value = resolved[key]
            if not (isinstance(value, str) and value.startswith("$credential:")):
                continue
            cred_name = value.removeprefix("$credential:")
            if cred_name not in cred_cache:
                cred_row = (
                    await db.execute(
                        select(Credential).where(Credential.name == cred_name)
                    )
                ).scalar_one_or_none()
                if cred_row:
                    try:
                        cred_cache[cred_name] = decrypt_dict(cred_row.secret_data)
                    except Exception:
                        cred_cache[cred_name] = {}
                else:
                    cred_cache[cred_name] = {}

            secret = cred_cache[cred_name]
            if key in secret:
                # Secret has a matching key — use that value directly
                resolved[key] = secret[key]
            elif secret:
                # No matching key — inject all secret fields and remove the reference
                del resolved[key]
                resolved.update(secret)
            # else: credential not found, leave the $credential: reference as-is

        return resolved

    assignments = []
    for assignment, app, version in all_rows:
        resolved_config = await _resolve_config(assignment)
        assignments.append({
            "assignment_id": str(assignment.id),
            "app_id": str(assignment.app_id),
            "app_name": app.name,
            "app_version": version.version,
            "device_id": str(assignment.device_id) if assignment.device_id else None,
            "schedule": {
                "type": assignment.schedule_type,
                "value": assignment.schedule_value,
            },
            "config": resolved_config,
            "resource_limits": assignment.resource_limits,
        })

    return {
        "status": "success",
        "data": {
            "config_version": collector.config_version,
            "settings": {"heartbeat_interval": 30, "push_interval": 10, "log_level": "INFO"},
            "assignments": assignments,
            "cluster": None,
        },
    }


@router.get("")
async def list_collectors(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all collectors with group and IP information."""
    from sqlalchemy.orm import selectinload
    stmt = select(Collector).options(selectinload(Collector.group))
    result = await db.execute(stmt)
    collectors = result.scalars().all()

    return {
        "status": "success",
        "data": [
            {
                "id": str(c.id),
                "name": c.name,
                "hostname": c.hostname,
                "status": c.status,
                "labels": c.labels,
                "ip_addresses": c.ip_addresses if isinstance(c.ip_addresses, list) else (list(c.ip_addresses.values()) if isinstance(c.ip_addresses, dict) else []),
                "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
                "cluster_id": str(c.cluster_id) if c.cluster_id else None,
                "group_id": str(c.group_id) if c.group_id else None,
                "group_name": c.group.name if c.group else None,
            }
            for c in collectors
        ],
    }


@router.put("/{collector_id}")
async def update_collector(
    collector_id: str,
    request: UpdateCollectorRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update a collector's name and/or group assignment."""
    from sqlalchemy.orm import selectinload
    c = (
        await db.execute(
            select(Collector)
            .where(Collector.id == uuid.UUID(collector_id))
            .options(selectinload(Collector.group))
        )
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")

    if request.name is not None:
        c.name = request.name

    if request.group_id is not None:
        if request.group_id == "":
            c.group_id = None
        else:
            group = await db.get(CollectorGroup, uuid.UUID(request.group_id))
            if group is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector group not found")
            c.group_id = group.id

    c.updated_at = utc_now()
    await db.flush()

    # Reload group after flush
    await db.refresh(c, ["group"])

    return {
        "status": "success",
        "data": {
            "id": str(c.id),
            "name": c.name,
            "hostname": c.hostname,
            "status": c.status,
            "labels": c.labels,
            "ip_addresses": c.ip_addresses if isinstance(c.ip_addresses, list) else [],
            "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
            "group_id": str(c.group_id) if c.group_id else None,
            "group_name": c.group.name if c.group else None,
        },
    }


@router.delete("/{collector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collector(
    collector_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Delete a collector and its associated API keys."""
    c = await db.get(Collector, uuid.UUID(collector_id))
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")
    await db.delete(c)
