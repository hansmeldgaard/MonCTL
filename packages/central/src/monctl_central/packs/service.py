"""Pack service — export, preview, and import logic."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.storage.models import (
    App,
    AppAlertDefinition,
    AppVersion,
    Connector,
    ConnectorVersion,
    CredentialTemplate,
    DeviceType,
    LabelKey,
    Pack,
    PackVersion,
    SnmpOid,
    Template,
)

# Maps section name → (Model, name_field)
# NOTE: alert_rules removed — alert definitions are now nested inside app versions
ENTITY_MAP: list[tuple[str, type, str]] = [
    ("apps", App, "name"),
    ("credential_templates", CredentialTemplate, "name"),
    ("snmp_oids", SnmpOid, "name"),
    ("device_templates", Template, "name"),
    ("device_types", DeviceType, "name"),
    ("label_keys", LabelKey, "key"),
    ("connectors", Connector, "name"),
]


def _section_to_model(section: str):
    for s, m, _ in ENTITY_MAP:
        if s == section:
            return m
    return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Export ────────────────────────────────────────────────────────────────────


async def export_pack(pack_id: uuid.UUID, db: AsyncSession) -> dict:
    """Export a pack and all its tagged entities to a JSON-serializable dict."""
    pack = await db.get(Pack, pack_id)
    if pack is None:
        raise ValueError("Pack not found")

    result: dict = {
        "monctl_pack": "1.0",
        "pack_uid": pack.pack_uid,
        "name": pack.name,
        "version": pack.current_version,
        "description": pack.description,
        "author": pack.author,
        "changelog": None,
        "exported_at": _utc_now().isoformat(),
        "contents": {},
    }

    latest_pv = (await db.execute(
        select(PackVersion)
        .where(PackVersion.pack_id == pack.id)
        .order_by(PackVersion.imported_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if latest_pv:
        result["changelog"] = latest_pv.changelog

    # Apps with versions and alert definitions
    apps = (await db.execute(
        select(App)
        .options(
            selectinload(App.versions).selectinload(AppVersion.alert_definitions),
        )
        .where(App.pack_id == pack.id)
    )).scalars().all()
    if apps:
        result["contents"]["apps"] = [_export_app(a) for a in apps]

    # Credential templates
    creds = (await db.execute(
        select(CredentialTemplate).where(CredentialTemplate.pack_id == pack.id)
    )).scalars().all()
    if creds:
        result["contents"]["credential_templates"] = [_export_cred_template(c) for c in creds]

    # SNMP OIDs
    oids = (await db.execute(
        select(SnmpOid).where(SnmpOid.pack_id == pack.id)
    )).scalars().all()
    if oids:
        result["contents"]["snmp_oids"] = [_export_oid(o) for o in oids]

    # Device templates
    templates = (await db.execute(
        select(Template).where(Template.pack_id == pack.id)
    )).scalars().all()
    if templates:
        result["contents"]["device_templates"] = [_export_template(t) for t in templates]

    # Device types
    device_types = (await db.execute(
        select(DeviceType).where(DeviceType.pack_id == pack.id)
    )).scalars().all()
    if device_types:
        result["contents"]["device_types"] = [_export_device_type(dt) for dt in device_types]

    # Label keys
    label_keys = (await db.execute(
        select(LabelKey).where(LabelKey.pack_id == pack.id)
    )).scalars().all()
    if label_keys:
        result["contents"]["label_keys"] = [_export_label_key(lk) for lk in label_keys]

    # Connectors with versions
    connectors = (await db.execute(
        select(Connector).options(selectinload(Connector.versions)).where(Connector.pack_id == pack.id)
    )).scalars().all()
    if connectors:
        result["contents"]["connectors"] = [_export_connector(c) for c in connectors]

    return result


def _export_app(a: App) -> dict:
    d: dict = {
        "name": a.name,
        "description": a.description,
        "app_type": a.app_type,
        "config_schema": a.config_schema,
        "target_table": a.target_table,
        "versions": [],
    }
    for v in a.versions:
        ver_data: dict = {
            "version": v.version,
            "source_code": v.source_code,
            "requirements": v.requirements or [],
            "entry_class": v.entry_class,
            "is_latest": v.is_latest,
            "display_template": v.display_template,
        }
        # Nest alert definitions into the version
        alert_defs = []
        for ad in getattr(v, "alert_definitions", []):
            alert_defs.append({
                "name": ad.name,
                "expression": ad.expression,
                "window": ad.window,
                "severity": ad.severity,
                "enabled": ad.enabled,
                "description": ad.description,
                "message_template": ad.message_template,
            })
        if alert_defs:
            ver_data["alert_definitions"] = alert_defs
        d["versions"].append(ver_data)
    return d


def _export_cred_template(c: CredentialTemplate) -> dict:
    return {
        "name": c.name,
        "description": c.description,
        "fields": c.fields,
    }


def _export_oid(o: SnmpOid) -> dict:
    return {
        "name": o.name,
        "oid": o.oid,
        "description": o.description,
    }


def _export_template(t: Template) -> dict:
    return {
        "name": t.name,
        "description": t.description,
        "config": t.config,
    }


def _export_device_type(dt: DeviceType) -> dict:
    return {
        "name": dt.name,
        "description": dt.description,
        "category": dt.category,
    }


def _export_label_key(lk: LabelKey) -> dict:
    return {
        "key": lk.key,
        "description": lk.description,
        "color": lk.color,
        "show_description": lk.show_description,
        "predefined_values": lk.predefined_values,
    }


def _export_connector(c: Connector) -> dict:
    d: dict = {
        "name": c.name,
        "description": c.description,
        "connector_type": c.connector_type,
        "requirements": c.requirements,
        "versions": [],
    }
    for v in c.versions:
        d["versions"].append({
            "version": v.version,
            "source_code": v.source_code,
            "requirements": v.requirements,
            "entry_class": v.entry_class,
            "is_latest": v.is_latest,
        })
    return d


# ── Preview ───────────────────────────────────────────────────────────────────


async def preview_import(data: dict, db: AsyncSession) -> dict:
    """Analyze a pack JSON and return conflict information."""
    entities: list[dict] = []

    for section, model, name_field in ENTITY_MAP:
        for item in data.get("contents", {}).get(section, []):
            item_name = item.get(name_field, "")
            existing = (await db.execute(
                select(model).where(getattr(model, name_field) == item_name)
            )).scalar_one_or_none()

            entry: dict = {
                "section": section,
                "name": item_name,
                "status": "new",
                "existing_pack": None,
            }

            if existing is not None:
                entry["status"] = "conflict"
                if hasattr(existing, "pack_id") and existing.pack_id:
                    pack = await db.get(Pack, existing.pack_id)
                    entry["existing_pack"] = pack.name if pack else None

            entities.append(entry)

    # Count alert definitions across all app versions (informational entries)
    for app_item in data.get("contents", {}).get("apps", []):
        alert_count = 0
        for ver in app_item.get("versions", []):
            alert_count += len(ver.get("alert_definitions", []))
        if alert_count > 0:
            entities.append({
                "section": "alert_definitions",
                "name": f"{app_item['name']} ({alert_count} alert"
                        f"{'s' if alert_count != 1 else ''})",
                "status": "info",
                "existing_pack": None,
            })

    result: dict = {
        "pack_uid": data["pack_uid"],
        "name": data["name"],
        "version": data["version"],
        "is_upgrade": False,
        "current_version": None,
        "entities": entities,
    }

    existing_pack = (await db.execute(
        select(Pack).where(Pack.pack_uid == data["pack_uid"])
    )).scalar_one_or_none()
    if existing_pack:
        result["is_upgrade"] = True
        result["current_version"] = existing_pack.current_version

    return result


# ── Import ────────────────────────────────────────────────────────────────────


async def import_pack(
    data: dict,
    resolutions: dict[str, str],
    db: AsyncSession,
) -> dict:
    """Import a pack, creating/updating entities per resolution decisions."""
    pack_uid = data["pack_uid"]
    version = data["version"]

    # Find or create pack record
    pack = (await db.execute(
        select(Pack).where(Pack.pack_uid == pack_uid)
    )).scalar_one_or_none()

    if pack is None:
        pack = Pack(
            pack_uid=pack_uid,
            name=data["name"],
            description=data.get("description"),
            author=data.get("author"),
            current_version=version,
        )
        db.add(pack)
        await db.flush()
    else:
        pack.name = data["name"]
        pack.description = data.get("description")
        pack.author = data.get("author")
        pack.current_version = version
        pack.updated_at = _utc_now()

    # Create version record
    pack_version = PackVersion(
        pack_id=pack.id,
        version=version,
        changelog=data.get("changelog"),
        manifest=_build_manifest(data),
    )
    db.add(pack_version)

    stats = {"created": 0, "updated": 0, "skipped": 0}

    for section, model, name_field in ENTITY_MAP:
        items = data.get("contents", {}).get(section, [])
        for item in items:
            item_name = item.get(name_field, "")
            resolution_key = f"{section}:{item_name}"
            resolution = resolutions.get(resolution_key, "skip")

            existing = (await db.execute(
                select(model).where(getattr(model, name_field) == item_name)
            )).scalar_one_or_none()

            if existing and resolution == "skip":
                stats["skipped"] += 1
                if section == "apps":
                    await _sync_app_versions(
                        db, existing, item.get("versions", []),
                        pack_uid=pack_uid, pack_id=pack.id, skip_app_update=True,
                    )
                continue
            elif existing and resolution == "overwrite":
                _update_entity(existing, item, section, pack.id)
                if section == "apps":
                    await _sync_app_versions(
                        db, existing, item.get("versions", []),
                        pack_uid=pack_uid, pack_id=pack.id,
                    )
                elif section == "connectors":
                    await _sync_connector_versions(db, existing, item.get("versions", []))
                stats["updated"] += 1
            elif existing and resolution == "rename":
                new_name = f"{item_name}-imported"
                item[name_field] = new_name
                entity = _create_entity(item, section, pack.id)
                db.add(entity)
                await db.flush()
                if section == "apps":
                    await _create_app_versions(
                        db, entity, item.get("versions", []),
                        pack_uid=pack_uid, pack_id=pack.id,
                    )
                elif section == "connectors":
                    await _create_connector_versions(db, entity, item.get("versions", []))
                stats["created"] += 1
            else:
                entity = _create_entity(item, section, pack.id)
                db.add(entity)
                await db.flush()
                if section == "apps":
                    await _create_app_versions(
                        db, entity, item.get("versions", []),
                        pack_uid=pack_uid, pack_id=pack.id,
                    )
                elif section == "connectors":
                    await _create_connector_versions(db, entity, item.get("versions", []))
                stats["created"] += 1

    await db.flush()
    return {"pack_id": str(pack.id), "version": version, **stats}


def _build_manifest(data: dict) -> dict:
    manifest: dict = {}
    contents = data.get("contents", {})
    for section in ["apps", "credential_templates", "snmp_oids",
                     "device_templates", "device_types", "label_keys", "connectors"]:
        items = contents.get(section, [])
        if items:
            if section == "apps":
                manifest[section] = [item["name"] for item in items]
                # Also count nested alert definitions
                alert_names: list[str] = []
                for app_item in items:
                    for ver in app_item.get("versions", []):
                        for ad in ver.get("alert_definitions", []):
                            alert_names.append(f"{app_item['name']}/{ad['name']}")
                if alert_names:
                    manifest["alert_definitions"] = alert_names
            else:
                name_field = "key" if section == "label_keys" else "name"
                manifest[section] = [item[name_field] for item in items]
    return manifest


def _create_entity(item: dict, section: str, pack_id: uuid.UUID):
    if section == "apps":
        return App(
            name=item["name"],
            description=item.get("description"),
            app_type=item.get("app_type", "script"),
            config_schema=item.get("config_schema"),
            target_table=item.get("target_table", "availability_latency"),
            pack_id=pack_id,
        )
    elif section == "credential_templates":
        return CredentialTemplate(
            name=item["name"],
            description=item.get("description"),
            fields=item.get("fields", []),
            pack_id=pack_id,
        )
    elif section == "snmp_oids":
        return SnmpOid(
            name=item["name"],
            oid=item["oid"],
            description=item.get("description"),
            pack_id=pack_id,
        )
    elif section == "device_templates":
        return Template(
            name=item["name"],
            description=item.get("description"),
            config=item.get("config", {}),
            pack_id=pack_id,
        )
    elif section == "device_types":
        return DeviceType(
            name=item["name"],
            description=item.get("description"),
            category=item.get("category", "other"),
            pack_id=pack_id,
        )
    elif section == "label_keys":
        return LabelKey(
            key=item["key"],
            description=item.get("description"),
            color=item.get("color"),
            show_description=item.get("show_description", False),
            predefined_values=item.get("predefined_values", []),
            pack_id=pack_id,
        )
    elif section == "connectors":
        return Connector(
            name=item["name"],
            description=item.get("description"),
            connector_type=item["connector_type"],
            requirements=item.get("requirements"),
            pack_id=pack_id,
        )


def _update_entity(existing, item: dict, section: str, pack_id: uuid.UUID) -> None:
    existing.pack_id = pack_id
    if section == "apps":
        existing.description = item.get("description")
        existing.app_type = item.get("app_type", existing.app_type)
        existing.config_schema = item.get("config_schema", existing.config_schema)
        existing.target_table = item.get("target_table", existing.target_table)
    elif section == "credential_templates":
        existing.description = item.get("description")
        existing.fields = item.get("fields", existing.fields)
    elif section == "snmp_oids":
        existing.oid = item.get("oid", existing.oid)
        existing.description = item.get("description")
    elif section == "device_templates":
        existing.description = item.get("description")
        existing.config = item.get("config", existing.config)
    elif section == "device_types":
        existing.description = item.get("description")
        existing.category = item.get("category", existing.category)
    elif section == "label_keys":
        existing.description = item.get("description")
        existing.color = item.get("color", existing.color)
        existing.show_description = item.get("show_description", existing.show_description)
        existing.predefined_values = item.get("predefined_values", existing.predefined_values)
    elif section == "connectors":
        existing.description = item.get("description")
        existing.connector_type = item.get("connector_type", existing.connector_type)
        existing.requirements = item.get("requirements", existing.requirements)


async def _create_app_versions(
    db: AsyncSession,
    app: App,
    versions_data: list[dict],
    pack_uid: str | None = None,
    pack_id: uuid.UUID | None = None,
) -> None:
    for vdata in versions_data:
        checksum = hashlib.sha256((vdata.get("source_code") or "").encode()).hexdigest()
        v = AppVersion(
            app_id=app.id,
            version=vdata["version"],
            source_code=vdata.get("source_code"),
            requirements=vdata.get("requirements", []),
            entry_class=vdata.get("entry_class"),
            checksum_sha256=checksum,
            is_latest=vdata.get("is_latest", False),
            display_template=vdata.get("display_template"),
        )
        db.add(v)
        await db.flush()
        # Create alert definitions for the new version
        await _sync_version_alert_definitions(
            db, app, v, vdata.get("alert_definitions", []), pack_uid, pack_id,
        )


async def _sync_app_versions(
    db: AsyncSession,
    app: App,
    versions_data: list[dict],
    pack_uid: str | None = None,
    pack_id: uuid.UUID | None = None,
    skip_app_update: bool = False,
) -> None:
    existing = (await db.execute(
        select(AppVersion).where(AppVersion.app_id == app.id)
    )).scalars().all()
    existing_by_ver = {v.version: v for v in existing}

    # Track old is_latest for threshold override migration
    old_latest = next((v for v in existing if v.is_latest), None)

    for vdata in versions_data:
        ver_str = vdata["version"]
        if ver_str in existing_by_ver:
            ev = existing_by_ver[ver_str]
            if not skip_app_update:
                if vdata.get("source_code"):
                    ev.source_code = vdata["source_code"]
                    ev.checksum_sha256 = hashlib.sha256(
                        vdata["source_code"].encode()
                    ).hexdigest()
                ev.requirements = vdata.get("requirements", ev.requirements)
                ev.entry_class = vdata.get("entry_class", ev.entry_class)
                if vdata.get("display_template") is not None:
                    ev.display_template = vdata["display_template"]
            # Sync alert definitions for this existing version
            await _sync_version_alert_definitions(
                db, app, ev, vdata.get("alert_definitions", []), pack_uid, pack_id,
            )
        else:
            checksum = hashlib.sha256(
                (vdata.get("source_code") or "").encode()
            ).hexdigest()
            new_ver = AppVersion(
                app_id=app.id,
                version=ver_str,
                source_code=vdata.get("source_code"),
                requirements=vdata.get("requirements", []),
                entry_class=vdata.get("entry_class"),
                checksum_sha256=checksum,
                is_latest=False,
                display_template=vdata.get("display_template"),
            )
            db.add(new_ver)
            await db.flush()
            # Create alert definitions for the new version
            await _sync_version_alert_definitions(
                db, app, new_ver, vdata.get("alert_definitions", []), pack_uid, pack_id,
            )

    await db.flush()
    all_v = (await db.execute(
        select(AppVersion).where(AppVersion.app_id == app.id)
    )).scalars().all()
    for v in all_v:
        matching = next((vd for vd in versions_data if vd["version"] == v.version), None)
        v.is_latest = matching.get("is_latest", False) if matching else False

    # Migrate threshold overrides if is_latest changed
    new_latest = next((v for v in all_v if v.is_latest), None)
    if new_latest and old_latest and new_latest.id != old_latest.id:
        from monctl_central.alerting.instance_sync import migrate_threshold_overrides_by_name
        await migrate_threshold_overrides_by_name(db, old_latest.id, new_latest.id)


async def _sync_version_alert_definitions(
    db: AsyncSession,
    app: App,
    version: AppVersion,
    alert_defs_data: list[dict],
    pack_uid: str | None = None,
    pack_id: uuid.UUID | None = None,
) -> None:
    """Sync alert definitions for a specific app version from pack data.

    - Creates missing definitions
    - Updates existing definitions (matched by name within version)
    - Does NOT delete definitions not in the pack (user may have added custom ones)
    - Never overwrites notification_channels
    """
    if not alert_defs_data:
        return

    existing_defs = (await db.execute(
        select(AppAlertDefinition).where(
            AppAlertDefinition.app_version_id == version.id,
        )
    )).scalars().all()
    existing_by_name = {d.name: d for d in existing_defs}

    for ad_data in alert_defs_data:
        name = ad_data["name"]
        if name in existing_by_name:
            # Update existing — but NEVER overwrite notification_channels
            existing_def = existing_by_name[name]
            existing_def.expression = ad_data["expression"]
            existing_def.window = ad_data.get("window", "5m")
            existing_def.severity = ad_data.get("severity", "warning")
            existing_def.enabled = ad_data.get("enabled", True)
            existing_def.description = ad_data.get("description")
            existing_def.message_template = ad_data.get("message_template")
            existing_def.pack_origin = pack_uid
            if pack_id:
                existing_def.pack_id = pack_id
        else:
            # Create new definition
            new_def = AppAlertDefinition(
                app_id=app.id,
                app_version_id=version.id,
                name=name,
                expression=ad_data["expression"],
                window=ad_data.get("window", "5m"),
                severity=ad_data.get("severity", "warning"),
                enabled=ad_data.get("enabled", True),
                description=ad_data.get("description"),
                message_template=ad_data.get("message_template"),
                notification_channels=[],
                pack_origin=pack_uid,
            )
            if pack_id:
                new_def.pack_id = pack_id
            db.add(new_def)
            await db.flush()
            # Auto-create AlertInstances for existing assignments
            from monctl_central.alerting.instance_sync import sync_instances_for_definition
            await sync_instances_for_definition(db, new_def)


async def _create_connector_versions(
    db: AsyncSession, connector: Connector, versions_data: list[dict],
) -> None:
    for vdata in versions_data:
        checksum = hashlib.sha256((vdata.get("source_code") or "").encode()).hexdigest()
        v = ConnectorVersion(
            connector_id=connector.id,
            version=vdata["version"],
            source_code=vdata.get("source_code", ""),
            requirements=vdata.get("requirements"),
            entry_class=vdata.get("entry_class", "Connector"),
            checksum=checksum,
            is_latest=vdata.get("is_latest", False),
        )
        db.add(v)


async def _sync_connector_versions(
    db: AsyncSession, connector: Connector, versions_data: list[dict],
) -> None:
    existing = (await db.execute(
        select(ConnectorVersion).where(ConnectorVersion.connector_id == connector.id)
    )).scalars().all()
    existing_by_ver = {v.version: v for v in existing}

    for vdata in versions_data:
        ver_str = vdata["version"]
        if ver_str in existing_by_ver:
            ev = existing_by_ver[ver_str]
            if vdata.get("source_code"):
                ev.source_code = vdata["source_code"]
                ev.checksum = hashlib.sha256(vdata["source_code"].encode()).hexdigest()
            ev.requirements = vdata.get("requirements", ev.requirements)
            ev.entry_class = vdata.get("entry_class", ev.entry_class)
        else:
            checksum = hashlib.sha256((vdata.get("source_code") or "").encode()).hexdigest()
            db.add(ConnectorVersion(
                connector_id=connector.id,
                version=ver_str,
                source_code=vdata.get("source_code", ""),
                requirements=vdata.get("requirements"),
                entry_class=vdata.get("entry_class", "Connector"),
                checksum=checksum,
                is_latest=False,
            ))

    await db.flush()
    all_v = (await db.execute(
        select(ConnectorVersion).where(ConnectorVersion.connector_id == connector.id)
    )).scalars().all()
    for v in all_v:
        matching = next((vd for vd in versions_data if vd["version"] == v.version), None)
        v.is_latest = matching.get("is_latest", False) if matching else False


# ── Entity counts ─────────────────────────────────────────────────────────────


async def get_entity_counts(pack_id: uuid.UUID, db: AsyncSession) -> dict:
    """Return count of entities tagged with this pack."""
    counts: dict = {}
    for section, model, _ in ENTITY_MAP:
        result = await db.execute(
            select(func.count()).select_from(model).where(model.pack_id == pack_id)
        )
        counts[section] = result.scalar() or 0

    # Count alert definitions on apps belonging to this pack
    alert_count = (await db.execute(
        select(func.count())
        .select_from(AppAlertDefinition)
        .where(AppAlertDefinition.pack_id == pack_id)
    )).scalar() or 0
    counts["alert_definitions"] = alert_count

    return counts
