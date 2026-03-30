"""Device discovery trigger endpoint — queues SNMP discovery via collector."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import Collector, Device
from monctl_central.cache import set_discovery_flag
from monctl_central.ws.router import manager as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{device_id}/discover")
async def trigger_discovery(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
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

    # Notify collectors in this group via WebSocket to sync jobs immediately
    ws_notified = 0
    try:
        result = await db.execute(
            select(Collector.id).where(
                Collector.group_id == device.collector_group_id,
                Collector.status == "APPROVED",
            )
        )
        collector_ids = result.scalars().all()

        for cid in collector_ids:
            if ws_manager.is_connected_local(cid):
                try:
                    await ws_manager.send_command(cid, "config_reload", {}, timeout=5)
                    ws_notified += 1
                except Exception as exc:
                    logger.debug("ws_config_reload_failed", collector_id=str(cid), error=str(exc))
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
