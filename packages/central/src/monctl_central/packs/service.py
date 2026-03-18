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
ENTITY_MAP: list[tuple[str, type, str]] = [
    ("apps", App, "name"),
    ("alert_rules", AppAlertDefinition, "name"),
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

    # Apps with versions
    apps = (await db.execute(
        select(App).options(selectinload(App.versions)).where(App.pack_id == pack.id)
    )).scalars().all()
    if apps:
        result["contents"]["apps"] = [_export_app(a) for a in apps]

    # Alert definitions (with app relationship for app_name)
    alerts = (await db.execute(
        select(AppAlertDefinition)
        .options(selectinload(AppAlertDefinition.app))
        .where(AppAlertDefinition.pack_id == pack.id)
    )).scalars().all()
    if alerts:
        result["contents"]["alert_rules"] = [_export_alert(a) for a in alerts]

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
        d["versions"].append({
            "version": v.version,
            "source_code": v.source_code,
            "requirements": v.requirements or [],
            "entry_class": v.entry_class,
            "is_latest": v.is_latest,
            "display_template": v.display_template,
        })
    return d


def _export_alert(a: AppAlertDefinition) -> dict:
    return {
        "name": a.name,
        "description": a.description,
        "app_name": a.app.name if a.app else None,
        "app_id": str(a.app_id),
        "app_version_id": str(a.app_version_id),
        "expression": a.expression,
        "window": a.window,
        "severity": a.severity,
        "message_template": a.message_template,
    }


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

    # Track app name → ID and old_id → new_id mapping for alert_rules resolution
    app_name_to_id: dict[str, uuid.UUID] = {}
    # Map old pack app_id UUIDs to new database UUIDs
    old_app_id_to_new: dict[str, uuid.UUID] = {}
    _pack_apps = data.get("contents", {}).get("apps", [])
    # Build reverse mapping: find which app_id UUIDs in alert_rules correspond to which app names
    # by checking if alert_rules reference app_ids that match the pack's own apps
    _pack_app_name_by_old_id: dict[str, str] = {}
    # The pack file may reference apps by UUID — build name lookup from alert rules' app_ids
    _alert_app_ids: set[str] = set()
    for _ar in data.get("contents", {}).get("alert_rules", []):
        if _ar.get("app_id"):
            _alert_app_ids.add(_ar["app_id"])

    for section, model, name_field in ENTITY_MAP:
        items = data.get("contents", {}).get(section, [])
        for item in items:
            # For alert_rules, resolve app_id to a valid app in the database
            if section == "alert_rules":
                resolved_id: uuid.UUID | None = None
                old_id = item.get("app_id", "")

                # 1. Try explicit app_name
                if item.get("app_name"):
                    resolved_id = app_name_to_id.get(item["app_name"])
                    if not resolved_id:
                        r = (await db.execute(select(App).where(App.name == item["app_name"]))).scalar_one_or_none()
                        if r:
                            resolved_id = r.id

                # 2. Try old_id → new_id mapping (from apps created earlier in this import)
                if not resolved_id and old_id in old_app_id_to_new:
                    resolved_id = old_app_id_to_new[old_id]

                # 3. Try to find old_id in pack app names, then look up by name
                if not resolved_id and old_id in _pack_app_name_by_old_id:
                    resolved_id = app_name_to_id.get(_pack_app_name_by_old_id[old_id])

                # 4. If pack has exactly one app, use it
                if not resolved_id and len(_pack_apps) == 1:
                    app_name_single = _pack_apps[0].get("name", "")
                    resolved_id = app_name_to_id.get(app_name_single)
                    if not resolved_id:
                        r = (await db.execute(select(App).where(App.name == app_name_single))).scalar_one_or_none()
                        if r:
                            resolved_id = r.id

                # 5. Last resort: check if old_id happens to exist in the DB
                if not resolved_id and old_id:
                    try:
                        r = (await db.execute(select(App).where(App.id == uuid.UUID(old_id)))).scalar_one_or_none()
                        if r:
                            resolved_id = r.id
                    except (ValueError, Exception):
                        pass

                if resolved_id:
                    item["app_id"] = str(resolved_id)
                    from monctl_central.storage.models import AppVersion
                    latest_ver = (await db.execute(
                        select(AppVersion).where(
                            AppVersion.app_id == resolved_id,
                            AppVersion.is_latest == True,  # noqa: E712
                        )
                    )).scalar_one_or_none()
                    if latest_ver:
                        item["app_version_id"] = str(latest_ver.id)

            item_name = item.get(name_field, "")
            resolution_key = f"{section}:{item_name}"
            resolution = resolutions.get(resolution_key, "skip")

            existing = (await db.execute(
                select(model).where(getattr(model, name_field) == item_name)
            )).scalar_one_or_none()

            if existing and resolution == "skip":
                stats["skipped"] += 1
                if section == "apps":
                    app_name_to_id[item_name] = existing.id
                    if len(_pack_apps) == 1:
                        for _aid in _alert_app_ids:
                            old_app_id_to_new[_aid] = existing.id
                continue
            elif existing and resolution == "overwrite":
                _update_entity(existing, item, section, pack.id)
                if section == "apps":
                    await _sync_app_versions(db, existing, item.get("versions", []))
                    app_name_to_id[item_name] = existing.id
                    if len(_pack_apps) == 1:
                        for _aid in _alert_app_ids:
                            old_app_id_to_new[_aid] = existing.id
                elif section == "connectors":
                    await _sync_connector_versions(db, existing, item.get("versions", []))
                stats["updated"] += 1
            elif existing and resolution == "rename":
                new_name = f"{item_name}-imported"
                item[name_field] = new_name
                entity = _create_entity(item, section, pack.id, db)
                db.add(entity)
                await db.flush()
                if section == "apps":
                    await _create_app_versions(db, entity, item.get("versions", []))
                    app_name_to_id[new_name] = entity.id
                    if len(_pack_apps) == 1:
                        for _aid in _alert_app_ids:
                            old_app_id_to_new[_aid] = entity.id
                elif section == "connectors":
                    await _create_connector_versions(db, entity, item.get("versions", []))
                stats["created"] += 1
            else:
                entity = _create_entity(item, section, pack.id, db)
                db.add(entity)
                await db.flush()
                if section == "apps":
                    await _create_app_versions(db, entity, item.get("versions", []))
                    app_name_to_id[item_name] = entity.id
                    if len(_pack_apps) == 1:
                        for _aid in _alert_app_ids:
                            old_app_id_to_new[_aid] = entity.id
                elif section == "connectors":
                    await _create_connector_versions(db, entity, item.get("versions", []))
                stats["created"] += 1

    await db.flush()
    return {"pack_id": str(pack.id), "version": version, **stats}


def _build_manifest(data: dict) -> dict:
    manifest: dict = {}
    contents = data.get("contents", {})
    for section in ["apps", "alert_rules", "credential_templates", "snmp_oids",
                     "device_templates", "device_types", "label_keys", "connectors"]:
        items = contents.get(section, [])
        if items:
            name_field = "key" if section == "label_keys" else "name"
            manifest[section] = [item[name_field] for item in items]
    return manifest


def _create_entity(item: dict, section: str, pack_id: uuid.UUID, db: AsyncSession):
    if section == "apps":
        return App(
            name=item["name"],
            description=item.get("description"),
            app_type=item.get("app_type", "script"),
            config_schema=item.get("config_schema"),
            target_table=item.get("target_table", "availability_latency"),
            pack_id=pack_id,
        )
    elif section == "alert_rules":
        # expression can be a string or dict — ensure it's a string
        expr = item["expression"]
        if isinstance(expr, dict):
            import json as _json
            expr = _json.dumps(expr)
        return AppAlertDefinition(
            app_id=uuid.UUID(item["app_id"]) if item.get("app_id") else uuid.uuid4(),
            app_version_id=uuid.UUID(item["app_version_id"]) if item.get("app_version_id") else uuid.uuid4(),
            name=item["name"],
            description=item.get("description"),
            expression=expr,
            window=item.get("window", "5m"),
            severity=item.get("severity", "warning"),
            message_template=item.get("message_template"),
            notification_channels=[],
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
    elif section == "alert_rules":
        existing.description = item.get("description")
        expr = item.get("expression", existing.expression)
        if isinstance(expr, dict):
            import json as _json
            expr = _json.dumps(expr)
        existing.expression = expr
        existing.window = item.get("window", existing.window)
        existing.severity = item.get("severity", existing.severity)
        existing.message_template = item.get("message_template")
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


async def _create_app_versions(db: AsyncSession, app: App, versions_data: list[dict]) -> None:
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


async def _sync_app_versions(db: AsyncSession, app: App, versions_data: list[dict]) -> None:
    existing = (await db.execute(
        select(AppVersion).where(AppVersion.app_id == app.id)
    )).scalars().all()
    existing_by_ver = {v.version: v for v in existing}

    for vdata in versions_data:
        ver_str = vdata["version"]
        if ver_str in existing_by_ver:
            ev = existing_by_ver[ver_str]
            if vdata.get("source_code"):
                ev.source_code = vdata["source_code"]
                ev.checksum_sha256 = hashlib.sha256(vdata["source_code"].encode()).hexdigest()
            ev.requirements = vdata.get("requirements", ev.requirements)
            ev.entry_class = vdata.get("entry_class", ev.entry_class)
            if vdata.get("display_template") is not None:
                ev.display_template = vdata["display_template"]
        else:
            checksum = hashlib.sha256((vdata.get("source_code") or "").encode()).hexdigest()
            db.add(AppVersion(
                app_id=app.id,
                version=ver_str,
                source_code=vdata.get("source_code"),
                requirements=vdata.get("requirements", []),
                entry_class=vdata.get("entry_class"),
                checksum_sha256=checksum,
                is_latest=False,
                display_template=vdata.get("display_template"),
            ))

    await db.flush()
    all_v = (await db.execute(
        select(AppVersion).where(AppVersion.app_id == app.id)
    )).scalars().all()
    for v in all_v:
        matching = next((vd for vd in versions_data if vd["version"] == v.version), None)
        v.is_latest = matching.get("is_latest", False) if matching else False


async def _create_connector_versions(db: AsyncSession, connector: Connector, versions_data: list[dict]) -> None:
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


async def _sync_connector_versions(db: AsyncSession, connector: Connector, versions_data: list[dict]) -> None:
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
    return counts
