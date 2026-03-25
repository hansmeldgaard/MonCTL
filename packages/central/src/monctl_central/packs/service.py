"""Pack service — export, preview, and import logic."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.storage.models import (
    App,
    AlertDefinition,
    AppVersion,
    Connector,
    ConnectorVersion,
    CredentialTemplate,
    DeviceCategory,
    DeviceType,
    LabelKey,
    Pack,
    PackVersion,
    SnmpOid,
    SystemSetting,
    Template,
    ThresholdVariable,
)

logger = logging.getLogger(__name__)

# Maps section name → (Model, name_field)
# NOTE: alert_rules removed — alert definitions are now nested inside app versions
ENTITY_MAP: list[tuple[str, type, str]] = [
    ("apps", App, "name"),
    ("credential_templates", CredentialTemplate, "name"),
    ("snmp_oids", SnmpOid, "name"),
    ("device_templates", Template, "name"),
    ("device_categories", DeviceCategory, "name"),
    ("label_keys", LabelKey, "key"),
    ("connectors", Connector, "name"),
    ("device_types", DeviceType, "name"),
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
        .options(selectinload(App.versions))
        .where(App.pack_id == pack.id)
    )).scalars().all()
    if apps:
        app_exports = []
        for a in apps:
            app_alert_defs = (await db.execute(
                select(AlertDefinition).where(AlertDefinition.app_id == a.id)
            )).scalars().all()
            app_tv = (await db.execute(
                select(ThresholdVariable).where(ThresholdVariable.app_id == a.id)
            )).scalars().all()
            app_exports.append(_export_app(a, app_alert_defs, list(app_tv)))
        result["contents"]["apps"] = app_exports

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

    # Device categories
    device_categories = (await db.execute(
        select(DeviceCategory).where(DeviceCategory.pack_id == pack.id)
    )).scalars().all()
    if device_categories:
        result["contents"]["device_categories"] = [_export_device_category(dc) for dc in device_categories]

    # Device types
    from sqlalchemy.orm import selectinload as _sinload
    device_types = (await db.execute(
        select(DeviceType)
        .options(_sinload(DeviceType.device_category))
        .where(DeviceType.pack_id == pack.id)
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

    # Grafana dashboards (optional — only if Grafana URL is configured)
    grafana_url = await _get_system_setting(db, "grafana_url")
    if grafana_url:
        try:
            grafana_dashboards = await _export_grafana_dashboards(grafana_url, pack)
            if grafana_dashboards:
                result["contents"]["grafana_dashboards"] = grafana_dashboards
        except Exception:
            logger.warning("Failed to export Grafana dashboards for pack %s", pack.pack_uid)

    return result


def _export_app(
    a: App,
    alert_definitions: list | None = None,
    threshold_vars: list | None = None,
) -> dict:
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
        d["versions"].append(ver_data)
    # Export threshold variables at the app level
    if threshold_vars:
        d["threshold_variables"] = [
            {
                "name": v.name,
                "default_value": v.default_value,
                "display_name": v.display_name,
                "unit": v.unit,
                "description": v.description,
            }
            for v in threshold_vars
        ]
    # Export alert definitions at the app level with threshold_defaults (backward compat)
    if alert_definitions:
        from monctl_central.alerting.dsl import validate_expression
        tv_by_name = {v.name: v for v in (threshold_vars or [])}
        d["alert_definitions"] = []
        for ad in alert_definitions:
            ad_dict = {
                "name": ad.name,
                "expression": ad.expression,
                "window": ad.window,
                "enabled": ad.enabled,
                "description": ad.description,
                "message_template": ad.message_template,
            }
            # Include threshold_defaults from threshold variables (backward compat)
            if tv_by_name:
                validation = validate_expression(ad.expression, a.target_table)
                if validation.valid and validation.threshold_params:
                    param_names = {p.name for p in validation.threshold_params}
                    relevant = [tv_by_name[n] for n in param_names if n in tv_by_name]
                    if relevant:
                        ad_dict["threshold_defaults"] = [
                            {
                                "param_key": v.name,
                                "default_value": v.default_value,
                                "display_name": v.display_name,
                                "unit": v.unit,
                                "description": v.description,
                            }
                            for v in relevant
                        ]
            d["alert_definitions"].append(ad_dict)
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


def _export_device_category(dc: DeviceCategory) -> dict:
    d: dict = {
        "name": dc.name,
        "description": dc.description,
        "category": dc.category,
    }
    if dc.icon:
        d["icon"] = dc.icon
    return d


def _export_device_type(dt: DeviceType) -> dict:
    return {
        "name": dt.name,
        "sys_object_id_pattern": dt.sys_object_id_pattern,
        "device_category_name": dt.device_category.name if dt.device_category else "",
        "vendor": dt.vendor,
        "model": dt.model,
        "os_family": dt.os_family,
        "description": dt.description,
        "priority": dt.priority,
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


# ── Grafana helpers ───────────────────────────────────────────────────────────

async def _get_system_setting(db: AsyncSession, key: str) -> str | None:
    row = await db.get(SystemSetting, key)
    return row.value if row else None


async def _export_grafana_dashboards(grafana_url: str, pack: Pack) -> list[dict]:
    """Fetch dashboards from Grafana that are tagged with the pack UID.

    Convention: dashboards belonging to a pack are tagged with `pack:{pack_uid}`.
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{grafana_url}/api/search",
            params={"tag": f"pack:{pack.pack_uid}", "type": "dash-db"},
            timeout=10.0,
        )
        resp.raise_for_status()
        search_results = resp.json()

        dashboards = []
        for item in search_results:
            detail_resp = await client.get(
                f"{grafana_url}/api/dashboards/uid/{item['uid']}",
                timeout=10.0,
            )
            detail_resp.raise_for_status()
            detail = detail_resp.json()

            dashboards.append({
                "name": item.get("title", ""),
                "uid": item.get("uid", ""),
                "description": detail.get("dashboard", {}).get("description", ""),
                "dashboard_json": detail.get("dashboard", {}),
            })

        return dashboards


