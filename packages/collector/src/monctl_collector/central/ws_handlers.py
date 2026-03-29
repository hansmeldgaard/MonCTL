"""Handlers for WebSocket commands received from central."""

from __future__ import annotations

import urllib.request
import json

import structlog

logger = structlog.get_logger()

_job_scheduler = None
_central_client = None
_sidecar_url = "http://monctl-docker-stats:9100"
_app_manager = None
_credential_manager = None


def init_handlers(scheduler, central_client, sidecar_url: str = "http://localhost:9100",
                  app_manager=None, credential_manager=None):
    """Initialize handler references. Called during cache-node startup."""
    global _job_scheduler, _central_client, _sidecar_url, _app_manager, _credential_manager
    _job_scheduler = scheduler
    _central_client = central_client
    _sidecar_url = sidecar_url
    _app_manager = app_manager
    _credential_manager = credential_manager


async def handle_poll_device(payload: dict) -> dict:
    """Trigger an ad-hoc poll of a specific device/assignment."""
    assignment_id = payload.get("assignment_id")
    device_id = payload.get("device_id")

    if not assignment_id:
        return {"success": False, "error": "assignment_id required"}

    if _job_scheduler:
        # trigger_immediate may not exist yet — graceful fallback
        trigger = getattr(_job_scheduler, "trigger_immediate", None)
        if trigger:
            success = await trigger(assignment_id)
            return {"success": success, "device_id": device_id, "assignment_id": assignment_id}
        return {"success": False, "error": "trigger_immediate not implemented yet"}

    return {"success": False, "error": "Scheduler not available"}


async def handle_config_reload(payload: dict) -> dict:
    """Signal the cache-node to re-fetch jobs from central."""
    if _job_scheduler:
        force_sync = getattr(_job_scheduler, "force_sync", None)
        if force_sync:
            await force_sync()
            return {"acknowledged": True}
        return {"acknowledged": True, "note": "force_sync not implemented, will sync on next interval"}
    return {"acknowledged": False, "error": "Scheduler not available"}


async def handle_health_check(payload: dict) -> dict:
    """Return current collector health status."""
    result = {"acknowledged": True}

    if _job_scheduler:
        import dataclasses
        load = dataclasses.asdict(_job_scheduler.get_current_load_info())
        result.update(load)

    return result


async def handle_module_update(payload: dict) -> dict:
    """Acknowledge that new modules are available."""
    return {"acknowledged": True}


async def handle_docker_health(payload: dict) -> dict:
    """Fetch Docker container stats from local sidecar."""
    try:
        req = urllib.request.Request(f"{_sidecar_url}/stats", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return {"success": True, "data": data}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def handle_docker_logs(payload: dict) -> dict:
    """Fetch Docker container logs from local sidecar."""
    container = payload.get("container", "")
    tail = payload.get("tail", 100)

    try:
        url = f"{_sidecar_url}/logs?container={container}&tail={tail}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return {"success": True, "data": data}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def handle_probe_oids(payload: dict) -> dict:
    """Probe specific SNMP OIDs on a device for eligibility checking.

    Uses the SNMP connector (same as poll-workers) to query OIDs.

    payload:
        device_host: str — IP/hostname to probe
        credential_name: str — SNMP credential name
        oids: list[str] — OIDs to GET
        connector_binding: {connector_id, connector_version_id}
    """
    device_host = payload.get("device_host")
    credential_name = payload.get("credential_name")
    oids = payload.get("oids", [])
    binding = payload.get("connector_binding", {})

    if not device_host or not oids:
        return {"success": False, "error": "device_host and oids required"}

    if not _app_manager or not _credential_manager:
        return {"success": False, "error": "App/credential manager not available"}

    connector_id = binding.get("connector_id")
    version_id = binding.get("connector_version_id")
    if not connector_id or not version_id:
        return {"success": False, "error": "connector_binding required"}

    try:
        # Load connector class via AppManager (downloads + installs if needed)
        # Load credential first — connector needs it in settings
        cred_data = {}
        if credential_name:
            cred_data = await _credential_manager.get_credential(credential_name) or {}

        connector_cls = await _app_manager.ensure_connector(connector_id, version_id)
        connector = connector_cls(settings={**binding.get("settings", {}), **cred_data})

        # Connect and probe
        await connector.connect(device_host)
        try:
            raw = await connector.get(oids)
        finally:
            close = getattr(connector, "close", None)
            if close:
                try:
                    await close()
                except Exception:
                    pass

        # Decode results
        import binascii

        def _decode(value) -> str | None:
            if value is None:
                return None
            val_str = str(value)
            if val_str.startswith("0x") and len(val_str) > 2:
                try:
                    return binascii.unhexlify(val_str[2:]).decode("utf-8", errors="replace").rstrip("\x00")
                except (ValueError, UnicodeDecodeError):
                    pass
            val_lower = val_str.lower()
            if "nosuchobject" in val_lower or "nosuchinstance" in val_lower:
                return None
            return val_str

        results = {}
        for oid in oids:
            results[oid] = _decode(raw.get(oid))

        return {"success": True, "results": results}

    except Exception as exc:
        logger.warning("probe_oids_failed", device_host=device_host, error=str(exc))
        return {"success": False, "error": str(exc)}
