"""Pack JSON schema validation."""

from __future__ import annotations

import re

from fastapi import HTTPException


_VALID_UNITS = {"percent", "ms", "seconds", "bytes", "count", "ratio", "dBm", "pps", "bps"}


def _validate_threshold_defaults(alert_def: dict) -> None:
    """Validate threshold_defaults entries in an alert definition."""
    for td in alert_def.get("threshold_defaults", []):
        name = alert_def.get("name", "?")
        if not td.get("param_key"):
            raise HTTPException(
                status_code=400,
                detail=f"threshold_defaults entry in alert '{name}' requires param_key",
            )
        if "default_value" not in td:
            raise HTTPException(
                status_code=400,
                detail=f"threshold_defaults entry '{td.get('param_key')}' in alert "
                       f"'{name}' requires default_value",
            )
        if td.get("unit") and td["unit"] not in _VALID_UNITS:
            raise HTTPException(
                status_code=400,
                detail=f"threshold_defaults unit '{td['unit']}' in alert '{name}' "
                       f"must be one of: {', '.join(sorted(_VALID_UNITS))}",
            )


VALID_SECTIONS = {
    "apps", "credential_templates", "snmp_oids",
    "device_templates", "device_categories", "label_keys", "connectors",
    "device_types", "grafana_dashboards", "event_policies",
}

_VALID_EVENT_SEVERITIES = {"info", "warning", "critical", "emergency"}
_VALID_EVENT_MODES = {"consecutive", "cumulative"}


