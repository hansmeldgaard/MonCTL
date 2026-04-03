"""OS package inventory collection from node sidecars."""

from __future__ import annotations

import asyncio

import httpx
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import NodePackage, SystemVersion

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


async def _collect_one(node: SystemVersion) -> tuple[str, str, list[dict]]:
    """Collect inventory for a single node. Returns (hostname, role, packages)."""
    try:
        packages = await collect_node_inventory(node.node_ip)
        return node.node_hostname, node.node_role, packages
    except Exception as exc:
        logger.warning(
            "inventory_collection_failed",
            node=node.node_hostname,
            error=str(exc),
        )
        return node.node_hostname, node.node_role, []


async def collect_all_inventory(session_factory) -> dict[str, int]:
    """Collect package inventory from all nodes in batches.

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
            for hostname, role, packages in results:
                if not packages:
                    continue

                # Full replacement: delete old, insert new
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

            await db.commit()

    logger.info(
        "inventory_collection_complete",
        nodes_collected=len(summary),
        total_nodes=len(nodes),
    )
    return summary
