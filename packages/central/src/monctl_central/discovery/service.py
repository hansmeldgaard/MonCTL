"""SNMP device discovery service — central-side rule matching and device update.

This service processes the config_data returned by the collector-side
snmp_discovery app. It matches sysObjectID against device types and
updates the device with category, metadata, and icon.
"""

from __future__ import annotations

import asyncio
import re
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import (
    App,
    AppAssignment,
    AppVersion,
    Device,
    DeviceCategory,
    DeviceType,
    Pack,
    SystemSetting,
)

import structlog
logger = structlog.get_logger(__name__)


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

    # Extract eligibility results before processing (internal metadata, not config)
    eligibility_results = config_data.pop("_eligibility_results", None)
    eligibility_error = config_data.pop("_eligibility_error", None)
    if eligibility_error:
        logger.warning("eligibility_probe_error", device_id=device_id, error=eligibility_error)

    sys_object_id = config_data.get("sys_object_id")

    # 1. Update device metadata with raw SNMP data
    metadata = dict(device.metadata_ or {})
    for key in ("sys_object_id", "sys_descr", "sys_name", "sys_location", "sys_contact", "serial"):
        val = config_data.get(key)
        if val:
            metadata[key] = val
    metadata["discovered_at"] = datetime.now(timezone.utc).isoformat()

    # Auto-rename: if device was bulk-imported (name == address), rename to sysName
    sys_name_val = (config_data.get("sys_name") or "").strip()
    if sys_name_val and device.name == device.address and len(sys_name_val) <= 255:
        changes: dict[str, str] = {"metadata": "updated", "name": f"{device.name} → {sys_name_val}"}
        device.name = sys_name_val
    else:
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

    # Post-discovery duplicate detection: compare identity fields against other
    # devices in the same tenant. Runs before we assign the metadata so we can
    # stash duplicate_of into the same JSONB write.
    dup_of = await _find_identity_duplicates(device, metadata, db)
    if dup_of:
        metadata["duplicate_of"] = dup_of
        metadata["duplicate_detected_at"] = datetime.now(timezone.utc).isoformat()
        changes["duplicate_of"] = ",".join(dup_of)
        logger.warning(
            "discovery_duplicate_detected",
            device_id=device_id,
            matches=dup_of,
            serial=metadata.get("serial"),
            sys_name=metadata.get("sys_name"),
            sys_object_id=metadata.get("sys_object_id"),
        )
    else:
        metadata.pop("duplicate_of", None)
        metadata.pop("duplicate_detected_at", None)

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

    # 6. Auto-apply hierarchical templates if enabled
    if match_result and match_result.matched:
        auto_apply = (await db.execute(
            select(SystemSetting).where(SystemSetting.key == "auto_apply_templates_on_discovery")
        )).scalar_one_or_none()
        if auto_apply and auto_apply.value == "true":
            try:
                from monctl_central.templates.resolver import resolve_templates_for_device
                from monctl_central.templates.router import apply_config_to_device

                resolved = await resolve_templates_for_device(device, db)
                if resolved["config"]:
                    await apply_config_to_device(device, resolved["config"], db)
                    await db.flush()
                    changes["auto_applied_templates"] = "true"
                    logger.info("discovery_auto_applied_templates",
                                device_id=device_id,
                                templates=[t["template_name"] for t in resolved["source_templates"]])
            except Exception:
                logger.exception("discovery_auto_apply_failed", device_id=device_id)

    # 7. Auto-assign packs if device type has auto_assign_packs
    if match_result and match_result.device_type and match_result.device_type.auto_assign_packs:
        needs_elig = await _has_apps_with_eligibility_oids(match_result.device_type, db)
        if needs_elig and eligibility_results is None:
            # Phase 1 complete — queue Phase 2 for eligibility probing
            from monctl_central.cache import set_discovery_flag, set_discovery_phase2_flag
            queued = await set_discovery_phase2_flag(device_id)
            if queued:
                await set_discovery_flag(device_id, ttl=300)
                changes["eligibility_check"] = "deferred_to_second_pass"
                logger.info("discovery_phase2_queued", device_id=device_id)
        else:
            assigned = await _auto_assign_packs(
                device, match_result.device_type, db,
                eligibility_results=eligibility_results,
            )
            if assigned:
                changes["packs_assigned"] = ", ".join(assigned)
            await db.flush()

    # 8. Update eligibility run tracking if this device is part of an active run
    try:
        from monctl_central.cache import get_eligibility_run_for_device
        run_info = await get_eligibility_run_for_device(device_id)
        if run_info:
            from monctl_central.dependencies import get_clickhouse
            ch = get_clickhouse()
            if ch:
                import json as _json
                from datetime import datetime as _dt, timezone as _tz
                now = _dt.now(_tz.utc)

                if eligibility_results is not None:
                    # We have probe results — evaluate eligibility
                    elig_oids_for_app = None
                    app_obj = (await db.execute(
                        select(App).where(App.id == _uuid.UUID(run_info["app_id"]))
                    )).scalar_one_or_none()
                    if app_obj:
                        latest_v = (await db.execute(
                            select(AppVersion).where(
                                AppVersion.app_id == app_obj.id,
                                AppVersion.is_latest == True,  # noqa: E712
                            )
                        )).scalar_one_or_none()
                        if latest_v:
                            elig_oids_for_app = latest_v.eligibility_oids

                    if elig_oids_for_app:
                        is_eligible = _check_eligibility(
                            app_obj.name if app_obj else "?",
                            elig_oids_for_app, eligibility_results, device_id,
                        )
                        reason = ""
                        if not is_eligible:
                            for check in elig_oids_for_app:
                                val = eligibility_results.get(check["oid"])
                                if check["check"] == "exists" and val is None:
                                    reason = f"OID {check['oid']} not found"
                                    break
                                elif check["check"] == "equals":
                                    reason = f"OID {check['oid']}: got {val}"
                                    break

                        await asyncio.to_thread(ch.insert_eligibility_results, [{
                            "run_id": run_info["run_id"],
                            "device_id": device_id,
                            "device_name": device.name,
                            "device_address": device.address,
                            "eligible": 1 if is_eligible else 0,
                            "already_assigned": 0,
                            "oid_results": _json.dumps(eligibility_results),
                            "reason": reason,
                            "probed_at": now,
                        }])
                        changes["eligibility_result"] = "eligible" if is_eligible else "ineligible"
                elif eligibility_error:
                    # Device was unreachable or probe failed
                    await asyncio.to_thread(ch.insert_eligibility_results, [{
                        "run_id": run_info["run_id"],
                        "device_id": device_id,
                        "device_name": device.name,
                        "device_address": device.address,
                        "eligible": 2,  # error
                        "already_assigned": 0,
                        "oid_results": "{}",
                        "reason": str(eligibility_error)[:200],
                        "probed_at": now,
                    }])
                    changes["eligibility_result"] = "error"

                # Update run progress counters if we inserted a result
                if "eligibility_result" in changes:
                    await asyncio.to_thread(
                        _update_eligibility_run_progress, ch, run_info["run_id"]
                    )
    except Exception:
        logger.exception("eligibility_tracking_failed", device_id=device_id)

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


