"""Handlers for WebSocket commands received from central."""

from __future__ import annotations

import urllib.request
import json

import structlog

logger = structlog.get_logger()

_job_scheduler = None
_central_client = None
_sidecar_url = "http://localhost:9100"


def init_handlers(scheduler, central_client, sidecar_url: str = "http://localhost:9100"):
    """Initialize handler references. Called during cache-node startup."""
    global _job_scheduler, _central_client, _sidecar_url
    _job_scheduler = scheduler
    _central_client = central_client
    _sidecar_url = sidecar_url


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
