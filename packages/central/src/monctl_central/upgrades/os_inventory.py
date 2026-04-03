"""OS package inventory collection from node sidecars."""

from __future__ import annotations

import asyncio

import httpx
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import NodePackage, SystemVersion
from monctl_central.upgrades.os_service import check_reboot_required

logger = structlog.get_logger()

SIDECAR_PORT = 9100
BATCH_SIZE = 20


async def collect_node_inventory(node_ip: str) -> list[dict]:
    """Fetch installed packages from a node's sidecar."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/installed"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return data.get("packages", [])


async def _get_system_info(node_ip: str) -> dict:
    """Fetch system info from a node's sidecar."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/system"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _collect_one(node: SystemVersion) -> tuple[str, str, list[dict], dict]:
    """Collect inventory + system info for a single node."""
    packages: list[dict] = []
    system_info: dict = {}
    try:
        packages = await collect_node_inventory(node.node_ip)
    except Exception as exc:
        logger.warning("inventory_collection_failed", node=node.node_hostname, error=str(exc))
    try:
        system_info = await _get_system_info(node.node_ip)
    except Exception:
        pass
    return node.node_hostname, node.node_role, packages, system_info


async def collect_all_inventory(session_factory) -> dict[str, int]:
    """Collect package inventory + system info from all nodes in batches.

    Returns {hostname: package_count} for successfully collected nodes.
    """
    async with session_factory() as db:
        result = await db.execute(select(SystemVersion))
        nodes = list(result.scalars().all())

    summary: dict[str, int] = {}

    for i in range(0, len(nodes), BATCH_SIZE):
        batch = nodes[i:i + BATCH_SIZE]
        results = await asyncio.gather(*[_collect_one(n) for n in batch])

        async with session_factory() as db:
            for hostname, role, packages, system_info in results:
                # Update package inventory
                if packages:
                    await db.execute(
                        delete(NodePackage).where(
                            NodePackage.node_hostname == hostname
                        )
                    )
                    for pkg in packages:
                        db.add(NodePackage(
                            node_hostname=hostname,
                            node_role=role,
                            package_name=pkg["package"],
                            installed_version=pkg["version"],
                            architecture=pkg.get("architecture", "amd64"),
                        ))
                    summary[hostname] = len(packages)

                # Update SystemVersion with system info + reboot status
                sv = (await db.execute(
                    select(SystemVersion).where(
                        SystemVersion.node_hostname == hostname
                    )
                )).scalar_one_or_none()
                if sv:
                    # Update OS/kernel info from sidecar /system
                    docker_info = system_info.get("docker", {})
                    if docker_info:
                        os_str = docker_info.get("os", "")
                        kernel = docker_info.get("kernel", "")
                        if os_str:
                            sv.os_version = os_str
                        if kernel:
                            sv.kernel_version = kernel
                    host_info = system_info.get("host", {})
                    # Python version from dpkg inventory (find python3 package)
                    for pkg in packages:
                        if pkg["package"] == "python3" and pkg.get("version"):
                            sv.python_version = pkg["version"]
                            break

                    # Check reboot-required
                    try:
                        reboot_info = await check_reboot_required(
                            sv.node_ip
                        )
                        sv.reboot_required = reboot_info.get("reboot_required", False)
                    except Exception:
                        pass

            await db.commit()

    logger.info(
        "inventory_collection_complete",
        nodes_collected=len(summary),
        total_nodes=len(nodes),
    )
    return summary
