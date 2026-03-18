"""Pack CRUD + import/export endpoints."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import Pack, PackVersion
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


# ── List packs ──────────────────────────────────────────────


@router.get("")
async def list_packs(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    packs = (await db.execute(select(Pack).order_by(Pack.name))).scalars().all()
    result = []
    for p in packs:
        counts = await get_entity_counts(p.id, db)
        result.append(_fmt_pack(p, counts))
    return {"status": "success", "data": result}


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
    pack_uid: str
    name: str
    version: str
    description: str | None = None
    author: str | None = None
    entity_ids: dict[str, list[str]]


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
