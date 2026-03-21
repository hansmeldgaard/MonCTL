"""Pack CRUD + import/export endpoints."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from monctl_common.validators import validate_semver, validate_slug
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import (
    Pack, PackVersion, App, AppAlertDefinition, CredentialTemplate,
    SnmpOid, Template, DeviceType, LabelKey, Connector,
)
from monctl_central.packs.schema import validate_pack_schema
from monctl_central.packs.service import (
    ENTITY_MAP,
    export_pack,
    get_entity_counts,
    import_pack,
    preview_import,
    _section_to_model,
    _build_manifest,
)
from monctl_common.utils import utc_now

router = APIRouter()


def _fmt_pack(p: Pack, entity_counts: dict | None = None) -> dict:
    return {
        "id": str(p.id),
        "pack_uid": p.pack_uid,
        "name": p.name,
        "description": p.description,
        "author": p.author,
        "current_version": p.current_version,
        "installed_at": p.installed_at.isoformat() if p.installed_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "entity_counts": entity_counts or {},
    }


def _fmt_version(v: PackVersion) -> dict:
    return {
        "id": str(v.id),
        "version": v.version,
        "manifest": v.manifest,
        "changelog": v.changelog,
        "imported_at": v.imported_at.isoformat() if v.imported_at else None,
    }


# ── Available entities (for Create Pack dialog) ─────────────


@router.get("/available-entities")
async def list_available_entities(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all entities that can be added to a pack, grouped by type."""
    result = {}

    _SECTIONS = [
        ("apps", App, "name"),
        ("alert_rules", AppAlertDefinition, "name"),
        ("credential_templates", CredentialTemplate, "name"),
        ("snmp_oids", SnmpOid, "name"),
        ("device_templates", Template, "name"),
        ("device_types", DeviceType, "name"),
        ("label_keys", LabelKey, "key"),
        ("connectors", Connector, "name"),
    ]

    for section, model, name_field in _SECTIONS:
        rows = (await db.execute(
            select(model).order_by(getattr(model, name_field))
        )).scalars().all()
        result[section] = [
            {
                "id": str(r.id),
                "name": getattr(r, name_field),
                "description": getattr(r, "description", None),
                "pack_id": str(r.pack_id) if r.pack_id else None,
            }
            for r in rows
        ]

    return {"status": "success", "data": result}


# ── List packs ──────────────────────────────────────────────


SORT_MAP = {
    "name": Pack.name,
    "pack_uid": Pack.pack_uid,
    "version": Pack.current_version,
    "created_at": Pack.installed_at,
}


@router.get("")
async def list_packs(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
    name: str | None = Query(default=None),
    pack_uid: str | None = Query(default=None),
    description: str | None = Query(default=None),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
):
    base_stmt = select(Pack)

    if name:
        base_stmt = base_stmt.where(Pack.name.ilike(f"%{name}%"))
    if pack_uid:
        base_stmt = base_stmt.where(Pack.pack_uid.ilike(f"%{pack_uid}%"))
    if description:
        base_stmt = base_stmt.where(Pack.description.ilike(f"%{description}%"))

    sort_col = SORT_MAP.get(sort_by, Pack.name)
    base_stmt = base_stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    count_stmt = select(sa.func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = base_stmt.offset(offset).limit(limit)
    packs = (await db.execute(stmt)).scalars().all()

    data = []
    for p in packs:
        counts = await get_entity_counts(p.id, db)
        data.append(_fmt_pack(p, counts))

    return {
        "status": "success",
        "data": data,
        "meta": {"limit": limit, "offset": offset, "count": len(data), "total": total},
    }


# ── Get pack detail ─────────────────────────────────────────


@router.get("/{pack_id}")
async def get_pack(
    pack_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    pack = await db.get(Pack, uuid.UUID(pack_id))
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")

    counts = await get_entity_counts(pack.id, db)
    versions = (await db.execute(
        select(PackVersion)
        .where(PackVersion.pack_id == pack.id)
        .order_by(PackVersion.imported_at.desc())
    )).scalars().all()

    data = _fmt_pack(pack, counts)
    data["versions"] = [_fmt_version(v) for v in versions]
    return {"status": "success", "data": data}


# ── Export pack ─────────────────────────────────────────────


@router.get("/{pack_id}/export")
async def export_pack_endpoint(
    pack_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    try:
        result = await export_pack(uuid.UUID(pack_id), db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success", "data": result}


# ── Preview import ──────────────────────────────────────────


class PreviewImportRequest(BaseModel):
    pack_data: dict


@router.post("/preview")
async def preview_import_endpoint(
    req: PreviewImportRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    validate_pack_schema(req.pack_data)
    result = await preview_import(req.pack_data, db)
    return {"status": "success", "data": result}


# ── Import pack ─────────────────────────────────────────────


class ImportPackRequest(BaseModel):
    pack_data: dict
    resolutions: dict[str, str]


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_pack_endpoint(
    req: ImportPackRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    validate_pack_schema(req.pack_data)
    result = await import_pack(req.pack_data, req.resolutions, db)
    return {"status": "success", "data": result}


# ── Create pack from existing entities ──────────────────────


class CreatePackRequest(BaseModel):
    pack_uid: str = Field(min_length=2, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=2000)
    author: str | None = Field(default=None, max_length=255)
    entity_ids: dict[str, list[str]]

    @field_validator("pack_uid")
    @classmethod
    def check_pack_uid(cls, v: str) -> str:
        return validate_slug(v, "pack_uid")

    @field_validator("version")
    @classmethod
    def check_version(cls, v: str) -> str:
        return validate_semver(v)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_pack(
    req: CreatePackRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", req.pack_uid):
        raise HTTPException(
            status_code=400,
            detail="pack_uid must be lowercase alphanumeric with hyphens",
        )

    existing = (await db.execute(
        select(Pack).where(Pack.pack_uid == req.pack_uid)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Pack UID already exists")

    pack = Pack(
        pack_uid=req.pack_uid,
        name=req.name,
        description=req.description,
        author=req.author,
        current_version=req.version,
    )
    db.add(pack)
    await db.flush()

    # Tag selected entities with pack_id
    manifest_names: dict[str, list[str]] = {}
    for section, ids in req.entity_ids.items():
        model = _section_to_model(section)
        if model is None:
            continue
        names = []
        name_field = "key" if section == "label_keys" else "name"
        for entity_id in ids:
            entity = await db.get(model, uuid.UUID(entity_id))
            if entity:
                entity.pack_id = pack.id
                names.append(getattr(entity, name_field, ""))
        if names:
            manifest_names[section] = names

    pack_version = PackVersion(
        pack_id=pack.id,
        version=req.version,
        manifest=manifest_names,
    )
    db.add(pack_version)
    await db.flush()

    return {"status": "success", "data": {"id": str(pack.id), "pack_uid": pack.pack_uid}}


# ── Delete pack ─────────────────────────────────────────────


@router.delete("/{pack_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pack(
    pack_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    pack = await db.get(Pack, uuid.UUID(pack_id))
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    await db.delete(pack)
