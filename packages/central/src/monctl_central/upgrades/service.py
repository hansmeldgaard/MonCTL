"""Upgrade orchestration service.

Manages rolling upgrades of central and collector nodes.
Central nodes are upgraded via SSH (SCP image + docker load + compose restart).
Collectors pull their upgrades from central (pull-based model).
The current node (running the orchestration) upgrades LAST.
"""

import asyncio
import socket
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.config import settings
from monctl_central.storage.models import (
    Collector,
    SystemVersion,
    UpgradeJob,
    UpgradeJobStep,
    UpgradePackage,
)

logger = structlog.get_logger()


async def create_upgrade_job(
    db: AsyncSession,
    package: UpgradePackage,
    scope: str,
    strategy: str,
    started_by: str | None,
) -> UpgradeJob:
    """Create an upgrade job with steps for each target node."""
    job = UpgradeJob(
        upgrade_package_id=package.id,
        target_version=package.version,
        scope=scope,
        strategy=strategy,
        status="pending",
        started_by=started_by,
    )
    db.add(job)
    await db.flush()

    step_order = 0
    current_hostname = socket.gethostname()

    # Central nodes
    if scope in ("central", "all") and package.contains_central:
        stmt = select(SystemVersion).where(SystemVersion.node_role == "central")
        result = await db.execute(stmt)
        central_nodes = list(result.scalars().all())

        # Current node goes last
        central_nodes.sort(key=lambda n: (n.node_hostname == current_hostname, n.node_hostname))

        for node in central_nodes:
            step_order += 1
            step = UpgradeJobStep(
                job_id=job.id,
                step_order=step_order,
                node_hostname=node.node_hostname,
                node_role="central",
                node_ip=node.node_ip,
                action="upgrade_central",
                status="pending",
            )
            db.add(step)

    # Collector nodes
    if scope in ("collectors", "all") and package.contains_collector:
        stmt = select(Collector).where(Collector.status == "ACTIVE")
        result = await db.execute(stmt)
        collectors = list(result.scalars().all())

        for collector in collectors:
            step_order += 1
            ip = ""
            if collector.ip_addresses and isinstance(collector.ip_addresses, dict):
                ip = collector.ip_addresses.get("primary", "")
            elif collector.ip_addresses and isinstance(collector.ip_addresses, list):
                ip = collector.ip_addresses[0] if collector.ip_addresses else ""
            step = UpgradeJobStep(
                job_id=job.id,
                step_order=step_order,
                node_hostname=collector.hostname or collector.name,
                node_role="collector",
                node_ip=ip,
                action="upgrade_collector",
                status="pending",
            )
            db.add(step)

    await db.flush()
    return job


async def execute_upgrade_job(
    session_factory,
    job_id: UUID,
) -> None:
    """Execute an upgrade job (runs as a background task).

    Central nodes are upgraded via SSH (push model).
    Collector nodes are set to 'waiting' (pull model — collectors fetch the image).
    """
    async with session_factory() as db:
        job = await db.get(UpgradeJob, job_id)
        if not job:
            logger.error("upgrade_job_not_found", job_id=str(job_id))
            return

        package = await db.get(UpgradePackage, job.upgrade_package_id)
        if not package:
            logger.error("upgrade_package_not_found", package_id=str(job.upgrade_package_id))
            job.status = "failed"
            job.error_message = "Upgrade package not found"
            await db.commit()
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            # Load steps
            stmt = select(UpgradeJobStep).where(
                UpgradeJobStep.job_id == job_id
            ).order_by(UpgradeJobStep.step_order)
            result = await db.execute(stmt)
            steps = list(result.scalars().all())

            failed = False
            for step in steps:
                if failed and job.strategy == "rolling":
                    step.status = "skipped"
                    await db.commit()
                    continue

                step.status = "running"
                step.started_at = datetime.now(timezone.utc)
                await db.commit()

                try:
                    if step.action == "upgrade_central":
                        await _upgrade_central_node(db, step, package)
                    elif step.action == "upgrade_collector":
                        # Collectors use pull model — mark as waiting
                        step.status = "waiting"
                        step.output_log = "Waiting for collector to pull upgrade"
                        await db.commit()
                        continue
                    step.status = "completed"
                    step.completed_at = datetime.now(timezone.utc)
                except Exception as exc:
                    step.status = "failed"
                    step.error_message = str(exc)
                    step.completed_at = datetime.now(timezone.utc)
                    failed = True
                    logger.error(
                        "upgrade_step_failed",
                        step_id=str(step.id),
                        node=step.node_hostname,
                        error=str(exc),
                    )
                await db.commit()

            # Determine final job status
            all_done = all(s.status in ("completed", "waiting") for s in steps)
            job.status = "completed" if all_done else "failed"
            job.completed_at = datetime.now(timezone.utc)
            if not all_done:
                failed_steps = [s.node_hostname for s in steps if s.status == "failed"]
                job.error_message = f"Failed on nodes: {', '.join(failed_steps)}"
            await db.commit()

        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error("upgrade_job_failed", job_id=str(job_id), error=str(exc))


async def _upgrade_central_node(
    db: AsyncSession,
    step: UpgradeJobStep,
    package: UpgradePackage,
) -> None:
    """Upgrade a central node via SSH: SCP image, docker load, compose restart, health check."""
    ip = step.node_ip
    ssh_user = "monctl"
    upgrade_dir = Path(settings.upgrade_storage_dir)
    logs: list[str] = []

    # Find the central image tarball within the extracted bundle
    bundle_dir = upgrade_dir / package.version
    central_tar = None
    for p in bundle_dir.rglob("monctl-central.tar"):
        central_tar = p
        break

    if not central_tar:
        raise RuntimeError("monctl-central.tar not found in upgrade bundle")

    # SCP the image to the target node
    remote_path = f"/tmp/monctl-central-{package.version}.tar"
    scp_cmd = f"scp -o StrictHostKeyChecking=no {central_tar} {ssh_user}@{ip}:{remote_path}"
    logs.append(f"$ {scp_cmd}")
    proc = await asyncio.create_subprocess_shell(
        scp_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"SCP failed: {stderr.decode()}")
    logs.append("SCP completed")

    # Docker load
    load_cmd = (
        f"ssh -o StrictHostKeyChecking=no {ssh_user}@{ip} "
        f"'docker load < {remote_path} && rm -f {remote_path}'"
    )
    logs.append(f"$ {load_cmd}")
    proc = await asyncio.create_subprocess_shell(
        load_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"Docker load failed: {stderr.decode()}")
    logs.append(f"Docker load: {stdout.decode().strip()}")

    # Compose restart
    restart_cmd = (
        f"ssh -o StrictHostKeyChecking=no {ssh_user}@{ip} "
        f"'cd /opt/monctl/central && docker compose down && docker compose up -d'"
    )
    logs.append(f"$ {restart_cmd}")
    proc = await asyncio.create_subprocess_shell(
        restart_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"Compose restart failed: {stderr.decode()}")
    logs.append("Compose restarted")

    # Health check
    healthy = await _wait_for_health(ip, port=8443, timeout=60)
    if not healthy:
        raise RuntimeError(f"Node {ip} did not become healthy after restart")
    logs.append("Health check passed")

    step.output_log = "\n".join(logs)


async def _wait_for_health(ip: str, port: int = 8443, timeout: int = 60) -> bool:
    """Poll the health endpoint until it responds 200 or timeout."""
    import aiohttp

    url = f"https://{ip}:{port}/v1/health"
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, ssl=False, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return True
        except Exception:
            pass
        await asyncio.sleep(3)
    return False
