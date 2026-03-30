"""Interface rule matching engine.

Evaluates declarative rules against interface properties and applies
monitoring settings. Rules are stored on Device.interface_rules (JSONB)
and evaluated at interface discovery, metadata change, and manual trigger.
"""

from __future__ import annotations

import fnmatch
import logging
import re
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from monctl_central.storage.models import InterfaceMetadata

log = logging.getLogger(__name__)

_VALID_MATCH_FIELDS_STR = {"if_alias", "if_name", "if_descr"}
_VALID_MATCH_FIELDS_NUM = {"if_speed_mbps"}
_VALID_STRING_TYPES = {"glob", "regex", "exact"}
_VALID_NUMERIC_OPS = {"eq", "gt", "lt", "gte", "lte"}
_VALID_SETTINGS_KEYS = {"polling_enabled", "alerting_enabled", "poll_metrics"}
_VALID_POLL_METRICS_PARTS = {"all", "traffic", "errors", "discards", "status"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_interface_rules(rules: list) -> list[str]:
    """Validate a list of interface rules. Returns list of error strings (empty = valid)."""
    errors: list[str] = []
    if not isinstance(rules, list):
        return ["interface_rules must be a list"]

    for i, rule in enumerate(rules):
        prefix = f"rule[{i}]"
        if not isinstance(rule, dict):
            errors.append(f"{prefix}: must be a dict")
            continue

        if not rule.get("name") or not isinstance(rule.get("name"), str):
            errors.append(f"{prefix}: 'name' is required (string)")

        # match
        match = rule.get("match")
        if not isinstance(match, dict) or not match:
            errors.append(f"{prefix}: 'match' is required (non-empty dict)")
        else:
            for field, spec in match.items():
                if field in _VALID_MATCH_FIELDS_STR:
                    if not isinstance(spec, dict):
                        errors.append(f"{prefix}.match.{field}: must be a dict")
                        continue
                    stype = spec.get("type", "glob")
                    if stype not in _VALID_STRING_TYPES:
                        errors.append(
                            f"{prefix}.match.{field}: type must be one of {_VALID_STRING_TYPES}"
                        )
                    if not isinstance(spec.get("pattern", ""), str):
                        errors.append(f"{prefix}.match.{field}: pattern must be a string")
                    if stype == "regex":
                        try:
                            re.compile(spec.get("pattern", ""))
                        except re.error as e:
                            errors.append(f"{prefix}.match.{field}: invalid regex: {e}")
                elif field in _VALID_MATCH_FIELDS_NUM:
                    if not isinstance(spec, dict):
                        errors.append(f"{prefix}.match.{field}: must be a dict")
                        continue
                    op = spec.get("op")
                    if op not in _VALID_NUMERIC_OPS:
                        errors.append(
                            f"{prefix}.match.{field}: op must be one of {_VALID_NUMERIC_OPS}"
                        )
                    val = spec.get("value")
                    if not isinstance(val, (int, float)):
                        errors.append(f"{prefix}.match.{field}: value must be a number")
                else:
                    errors.append(
                        f"{prefix}.match.{field}: unknown field "
                        f"(allowed: {_VALID_MATCH_FIELDS_STR | _VALID_MATCH_FIELDS_NUM})"
                    )

        # settings
        settings = rule.get("settings")
        if not isinstance(settings, dict) or not settings:
            errors.append(f"{prefix}: 'settings' is required (non-empty dict)")
        else:
            for key, val in settings.items():
                if key not in _VALID_SETTINGS_KEYS:
                    errors.append(f"{prefix}.settings.{key}: unknown setting")
                elif key in ("polling_enabled", "alerting_enabled"):
                    if not isinstance(val, bool):
                        errors.append(f"{prefix}.settings.{key}: must be boolean")
                elif key == "poll_metrics":
                    if not isinstance(val, str):
                        errors.append(f"{prefix}.settings.{key}: must be a string")
                    else:
                        parts = [p.strip() for p in val.split(",") if p.strip()]
                        if not parts or not all(p in _VALID_POLL_METRICS_PARTS for p in parts):
                            errors.append(
                                f"{prefix}.settings.{key}: must be 'all' or comma-separated "
                                f"subset of {_VALID_POLL_METRICS_PARTS - {'all'}}"
                            )

        # priority
        prio = rule.get("priority")
        if not isinstance(prio, int) or prio < 0:
            errors.append(f"{prefix}: 'priority' is required (non-negative int)")

    return errors


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _match_string(field_value: str, spec: dict) -> bool:
    pattern = spec.get("pattern", "")
    match_type = spec.get("type", "glob")
    if match_type == "glob":
        return fnmatch.fnmatch(field_value, pattern)
    elif match_type == "regex":
        try:
            return bool(re.search(pattern, field_value))
        except re.error:
            return False
    elif match_type == "exact":
        return field_value == pattern
    return False


def _match_numeric(field_value: int | float, spec: dict) -> bool:
    op = spec.get("op", "eq")
    val = spec.get("value", 0)
    if op == "eq":
        return field_value == val
    elif op == "gt":
        return field_value > val
    elif op == "lt":
        return field_value < val
    elif op == "gte":
        return field_value >= val
    elif op == "lte":
        return field_value <= val
    return False


def match_interface(rule: dict, iface: dict) -> bool:
    """Check if a rule's match criteria apply to an interface. All fields are AND."""
    match = rule.get("match", {})
    if not match:
        return False
    for field, spec in match.items():
        value = iface.get(field, "" if field in _VALID_MATCH_FIELDS_STR else 0)
        if field in _VALID_MATCH_FIELDS_STR:
            if not _match_string(str(value), spec):
                return False
        elif field in _VALID_MATCH_FIELDS_NUM:
            if not _match_numeric(value if isinstance(value, (int, float)) else 0, spec):
                return False
        else:
            return False
    return True


def evaluate_rules(rules: list[dict], iface: dict) -> dict | None:
    """Evaluate all rules, return settings from highest-priority match, or None."""
    best: dict | None = None
    best_prio = -1
    for rule in rules:
        prio = rule.get("priority", 0)
        if prio > best_prio and match_interface(rule, iface):
            best = rule.get("settings", {})
            best_prio = prio
    return best


def _iface_dict(meta: "InterfaceMetadata") -> dict:
    return {
        "if_name": meta.if_name,
        "if_alias": meta.if_alias,
        "if_descr": meta.if_descr,
        "if_speed_mbps": meta.if_speed_mbps,
    }


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def apply_settings_to_meta(
    meta: "InterfaceMetadata", settings: dict
) -> bool:
    """Apply settings dict to an InterfaceMetadata row. Returns True if anything changed."""
    changed = False
    if "polling_enabled" in settings and meta.polling_enabled != settings["polling_enabled"]:
        meta.polling_enabled = settings["polling_enabled"]
        changed = True
    if "alerting_enabled" in settings and meta.alerting_enabled != settings["alerting_enabled"]:
        meta.alerting_enabled = settings["alerting_enabled"]
        changed = True
    if "poll_metrics" in settings and meta.poll_metrics != settings["poll_metrics"]:
        meta.poll_metrics = settings["poll_metrics"]
        changed = True
    if changed:
        meta.rules_managed = True
    return changed


def apply_rules_to_interface(
    meta: "InterfaceMetadata", rules: list[dict], *, force: bool = False
) -> bool:
    """Evaluate rules against one interface and apply settings.

    Skips interfaces where rules_managed=False (manual override) unless force=True.
    Returns True if settings were changed.
    """
    if not force and not meta.rules_managed and _has_been_manually_set(meta):
        return False
    settings = evaluate_rules(rules, _iface_dict(meta))
    if settings is None:
        return False
    return apply_settings_to_meta(meta, settings)


def _has_been_manually_set(meta: "InterfaceMetadata") -> bool:
    """Check if the interface has been manually configured (not at defaults and not rules_managed)."""
    # If rules_managed is False and settings differ from defaults, assume manual override
    if meta.rules_managed:
        return False
    defaults = (meta.polling_enabled is True and meta.alerting_enabled is True
                and meta.poll_metrics == "all")
    return not defaults


async def apply_rules_to_all_interfaces(
    device_id: uuid.UUID,
    rules: list[dict],
    db: "AsyncSession",
    *,
    force: bool = False,
) -> dict:
    """Re-evaluate rules for all interfaces on a device. Returns summary."""
    from monctl_central.storage.models import InterfaceMetadata
    from monctl_common.utils import utc_now

    stmt = select(InterfaceMetadata).where(InterfaceMetadata.device_id == device_id)
    rows = (await db.execute(stmt)).scalars().all()

    summary = {"total": len(rows), "matched": 0, "changed": 0, "skipped_manual": 0, "unmatched": 0}
    invalidate_names: list[str] = []

    for meta in rows:
        if not force and not meta.rules_managed and _has_been_manually_set(meta):
            summary["skipped_manual"] += 1
            continue
        settings = evaluate_rules(rules, _iface_dict(meta))
        if settings is None:
            summary["unmatched"] += 1
            continue
        summary["matched"] += 1
        if apply_settings_to_meta(meta, settings):
            meta.updated_at = utc_now()
            summary["changed"] += 1
            invalidate_names.append(meta.if_name)

    if invalidate_names:
        await db.flush()
        try:
            from monctl_central.cache import invalidate_cached_interface
            for name in invalidate_names:
                await invalidate_cached_interface(str(device_id), name)
        except Exception:
            log.warning("Failed to invalidate interface cache after rule application", exc_info=True)

    return summary


async def preview_rules(
    device_id: uuid.UUID,
    rules: list[dict],
    db: "AsyncSession",
) -> list[dict]:
    """Dry-run: return per-interface match results without applying."""
    from monctl_central.storage.models import InterfaceMetadata

    stmt = (
        select(InterfaceMetadata)
        .where(InterfaceMetadata.device_id == device_id)
        .order_by(InterfaceMetadata.current_if_index)
    )
    rows = (await db.execute(stmt)).scalars().all()
    results = []
    for meta in rows:
        iface = _iface_dict(meta)
        settings = evaluate_rules(rules, iface)
        # Find which rule matched
        matched_rule_name = None
        if settings is not None:
            best_prio = -1
            for rule in rules:
                prio = rule.get("priority", 0)
                if prio > best_prio and match_interface(rule, iface):
                    matched_rule_name = rule.get("name")
                    best_prio = prio

        current = {
            "polling_enabled": meta.polling_enabled,
            "alerting_enabled": meta.alerting_enabled,
            "poll_metrics": meta.poll_metrics,
        }
        proposed = dict(current)
        if settings:
            proposed.update(settings)

        results.append({
            "interface_id": str(meta.id),
            "if_name": meta.if_name,
            "if_alias": meta.if_alias,
            "if_descr": meta.if_descr,
            "if_speed_mbps": meta.if_speed_mbps,
            "rules_managed": meta.rules_managed,
            "matched_rule": matched_rule_name,
            "current_settings": current,
            "proposed_settings": proposed,
            "would_change": current != proposed,
        })
    return results
