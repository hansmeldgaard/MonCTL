"""OS update management via docker-stats sidecar."""

from __future__ import annotations

import asyncio
import os
import socket
from datetime import datetime, timezone
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


async def get_node_uptime(node_ip: str) -> float | None:
    """Return the current uptime in seconds via sidecar /system, or None on error."""
    try:
        async with httpx.AsyncClient(timeout=SIDECAR_TIMEOUT) as client:
            resp = await client.get(f"http://{node_ip}:{SIDECAR_PORT}/system")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("uptime_seconds")
    except Exception:
        return None
    return None


async def wait_for_node_recovery(
    node_ip: str, timeout: int = 300, pre_reboot_uptime: float | None = None,
) -> bool:
    """Wait for a node to reboot and come back healthy.

    Verifies the reboot actually happened by comparing uptime:
      - If pre_reboot_uptime is provided, we wait until uptime decreases
        (i.e., the node rebooted).
      - Otherwise we wait until uptime is small (< 5 minutes), suggesting
        a recent reboot.
      - Finally we wait for /health to respond 200 to confirm the new sidecar
        is up and stable.
    """
    deadline = asyncio.get_event_loop().time() + timeout

    # Step 1: Wait for the reboot to actually happen (uptime must reset)
    await asyncio.sleep(15)  # initial grace period — kernel shutdown + reboot
    rebooted = False
    while asyncio.get_event_loop().time() < deadline:
        uptime = await get_node_uptime(node_ip)
        if uptime is not None:
            if pre_reboot_uptime is not None:
                # Reboot confirmed when uptime is less than before (clock reset)
                if uptime < pre_reboot_uptime:
                    rebooted = True
                    break
            else:
                # No baseline — accept uptime < 5 min as "freshly rebooted"
                if uptime < 300:
                    rebooted = True
                    break
        # uptime unchanged or unreachable — keep waiting
        await asyncio.sleep(5)

    if not rebooted:
        return False

    # Step 2: Node has rebooted — wait for sidecar health to stabilize
    health_url = f"http://{node_ip}:{SIDECAR_PORT}/health"
    stable_count = 0
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    stable_count += 1
                    if stable_count >= 3:  # 3 consecutive OK = stable
                        return True
                else:
                    stable_count = 0
        except Exception:
            stable_count = 0
        await asyncio.sleep(3)
    return False


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
    """Run all pending steps in order. Handles test_first pause and fail-fast.

    Central node steps are executed directly via sidecar.
    Collector node steps are marked 'awaiting_collector' — collectors pull and
    execute them via the /api/v1/os-packages/my-tasks polling endpoint.
    """
    steps = sorted(job.steps, key=lambda s: s.step_order)
    failed = False
    current = _current_hostname()

    # Defer the current node's reboot to the very end — it must run LAST because
    # rebooting the executor's node kills the executor. If we're running as
    # advance_collector_job on whichever central received a step-result POST
    # (HAProxy routes via source hash), this ensures we process all OTHER nodes
    # first and only reboot self as the final step.
    def _pick_next_pending(steps_list: list, current_host: str, i_start: int) -> int | None:
        """Return index of next pending step, preferring non-current nodes."""
        # First pass: skip current node's reboot/health_check steps
        for j in range(i_start, len(steps_list)):
            s = steps_list[j]
            if s.status != "pending":
                continue
            if s.action in ("reboot", "health_check") and s.node_hostname == current_host:
                continue
            return j
        # Second pass: only current node steps left
        for j in range(i_start, len(steps_list)):
            s = steps_list[j]
            if s.status == "pending":
                return j
        return None

    i = 0
    while True:
        idx = _pick_next_pending(steps, current, i)
        if idx is None:
            break
        step = steps[idx]
        i = idx  # allow backtracking if new pending steps appear — not expected here

        if failed and job.strategy in ("rolling", "test_first"):
            step.status = "skipped"
            await db.commit()
            i += 1
            continue

        # ── Collector steps: delegate to collector pull-loop ──────────
        if step.node_role != "central":
            step.status = "awaiting_collector"
            step.started_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(
                "os_step_awaiting_collector",
                job_id=str(job.id),
                step_id=str(step.id),
                node=step.node_hostname,
                action=step.action,
            )
            # For rolling/test_first: pause and let the collector complete
            # before advancing to the next step.  The advance_collector_job()
            # function will resume the job when the collector reports back.
            if job.strategy in ("rolling", "test_first"):
                return
            # For all_at_once: mark all remaining collector steps and continue
            i += 1
            continue

        # ── Central steps: execute directly via sidecar ───────────────
        step.status = "running"
        step.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            if step.action == "install":
                # apt-get install via local sidecar — dependencies resolved via
                # central apt-cache proxy (see nginx-apt-cache on central:18080)
                result = await install_packages_on_node(step.node_ip, job.package_names)
                step.output_log = result.get("output", "")
                # Treat partial success (some installed, some failed) as success
                # Only fail if nothing was installed at all and there were real errors
                failed_pkgs = result.get("failed", [])
                installed_pkgs = result.get("installed", [])
                skipped_pkgs = result.get("skipped", [])
                warnings = result.get("warnings") or []
                if not result.get("success", False) and not installed_pkgs and not skipped_pkgs:
                    raise RuntimeError(
                        f"Install failed (rc={result.get('returncode')}): "
                        f"{result.get('output', '')[:500]}"
                    )
                if failed_pkgs:
                    step.output_log += f"\nWarning: {len(failed_pkgs)} package(s) failed: {', '.join(failed_pkgs)}"
                # Surface postinst warnings detected by the sidecar
                # (apparmor reload failures, DBus errors, initramfs hook
                # errors that apt swallowed with exit 0, etc.)
                if warnings:
                    step.output_log += "\n[postinst warnings]"
                    for w in warnings:
                        step.output_log += f"\n  {w}"
                # Check if the install produced a reboot-required flag
                # (kernel, libc, firmware etc.). Non-fatal — just annotate.
                try:
                    reboot_info = await check_reboot_required(step.node_ip)
                    if reboot_info.get("reboot_required"):
                        rb_pkgs = reboot_info.get("packages") or []
                        tag = ", ".join(rb_pkgs) if rb_pkgs else "unspecified"
                        step.output_log += f"\n[reboot-required] {tag}"
                except Exception as exc:
                    logger.warning(
                        "reboot_required_check_failed",
                        node=step.node_hostname,
                        error=str(exc),
                    )
                for pkg in job.package_names:
                    await db.execute(
                        sql_update(OsAvailableUpdate)
                        .where(
                            OsAvailableUpdate.node_hostname == step.node_hostname,
                            OsAvailableUpdate.package_name == pkg,
                        )
                        .values(is_installed=True)
                    )

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
                    pass

            elif step.action == "reboot":
                is_current = step.node_hostname == current
                if is_current:
                    # This is the executor's own reboot — we picked it because
                    # no other steps remain. Mark the associated health_check as
                    # completed (we're alive now), mark reboot as completed, and
                    # fire the reboot. The process dies shortly after.
                    step.status = "completed"
                    step.completed_at = datetime.now(timezone.utc)
                    step.output_log = "Reboot initiated (current node — final step)"
                    # Mark the matching health_check step for this node as completed too
                    for hc in steps:
                        if (hc.node_hostname == current
                            and hc.action == "health_check"
                            and hc.status == "pending"):
                            hc.status = "completed"
                            hc.completed_at = datetime.now(timezone.utc)
                            hc.output_log = "Skipped (own reboot)"
                    job.status = "completed"
                    job.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    await reboot_node(step.node_ip)
                    return

                # Record uptime BEFORE reboot so health_check can verify the node
                # actually rebooted. Encode pre-uptime in output_log for the
                # health_check step to read (survives DB commits/refreshes).
                pre_uptime = await get_node_uptime(step.node_ip)
                await reboot_node(step.node_ip)
                if pre_uptime is not None:
                    step.output_log = f"Reboot command sent (pre-uptime={pre_uptime:.0f}s) [pre_uptime={pre_uptime}]"
                else:
                    step.output_log = "Reboot command sent"

            elif step.action == "health_check":
                # Look up the matching reboot step for this node and parse
                # the pre-reboot uptime from its output_log
                pre_uptime = None
                for prior in steps:
                    if (prior.node_hostname == step.node_hostname
                        and prior.action == "reboot"
                        and prior.status == "completed"
                        and prior.output_log):
                        import re as _re
                        m = _re.search(r"\[pre_uptime=([0-9.]+)\]", prior.output_log)
                        if m:
                            pre_uptime = float(m.group(1))
                        break
                ok = await wait_for_node_recovery(
                    step.node_ip, timeout=300, pre_reboot_uptime=pre_uptime,
                )
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
            next_steps = [s for s in steps[i + 1:] if s.status == "pending"]
            if next_steps and not next_steps[0].is_test_node:
                job.status = "awaiting_approval"
                await db.commit()
                logger.info("os_install_job_awaiting_approval", job_id=str(job.id))
                return

        i += 1

    # Determine final job status — but only if no steps are still awaiting collectors
    still_waiting = any(s.status == "awaiting_collector" for s in steps)
    if still_waiting:
        # Job stays "running" — advance_collector_job will finalize
        return

    all_done = all(s.status in ("completed", "skipped") for s in steps)
    any_failed = any(s.status == "failed" for s in steps)
    job.status = "completed" if (all_done and not any_failed) else "failed"
    job.completed_at = datetime.now(timezone.utc)
    if any_failed:
        failed_nodes = [s.node_hostname for s in steps if s.status == "failed"]
        job.error_message = f"Failed on: {', '.join(set(failed_nodes))}"
    await db.commit()


