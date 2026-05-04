"""Collector management endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import os

from starlette.requests import Request

from monctl_central.dependencies import get_db, require_collector_key, require_permission, require_admin
from monctl_central.storage.models import ApiKey, Collector, CollectorGroup, RegistrationToken, SystemSetting
from monctl_central.ws.router import manager as ws_manager
from monctl_common.utils import generate_api_key, hash_api_key, key_prefix_display, utc_now
from monctl_common.constants import COLLECTOR_KEY_PREFIX
from monctl_common.validators import validate_labels, validate_uuid

router = APIRouter()


class RegisterRequest(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    registration_token: str | None = Field(default=None, max_length=512)  # Legacy long token
    registration_code: str | None = Field(default=None, min_length=6, max_length=6)  # Short 6-char code (preferred)
    os_info: dict | None = None
    ip_addresses: list[str] | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    cluster_id: str | None = None
    fingerprint: str | None = Field(default=None, max_length=512)

    @field_validator("labels")
    @classmethod
    def check_labels(cls, v: dict[str, str]) -> dict[str, str]:
        return validate_labels(v)

    @field_validator("cluster_id")
    @classmethod
    def check_cluster_id(cls, v: str | None) -> str | None:
        if v is not None:
            validate_uuid(v, "cluster_id")
        return v


class RegisterResponse(BaseModel):
    collector_id: str
    api_key: str
    name: str
    status: str


class HeartbeatRequest(BaseModel):
    collector_id: str
    timestamp: datetime
    config_version: int = Field(ge=0)
    system_stats: dict | None = None
    app_statuses: dict | None = None
    @field_validator("collector_id")
    @classmethod
    def check_collector_id(cls, v: str) -> str:
        validate_uuid(v, "collector_id")
        return v


class HeartbeatResponse(BaseModel):
    config_version: int
    config_changed: bool


class UpdateCollectorRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    group_id: str | None = None  # empty string = unassign, UUID string = assign
    log_level_filter: str | None = Field(
        default=None, pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"
    )

    @field_validator("group_id")
    @classmethod
    def check_group_id(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            validate_uuid(v, "group_id")
        return v


class ApproveRequest(BaseModel):
    group_id: str

    @field_validator("group_id")
    @classmethod
    def check_group_id(cls, v: str) -> str:
        validate_uuid(v, "group_id")
        return v


class RejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


# ---------------------------------------------------------------------------
# GET /v1/collectors/setup-context  (admin-only)
# ---------------------------------------------------------------------------

@router.get("/setup-context")
async def get_setup_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Return collector API key and central URL for the setup guide."""
    collector_api_key = os.environ.get("MONCTL_COLLECTOR_API_KEY", "")
    if not collector_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MONCTL_COLLECTOR_API_KEY is not configured on central. Set this environment variable and restart.",
        )

    # Prefer collector_central_url from system settings, fall back to request origin
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "collector_central_url")
    )
    setting = result.scalar_one_or_none()
    central_url = (setting.value if setting and setting.value else "") or str(request.base_url).rstrip("/")

    return {
        "status": "success",
        "data": {
            "collector_api_key": collector_api_key,
            "central_url": central_url,
        },
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_collector(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Register a new collector with the central server.

    Accepts either a short registration code (6 chars) or a legacy long token.
    Collectors start as PENDING and must be approved by an admin.
    The API key is returned immediately so the collector can poll for status.
    """
    reg_token = None

    # Try short code first (preferred)
    if request.registration_code:
        code = request.registration_code.strip().upper()
        stmt = select(RegistrationToken).where(RegistrationToken.short_code == code)
        result = await db.execute(stmt)
        reg_token = result.scalar_one_or_none()
    elif request.registration_token:
        # Legacy: validate by hash
        token_hash = hash_api_key(request.registration_token)
        stmt = select(RegistrationToken).where(RegistrationToken.token_hash == token_hash)
        result = await db.execute(stmt)
        reg_token = result.scalar_one_or_none()

    if reg_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid registration code")

    if reg_token.one_time and reg_token.used:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Registration token already used")

    if reg_token.expires_at and reg_token.expires_at < utc_now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Registration token expired")

    # Check if a collector with this hostname already exists (re-registration)
    existing_stmt = select(Collector).where(Collector.hostname == request.hostname)
    existing_result = await db.execute(existing_stmt)
    collector = existing_result.scalar_one_or_none()

    if collector is not None:
        # Re-registration: reset to PENDING, update fields
        collector.ip_addresses = request.ip_addresses
        collector.os_info = request.os_info
        collector.labels = request.labels
        collector.status = "PENDING"
        collector.fingerprint = request.fingerprint
        collector.approved_at = None
        collector.approved_by = None
        collector.rejected_reason = None
        collector.last_seen_at = utc_now()
        collector.updated_at = utc_now()

        # Delete old API keys for this collector and drop them from the cache so
        # a re-registered collector cannot keep operating with its previous key.
        from monctl_central.cache import delete_cached_api_key

        old_keys_stmt = select(ApiKey).where(ApiKey.collector_id == collector.id)
        old_keys = (await db.execute(old_keys_stmt)).scalars().all()
        for old_key in old_keys:
            await delete_cached_api_key(old_key.key_hash)
            await db.delete(old_key)
        await db.flush()
    else:
        # New collector
        collector = Collector(
            name=request.hostname,
            hostname=request.hostname,
            ip_addresses=request.ip_addresses,
            os_info=request.os_info,
            labels=request.labels,
            status="PENDING",
            cluster_id=uuid.UUID(request.cluster_id) if request.cluster_id else reg_token.cluster_id,
            fingerprint=request.fingerprint,
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
        status="PENDING",
    )


# ---------------------------------------------------------------------------
# GET /v1/collectors/{collector_id}/registration-status
# ---------------------------------------------------------------------------

@router.get("/{collector_id}/registration-status")
async def get_registration_status(
    collector_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: dict = Depends(require_collector_key),
):
    """Poll registration status. Used by TUI after registration."""
    if api_key["collector_id"] != collector_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Collector ID mismatch")

    from sqlalchemy.orm import selectinload

    stmt = (
        select(Collector)
        .where(Collector.id == uuid.UUID(collector_id))
        .options(selectinload(Collector.group))
    )
    result = await db.execute(stmt)
    collector = result.scalar_one_or_none()
    if collector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")

    return {
        "status": collector.status,
        "group_id": str(collector.group_id) if collector.group_id else None,
        "group_name": collector.group.name if collector.group else None,
        "rejected_reason": collector.rejected_reason,
    }


# ---------------------------------------------------------------------------
# POST /v1/collectors/{collector_id}/approve
# ---------------------------------------------------------------------------

class ProvisionKeyRequest(BaseModel):
    revoke_existing: bool = False


class ProvisionKeyResponse(BaseModel):
    collector_id: str
    api_key: str
    name: str
    status: str
    created: bool


@router.post(
    "/by-hostname/{hostname}/api-keys",
    status_code=status.HTTP_201_CREATED,
    response_model=ProvisionKeyResponse,
)
async def provision_collector_api_key(
    hostname: str,
    request: ProvisionKeyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
) -> ProvisionKeyResponse:
    """Admin-only: mint a per-collector API key for ``hostname``.

    Wave 2 installer enabler (M-INST-011 / S-COL-002 / S-X-002). The
    customer installer needs to provision per-host collector API keys
    at install time so that ``MONCTL_COLLECTOR_API_KEY`` shipped to
    each collector host is unique to that host (instead of every host
    sharing the cluster-wide secret). The collector self-registration
    flow at ``POST /v1/collectors/register`` requires the collector to
    initiate; this endpoint inverts that — central operators (with
    admin credentials in their `secrets.env`) can mint keys directly,
    suitable for orchestration from ``monctl_ctl deploy``.

    If a Collector with the requested hostname doesn't exist yet, one
    is created with ``status="PENDING"``. The operator approves it
    via the existing ``POST /v1/collectors/{id}/approve`` flow once
    the collector host is up. Re-running this endpoint mints
    additional keys (multiple keys per collector are supported by the
    current model — useful for key rotation). Pass
    ``revoke_existing: true`` to delete prior keys at the same time.
    """
    if not hostname.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hostname is required",
        )

    existing_stmt = select(Collector).where(Collector.hostname == hostname)
    collector = (await db.execute(existing_stmt)).scalar_one_or_none()
    created = False
    if collector is None:
        collector = Collector(
            name=hostname,
            hostname=hostname,
            status="PENDING",
            last_seen_at=utc_now(),
        )
        db.add(collector)
        await db.flush()
        created = True

    if request.revoke_existing:
        # Drop any existing keys + invalidate the cache so a stale key
        # the operator may have leaked stops working immediately.
        from monctl_central.cache import delete_cached_api_key

        old_keys = (
            await db.execute(
                select(ApiKey).where(ApiKey.collector_id == collector.id)
            )
        ).scalars().all()
        for old_key in old_keys:
            await delete_cached_api_key(old_key.key_hash)
            await db.delete(old_key)
        await db.flush()

    raw_key = generate_api_key(COLLECTOR_KEY_PREFIX)
    api_key_row = ApiKey(
        key_hash=hash_api_key(raw_key),
        key_prefix=key_prefix_display(raw_key),
        key_type="collector",
        collector_id=collector.id,
        scopes=["collector:*"],
    )
    db.add(api_key_row)
    await db.flush()

    return ProvisionKeyResponse(
        collector_id=str(collector.id),
        api_key=raw_key,
        name=collector.name,
        status=collector.status,
        created=created,
    )


@router.post("/{collector_id}/approve")
async def approve_collector(
    collector_id: str,
    request: ApproveRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Approve a pending collector and assign it to a group."""
    collector = await db.get(Collector, uuid.UUID(collector_id))
    if collector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")

    # Validate group exists
    group = await db.get(CollectorGroup, uuid.UUID(request.group_id))
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector group not found")

    collector.status = "ACTIVE"
    collector.group_id = group.id
    collector.approved_at = utc_now()
    collector.approved_by = auth.get("username", "admin")
    collector.rejected_reason = None
    collector.updated_at = utc_now()
    # Invalidate weight snapshot — new collector joined the group
    group.weight_snapshot = None
    await db.flush()

    return {
        "status": "success",
        "data": {
            "id": str(collector.id),
            "name": collector.name,
            "status": collector.status,
            "group_id": str(collector.group_id),
            "group_name": group.name,
            "approved_at": collector.approved_at.isoformat(),
            "approved_by": collector.approved_by,
        },
    }


# ---------------------------------------------------------------------------
# POST /v1/collectors/{collector_id}/reject
# ---------------------------------------------------------------------------

@router.post("/{collector_id}/reject")
async def reject_collector(
    collector_id: str,
    request: RejectRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Reject a pending collector."""
    collector = await db.get(Collector, uuid.UUID(collector_id))
    if collector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")

    collector.status = "REJECTED"
    collector.rejected_reason = request.reason
    collector.updated_at = utc_now()
    await db.flush()

    return {
        "status": "success",
        "data": {
            "id": str(collector.id),
            "name": collector.name,
            "status": collector.status,
            "rejected_reason": collector.rejected_reason,
        },
    }


# ---------------------------------------------------------------------------
# POST /v1/collectors/{collector_id}/heartbeat
# ---------------------------------------------------------------------------

@router.post("/{collector_id}/heartbeat")
async def heartbeat(
    collector_id: str,
    request: HeartbeatRequest,
    raw_request: Request,
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

    # Don't flip PENDING or REJECTED to ACTIVE via heartbeat
    if collector.status not in ("PENDING", "REJECTED"):
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

    # Update system version info from heartbeat
    if request.system_stats:
        from monctl_central.storage.models import SystemVersion
        sv = (await db.execute(
            select(SystemVersion).where(SystemVersion.node_hostname == collector.hostname)
        )).scalar_one_or_none()
        if sv is None:
            # Use X-Forwarded-For (from HAProxy) or client IP for real node IP
            real_ip = (
                raw_request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                or str(raw_request.client.host if raw_request.client else "")
            )
            sv = SystemVersion(
                node_hostname=collector.hostname,
                node_role="collector",
                node_ip=real_ip,
            )
            db.add(sv)
        # Update node_ip if it's a Docker bridge IP (172.x)
        if sv.node_ip.startswith("172."):
            real_ip = (
                raw_request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                or str(raw_request.client.host if raw_request.client else "")
            )
            if real_ip and not real_ip.startswith("172."):
                sv.node_ip = real_ip
        sv.monctl_version = request.system_stats.get("monctl_version")
        os_info = request.system_stats.get("os_info", {})
        if isinstance(os_info, dict):
            sv.os_version = os_info.get("os_version")
            sv.kernel_version = os_info.get("kernel_version")
            sv.python_version = os_info.get("python_version")
        sv.last_reported_at = utc_now()

    current_version = collector.config_version
    config_changed = current_version != request.config_version

    return HeartbeatResponse(
        config_version=current_version,
        config_changed=config_changed,
    )


# ---------------------------------------------------------------------------
# GET /v1/collectors/{collector_id}/config
# ---------------------------------------------------------------------------

@router.get("/{collector_id}/config")
async def get_collector_config(
    collector_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: dict = Depends(require_collector_key),
):
    """Return the full configuration snapshot for a collector.

    - Device address is injected into app config when assignment has a device_id.
    - Credential references ($credential:name) are resolved to plaintext values.
    - Cluster peer info is included when the collector belongs to a group.
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
    group_rows: list[tuple] = []
    group_collectors: list[Collector] = []
    if collector.group_id:
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
        group_collectors = list((await db.execute(stmt_gc)).scalars().all())
        group_size = len(group_collectors)
        my_position = next(
            (i for i, c in enumerate(group_collectors) if str(c.id) == collector_id), -1
        )

        if group_size > 0 and my_position >= 0:
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
                .order_by(AppAssignment.id)
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
                resolved["device_category"] = device.device_category

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
                resolved[key] = secret[key]
            elif secret:
                del resolved[key]
                resolved.update(secret)

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

    # Build cluster info
    cluster_info = None
    if collector.group_id:
        from sqlalchemy.orm import selectinload
        group_stmt = select(CollectorGroup).where(CollectorGroup.id == collector.group_id)
        group_result = await db.execute(group_stmt)
        group = group_result.scalar_one_or_none()

        cluster_info = {
            "group_id": str(collector.group_id),
            "group_name": group.name if group else None,
        }

    return {
        "status": "success",
        "data": {
            "config_version": collector.config_version,
            "settings": {"heartbeat_interval": 30, "push_interval": 10, "log_level": "INFO"},
            "assignments": assignments,
            "cluster": cluster_info,
        },
    }


# ---------------------------------------------------------------------------
# GET /v1/collectors
# ---------------------------------------------------------------------------

@router.get("")
async def list_collectors(
    group_id: str | None = Query(default=None, description="Filter by collector group UUID"),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("collector", "view")),
):
    """List all collectors with group and IP information."""
    from sqlalchemy.orm import selectinload
    stmt = select(Collector).options(selectinload(Collector.group))
    if group_id:
        stmt = stmt.where(Collector.group_id == uuid.UUID(group_id))
    result = await db.execute(stmt)
    collectors = result.scalars().all()

    data = []
    for c in collectors:
        data.append({
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
            "fingerprint": c.fingerprint,
            "approved_at": c.approved_at.isoformat() if c.approved_at else None,
            "approved_by": c.approved_by,
            "rejected_reason": c.rejected_reason,
            "registered_at": c.registered_at.isoformat() if c.registered_at else None,
            "log_level_filter": c.log_level_filter,
            "ws_connected": await ws_manager.is_connected(c.id),
            "ws_connection": await ws_manager.get_connection_info(c.id),
        })
    return {"status": "success", "data": data}


# ---------------------------------------------------------------------------
# PUT /v1/collectors/{collector_id}
# ---------------------------------------------------------------------------

@router.put("/{collector_id}")
async def update_collector(
    collector_id: str,
    request: UpdateCollectorRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("collector", "manage")),
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

    if request.log_level_filter is not None:
        c.log_level_filter = request.log_level_filter

    if request.group_id is not None:
        # Invalidate weight snapshot on old group (collector leaving)
        if c.group_id:
            old_group = await db.get(CollectorGroup, c.group_id)
            if old_group:
                old_group.weight_snapshot = None
        if request.group_id == "":
            c.group_id = None
        else:
            group = await db.get(CollectorGroup, uuid.UUID(request.group_id))
            if group is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector group not found")
            c.group_id = group.id
            # Invalidate weight snapshot on new group (collector joining)
            group.weight_snapshot = None

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
            "log_level_filter": c.log_level_filter,
            "ws_connected": await ws_manager.is_connected(c.id),
            "ws_connection": await ws_manager.get_connection_info(c.id),
        },
    }


# ---------------------------------------------------------------------------
# DELETE /v1/collectors/{collector_id}
# ---------------------------------------------------------------------------

@router.delete("/{collector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collector(
    collector_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("collector", "manage")),
):
    """Delete a collector and its associated API keys."""
    c = await db.get(Collector, uuid.UUID(collector_id))
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector not found")
    await db.delete(c)