# ── Auto-assign packs with eligibility checking ─────────────────────────────


async def _auto_assign_packs(
    device: Device,
    device_type: DeviceType,
    db: AsyncSession,
    eligibility_results: dict[str, str | None] | None = None,
) -> list[str]:
    """Auto-assign apps from packs linked to the device type.

    Three-layer filtering per app:
      Layer 1: Vendor scope (dot-boundary prefix match — no SNMP)
      Layer 2: Eligibility OIDs (SNMP probe results)
      Layer 3: Existing assignment check
    """
    if not device_type.auto_assign_packs:
        return []

    device_sys_oid = (device.metadata_ or {}).get("sys_object_id")
    assigned_packs: list[str] = []

    for pack_uid in device_type.auto_assign_packs:
        pack = (await db.execute(
            select(Pack).where(Pack.pack_uid == pack_uid)
        )).scalar_one_or_none()
        if not pack:
            continue

        apps = (await db.execute(select(App).where(App.pack_id == pack.id))).scalars().all()
        pack_had_assignment = False

        for app in apps:
            # Layer 1: Vendor scope check
            if app.vendor_oid_prefix and device_sys_oid:
                pfx = app.vendor_oid_prefix
                if not (device_sys_oid == pfx or device_sys_oid.startswith(pfx + ".")):
                    logger.info("vendor_scope_mismatch", app=app.name, device=str(device.id))
                    continue

            # Layer 3: Already assigned?
            existing = (await db.execute(
                select(AppAssignment.id).where(
                    AppAssignment.app_id == app.id,
                    AppAssignment.device_id == device.id,
                )
            )).scalar_one_or_none()
            if existing:
                continue

            # Get latest version
            latest = (await db.execute(
                select(AppVersion).where(
                    AppVersion.app_id == app.id,
                    AppVersion.is_latest == True,  # noqa: E712
                )
            )).scalar_one_or_none()
            if not latest:
                continue

            # Layer 2: Eligibility OID check
            if latest.eligibility_oids:
                if eligibility_results is None:
                    logger.info("eligibility_deferred", app=app.name, device=str(device.id))
                    continue
                if not _check_eligibility(app.name, latest.eligibility_oids,
                                          eligibility_results, str(device.id)):
                    continue

            # All checks passed — create assignment
            assignment = AppAssignment(
                app_id=app.id,
                app_version_id=latest.id,
                device_id=device.id,
                config={},
                schedule_type="interval",
                schedule_value="60",
                use_latest=True,
                enabled=True,
            )
            db.add(assignment)
            pack_had_assignment = True
            logger.info("auto_assigned_app", app=app.name, device=str(device.id), pack=pack_uid)

        if pack_had_assignment:
            assigned_packs.append(pack_uid)

    return assigned_packs


