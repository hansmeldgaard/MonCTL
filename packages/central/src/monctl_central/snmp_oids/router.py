"""SNMP OID catalog endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_admin, require_auth
from monctl_central.storage.models import SnmpOid

router = APIRouter()


class SnmpOidCreate(BaseModel):
    name: str
    oid: str
    description: str | None = None


class SnmpOidUpdate(BaseModel):
    name: str | None = None
    oid: str | None = None
    description: str | None = None


def _format_oid(o: SnmpOid) -> dict:
    return {
        "id": str(o.id),
        "name": o.name,
        "oid": o.oid,
        "description": o.description,
    }


@router.get("")
async def list_snmp_oids(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """List all SNMP OIDs in the catalog."""
    oids = (await db.execute(select(SnmpOid).order_by(SnmpOid.name))).scalars().all()
    return {"status": "success", "data": [_format_oid(o) for o in oids]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_snmp_oid(
    request: SnmpOidCreate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Create a new SNMP OID catalog entry (admin only)."""
    oid = SnmpOid(name=request.name, oid=request.oid, description=request.description)
    db.add(oid)
    await db.flush()
    return {"status": "success", "data": _format_oid(oid)}


@router.put("/{oid_id}")
async def update_snmp_oid(
    oid_id: str,
    request: SnmpOidUpdate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Update an SNMP OID catalog entry (admin only)."""
    oid = await db.get(SnmpOid, uuid.UUID(oid_id))
    if oid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SNMP OID not found")
    if request.name is not None:
        oid.name = request.name
    if request.oid is not None:
        oid.oid = request.oid
    if request.description is not None:
        oid.description = request.description
    await db.flush()
    return {"status": "success", "data": _format_oid(oid)}


@router.delete("/{oid_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snmp_oid(
    oid_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_admin),
):
    """Delete an SNMP OID catalog entry (admin only)."""
    oid = await db.get(SnmpOid, uuid.UUID(oid_id))
    if oid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SNMP OID not found")
    await db.delete(oid)
