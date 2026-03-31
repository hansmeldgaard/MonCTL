"""Credential template management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_permission
from monctl_central.storage.models import CredentialTemplate, CredentialKey, CredentialType
from monctl_common.utils import utc_now

router = APIRouter()


class TemplateField(BaseModel):
    key_name: str = Field(min_length=1, max_length=64)
    required: bool = True
    default_value: str | None = Field(default=None, max_length=1000)
    display_order: int = Field(default=0, ge=0, le=999)


class CreateCredentialTemplateRequest(BaseModel):
    name: str = Field(max_length=64)
    credential_type: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    fields: list[TemplateField] = Field(min_length=1, max_length=50)


class UpdateCredentialTemplateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    credential_type: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    fields: list[TemplateField] | None = Field(default=None, min_length=1, max_length=50)


def _fmt(t: CredentialTemplate) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "credential_type": t.credential_type,
        "description": t.description,
        "fields": t.fields,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


async def _validate_credential_type(credential_type: str, db: AsyncSession) -> None:
    """Ensure the credential_type exists in the credential_types table."""
    exists = (await db.execute(
        select(CredentialType).where(CredentialType.name == credential_type)
    )).scalar_one_or_none()
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown credential type: '{credential_type}'. "
                   "Create it first via /v1/credentials/types.",
        )


async def _validate_fields(fields: list[TemplateField], db: AsyncSession) -> None:
    """Ensure all referenced key_names exist and defaults are valid for enum keys."""
    key_names = {f.key_name for f in fields}
    rows = (await db.execute(
        select(CredentialKey).where(CredentialKey.name.in_(key_names))
    )).scalars().all()
    keys_by_name = {k.name: k for k in rows}

    missing = key_names - set(keys_by_name.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown credential keys: {', '.join(sorted(missing))}. "
                   "Create them first via /v1/credential-keys.",
        )

    # Validate default_value against enum_values
    for f in fields:
        key_def = keys_by_name[f.key_name]
        if f.default_value is not None and key_def.key_type == "enum" and key_def.enum_values:
            if f.default_value not in key_def.enum_values:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid default for '{f.key_name}': '{f.default_value}'. "
                           f"Must be one of: {', '.join(key_def.enum_values)}",
                )


@router.get("")
async def list_credential_templates(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("credential", "view")),
):
    rows = (await db.execute(
        select(CredentialTemplate).order_by(CredentialTemplate.name)
    )).scalars().all()
    return {"status": "success", "data": [_fmt(t) for t in rows]}


@router.get("/{template_id}")
async def get_credential_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("credential", "view")),
):
    t = await db.get(CredentialTemplate, uuid.UUID(template_id))
    if t is None:
        raise HTTPException(status_code=404, detail="Credential template not found")
    return {"status": "success", "data": _fmt(t)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_credential_template(
    request: CreateCredentialTemplateRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("credential", "create")),
):
    existing = (await db.execute(
        select(CredentialTemplate).where(CredentialTemplate.name == request.name)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Template '{request.name}' already exists")

    await _validate_credential_type(request.credential_type, db)
    await _validate_fields(request.fields, db)

    t = CredentialTemplate(
        name=request.name,
        credential_type=request.credential_type,
        description=request.description,
        fields=[f.model_dump() for f in request.fields],
    )
    db.add(t)
    await db.flush()
    return {"status": "success", "data": _fmt(t)}


@router.put("/{template_id}")
async def update_credential_template(
    template_id: str,
    request: UpdateCredentialTemplateRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("credential", "edit")),
):
    t = await db.get(CredentialTemplate, uuid.UUID(template_id))
    if t is None:
        raise HTTPException(status_code=404, detail="Credential template not found")

    if request.name is not None:
        t.name = request.name
    if request.credential_type is not None:
        await _validate_credential_type(request.credential_type, db)
        t.credential_type = request.credential_type
    if request.description is not None:
        t.description = request.description
    if request.fields is not None:
        await _validate_fields(request.fields, db)
        t.fields = [f.model_dump() for f in request.fields]
    t.updated_at = utc_now()
    return {"status": "success", "data": _fmt(t)}


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("credential", "delete")),
):
    t = await db.get(CredentialTemplate, uuid.UUID(template_id))
    if t is None:
        raise HTTPException(status_code=404, detail="Credential template not found")
    await db.delete(t)