def _update_eligibility_run_progress(ch, run_id: str) -> None:
    """Recount eligibility results and update the run row.

    Uses ReplacingMergeTree — inserting a new row with the same run_id
    and a newer finished_at supersedes the previous one.
    """
    try:
        from datetime import datetime as _dt, timezone as _tz
        client = ch._get_client()
        # Count DISTINCT devices (forwarder may deliver results to multiple centrals)
        sql = """
            SELECT eligible, count(DISTINCT device_id) as cnt
            FROM eligibility_results
            WHERE run_id = {run_id:UUID}
            GROUP BY eligible
        """
        rows = client.query(sql, parameters={"run_id": run_id}).result_rows
        eligible_count = 0
        ineligible_count = 0
        error_count = 0
        for elig_val, cnt in rows:
            if elig_val == 1:
                eligible_count += cnt
            elif elig_val == 0:
                ineligible_count += cnt
            else:
                error_count += cnt

        tested = eligible_count + ineligible_count + error_count

        # Get original run info
        runs, _ = ch.query_eligibility_runs_by_run_id(run_id)
        if not runs:
            return
        run = runs[0]

        now = _dt.now(_tz.utc)
        is_complete = tested >= run["total_devices"]

        # ClickHouse returns naive datetimes — make timezone-aware for subtraction
        started = run["started_at"]
        if started and not getattr(started, 'tzinfo', None):
            started = started.replace(tzinfo=_tz.utc)
        duration = int((now - started).total_seconds() * 1000) if is_complete and started else 0

        ch.update_eligibility_run({
            "run_id": run_id,
            "app_id": str(run["app_id"]),
            "app_name": run["app_name"],
            "status": "completed" if is_complete else "running",
            "started_at": run["started_at"],
            "finished_at": now if is_complete else run["finished_at"],
            "duration_ms": duration,
            "total_devices": run["total_devices"],
            "tested": tested,
            "eligible": eligible_count,
            "ineligible": ineligible_count,
            "unreachable": error_count,
            "triggered_by": run["triggered_by"],
        })
    except Exception:
        logger.exception("eligibility_run_progress_update_failed", run_id=run_id)