async def advance_collector_job(session_factory, job_id: UUID) -> None:
    """Called when a collector reports a step result. Advances the job to the next step.

    For rolling/test_first strategies, this activates the next pending step.
    For all_at_once, it checks if all collector steps are done and finalizes.
    """
    async with session_factory() as db:
        job = await db.get(OsInstallJob, job_id, options=[selectinload(OsInstallJob.steps)])
        if not job or job.status not in ("running",):
            return

        steps = sorted(job.steps, key=lambda s: s.step_order)

        # Check for test_first pause
        if job.strategy == "test_first":
            completed_test = [
                s for s in steps
                if s.is_test_node and s.status == "completed"
            ]
            pending_non_test = [
                s for s in steps
                if not s.is_test_node and s.status == "pending"
            ]
            if completed_test and pending_non_test:
                job.status = "awaiting_approval"
                await db.commit()
                logger.info("os_install_job_awaiting_approval", job_id=str(job_id))
                return

        # For rolling: activate the next pending collector step
        if job.strategy in ("rolling", "test_first"):
            # Check if any step failed → fail-fast
            any_failed = any(s.status == "failed" for s in steps)
            if any_failed:
                for s in steps:
                    if s.status in ("pending", "awaiting_collector"):
                        s.status = "skipped"
                job.status = "failed"
                failed_nodes = [s.node_hostname for s in steps if s.status == "failed"]
                job.error_message = f"Failed on: {', '.join(set(failed_nodes))}"
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
                return

            # Find next pending step and activate it
            for s in steps:
                if s.status != "pending":
                    continue
                if s.node_role != "central":
                    # Collector step: mark awaiting_collector
                    s.status = "awaiting_collector"
                    s.started_at = datetime.now(timezone.utc)
                    await db.commit()
                    logger.info(
                        "os_step_awaiting_collector",
                        job_id=str(job_id),
                        step_id=str(s.id),
                        node=s.node_hostname,
                    )
                    return
                else:
                    # Central step: execute directly via _run_steps
                    # Re-run the step executor which handles central steps
                    await db.commit()
                    await _run_steps(db, job)
                    # After _run_steps returns, check if job finished
                    await db.refresh(job, ["steps"])
                    still_active = any(
                        st.status in ("pending", "awaiting_collector", "running")
                        for st in job.steps
                    )
                    if not still_active:
                        any_f = any(st.status == "failed" for st in job.steps)
                        job.status = "completed" if not any_f else "failed"
                        job.completed_at = datetime.now(timezone.utc)
                        if any_f:
                            fn = [st.node_hostname for st in job.steps if st.status == "failed"]
                            job.error_message = f"Failed on: {', '.join(set(fn))}"
                        await db.commit()
                        try:
                            from monctl_central.upgrades.os_inventory import collect_all_inventory
                            await collect_all_inventory(session_factory)
                        except Exception:
                            logger.warning("post_install_inventory_collection_failed", exc_info=True)
                    return

        # Check if all steps are terminal
        still_active = any(s.status in ("pending", "awaiting_collector", "running") for s in steps)
        if not still_active:
            any_failed = any(s.status == "failed" for s in steps)
            job.status = "completed" if not any_failed else "failed"
            job.completed_at = datetime.now(timezone.utc)
            if any_failed:
                failed_nodes = [s.node_hostname for s in steps if s.status == "failed"]
                job.error_message = f"Failed on: {', '.join(set(failed_nodes))}"
            await db.commit()

            # Refresh inventory after job completes
            try:
                from monctl_central.upgrades.os_inventory import collect_all_inventory
                await collect_all_inventory(session_factory)
            except Exception:
                logger.warning("post_install_inventory_collection_failed", exc_info=True)


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