def validate_pack_schema(data: dict) -> None:
    """Validate pack JSON structure. Raises HTTPException(400) on invalid."""
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Pack data must be a JSON object")

    if data.get("monctl_pack") != "1.0":
        raise HTTPException(status_code=400, detail="Unsupported pack format version (expected '1.0')")

    pack_uid = data.get("pack_uid", "")
    if not pack_uid or not re.match(r"^[a-z0-9][a-z0-9-]{0,126}[a-z0-9]$", pack_uid):
        raise HTTPException(
            status_code=400,
            detail="Invalid pack_uid: must be 2-128 chars, lowercase alphanumeric + hyphens",
        )

    if not data.get("name"):
        raise HTTPException(status_code=400, detail="Pack name is required")

    version = data.get("version", "")
    if not version or not re.match(r"^\d+\.\d+(\.\d+)?$", version):
        raise HTTPException(status_code=400, detail="Invalid version: must be semver (e.g. '1.0.0')")

    contents = data.get("contents", {})
    if not isinstance(contents, dict):
        raise HTTPException(status_code=400, detail="contents must be an object")

    for key in contents:
        if key not in VALID_SECTIONS:
            raise HTTPException(status_code=400, detail=f"Unknown section: {key}")

    for app in contents.get("apps", []):
        if not app.get("name"):
            raise HTTPException(status_code=400, detail="App name is required")
        if not app.get("versions") or len(app["versions"]) == 0:
            raise HTTPException(
                status_code=400, detail=f"App '{app['name']}' must have at least one version"
            )
        # Validate alert_definitions within each version
        for ver in app["versions"]:
            for alert_def in ver.get("alert_definitions", []):
                if not alert_def.get("name"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Alert definition in app '{app['name']}' version "
                               f"'{ver.get('version', '?')}' requires a name",
                    )
                if not alert_def.get("expression"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Alert definition '{alert_def.get('name', '?')}' in app "
                               f"'{app['name']}' requires an expression",
                    )
                if alert_def.get("severity") and alert_def["severity"] not in (
                    "info", "warning", "critical", "emergency",
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Alert definition '{alert_def['name']}': "
                               "severity must be info/warning/critical/emergency",
                    )
                if alert_def.get("window") and alert_def["window"] not in (
                    "30s", "1m", "5m", "15m", "1h", "6h", "1d",
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Alert definition '{alert_def['name']}': invalid window value",
                    )
                _validate_threshold_defaults(alert_def)

        # App-level alert_definitions (new location)
        for alert_def in app.get("alert_definitions", []):
            if not alert_def.get("name"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Alert definition in app '{app['name']}' requires a name",
                )
            if not alert_def.get("expression"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Alert definition '{alert_def.get('name', '?')}' in app "
                           f"'{app['name']}' requires an expression",
                )
            _validate_threshold_defaults(alert_def)

        # App-level threshold_variables
        for tv in app.get("threshold_variables", []):
            app_name = app.get("name", "?")
            if not tv.get("name"):
                raise HTTPException(
                    status_code=400,
                    detail=f"threshold_variables entry in app '{app_name}' requires name",
                )
            if not re.match(r"^[a-z_][a-z0-9_]*$", tv["name"]):
                raise HTTPException(
                    status_code=400,
                    detail=f"threshold_variables name '{tv['name']}' in app '{app_name}' "
                           "must be lowercase letters, digits, and underscores only",
                )
            if "default_value" not in tv:
                raise HTTPException(
                    status_code=400,
                    detail=f"threshold_variables entry '{tv['name']}' in app "
                           f"'{app_name}' requires default_value",
                )
            if tv.get("unit") and tv["unit"] not in _VALID_UNITS:
                raise HTTPException(
                    status_code=400,
                    detail=f"threshold_variables unit '{tv['unit']}' in app '{app_name}' "
                           f"must be one of: {', '.join(sorted(_VALID_UNITS))}",
                )

    for conn in contents.get("connectors", []):
        if not conn.get("name"):
            raise HTTPException(status_code=400, detail="Connector name is required")
        if not conn.get("versions") or len(conn["versions"]) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Connector '{conn['name']}' must have at least one version",
            )

    for oid in contents.get("snmp_oids", []):
        if not oid.get("name") or not oid.get("oid"):
            raise HTTPException(status_code=400, detail="SNMP OIDs require name and oid")

    for dr in contents.get("device_types", []):
        if not dr.get("name") or not dr.get("sys_object_id_pattern") or not dr.get("device_category_name"):
            raise HTTPException(
                status_code=400,
                detail="Device types require name, sys_object_id_pattern, and device_category_name",
            )

    for lk in contents.get("label_keys", []):
        if not lk.get("key"):
            raise HTTPException(status_code=400, detail="Label keys require key field")

    for i, gd in enumerate(contents.get("grafana_dashboards", [])):
        if not isinstance(gd, dict):
            raise HTTPException(status_code=400, detail=f"grafana_dashboards[{i}] must be an object")
        if not gd.get("name"):
            raise HTTPException(status_code=400, detail=f"grafana_dashboards[{i}].name is required")
        if not gd.get("uid"):
            raise HTTPException(status_code=400, detail=f"grafana_dashboards[{i}].uid is required")
        if not isinstance(gd.get("dashboard_json"), dict):
            raise HTTPException(
                status_code=400,
                detail=f"grafana_dashboards[{i}].dashboard_json must be an object",
            )

    for i, ep in enumerate(contents.get("event_policies", [])):
        if not isinstance(ep, dict):
            raise HTTPException(status_code=400, detail=f"event_policies[{i}] must be an object")
        if not ep.get("name"):
            raise HTTPException(status_code=400, detail=f"event_policies[{i}].name is required")
        if not ep.get("app_name"):
            raise HTTPException(
                status_code=400, detail=f"event_policies[{i}].app_name is required",
            )
        if not ep.get("alert_name"):
            raise HTTPException(
                status_code=400, detail=f"event_policies[{i}].alert_name is required",
            )
        if ep.get("mode") and ep["mode"] not in _VALID_EVENT_MODES:
            raise HTTPException(
                status_code=400,
                detail=f"event_policies[{i}].mode must be consecutive or cumulative",
            )
        if ep.get("event_severity") and ep["event_severity"] not in _VALID_EVENT_SEVERITIES:
            raise HTTPException(
                status_code=400,
                detail=f"event_policies[{i}].event_severity must be one of: "
                       f"{', '.join(sorted(_VALID_EVENT_SEVERITIES))}",
            )
