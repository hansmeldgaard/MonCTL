"""OS update management via docker-stats sidecar."""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monctl_central.storage.models import (
    OsAvailableUpdate,
    OsInstallJob,
    OsInstallJobStep,
    SystemVersion,
)

logger = structlog.get_logger()

SIDECAR_PORT = 9100
SIDECAR_TIMEOUT = 8.0


# ---------------------------------------------------------------------------
# Sidecar helpers
# ---------------------------------------------------------------------------

async def check_node_updates(node_ip: str) -> list[dict]:
    """Query a node's sidecar for available OS updates."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/check"
    async with httpx.AsyncClient(timeout=120) as client:
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


async def reboot_node(node_ip: str) -> dict:
    """Tell a node's sidecar to reboot the host."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/reboot"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json={"delay_seconds": 3})
        resp.raise_for_status()
        return resp.json()


async def check_reboot_required(node_ip: str) -> dict:
    """Check if a node requires a reboot."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/reboot-required"
    async with httpx.AsyncClient(timeout=SIDECAR_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def wait_for_node_recovery(node_ip: str, timeout: int = 300) -> bool:
    """Poll sidecar /health until it responds or timeout."""
    url = f"http://{node_ip}:{SIDECAR_PORT}/health"
    deadline = asyncio.get_event_loop().time() + timeout
    # Wait a bit for the node to actually go down first
    await asyncio.sleep(10)
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(5)
    return False


def compute_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


async def prepare_archive(central_node_ip: str, package_names: list[str], proxy_url: str = "") -> dict:
    """Tell a central node's sidecar to prepare an apt cache archive with packages + deps."""
    url = f"http://{central_node_ip}:{SIDECAR_PORT}/os/prepare-archive"
    async with httpx.AsyncClient(timeout=660) as client:
        resp = await client.post(url, json={
            "packages": package_names,
            "proxy_url": proxy_url,
        })
        resp.raise_for_status()
        return resp.json()


async def install_via_archive(
    node_ip: str, package_names: list[str], db: AsyncSession,
) -> dict:
    """Install packages on a node via apt cache archive from central.

    Used for collectors (no internet) and central nodes in offline mode.
    1. Find a central node that has a prepared archive
    2. Tell worker sidecar to fetch archive, unpack to apt cache, apt-get install
    """
    import os as _os

    central_url = f"https://{_os.environ.get('MONCTL_VIP_ADDRESS', '10.145.210.40')}"
    api_key = _os.environ.get("MONCTL_COLLECTOR_API_KEY", "")

    # Call worker sidecar to fetch archive from central + install
    url = f"http://{node_ip}:{SIDECAR_PORT}/os/install-from-archive"
    async with httpx.AsyncClient(timeout=660) as client:
        resp = await client.post(url, json={
            "central_url": central_url,
            "api_key": api_key,
            "packages": package_names,
        })
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Network mode helper (reuse pattern from python_modules)
# ---------------------------------------------------------------------------

async def _get_network_mode(db: AsyncSession) -> tuple[str, str]:
    """Return (network_mode, proxy_url) from system settings."""
    from monctl_central.storage.models import SystemSetting

    mode = "direct"
    proxy_url = ""
    for key in ("pypi_network_mode", "pypi_proxy_url"):
        row = await db.get(SystemSetting, key)
        if row:
            if key == "pypi_network_mode":
                mode = row.value
            else:
                proxy_url = row.value
    return mode, proxy_url


# ---------------------------------------------------------------------------
# OS Install Job: creation
# ---------------------------------------------------------------------------

def _current_hostname() -> str:
    return (
        os.environ.get("MONCTL_NODE_NAME")
        or socket.gethostname()
    )