def _check_eligibility(
    app_name: str,
    eligibility_oids: list[dict],
    probe_results: dict[str, str | None],
    device_id: str,
) -> bool:
    """Evaluate eligibility OID checks. All must pass (AND logic)."""
    for check in eligibility_oids:
        oid = check["oid"]
        check_type = check["check"]
        probe_value = probe_results.get(oid)

        if check_type == "exists":
            if probe_value is None:
                logger.info("eligibility_failed", app=app_name, device=device_id,
                            oid=oid, check="exists", reason="not_found")
                return False
        elif check_type == "equals":
            expected = check.get("value", "")
            if probe_value is None:
                logger.info("eligibility_failed", app=app_name, device=device_id,
                            oid=oid, check="equals", reason="not_found")
                return False
            if probe_value.lstrip(".") != expected.lstrip("."):
                logger.info("eligibility_failed", app=app_name, device=device_id,
                            oid=oid, check="equals", expected=expected, actual=probe_value)
                return False

    logger.info("eligibility_passed", app=app_name, device=device_id)
    return True


async def _find_identity_duplicates(
    device: Device,
    metadata: dict,
    db: AsyncSession,
) -> list[str]:
    """Return IDs of other devices in the same tenant that share a stable
    identity with `device`.

    Precedence:
      1. Hardware serial (entPhysicalSerialNum) — strongest signal.
      2. sys_name + sys_object_id — fallback only when neither side has a serial.
         A mismatched serial is a *negative* signal and suppresses the fallback.
    """
    serial = (metadata.get("serial") or "").strip()
    sys_name = (metadata.get("sys_name") or "").strip()
    sys_object_id = (metadata.get("sys_object_id") or "").strip()

    if not serial and not (sys_name and sys_object_id):
        return []

    stmt = select(Device.id, Device.metadata_).where(Device.id != device.id)
    if device.tenant_id is None:
        stmt = stmt.where(Device.tenant_id.is_(None))
    else:
        stmt = stmt.where(Device.tenant_id == device.tenant_id)

    rows = (await db.execute(stmt)).all()
    matches: list[str] = []
    for other_id, other_meta in rows:
        other_meta = other_meta or {}
        other_serial = (other_meta.get("serial") or "").strip()
        if serial and other_serial and serial == other_serial:
            matches.append(str(other_id))
            continue
        if serial or other_serial:
            continue
        if not (sys_name and sys_object_id):
            continue
        other_sn = (other_meta.get("sys_name") or "").strip()
        other_oid = (other_meta.get("sys_object_id") or "").strip()
        if other_sn == sys_name and other_oid == sys_object_id:
            matches.append(str(other_id))
    return matches


async def _has_apps_with_eligibility_oids(device_type: DeviceType, db: AsyncSession) -> bool:
    """Check if any app in auto_assign_packs has eligibility_oids defined."""
    if not device_type.auto_assign_packs:
        return False
    for pack_uid in device_type.auto_assign_packs:
        pack = (await db.execute(
            select(Pack).where(Pack.pack_uid == pack_uid)
        )).scalar_one_or_none()
        if not pack:
            continue
        apps = (await db.execute(select(App).where(App.pack_id == pack.id))).scalars().all()
        for app in apps:
            latest = (await db.execute(
                select(AppVersion).where(
                    AppVersion.app_id == app.id,
                    AppVersion.is_latest == True,  # noqa: E712
                )
            )).scalar_one_or_none()
            if latest and latest.eligibility_oids:
                return True
    return False
