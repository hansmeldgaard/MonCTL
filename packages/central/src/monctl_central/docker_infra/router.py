"""Docker Infrastructure proxy router.

Proxies requests to docker-stats sidecars on central-tier hosts.
Worker-tier data comes from ClickHouse (via the existing _check_docker_infrastructure).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
import httpx

from monctl_central.config import settings
from monctl_central.dependencies import require_admin

router = APIRouter()


def _get_sidecar_hosts() -> dict[str, str]:
    """Parse MONCTL_DOCKER_STATS_HOSTS into {label: base_url} dict."""
    raw = settings.docker_stats_hosts
    hosts = {}
    if raw:
        for entry in raw.split(","):
            parts = entry.strip().split(":")
            if len(parts) == 3:
                hosts[parts[0]] = f"http://{parts[1]}:{parts[2]}"
    return hosts


def _get_host_url(host_label: str) -> str:
    """Resolve a host label to its sidecar base URL. Raises 404 if unknown."""
    hosts = _get_sidecar_hosts()
    url = hosts.get(host_label)
    if not url:
        raise HTTPException(status_code=404, detail=f"Unknown docker host: {host_label}")
    return url


@router.get("/hosts")
async def list_docker_hosts(auth: dict = Depends(require_admin)):
    """List all configured docker sidecar hosts."""
    hosts = _get_sidecar_hosts()
    return {
        "status": "success",
        "data": [{"label": label, "url": url} for label, url in hosts.items()],
    }


@router.get("/overview")
async def get_docker_overview(auth: dict = Depends(require_admin)):
    """Fetch system info from all sidecar hosts in parallel."""
    hosts = _get_sidecar_hosts()
    if not hosts:
        return {"status": "success", "data": {"configured": False, "hosts": []}}

    async def _fetch(client: httpx.AsyncClient, label: str, base_url: str) -> dict:
        try:
            resp = await client.get(f"{base_url}/system", timeout=5.0)
            resp.raise_for_status()
            return {"label": label, "status": "ok", "data": resp.json()}
        except Exception as exc:
            return {"label": label, "status": "unreachable", "error": str(exc), "data": None}

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_fetch(client, label, url) for label, url in hosts.items()]
        )

    return {
        "status": "success",
        "data": {
            "configured": True,
            "hosts": list(results),
        },
    }


@router.get("/hosts/{host_label}/stats")
async def get_host_stats(host_label: str, auth: dict = Depends(require_admin)):
    """Proxy /stats from a specific sidecar host."""
    url = _get_host_url(host_label)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{url}/stats", timeout=5.0)
            resp.raise_for_status()
            return {"status": "success", "data": resp.json()}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")


@router.get("/hosts/{host_label}/logs")
async def get_container_logs(
    host_label: str,
    container: str = Query(..., description="Container name"),
    tail: int = Query(100, ge=1, le=500),
    auth: dict = Depends(require_admin),
):
    """Proxy container logs from a specific sidecar host."""
    url = _get_host_url(host_label)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{url}/logs",
                params={"container": container, "tail": tail},
                timeout=5.0,
            )
            resp.raise_for_status()
            return {"status": "success", "data": resp.json()}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")


@router.get("/hosts/{host_label}/events")
async def get_docker_events(
    host_label: str,
    since: float = Query(0, description="Unix timestamp filter"),
    limit: int = Query(100, ge=1, le=500),
    auth: dict = Depends(require_admin),
):
    """Proxy docker events from a specific sidecar host."""
    url = _get_host_url(host_label)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{url}/events",
                params={"since": since, "limit": limit},
                timeout=5.0,
            )
            resp.raise_for_status()
            return {"status": "success", "data": resp.json()}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")


@router.get("/hosts/{host_label}/images")
async def get_docker_images(host_label: str, auth: dict = Depends(require_admin)):
    """Proxy image/volume inventory from a specific sidecar host."""
    url = _get_host_url(host_label)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{url}/images", timeout=10.0)
            resp.raise_for_status()
            return {"status": "success", "data": resp.json()}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")


@router.get("/hosts/{host_label}/system")
async def get_host_system_info(host_label: str, auth: dict = Depends(require_admin)):
    """Proxy host system info from a specific sidecar host."""
    url = _get_host_url(host_label)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{url}/system", timeout=5.0)
            resp.raise_for_status()
            return {"status": "success", "data": resp.json()}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sidecar unreachable: {exc}")
