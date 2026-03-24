"""Docker Infrastructure proxy router.

Central-tier hosts: proxied directly to docker-stats sidecars (same network).
Worker-tier hosts: served from Redis (workers push data to central via VIP).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
import httpx

from monctl_central.cache import (
    get_docker_push,
    get_docker_push_events,
    get_docker_push_logs,
    get_pushed_docker_hosts,
)
from monctl_central.config import settings
from monctl_central.dependencies import require_admin

router = APIRouter()


# ---------------------------------------------------------------------------
# Host resolution: central (sidecar HTTP) vs worker (Redis push)
# ---------------------------------------------------------------------------

def _get_central_hosts() -> dict[str, str]:
    """Parse MONCTL_DOCKER_STATS_HOSTS into {label: base_url} dict."""
    raw = settings.docker_stats_hosts
    hosts = {}
    if raw:
        for entry in raw.split(","):
            parts = entry.strip().split(":")
            if len(parts) == 3:
                hosts[parts[0]] = f"http://{parts[1]}:{parts[2]}"
    return hosts


async def _get_worker_hosts() -> dict[str, dict]:
    """Get worker hosts that have recently pushed docker-stats data."""
    pushed = await get_pushed_docker_hosts()
    return {h["host_label"]: h for h in pushed}


async def _resolve_host(host_label: str) -> tuple[str, str | dict]:
    """Resolve host label to ("central", base_url) or ("worker", meta_dict).

    Raises 404 if host is unknown.
    """
    central = _get_central_hosts()
    if host_label in central:
        return ("central", central[host_label])

    workers = await _get_worker_hosts()
    if host_label in workers:
        return ("worker", workers[host_label])

    raise HTTPException(status_code=404, detail=f"Unknown docker host: {host_label}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/hosts")
async def list_docker_hosts(auth: dict = Depends(require_admin)):
    """List all known docker hosts (central sidecars + pushed workers)."""
    central = _get_central_hosts()
    workers = await _get_worker_hosts()

    data = []
    for label, url in central.items():
        data.append({"label": label, "tier": "central", "source": "sidecar", "url": url})
    for label, meta in workers.items():
        if label not in central:
            data.append({"label": label, "tier": "worker", "source": "push", "last_push": meta.get("last_push")})

    return {"status": "success", "data": data}


@router.get("/overview")
async def get_docker_overview(auth: dict = Depends(require_admin)):
    """Fetch unified host list from both central (sidecar) and worker (Redis) tiers."""
    central = _get_central_hosts()
    workers = await _get_worker_hosts()

    if not central and not workers:
        return {"status": "success", "data": {"configured": False, "hosts": []}}

    results = []

    # Central hosts: proxy HTTP — fetch /system + /stats in parallel per host
    async def _fetch_central(client: httpx.AsyncClient, label: str, base_url: str) -> dict:
        try:
            sys_resp, stats_resp = await asyncio.gather(
                client.get(f"{base_url}/system", timeout=5.0),
                client.get(f"{base_url}/stats", timeout=5.0),
            )
            sys_resp.raise_for_status()
            sys_data = sys_resp.json()

            containers = []
            if stats_resp.status_code == 200:
                containers = stats_resp.json().get("containers", [])

            running = [c for c in containers if c.get("status") == "running"]
            unhealthy = [c for c in containers if c.get("health") == "unhealthy"]

            return {
                "label": label,
                "tier": "central",
                "source": "sidecar",
                "status": "ok",
                "container_count": len(running),
                "total_containers": len(containers),
                "unhealthy_count": len(unhealthy),
                "last_seen": None,
                "data": {**sys_data, "containers": containers},
            }
        except Exception as exc:
            return {
                "label": label,
                "tier": "central",
                "source": "sidecar",
                "status": "unreachable",
                "container_count": 0,
                "total_containers": 0,
                "unhealthy_count": 0,
                "last_seen": None,
                "error": str(exc),
                "data": None,
            }

    async with httpx.AsyncClient() as client:
        central_results = await asyncio.gather(
            *[_fetch_central(client, label, url) for label, url in central.items()]
        )
    results.extend(central_results)

    # Worker hosts: read from Redis
    for label, meta in workers.items():
        if label in central:
            continue
        stats = await get_docker_push(label, "stats")
        system = await get_docker_push(label, "system")

        containers = stats.get("containers", []) if stats else []
        running = [c for c in containers if c.get("status") == "running"]
        unhealthy = [c for c in containers if c.get("health") == "unhealthy"]

        if stats or system:
            results.append({
                "label": label,
                "tier": "worker",
                "source": "push",
                "status": "degraded" if unhealthy else "ok",
                "container_count": len(running),
                "total_containers": len(containers),
                "unhealthy_count": len(unhealthy),
                "last_seen": meta.get("last_push"),
                "data": {**(system or {}), "containers": containers},
            })
        else:
            results.append({
                "label": label,
                "tier": "worker",
                "source": "push",
                "status": "stale",
                "container_count": 0,
                "total_containers": 0,
                "unhealthy_count": 0,
                "last_seen": meta.get("last_push"),
                "error": "No recent data",
                "data": None,
            })

    return {
        "status": "success",
        "data": {"configured": True, "hosts": results},
    }


@router.get("/hosts/{host_label}/stats")
async def get_host_stats(host_label: str, auth: dict = Depends(require_admin)):
    """Get container stats from a specific host."""
    tier, ref = await _resolve_host(host_label)

    if tier == "central":
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{ref}/stats", timeout=5.0)
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")

    # Worker: read from Redis
    data = await get_docker_push(host_label, "stats")
    if data is None:
        raise HTTPException(status_code=502, detail="No recent stats data from worker")
    return {"status": "success", "data": data}


@router.get("/hosts/{host_label}/logs")
async def get_container_logs(
    host_label: str,
    container: str = Query(..., description="Container name"),
    tail: int = Query(100, ge=1, le=500),
    auth: dict = Depends(require_admin),
):
    """Get container logs from a specific host."""
    tier, ref = await _resolve_host(host_label)

    if tier == "central":
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{ref}/logs",
                    params={"container": container, "tail": tail},
                    timeout=5.0,
                )
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")

    # Worker: read from Redis
    lines = await get_docker_push_logs(host_label, container, tail)
    return {
        "status": "success",
        "data": {
            "container": container,
            "lines": lines,
            "count": len(lines),
            "buffer_size": 500,
        },
    }


@router.get("/hosts/{host_label}/events")
async def get_docker_events(
    host_label: str,
    since: float = Query(0, description="Unix timestamp filter"),
    limit: int = Query(100, ge=1, le=500),
    auth: dict = Depends(require_admin),
):
    """Get docker events from a specific host."""
    tier, ref = await _resolve_host(host_label)

    if tier == "central":
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{ref}/events",
                    params={"since": since, "limit": limit},
                    timeout=5.0,
                )
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")

    # Worker: read from Redis
    events = await get_docker_push_events(host_label, since, limit)
    return {
        "status": "success",
        "data": {
            "events": events,
            "count": len(events),
            "buffer_size": 500,
            "oldest_ts": events[0]["time"] if events else None,
        },
    }


@router.get("/hosts/{host_label}/images")
async def get_docker_images(host_label: str, auth: dict = Depends(require_admin)):
    """Get image/volume inventory from a specific host."""
    tier, ref = await _resolve_host(host_label)

    if tier == "central":
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{ref}/images", timeout=10.0)
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")

    # Worker: read from Redis
    data = await get_docker_push(host_label, "images")
    if data is None:
        raise HTTPException(status_code=502, detail="No recent images data from worker")
    return {"status": "success", "data": data}


@router.get("/hosts/{host_label}/system")
async def get_host_system_info(host_label: str, auth: dict = Depends(require_admin)):
    """Get host system info from a specific host."""
    tier, ref = await _resolve_host(host_label)

    if tier == "central":
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{ref}/system", timeout=5.0)
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")

    # Worker: read from Redis
    data = await get_docker_push(host_label, "system")
    if data is None:
        raise HTTPException(status_code=502, detail="No recent system data from worker")
    return {"status": "success", "data": data}