async def create_os_install_job(
    db: AsyncSession,
    package_names: list[str],
    scope: str,
    target_nodes: list[str] | None,
    strategy: str,
    restart_policy: str,
    started_by: str | None,
) -> OsInstallJob:
    """Create an OS install job with ordered steps."""
    job = OsInstallJob(
        package_names=package_names,
        scope=scope,
        target_nodes=target_nodes,
        strategy=strategy,
        restart_policy=restart_policy,
        status="pending",
        started_by=started_by,
    )
    db.add(job)
    await db.flush()

    # Resolve target nodes
    if scope == "nodes" and target_nodes:
        stmt = select(SystemVersion).where(SystemVersion.node_hostname.in_(target_nodes))
    elif scope == "central":
        stmt = select(SystemVersion).where(SystemVersion.node_role == "central")
    elif scope == "collectors":
        stmt = select(SystemVersion).where(SystemVersion.node_role != "central")
    else:  # all
        stmt = select(SystemVersion)

    result = await db.execute(stmt)
    nodes = list(result.scalars().all())

    # Order: collectors first, then non-current central, then current central LAST
    current = _current_hostname()
    nodes.sort(key=lambda n: (
        n.node_role == "central",        # collectors first
        n.node_hostname == current,       # current node last
        n.node_hostname,
    ))

    step_order = 0
    for i, node in enumerate(nodes):
        is_test = (strategy == "test_first" and i == 0)

        # Install step
        step_order += 1
        db.add(OsInstallJobStep(
            job_id=job.id,
            step_order=step_order,
            node_hostname=node.node_hostname,
            node_role=node.node_role,
            node_ip=node.node_ip,
            action="install",
            status="pending",
            is_test_node=is_test,
        ))

        # Reboot + health_check steps
        if restart_policy == "rolling":
            step_order += 1
            db.add(OsInstallJobStep(
                job_id=job.id,
                step_order=step_order,
                node_hostname=node.node_hostname,
                node_role=node.node_role,
                node_ip=node.node_ip,
                action="reboot",
                status="pending",
                is_test_node=is_test,
            ))
            step_order += 1
            db.add(OsInstallJobStep(
                job_id=job.id,
                step_order=step_order,
                node_hostname=node.node_hostname,
                node_role=node.node_role,
                node_ip=node.node_ip,
                action="health_check",
                status="pending",
                is_test_node=is_test,
            ))

    await db.flush()
    return job


# ---------------------------------------------------------------------------
# OS Install Job: executor (background task)
# ---------------------------------------------------------------------------

async def execute_os_install_job(session_factory, job_id: UUID) -> None:
    """Execute an OS install job as a background task."""
    async with session_factory() as db:
        job = await db.get(OsInstallJob, job_id, options=[selectinload(OsInstallJob.steps)])
        if not job:
            logger.error("os_install_job_not_found", job_id=str(job_id))
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            await _run_steps(db, job)
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error("os_install_job_failed", job_id=str(job_id), error=str(exc))

        # Refresh inventory after job completes to update progress counts
        try:
            from monctl_central.upgrades.os_inventory import collect_all_inventory
            await collect_all_inventory(session_factory)
        except Exception:
            logger.warning("post_install_inventory_collection_failed", exc_info=True)


