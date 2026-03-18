"""Pack JSON schema validation."""

from __future__ import annotations

import re

from fastapi import HTTPException


VALID_SECTIONS = {
    "apps", "alert_rules", "credential_templates", "snmp_oids",
    "device_templates", "device_types", "label_keys", "connectors",
}


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

    for conn in contents.get("connectors", []):
        if not conn.get("name"):
            raise HTTPException(status_code=400, detail="Connector name is required")
        if not conn.get("versions") or len(conn["versions"]) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Connector '{conn['name']}' must have at least one version",
            )

    for rule in contents.get("alert_rules", []):
        if not rule.get("name") or not rule.get("expression"):
            raise HTTPException(
                status_code=400, detail="Alert rules require name and expression"
            )

    for oid in contents.get("snmp_oids", []):
        if not oid.get("name") or not oid.get("oid"):
            raise HTTPException(status_code=400, detail="SNMP OIDs require name and oid")

    for lk in contents.get("label_keys", []):
        if not lk.get("key"):
            raise HTTPException(status_code=400, detail="Label keys require key field")
