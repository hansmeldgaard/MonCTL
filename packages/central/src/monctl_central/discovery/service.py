"""SNMP device discovery service — central-side rule matching and device update.

This service processes the config_data returned by the collector-side
snmp_discovery app. It matches sysObjectID against device types and
updates the device with category, metadata, and icon.
"""

from __future__ import annotations

import logging
import re
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import (
    Device,
    DeviceCategory,
    DeviceType,
)

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryMatchResult:
    """Result of matching a sysObjectID against device types."""
    matched: bool
    device_type: DeviceType | None = None
    device_category: DeviceCategory | None = None
    vendor: str | None = None
    model: str | None = None
    os_family: str | None = None


async def process_discovery_result(
    device_id: str,
    config_data: dict[str, str],
    db: AsyncSession,
) -> dict[str, str]:
    """Process discovery config_data from the collector's snmp_discovery app.

    1. Extract sysObjectID from config_data
    2. Match against device types (longest prefix match)
    3. Update device metadata and category

    Returns a dict of changes made.
    """
    device = await db.get(Device, _uuid.UUID(device_id))
    if not device:
        logger.warning("discovery_device_not_found", device_id=device_id)
        return {}

    sys_object_id = config_data.get("sys_object_id")

    # 1. Update device metadata with raw SNMP data
    metadata = dict(device.metadata_ or {})
    for key in ("sys_object_id", "sys_descr", "sys_name", "sys_location", "sys_contact"):
        val = config_data.get(key)
        if val:
            metadata[key] = val
    metadata["discovered_at"] = datetime.now(timezone.utc).isoformat()

    changes: dict[str, str] = {"metadata": "updated"}

    # 2. Match sysObjectID against device types
    match_result = None
    if sys_object_id:
        match_result = await _match_rule(sys_object_id, db)

    # 3. Extract vendor/model/OS from rule or sysDescr
    vendor = match_result.vendor if match_result and match_result.vendor else None
    model = match_result.model if match_result and match_result.model else None
    os_family = match_result.os_family if match_result and match_result.os_family else None

    # Best-effort extraction from sysDescr if rule didn't provide values
    sys_descr = config_data.get("sys_descr")
    if sys_descr:
        extracted = _parse_sys_descr(sys_descr)
        vendor = vendor or extracted.get("vendor")
        model = model or extracted.get("model")
        os_family = os_family or extracted.get("os_family")

    if vendor:
        metadata["vendor"] = vendor
    if model:
        metadata["model"] = model
    if os_family:
        metadata["os_family"] = os_family

    device.metadata_ = metadata

    # 4. Update device category if a rule matched
    if match_result and match_result.device_category:
        old_category = device.device_category
        device.device_category = match_result.device_category.name
        if old_category != device.device_category:
            changes["device_category"] = f"{old_category} → {device.device_category}"

    # 5. Persist matched device type
    if match_result and match_result.device_type:
        device.device_type_id = match_result.device_type.id
        changes["device_type"] = match_result.device_type.name
    else:
        device.device_type_id = None

    await db.flush()

    logger.info("discovery_applied",
                device_id=device_id,
                sys_object_id=sys_object_id,
                vendor=vendor,
                model=model,
                device_category=device.device_category,
                changes=changes)

    return changes


async def _match_rule(sys_object_id: str, db: AsyncSession) -> DiscoveryMatchResult | None:
    """Find the best matching device type for a sysObjectID.

    Algorithm: load all device types, filter to those whose pattern is a prefix of
    the sysObjectID (at a dot boundary), then pick the one with the longest
    pattern (most specific). On tie, highest priority wins.

    We load all device types into memory because the table is small (typically <1000 rows)
    and this avoids complex SQL prefix matching.
    """
    rules = (await db.execute(
        select(DeviceType).order_by(DeviceType.priority.desc())
    )).scalars().all()

    best: DeviceType | None = None
    best_len = 0

    for rule in rules:
        pattern = rule.sys_object_id_pattern
        # Dot-boundary prefix match:
        # "1.3.6.1.4.1.9" matches "1.3.6.1.4.1.9.1.123"
        # but NOT "1.3.6.1.4.1.90.1.2"
        if sys_object_id == pattern or sys_object_id.startswith(pattern + "."):
            if len(pattern) > best_len or (
                len(pattern) == best_len
                and rule.priority > (best.priority if best else 0)
            ):
                best = rule
                best_len = len(pattern)

    if not best:
        return None

    # Load the device category
    dc = await db.get(DeviceCategory, best.device_category_id)
    return DiscoveryMatchResult(
        matched=True,
        device_type=best,
        device_category=dc,
        vendor=best.vendor,
        model=best.model,
        os_family=best.os_family,
    )


def _parse_sys_descr(sys_descr: str) -> dict[str, str]:
    """Best-effort extraction of vendor, model, OS from sysDescr string."""
    result: dict[str, str] = {}
    descr_lower = sys_descr.lower()

    # Cisco
    if "cisco" in descr_lower:
        result["vendor"] = "Cisco"
        m = re.search(r"Cisco IOS.*?,\s*(\S+)\s+Software", sys_descr)
        if m:
            result["model"] = m.group(1)
        if "IOS XE" in sys_descr or "IOSXE" in sys_descr:
            result["os_family"] = "IOS-XE"
        elif "IOS XR" in sys_descr or "IOSXR" in sys_descr:
            result["os_family"] = "IOS-XR"
        elif "NX-OS" in sys_descr:
            result["os_family"] = "NX-OS"
        elif "IOS" in sys_descr:
            result["os_family"] = "IOS"

    # Linux
    elif "linux" in descr_lower:
        result["vendor"] = "Linux"
        result["os_family"] = "Linux"
        m = re.search(r"Linux\s+\S+\s+([\d.]+\S+)", sys_descr)
        if m:
            result["model"] = f"Kernel {m.group(1)}"

    # Juniper
    elif "juniper" in descr_lower:
        result["vendor"] = "Juniper"
        m = re.search(r"juniper.*?\b(ex\d+|mx\d+|qfx\d+|srx\d+|acx\d+)\S*", descr_lower)
        if m:
            result["model"] = m.group(1).upper()
        if "junos" in descr_lower:
            result["os_family"] = "Junos"

    # Arista
    elif "arista" in descr_lower:
        result["vendor"] = "Arista"
        result["os_family"] = "EOS"
        m = re.search(r"Arista Networks\s+(DCS-\S+)", sys_descr)
        if m:
            result["model"] = m.group(1)

    # HP / HPE
    elif "hp " in descr_lower or "hewlett" in descr_lower or "procurve" in descr_lower:
        result["vendor"] = "HP"
        m = re.search(r"(J\d{4}\w)\s+", sys_descr)
        if m:
            result["model"] = m.group(1)

    # Fortinet
    elif "fortinet" in descr_lower or "fortigate" in descr_lower:
        result["vendor"] = "Fortinet"
        result["os_family"] = "FortiOS"

    # Palo Alto
    elif "palo alto" in descr_lower or "panos" in descr_lower:
        result["vendor"] = "Palo Alto"
        result["os_family"] = "PAN-OS"

    # MikroTik
    elif "mikrotik" in descr_lower or "routeros" in descr_lower:
        result["vendor"] = "MikroTik"
        result["os_family"] = "RouterOS"

    # Ubiquiti
    elif "ubiquiti" in descr_lower or "unifi" in descr_lower or "edgeos" in descr_lower:
        result["vendor"] = "Ubiquiti"

    return result