async def _run_steps(db: AsyncSession, job: OsInstallJob) -> None:
    """Run all pending steps in order. Handles test_first pause and fail-fast."""
    steps = sorted(job.steps, key=lambda s: s.step_order)
    failed = False
    current = _current_hostname()

    for i, step in enumerate(steps):
        if step.status != "pending":
            continue

        if failed and job.strategy in ("rolling", "test_first"):
            step.status = "skipped"
            await db.commit()
            continue

        step.status = "running"
        step.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            if step.action == "install":
                network_mode, proxy_url = await _get_network_mode(db)
                # Central with internet: apt-get install
                # Collectors or offline mode: .deb distribution from central cache
                if step.node_role == "central" and network_mode != "offline":
                    result = await install_packages_on_node(step.node_ip, job.package_names)
                else:
                    result = await install_via_archive(step.node_ip, job.package_names, db)
                step.output_log = result.get("output", "")
                if not result.get("success", False):
                    raise RuntimeError(
                        f"Install failed (rc={result.get('returncode')}): "
                        f"{result.get('output', '')[:500]}"
                    )
                # Mark packages as installed for this node
                for pkg in job.package_names:
                    await db.execute(
                        sql_update(OsAvailableUpdate)
                        .where(
                            OsAvailableUpdate.node_hostname == step.node_hostname,
                            OsAvailableUpdate.package_name == pkg,
                        )
                        .values(is_installed=True)
                    )

                # Write audit log entry
                try:
                    from monctl_central.storage.models import OsInstallAudit
                    for pkg in job.package_names:
                        db.add(OsInstallAudit(
                            node_hostname=step.node_hostname,
                            node_role=step.node_role,
                            package_name=pkg,
                            action="install",
                            job_id=job.id,
                            installed_by=job.started_by or "system",
                        ))
                except Exception:
                    pass  # Don't fail install if audit logging fails

            elif step.action == "reboot":
                # Current node: mark job completed before rebooting
                is_current = step.node_hostname == current
                if is_current:
                    step.status = "completed"
                    step.completed_at = datetime.now(timezone.utc)
                    step.output_log = "Reboot initiated (current node — job marked complete)"
                    # Skip remaining health_check step for current node
                    for remaining in steps[i + 1:]:
                        if remaining.status == "pending":
                            remaining.status = "skipped"
                            remaining.output_log = "Skipped (current node reboot)"
                    job.status = "completed"
                    job.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    # Fire and forget — we'll be killed by the reboot
                    await reboot_node(step.node_ip)
                    return

                await reboot_node(step.node_ip)
                step.output_log = "Reboot command sent"

            elif step.action == "health_check":
                ok = await wait_for_node_recovery(step.node_ip, timeout=300)
                if not ok:
                    raise RuntimeError(f"Node {step.node_hostname} did not recover within 5 minutes")
                step.output_log = "Node recovered successfully"

            step.status = "completed"
            step.completed_at = datetime.now(timezone.utc)

        except Exception as exc:
            step.status = "failed"
            step.error_message = str(exc)
            step.completed_at = datetime.now(timezone.utc)
            failed = True
            logger.error(
                "os_install_step_failed",
                step_id=str(step.id),
                node=step.node_hostname,
                action=step.action,
                error=str(exc),
            )

        await db.commit()

        # test_first pause: after test node's last step, pause for approval
        if (
            job.strategy == "test_first"
            and step.is_test_node
            and not failed
        ):
            # Check if next step is a non-test step
            next_steps = [s for s in steps[i + 1:] if s.status == "pending"]
            if next_steps and not next_steps[0].is_test_node:
                job.status = "awaiting_approval"
                await db.commit()
                logger.info("os_install_job_awaiting_approval", job_id=str(job.id))
                return

    # Determine final job status
    all_done = all(s.status in ("completed", "skipped") for s in steps)
    any_failed = any(s.status == "failed" for s in steps)
    job.status = "completed" if (all_done and not any_failed) else "failed"
    job.completed_at = datetime.now(timezone.utc)
    if any_failed:
        failed_nodes = [s.node_hostname for s in steps if s.status == "failed"]
        job.error_message = f"Failed on: {', '.join(set(failed_nodes))}"
    await db.commit()


async def resume_os_install_job(session_factory, job_id: UUID) -> None:
    """Resume an awaiting_approval job from the first pending step."""
    async with session_factory() as db:
        job = await db.get(OsInstallJob, job_id, options=[selectinload(OsInstallJob.steps)])
        if not job or job.status != "awaiting_approval":
            return
        job.status = "running"
        await db.commit()
        try:
            await _run_steps(db, job)
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error("os_install_job_resume_failed", job_id=str(job_id), error=str(exc))
