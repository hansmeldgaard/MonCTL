"""User management endpoints (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from monctl_common.validators import validate_uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_admin, require_auth
from monctl_central.storage.models import Tenant, User, UserTenant
from monctl_common.utils import utc_now

router = APIRouter()


def _fmt_user(u: User, role_name: str | None = None) -> dict:
    # Try to get role_name from eagerly loaded relationship, fallback to explicit param
    rn = role_name
    if rn is None:
        try:
            rn = u.assigned_role.name if u.assigned_role else None
        except Exception:
            rn = None
    return {
        "id": str(u.id),
        "username": u.username,
        "display_name": u.display_name,
        "email": u.email,
        "role": u.role,
        "role_id": str(u.role_id) if u.role_id else None,
        "role_name": rn,
        "all_tenants": u.all_tenants,
        # Stored value, not the OAuth-derived effective tier — admin UI
        # needs to distinguish "explicitly set" from "derived from role".
        "superset_access": u.superset_access,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


# ── Request models ───────────────────────────────────────────────────────────

_VALID_SUPERSET_ACCESS = {"none", "viewer", "analyst", "admin"}


def _check_superset_access(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    v = v.strip().lower()
    if v not in _VALID_SUPERSET_ACCESS:
        raise ValueError(
            f"superset_access must be one of {sorted(_VALID_SUPERSET_ACCESS)}"
        )
    return v


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=6, max_length=128)
    role: str = Field(default="user", description="'admin' or 'user'")
    role_id: str | None = None
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    all_tenants: bool = False
    superset_access: str | None = None

    @field_validator("role")
    @classmethod
    def check_role(cls, v: str) -> str:
        if v not in {"admin", "user"}:
            raise ValueError("role must be 'admin' or 'user'")
        return v

    @field_validator("superset_access")
    @classmethod
    def _check_superset_access(cls, v: str | None) -> str | None:
        return _check_superset_access(v)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        if v is not None:
            if "@" not in v or "." not in v.split("@")[-1]:
                raise ValueError("Invalid email format")
        return v

    @field_validator("role_id")
    @classmethod
    def check_role_id(cls, v: str | None) -> str | None:
        if v is not None:
            validate_uuid(v, "role_id")
        return v


class UpdateUserRequest(BaseModel):
    role: str | None = None
    role_id: str | None = None
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    all_tenants: bool | None = None
    is_active: bool | None = None
    timezone: str | None = Field(default=None, max_length=50)
    superset_access: str | None = None

    @field_validator("role")
    @classmethod
    def check_role(cls, v: str | None) -> str | None:
        if v is not None and v not in {"admin", "user"}:
            raise ValueError("role must be 'admin' or 'user'")
        return v

    @field_validator("superset_access")
    @classmethod
    def _check_superset_access(cls, v: str | None) -> str | None:
        return _check_superset_access(v)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        if v is not None:
            if "@" not in v or "." not in v.split("@")[-1]:
                raise ValueError("Invalid email format")
        return v

    @field_validator("role_id")
    @classmethod
    def check_role_id(cls, v: str | None) -> str | None:
        if v is not None:
            validate_uuid(v, "role_id")
        return v


class UpdateTimezoneRequest(BaseModel):
    timezone: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z_/]+$")


VALID_PAGE_SIZES = {50, 100, 250, 500}
VALID_SCROLL_MODES = {"paginated", "infinite"}


class UpdateTablePreferencesRequest(BaseModel):
    table_page_size: int | None = Field(default=None, ge=10, le=500)
    table_scroll_mode: str | None = Field(default=None, max_length=20)


VALID_IDLE_TIMEOUTS = {15, 30, 60, 120, 240, 480, 0}

VALID_IFACE_STATUS_FILTERS = {"all", "up", "down", "unmonitored"}
VALID_IFACE_TRAFFIC_UNITS = {"auto", "kbps", "mbps", "gbps", "pct"}
VALID_IFACE_CHART_METRICS = {"traffic", "errors", "discards"}
VALID_IFACE_TIME_RANGES = {"1h", "6h", "24h", "7d", "30d"}


class UpdateInterfacePreferencesRequest(BaseModel):
    iface_status_filter: str | None = Field(default=None)
    iface_traffic_unit: str | None = Field(default=None)
    iface_chart_metric: str | None = Field(default=None)
    iface_time_range: str | None = Field(default=None)


class UpdateUiPreferencesRequest(BaseModel):
    """Replace the user's ui_preferences blob wholesale.

    Shape is opaque on the backend — the frontend validates the schema
    version and per-column-config invariants before POSTing.
    """
    ui_preferences: dict


class UpdateIdleTimeoutRequest(BaseModel):
    idle_timeout_minutes: int | None = Field(
        default=None,
        description="Idle timeout in minutes. NULL = use system default. 0 = never.",
    )


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6, max_length=128)


class AssignTenantRequest(BaseModel):
    tenant_id: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.put("/me/table-preferences")
async def update_my_table_preferences(
    request: UpdateTablePreferencesRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update the current user's table display preferences."""
    user = await db.get(User, uuid.UUID(auth["user_id"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if request.table_page_size is not None:
        if request.table_page_size not in VALID_PAGE_SIZES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"table_page_size must be one of {sorted(VALID_PAGE_SIZES)}",
            )
        user.table_page_size = request.table_page_size

    if request.table_scroll_mode is not None:
        if request.table_scroll_mode not in VALID_SCROLL_MODES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"table_scroll_mode must be one of {sorted(VALID_SCROLL_MODES)}",
            )
        user.table_scroll_mode = request.table_scroll_mode

    user.updated_at = utc_now()
    return {
        "status": "success",
        "data": {
            "table_page_size": user.table_page_size,
            "table_scroll_mode": user.table_scroll_mode,
        },
    }


@router.put("/me/idle-timeout")
async def update_my_idle_timeout(
    request: UpdateIdleTimeoutRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update the current user's idle timeout preference."""
    user = await db.get(User, uuid.UUID(auth["user_id"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if request.idle_timeout_minutes is not None and request.idle_timeout_minutes not in VALID_IDLE_TIMEOUTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"idle_timeout_minutes must be one of {sorted(VALID_IDLE_TIMEOUTS)} or null",
        )

    user.idle_timeout_minutes = request.idle_timeout_minutes
    user.updated_at = utc_now()
    return {
        "status": "success",
        "data": {"idle_timeout_minutes": user.idle_timeout_minutes},
    }


@router.put("/me/timezone")
async def update_my_timezone(
    request: UpdateTimezoneRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update the current user's timezone preference."""
    user = await db.get(User, uuid.UUID(auth["user_id"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.timezone = request.timezone
    user.updated_at = utc_now()
    return {"status": "success", "data": {"timezone": user.timezone}}


@router.put("/me/interface-preferences")
async def update_my_interface_preferences(
    request: UpdateInterfacePreferencesRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update the current user's interface tab display preferences."""
    user = await db.get(User, uuid.UUID(auth["user_id"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    validators = {
        "iface_status_filter": VALID_IFACE_STATUS_FILTERS,
        "iface_traffic_unit": VALID_IFACE_TRAFFIC_UNITS,
        "iface_chart_metric": VALID_IFACE_CHART_METRICS,
        "iface_time_range": VALID_IFACE_TIME_RANGES,
    }
    for field, valid_set in validators.items():
        val = getattr(request, field)
        if val is not None:
            if val not in valid_set:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{field} must be one of {sorted(valid_set)}",
                )
            setattr(user, field, val)

    user.updated_at = utc_now()
    return {
        "status": "success",
        "data": {
            "iface_status_filter": user.iface_status_filter,
            "iface_traffic_unit": user.iface_traffic_unit,
            "iface_chart_metric": user.iface_chart_metric,
            "iface_time_range": user.iface_time_range,
        },
    }


# Cap the stored blob so a single user can't balloon their row. 32 KB is
# ample for dozens of tables × dozens of columns each.
_UI_PREFERENCES_MAX_BYTES = 32 * 1024


@router.put("/me/ui-preferences")
async def update_my_ui_preferences(
    request: UpdateUiPreferencesRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Replace the current user's ui_preferences blob.

    Schema is opaque on the backend — we only enforce a size cap and that
    the top-level value is a dict. The frontend is responsible for its
    own versioning and migration under `ui_preferences.tables[id].v1`.
    """
    import json

    user = await db.get(User, uuid.UUID(auth["user_id"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    payload = request.ui_preferences
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ui_preferences must be a JSON object",
        )

    encoded = json.dumps(payload, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _UI_PREFERENCES_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"ui_preferences exceeds {_UI_PREFERENCES_MAX_BYTES} bytes",
        )

    user.ui_preferences = payload
    user.updated_at = utc_now()
    return {
        "status": "success",
        "data": {"ui_preferences": user.ui_preferences},
    }


VALID_DEFAULT_PAGES = {
    "/", "/system-health", "/devices", "/device-types", "/assignments",
    "/apps", "/connectors", "/python-modules", "/templates", "/credentials",
    "/labels", "/packs", "/alerts", "/events", "/automations",
    "/analytics/explorer", "/analytics/dashboards", "/upgrades", "/settings",
}


class UpdateDefaultPageRequest(BaseModel):
    default_page: str = Field(min_length=1, max_length=255)


@router.put("/me/default-page")
async def update_my_default_page(
    request: UpdateDefaultPageRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Update the current user's default landing page."""
    if request.default_page not in VALID_DEFAULT_PAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid default_page. Must be one of: {sorted(VALID_DEFAULT_PAGES)}",
        )
    user = await db.get(User, uuid.UUID(auth["user_id"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.default_page = request.default_page
    user.updated_at = utc_now()
    return {"status": "success", "data": {"default_page": user.default_page}}


@router.put("/me/password")
async def change_my_password(
    request: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Change the current user's password (self-service)."""
    from monctl_central.auth.service import hash_password, verify_password

    user = await db.get(User, uuid.UUID(auth["user_id"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not verify_password(request.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    user.password_hash = hash_password(request.new_password)
    user.updated_at = utc_now()
    return {"status": "success", "data": {"message": "Password changed successfully"}}


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


@router.post("/{user_id}/reset-password")
async def admin_reset_password(
    user_id: str,
    request: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Admin sets a new password for another user. Bumps token_version so
    every outstanding access + refresh JWT is invalidated — the target user
    is forced to re-authenticate with the new password."""
    from monctl_central.auth.service import hash_password

    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = hash_password(request.new_password)
    user.token_version = (user.token_version or 0) + 1
    user.updated_at = utc_now()
    await db.flush()

    # Drop any cached auth state so the new token_version is seen immediately.
    from monctl_central.cache import invalidate_user_auth_cache
    await invalidate_user_auth_cache(db, user_id)

    return {
        "status": "success",
        "data": {
            "user_id": str(user.id),
            "username": user.username,
            "message": "Password reset; existing sessions invalidated",
        },
    }


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """List all users (admin only)."""
    from sqlalchemy.orm import selectinload
    users = (await db.execute(
        select(User).options(selectinload(User.assigned_role)).order_by(User.username)
    )).scalars().all()
    result = []
    for u in users:
        # Count tenant assignments
        tenant_count = (await db.execute(
            select(UserTenant).where(UserTenant.user_id == u.id)
        )).scalars()
        tenants = list(tenant_count)
        row = _fmt_user(u)
        row["tenant_count"] = len(tenants)
        result.append(row)
    return {"status": "success", "data": result}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Create a new user (admin only)."""
    from monctl_central.auth.service import hash_password

    # Check for duplicate username
    existing = (
        await db.execute(select(User).where(User.username == request.username))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{request.username}' already exists",
        )

    user = User(
        username=request.username,
        password_hash=hash_password(request.password),
        role=request.role,
        display_name=request.display_name,
        email=request.email,
        all_tenants=request.all_tenants,
        superset_access=request.superset_access,
    )
    if request.role_id:
        user.role_id = uuid.UUID(request.role_id)
    db.add(user)
    await db.flush()
    # Reload with relationship
    from sqlalchemy.orm import selectinload
    user = (await db.execute(
        select(User).options(selectinload(User.assigned_role)).where(User.id == user.id)
    )).scalar_one()
    return {"status": "success", "data": _fmt_user(user)}


@router.get("/{user_id}")
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Get a user by ID including their tenant assignments (admin only)."""
    from sqlalchemy.orm import selectinload
    user = (await db.execute(
        select(User).options(selectinload(User.assigned_role)).where(User.id == uuid.UUID(user_id))
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Load tenant assignments
    tenant_rows = (await db.execute(
        select(UserTenant, Tenant)
        .join(Tenant, UserTenant.tenant_id == Tenant.id)
        .where(UserTenant.user_id == user.id)
    )).all()
    tenants = [{"id": str(t.id), "name": t.name} for _, t in tenant_rows]

    data = _fmt_user(user)
    data["tenants"] = tenants
    return {"status": "success", "data": data}


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Update a user (admin only)."""
    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    auth_changed = False
    if request.role is not None:
        if user.role != request.role:
            auth_changed = True
        user.role = request.role
    if request.role_id is not None:
        new_role_id = uuid.UUID(request.role_id) if request.role_id else None
        if user.role_id != new_role_id:
            auth_changed = True
        user.role_id = new_role_id
    if request.display_name is not None:
        user.display_name = request.display_name
    if request.email is not None:
        user.email = request.email
    if request.all_tenants is not None:
        if user.all_tenants != request.all_tenants:
            auth_changed = True
        user.all_tenants = request.all_tenants
    if request.is_active is not None:
        if user.is_active and not request.is_active:
            auth_changed = True
        user.is_active = request.is_active
    if request.timezone is not None:
        user.timezone = request.timezone
    if request.superset_access is not None:
        # Doesn't affect MonCTL auth, only the BI tier mapped at next OAuth
        # login. No token_version bump — Superset's before_request hook
        # re-syncs roles via AUTH_ROLES_SYNC_AT_LOGIN on next sign-in.
        user.superset_access = request.superset_access
    if auth_changed:
        # Revoke every outstanding JWT for this user — they'll need to
        # re-auth to pick up the new role/tenants/active state.
        user.token_version = (user.token_version or 0) + 1
    user.updated_at = utc_now()
    await db.flush()

    if auth_changed:
        from monctl_central.cache import invalidate_user_auth_cache
        await invalidate_user_auth_cache(db, user_id)
    # Reload with relationship
    from sqlalchemy.orm import selectinload
    user = (await db.execute(
        select(User).options(selectinload(User.assigned_role)).where(User.id == uuid.UUID(user_id))
    )).scalar_one()

    return {"status": "success", "data": _fmt_user(user)}


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Delete a user (admin only). Cannot delete yourself."""
    if auth.get("user_id") == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    from monctl_central.cache import invalidate_user_auth_cache
    await invalidate_user_auth_cache(db, user_id)

    await db.delete(user)


# ── Tenant assignment endpoints ───────────────────────────────────────────────

@router.get("/{user_id}/tenants")
async def get_user_tenants(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """List tenants assigned to a user (admin only)."""
    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    rows = (await db.execute(
        select(UserTenant, Tenant)
        .join(Tenant, UserTenant.tenant_id == Tenant.id)
        .where(UserTenant.user_id == user.id)
        .order_by(Tenant.name)
    )).all()
    tenants = [{"id": str(t.id), "name": t.name} for _, t in rows]
    return {"status": "success", "data": tenants}


@router.post("/{user_id}/tenants", status_code=status.HTTP_201_CREATED)
async def assign_tenant(
    user_id: str,
    request: AssignTenantRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Assign a tenant to a user (admin only)."""
    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    tenant = await db.get(Tenant, uuid.UUID(request.tenant_id))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # Check if already assigned
    existing = await db.get(
        UserTenant, (uuid.UUID(user_id), uuid.UUID(request.tenant_id))
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant already assigned to this user",
        )

    assoc = UserTenant(
        user_id=uuid.UUID(user_id),
        tenant_id=uuid.UUID(request.tenant_id),
    )
    db.add(assoc)
    await db.flush()
    return {"status": "success", "data": {"tenant_id": request.tenant_id}}


@router.delete("/{user_id}/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tenant(
    user_id: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Remove a tenant assignment from a user (admin only)."""
    assoc = await db.get(
        UserTenant, (uuid.UUID(user_id), uuid.UUID(tenant_id))
    )
    if assoc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant assignment not found",
        )
    await db.delete(assoc)
