"""OS update management via docker-stats sidecar."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger()

SIDECAR_PORT = 9100
SIDECAR_TIMEOUT = 120.0


async def check_node_updates(node_ip: str) -> list[dict]:
    """Query a node's sidecar for available OS updates."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/check"
    async with httpx.AsyncClient(timeout=SIDECAR_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"OS check failed on {node_ip}: {data['error']}")
    return data.get("updates", [])


async def install_packages_on_node(node_ip: str, package_names: list[str]) -> dict:
    """Tell a node's sidecar to install packages via apt-get."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/install"
    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(url, json={"packages": package_names})
        resp.raise_for_status()
        return resp.json()


async def install_deb_files_on_node(node_ip: str, deb_dir: str, filenames: list[str]) -> dict:
    """Tell a node's sidecar to install .deb files via dpkg -i."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/install-deb"
    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(url, json={"deb_dir": deb_dir, "filenames": filenames})
        resp.raise_for_status()
        return resp.json()


async def download_packages_via_sidecar(node_ip: str, package_names: list[str]) -> dict:
    """Tell a node's sidecar to apt-get download packages."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/download"
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(url, json={"packages": package_names})
        resp.raise_for_status()
        return resp.json()


async def fetch_deb_from_sidecar(node_ip: str, filename: str) -> bytes:
    """Download a .deb file from a node's sidecar."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/packages/{filename}"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def compute_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()
