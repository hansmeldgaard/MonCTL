"""Role management endpoints (admin only)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_db, require_admin
from monctl_central.storage.models import Role, RolePermission, User
from monctl_common.utils import utc_now

router = APIRouter()

VALID_RESOURCES = {
    "device", "app", "assignment", "credential", "alert",
    "automation", "event", "connector", "dashboard",
    "collector", "tenant", "user", "template", "settings", "result",
    "audit",
}

VALID_ACTIONS = {"view", "create", "edit", "delete", "manage"}

RESOURCE_ACTIONS: dict[str, list[str]] = {
    "device": ["view", "create", "edit", "delete"],
    "app": ["view", "create", "edit", "delete"],
    "assignment": ["view", "create", "edit", "delete"],
    "credential": ["view", "create", "edit", "delete"],
    "alert": ["view", "create", "edit", "delete"],
    "automation": ["view", "create", "edit", "delete"],
    "event": ["view", "manage"],
    "connector": ["view", "create", "edit", "delete"],
    "dashboard": ["view", "create", "edit", "delete"],
    "collector": ["view", "manage"],
    "tenant": ["view", "manage"],
    "user": ["view", "manage"],
    "template": ["view", "create", "edit", "delete"],
    "settings": ["view", "manage"],
    "result": ["view"],
    "audit": ["view"],
}


def _fmt_permission(p: RolePermission) -> dict:
    return {"id": str(p.id), "resource": p.resource, "action": p.action}


def _fmt_role(r: Role) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "is_system": r.is_system,
        "permissions": [_fmt_permission(p) for p in r.permissions],
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


class PermissionEntry(BaseModel):
    resource: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=32)


class CreateRoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    permissions: list[PermissionEntry] = Field(default_factory=list, max_length=200)


class UpdateRoleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    permissions: list[PermissionEntry] | None = Field(default=None, max_length=200)


@router.get("")
async def list_roles(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """List all roles with their permissions."""
    roles = (await db.execute(
        select(Role).options(selectinload(Role.permissions)).order_by(Role.name)
    )).scalars().all()
    return {"status": "success", "data": [_fmt_role(r) for r in roles]}


@router.get("/resources")
async def list_resources(auth: dict = Depends(require_admin)):
    """List all valid resource/action combinations."""
    return {"status": "success", "data": RESOURCE_ACTIONS}


@router.get("/{role_id}")
async def get_role(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Get a single role with permissions."""
    role = (await db.execute(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == uuid.UUID(role_id))
    )).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return {"status": "success", "data": _fmt_role(role)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_role(
    req: CreateRoleRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Create a new role with permissions."""
    for p in req.permissions:
        if p.resource not in VALID_RESOURCES:
            raise HTTPException(status_code=422, detail=f"Invalid resource: {p.resource}")
        if p.action not in VALID_ACTIONS:
            raise HTTPException(status_code=422, detail=f"Invalid action: {p.action}")

    role = Role(name=req.name, description=req.description)
    db.add(role)
    await db.flush()

    for p in req.permissions:
        db.add(RolePermission(role_id=role.id, resource=p.resource, action=p.action))
    await db.flush()

    role = (await db.execute(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
    )).scalar_one()
    return {"status": "success", "data": _fmt_role(role)}


@router.put("/{role_id}")
async def update_role(
    role_id: str,
    req: UpdateRoleRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Update a role. If permissions are provided, they replace all existing permissions."""
    role = (await db.execute(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == uuid.UUID(role_id))
    )).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    if req.name is not None:
        role.name = req.name
    if req.description is not None:
        role.description = req.description
    role.updated_at = utc_now()

    if req.permissions is not None:
        for p in req.permissions:
            if p.resource not in VALID_RESOURCES:
                raise HTTPException(status_code=422, detail=f"Invalid resource: {p.resource}")
            if p.action not in VALID_ACTIONS:
                raise HTTPException(status_code=422, detail=f"Invalid action: {p.action}")

        for existing in list(role.permissions):
            await db.delete(existing)
        await db.flush()

        for p in req.permissions:
            db.add(RolePermission(role_id=role.id, resource=p.resource, action=p.action))
        await db.flush()

    # Invalidate permission cache + user-bound API key cache + every
    # outstanding JWT for users with this role. The api_key cache payload
    # embeds the permissions list and access tokens carry stale perms via
    # their role claim, so both need to be dropped on a permission edit.
    from monctl_central.cache import invalidate_user_auth_cache

    user_rows = (await db.execute(
        select(User).where(User.role_id == role.id)
    )).scalars().all()
    for u in user_rows:
        u.token_version = (u.token_version or 0) + 1
    if user_rows:
        await db.flush()
    for u in user_rows:
        await invalidate_user_auth_cache(db, str(u.id))

    role = (await db.execute(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
    )).scalar_one()
    return {"status": "success", "data": _fmt_role(role)}


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Delete a role. System roles cannot be deleted."""
    role = await db.get(Role, uuid.UUID(role_id))
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")
    await db.delete(role)
