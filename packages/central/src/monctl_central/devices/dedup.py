"""Device duplicate-detection helpers.

Used by the device create + bulk-import endpoints (Phase A) and by the
discovery service post-poll (Phase B) to surface devices that look like
duplicates of an existing one.
"""

from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import Device


async def find_address_duplicates(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    addresses: Iterable[str],
    exclude_id: uuid.UUID | None = None,
) -> dict[str, list[Device]]:
    """Return a mapping of address -> existing devices that share that address
    within the given tenant scope.

    Tenant scoping treats NULL tenant_id as its own bucket (NULL matches NULL,
    not arbitrary tenants), which mirrors how the rest of the codebase treats
    the "no tenant" case.
    """
    addrs = [a for a in addresses if a]
    if not addrs:
        return {}

    stmt = select(Device).where(Device.address.in_(addrs))
    if tenant_id is None:
        stmt = stmt.where(Device.tenant_id.is_(None))
    else:
        stmt = stmt.where(Device.tenant_id == tenant_id)
    if exclude_id is not None:
        stmt = stmt.where(Device.id != exclude_id)

    rows = (await db.execute(stmt)).scalars().all()
    out: dict[str, list[Device]] = {}
    for d in rows:
        out.setdefault(d.address, []).append(d)
    return out


def serialize_candidate(device: Device) -> dict:
    """Compact representation of a duplicate-candidate device for API responses."""
    meta = device.metadata_ or {}
    return {
        "id": str(device.id),
        "name": device.name,
        "address": device.address,
        "tenant_id": str(device.tenant_id) if device.tenant_id else None,
        "sys_name": meta.get("sys_name"),
        "sys_object_id": meta.get("sys_object_id"),
        "serial": meta.get("serial"),
    }
