"""Hierarchical template resolution engine.

Resolves templates for a device by merging category-level and type-level
template bindings. Type-level overrides category-level on overlap.
"""

from __future__ import annotations

import copy
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.storage.models import (
    Device,
    DeviceCategory,
    DeviceCategoryTemplateBinding,
    DeviceType,
    DeviceTypeTemplateBinding,
    Template,
)


def merge_configs(base: dict, overlay: dict) -> dict:
    """Merge two template configs. Overlay wins on overlap.

    - monitoring roles: overlay replaces per role
    - apps: overlay replaces by app_name match, non-overlapping kept
    - labels: dict merge, overlay wins per key
    - scalars (credential, collector group): overlay wins if set
    """
    result = copy.deepcopy(base)

    # Monitoring: overlay per role
    if overlay.get("monitoring"):
        result.setdefault("monitoring", {})
        for role in ("availability", "latency", "interface"):
            if overlay["monitoring"].get(role):
                result["monitoring"][role] = copy.deepcopy(overlay["monitoring"][role])

    # Apps: overlay by app_name
    if overlay.get("apps"):
        existing_apps = {a["app_name"]: a for a in result.get("apps", []) if a.get("app_name")}
        for app_entry in overlay["apps"]:
            if app_entry.get("app_name"):
                existing_apps[app_entry["app_name"]] = copy.deepcopy(app_entry)
        result["apps"] = list(existing_apps.values())

    # Labels: dict merge
    if overlay.get("labels"):
        result.setdefault("labels", {})
        result["labels"].update(overlay["labels"])

    # Scalar overrides
    if overlay.get("default_credential_id"):
        result["default_credential_id"] = overlay["default_credential_id"]
    if overlay.get("default_collector_group_id"):
        result["default_collector_group_id"] = overlay["default_collector_group_id"]

    return result


def _sort_key(binding):
    """Sort bindings by priority (asc), then template name for determinism."""
    return (binding.priority, binding.template.name)


async def resolve_templates_for_device(
    device: Device, db: AsyncSession
) -> dict:
    """Resolve merged template config for a device using hierarchy.

    1. Load category-level bindings (via device.device_category string → DeviceCategory)
    2. Load type-level bindings (via device.device_type_id)
    3. Merge in order: category templates (low→high priority), then type templates
    """
    merged: dict = {}
    source_templates: list[dict] = []

    # Phase 1: category-level
    if device.device_category:
        cat_stmt = (
            select(DeviceCategoryTemplateBinding)
            .join(DeviceCategory)
            .join(Template)
            .where(DeviceCategory.name == device.device_category)
            .options(
                selectinload(DeviceCategoryTemplateBinding.template),
                selectinload(DeviceCategoryTemplateBinding.device_category),
            )
        )
        cat_bindings = (await db.execute(cat_stmt)).scalars().all()
        for binding in sorted(cat_bindings, key=_sort_key):
            merged = merge_configs(merged, binding.template.config or {})
            source_templates.append({
                "template_id": str(binding.template.id),
                "template_name": binding.template.name,
                "level": "category",
                "category_name": binding.device_category.name,
                "priority": binding.priority,
            })

    # Phase 2: type-level (overrides category)
    if device.device_type_id:
        type_stmt = (
            select(DeviceTypeTemplateBinding)
            .join(DeviceType)
            .join(Template)
            .where(DeviceTypeTemplateBinding.device_type_id == device.device_type_id)
            .options(
                selectinload(DeviceTypeTemplateBinding.template),
                selectinload(DeviceTypeTemplateBinding.device_type),
            )
        )
        type_bindings = (await db.execute(type_stmt)).scalars().all()
        for binding in sorted(type_bindings, key=_sort_key):
            merged = merge_configs(merged, binding.template.config or {})
            source_templates.append({
                "template_id": str(binding.template.id),
                "template_name": binding.template.name,
                "level": "device_type",
                "device_type_name": binding.device_type.name,
                "priority": binding.priority,
            })

    return {"config": merged, "source_templates": source_templates}


async def resolve_templates_for_devices(
    devices: list[Device], db: AsyncSession
) -> list[dict]:
    """Batch-resolve templates for multiple devices.

    Groups devices by (device_category, device_type_id) to avoid redundant queries.
    """
    cache: dict[tuple, dict] = {}
    results = []

    for device in devices:
        cache_key = (device.device_category, str(device.device_type_id) if device.device_type_id else None)
        if cache_key not in cache:
            cache[cache_key] = await resolve_templates_for_device(device, db)

        resolved = cache[cache_key]
        results.append({
            "device_id": str(device.id),
            "device_name": device.name,
            "device_address": device.address,
            "resolved_config": resolved["config"],
            "source_templates": resolved["source_templates"],
        })

    return results