async def _import_grafana_dashboards(
    grafana_url: str,
    dashboards: list[dict],
    pack_uid: str,
    resolutions: dict[str, str],
) -> list[dict]:
    """Import Grafana dashboards via Grafana HTTP API."""
    import httpx

    results = []
    async with httpx.AsyncClient() as client:
        for db_entry in dashboards:
            resolution_key = f"grafana_dashboards:{db_entry['uid']}"
            resolution = resolutions.get(resolution_key, "create")

            if resolution == "skip":
                results.append({"name": db_entry["name"], "action": "skipped"})
                continue

            dashboard_json = db_entry["dashboard_json"]
            dashboard_json.setdefault("tags", [])
            if f"pack:{pack_uid}" not in dashboard_json["tags"]:
                dashboard_json["tags"].append(f"pack:{pack_uid}")

            # Remove id to allow creation/overwrite
            dashboard_json.pop("id", None)

            payload = {
                "dashboard": dashboard_json,
                "folderId": 0,
                "overwrite": resolution == "overwrite",
            }

            try:
                resp = await client.post(
                    f"{grafana_url}/api/dashboards/db",
                    json=payload,
                    timeout=10.0,
                )
                resp.raise_for_status()
                results.append({"name": db_entry["name"], "action": "created"})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 412:
                    results.append({"name": db_entry["name"], "action": "conflict"})
                else:
                    results.append({"name": db_entry["name"], "action": "failed", "error": str(exc)})

    return results


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

            # Device types: also match on sys_object_id_pattern (unique constraint)
            if section == "device_types" and not existing:
                pattern = item.get("sys_object_id_pattern", "")
                if pattern:
                    existing = (await db.execute(
                        select(DeviceType).where(DeviceType.sys_object_id_pattern == pattern)
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

    # Count alert definitions at app level (informational entries)
    for app_item in data.get("contents", {}).get("apps", []):
        alert_count = len(app_item.get("alert_definitions", []))
        if alert_count > 0:
            entities.append({
                "section": "alert_definitions",
                "name": f"{app_item['name']} ({alert_count} alert"
                        f"{'s' if alert_count != 1 else ''})",
                "status": "info",
                "existing_pack": None,
            })

    # Grafana dashboards (informational — not stored in DB)
    for gd in data.get("contents", {}).get("grafana_dashboards", []):
        entities.append({
            "section": "grafana_dashboards",
            "name": gd.get("name", gd.get("uid", "?")),
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

            # Device types: resolve device_category_name → device_category_id before any create/update
            if section == "device_types" and "device_category_name" in item:
                dc = (await db.execute(
                    select(DeviceCategory).where(DeviceCategory.name == item["device_category_name"])
                )).scalar_one_or_none()
                if dc:
                    item["_resolved_device_category_id"] = str(dc.id)
                else:
                    logger.warning("device_type_skip_no_device_category",
                                   rule=item_name, device_category_name=item["device_category_name"])
                    stats["skipped"] += 1
                    continue

            existing = (await db.execute(
                select(model).where(getattr(model, name_field) == item_name)
            )).scalar_one_or_none()

            # Device types: also check for existing pattern match (unique constraint)
            if section == "device_types" and not existing:
                pattern = item.get("sys_object_id_pattern", "")
                if pattern:
                    existing = (await db.execute(
                        select(DeviceType).where(DeviceType.sys_object_id_pattern == pattern)
                    )).scalar_one_or_none()
                    if existing:
                        # Update resolution to overwrite by default for pattern match
                        resolution = resolutions.get(resolution_key, "overwrite")

            if existing and resolution == "skip":
                stats["skipped"] += 1
                if section == "apps":
                    await _sync_app_versions(
                        db, existing, item.get("versions", []),
                        pack_uid=pack_uid, pack_id=pack.id, skip_app_update=True,
                        alert_defs_data=item.get("alert_definitions", []),
                        threshold_vars_data=item.get("threshold_variables", []),
                    )
                continue
            elif existing and resolution == "overwrite":
                _update_entity(existing, item, section, pack.id)
                if section == "apps":
                    await _sync_app_versions(
                        db, existing, item.get("versions", []),
                        pack_uid=pack_uid, pack_id=pack.id,
                        alert_defs_data=item.get("alert_definitions", []),
                        threshold_vars_data=item.get("threshold_variables", []),
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
                        alert_defs_data=item.get("alert_definitions", []),
                        threshold_vars_data=item.get("threshold_variables", []),
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
                        alert_defs_data=item.get("alert_definitions", []),
                        threshold_vars_data=item.get("threshold_variables", []),
                    )
                elif section == "connectors":
                    await _create_connector_versions(db, entity, item.get("versions", []))
                stats["created"] += 1

    await db.flush()

    # Import Grafana dashboards (if present and Grafana is configured)
    grafana_results = []
    grafana_dashboards = data.get("contents", {}).get("grafana_dashboards", [])
    if grafana_dashboards:
        grafana_url = await _get_system_setting(db, "grafana_url")
        if grafana_url:
            try:
                grafana_results = await _import_grafana_dashboards(
                    grafana_url, grafana_dashboards, pack_uid, resolutions,
                )
            except Exception:
                logger.warning("Failed to import Grafana dashboards for pack %s", pack_uid)

    result = {"pack_id": str(pack.id), "version": version, **stats}
    if grafana_results:
        result["grafana_dashboards"] = grafana_results
    return result


def _build_manifest(data: dict) -> dict:
    manifest: dict = {}
    contents = data.get("contents", {})
    for section in ["apps", "credential_templates", "snmp_oids",
                     "device_templates", "device_categories", "label_keys", "connectors",
                     "device_types"]:
        items = contents.get(section, [])
        if items:
            if section == "apps":
                manifest[section] = [item["name"] for item in items]
                # Also count app-level alert definitions
                alert_names: list[str] = []
                for app_item in items:
                    for ad in app_item.get("alert_definitions", []):
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
    elif section == "device_categories":
        return DeviceCategory(
            name=item["name"],
            description=item.get("description"),
            category=item.get("category", "other"),
            icon=item.get("icon"),
            pack_id=pack_id,
        )
    elif section == "device_types":
        # device_category_id is resolved before calling this
        return DeviceType(
            name=item["name"],
            sys_object_id_pattern=item["sys_object_id_pattern"],
            device_category_id=uuid.UUID(item["_resolved_device_category_id"]),
            vendor=item.get("vendor"),
            model=item.get("model"),
            os_family=item.get("os_family"),
            description=item.get("description"),
            priority=item.get("priority", 0),
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
    elif section == "device_categories":
        existing.description = item.get("description")
        existing.category = item.get("category", existing.category)
        if "icon" in item:
            existing.icon = item["icon"]
    elif section == "device_types":
        existing.sys_object_id_pattern = item.get("sys_object_id_pattern", existing.sys_object_id_pattern)
        if "_resolved_device_category_id" in item:
            existing.device_category_id = uuid.UUID(item["_resolved_device_category_id"])
        existing.vendor = item.get("vendor")
        existing.model = item.get("model")
        existing.os_family = item.get("os_family")
        existing.description = item.get("description")
        existing.priority = item.get("priority", existing.priority)
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
    alert_defs_data: list[dict] | None = None,
    threshold_vars_data: list[dict] | None = None,
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
    # Import threshold variables BEFORE alert definitions
    if threshold_vars_data:
        await _import_threshold_variables(db, app, threshold_vars_data)
    # Sync alert definitions at app level
    if alert_defs_data:
        await _sync_app_alert_definitions(db, app, alert_defs_data, pack_uid)


async def _sync_app_versions(
    db: AsyncSession,
    app: App,
    versions_data: list[dict],
    pack_uid: str | None = None,
    pack_id: uuid.UUID | None = None,
    skip_app_update: bool = False,
    alert_defs_data: list[dict] | None = None,
    threshold_vars_data: list[dict] | None = None,
) -> None:
    existing = (await db.execute(
        select(AppVersion).where(AppVersion.app_id == app.id)
    )).scalars().all()
    existing_by_ver = {v.version: v for v in existing}

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

    await db.flush()
    all_v = (await db.execute(
        select(AppVersion).where(AppVersion.app_id == app.id)
    )).scalars().all()
    for v in all_v:
        matching = next((vd for vd in versions_data if vd["version"] == v.version), None)
        v.is_latest = matching.get("is_latest", False) if matching else False

    # Import threshold variables BEFORE alert definitions
    if threshold_vars_data:
        await _import_threshold_variables(db, app, threshold_vars_data)
    # Sync alert definitions at app level
    if alert_defs_data:
        await _sync_app_alert_definitions(db, app, alert_defs_data, pack_uid)


async def _import_threshold_variables(
    db: AsyncSession,
    app: App,
    threshold_vars_data: list[dict],
) -> None:
    """Import threshold variables for an app from pack data."""
    for tv_data in threshold_vars_data:
        existing = (await db.execute(
            select(ThresholdVariable).where(
                ThresholdVariable.app_id == app.id,
                ThresholdVariable.name == tv_data["name"],
            )
        )).scalar_one_or_none()
        if existing is None:
            new_var = ThresholdVariable(
                app_id=app.id,
                name=tv_data["name"],
                default_value=tv_data["default_value"],
                display_name=tv_data.get("display_name"),
                unit=tv_data.get("unit"),
                description=tv_data.get("description"),
            )
            db.add(new_var)
        else:
            # Update default_value, but preserve app_value (user override)
            if existing.default_value != tv_data["default_value"]:
                existing.default_value = tv_data["default_value"]
            # Update display_name/unit/description only if not yet set
            if tv_data.get("display_name") and not existing.display_name:
                existing.display_name = tv_data["display_name"]
            if tv_data.get("description") and not existing.description:
                existing.description = tv_data["description"]
    await db.flush()


async def _sync_app_alert_definitions(
    db: AsyncSession,
    app: App,
    alert_defs_data: list[dict],
    pack_uid: str | None = None,
) -> None:
    """Sync alert definitions for an app from pack data.

    - Creates missing definitions
    - Updates existing definitions if expression differs (matched by name)
    - Does NOT delete definitions not in the pack (user may have added custom ones)
    """
    if not alert_defs_data:
        return

    existing_defs = (await db.execute(
        select(AlertDefinition).where(
            AlertDefinition.app_id == app.id,
        )
    )).scalars().all()
    existing_by_name = {d.name: d for d in existing_defs}

    for ad_data in alert_defs_data:
        name = ad_data["name"]
        if name in existing_by_name:
            existing_def = existing_by_name[name]
            # Update if expression differs
            if existing_def.expression != ad_data["expression"]:
                existing_def.expression = ad_data["expression"]
                existing_def.window = ad_data.get("window", "5m")
                existing_def.enabled = ad_data.get("enabled", True)
                existing_def.description = ad_data.get("description")
                existing_def.message_template = ad_data.get("message_template")
                existing_def.pack_origin = pack_uid
        else:
            # Create new definition
            existing_def = AlertDefinition(
                app_id=app.id,
                name=name,
                expression=ad_data["expression"],
                window=ad_data.get("window", "5m"),
                enabled=ad_data.get("enabled", True),
                description=ad_data.get("description"),
                message_template=ad_data.get("message_template"),
                pack_origin=pack_uid,
            )
            db.add(existing_def)
            await db.flush()
            existing_by_name[name] = existing_def
            # Auto-create AlertEntities for existing assignments
            from monctl_central.alerting.instance_sync import sync_instances_for_definition
            await sync_instances_for_definition(db, existing_def)

    # Sync threshold variables for all definitions
    from monctl_central.alerting.threshold_sync import sync_threshold_variables
    for ad_data in alert_defs_data:
        defn = existing_by_name.get(ad_data["name"])
        if defn:
            await sync_threshold_variables(
                db,
                app_id=app.id,
                definition=defn,
                target_table=app.target_table,
                pack_hints=ad_data.get("threshold_defaults"),
            )


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
        .select_from(AlertDefinition)
        .join(App, AlertDefinition.app_id == App.id)
        .where(App.pack_id == pack_id)
    )).scalar() or 0
    counts["alert_definitions"] = alert_count

    return counts
