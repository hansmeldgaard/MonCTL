"""Device discovery trigger endpoint — queues SNMP discovery via collector."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_permission
from monctl_central.storage.models import Collector, Device
from monctl_central.cache import set_discovery_flag
from monctl_central.ws.router import manager as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{device_id}/discover")
async def trigger_discovery(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_permission("device", "edit")),
):
    """Queue SNMP discovery for a device.

    Sets a Redis flag that causes the collector API to inject a one-shot
    snmp_discovery job on the next job fetch. The collector runs the SNMP
    queries and returns results via the normal ingest pipeline. Central
    then matches the results against discovery rules and updates the device.

    After setting the flag, sends a config_reload command via WebSocket to
    collectors in the device's group so they sync jobs immediately instead
    of waiting up to 60s for the next poll cycle.

    The response is immediate (202 Accepted) — discovery results will appear
    in device metadata once the collector completes the job.
    """
    device = await db.get(Device, uuid.UUID(device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    # Validate: device needs a collector group
    if not device.collector_group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device is not assigned to a collector group. Assign it to a group first.",
        )

    # Validate: device needs an SNMP credential
    has_snmp = False
    if device.credentials:
        has_snmp = any("snmp" in k.lower() for k in device.credentials)

    if not has_snmp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No SNMP credential found on this device. Assign an SNMP credential first.",
        )

    await set_discovery_flag(device_id)

    # Notify collectors in this group via WebSocket to sync jobs immediately.
    # Uses `notify_config_reload` so the reload is fanned out via Redis if
    # the collector's WS lives on a different central node. Previous code
    # used `send_command` + `is_connected_local`, which silently dropped the
    # notification for any collector whose WS was not on the central that
    # served this HTTP request — and additionally filtered on status
    # "APPROVED" which never occurs in steady state (collectors are "ACTIVE"
    # once they start heartbeating).
    ws_notified = 0
    try:
        result = await db.execute(
            select(Collector.id).where(
                Collector.group_id == device.collector_group_id,
                Collector.status == "ACTIVE",
            )
        )
        collector_ids = list(result.scalars().all())
        ws_notified = await ws_manager.notify_config_reload(collector_ids)
    except Exception as exc:
        logger.warning("ws_notify_collectors_failed", error=str(exc))

    return {
        "status": "success",
        "data": {
            "message": "Discovery queued. The collector will run SNMP discovery on the next poll cycle.",
            "device_id": device_id,
            "ws_notified": ws_notified,
        },
    }
