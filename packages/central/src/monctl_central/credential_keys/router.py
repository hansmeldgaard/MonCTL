"""Credential key management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_permission
from monctl_central.storage.models import CredentialKey

router = APIRouter()

VALID_KEY_TYPES = {"plain", "secret", "enum"}


class CreateCredentialKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    key_type: str = Field(default="plain", description="plain | secret | enum")
    enum_values: list[str] | None = Field(
        default=None, description="Allowed values when key_type is 'enum'"
    )

    @field_validator("key_type")
    @classmethod
    def check_key_type(cls, v: str) -> str:
        if v not in {"plain", "secret", "enum"}:
            raise ValueError("key_type must be one of: plain, secret, enum")
        return v

    @field_validator("enum_values")
    @classmethod
    def check_enum_values(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            if len(v) < 2:
                raise ValueError("enum_values must have at least 2 values")
            if len(v) != len(set(v)):
                raise ValueError("enum_values must be unique")
            for val in v:
                if len(val) > 255:
                    raise ValueError("Each enum value must be at most 255 characters")
        return v


class UpdateCredentialKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    key_type: str | None = None
    enum_values: list[str] | None = None

    @field_validator("key_type")
    @classmethod
    def check_key_type(cls, v: str | None) -> str | None:
        if v is not None and v not in {"plain", "secret", "enum"}:
            raise ValueError("key_type must be one of: plain, secret, enum")
        return v

    @field_validator("enum_values")
    @classmethod
    def check_enum_values(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            if len(v) < 2:
                raise ValueError("enum_values must have at least 2 values")
            if len(v) != len(set(v)):
                raise ValueError("enum_values must be unique")
            for val in v:
                if len(val) > 255:
                    raise ValueError("Each enum value must be at most 255 characters")
        return v


def _fmt(k: CredentialKey) -> dict:
    return {
        "id": str(k.id),
        "name": k.name,
        "description": k.description,
        "key_type": k.key_type,
        "is_secret": k.is_secret,
        "enum_values": k.enum_values,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


def _validate_key_type(key_type: str, enum_values: list[str] | None) -> None:
    if key_type not in VALID_KEY_TYPES:
        raise HTTPException(400,
            f"Invalid key_type '{key_type}'. Must be: {', '.join(sorted(VALID_KEY_TYPES))}")
    if key_type == "enum":
        if not enum_values or len(enum_values) < 2:
            raise HTTPException(400, "Enum requires at least 2 values")
        if len(enum_values) != len(set(enum_values)):
            raise HTTPException(400, "Enum values must be unique")
    elif enum_values is not None:
        raise HTTPException(400,
            f"enum_values only allowed when key_type is 'enum', not '{key_type}'")


@router.get("")
async def list_credential_keys(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("credential", "view")),
):
    """List all credential keys."""
    rows = (await db.execute(select(CredentialKey).order_by(CredentialKey.name))).scalars().all()
    return {"status": "success", "data": [_fmt(k) for k in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_credential_key(
    request: CreateCredentialKeyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("credential", "create")),
):
    """Create a new credential key definition."""
    existing = (
        await db.execute(select(CredentialKey).where(CredentialKey.name == request.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Credential key '{request.name}' already exists",
        )

    _validate_key_type(request.key_type, request.enum_values)
    key = CredentialKey(
        name=request.name,
        description=request.description,
        key_type=request.key_type,
        enum_values=request.enum_values,
    )
    db.add(key)
    await db.flush()
    return {"status": "success", "data": _fmt(key)}


@router.put("/{key_id}")
async def update_credential_key(
    key_id: str,
    request: UpdateCredentialKeyRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("credential", "edit")),
):
    """Update a credential key."""
    key = await db.get(CredentialKey, uuid.UUID(key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential key not found")

    # Resolve final state for cross-field validation
    final_type = request.key_type if request.key_type is not None else key.key_type
    final_enums = request.enum_values if request.enum_values is not None else key.enum_values
    # If switching away from enum, clear enum_values
    if request.key_type is not None and request.key_type != "enum":
        final_enums = None
    _validate_key_type(final_type, final_enums)

    if request.name is not None:
        key.name = request.name
    if request.description is not None:
        key.description = request.description
    if request.key_type is not None:
        key.key_type = request.key_type
        if request.key_type != "enum":
            key.enum_values = None
    if request.enum_values is not None:
        key.enum_values = request.enum_values

    return {"status": "success", "data": _fmt(key)}


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("credential", "delete")),
):
    """Delete a credential key."""
    key = await db.get(CredentialKey, uuid.UUID(key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential key not found")
    await db.delete(key)
