"""Collector-side OS update agent.

Polls central for pending OS install tasks assigned to this collector.
When a task is found:
1. For "install": downloads packages from central, installs via local sidecar
2. For "reboot": tells local sidecar to reboot the host
3. For "health_check": reports healthy (if we're running, the node is up)

All communication with central is outbound HTTPS (pull-based).
Local apt operations go through the docker-stats sidecar on the same host.
"""

import asyncio
import os

import aiohttp
import structlog

logger = structlog.get_logger()

SIDECAR_URL = os.environ.get("MONCTL_DOCKER_STATS_URL", "http://monctl-docker-stats:9100")


class OsUpdateAgent:
    def __init__(
        self,
        central_url: str,
        api_key: str,
        hostname: str,
        verify_ssl: bool = True,
        poll_interval: int = 30,
    ):
        self._central_url = central_url.rstrip("/")
        self._api_key = api_key
        self._hostname = hostname
        self._verify_ssl = verify_ssl
        self._poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> asyncio.Task:
        self._running = True
        self._task = asyncio.create_task(self._run())
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("os_update_agent_started", hostname=self._hostname, interval=self._poll_interval)
        return self._task

    async def stop(self):
        self._running = False
        for t in (self._task, getattr(self, "_scan_task", None)):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    async def _run(self):
        await asyncio.sleep(60)  # Let collector fully start first
        # Ensure apt source is configured to use central as apt proxy
        try:
            await self._ensure_apt_source()
        except Exception:
            logger.error("apt_source_setup_error", exc_info=True)
        while self._running:
            try:
                await self._poll_and_execute()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("os_update_agent_error", exc_info=True)
            await asyncio.sleep(self._poll_interval)

    async def _scan_loop(self):
        """Periodically scan for available OS updates and report to central."""
        await asyncio.sleep(120)  # Wait for apt source to be configured
        while self._running:
            try:
                await self._scan_and_report()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("os_scan_error", exc_info=True)
            await asyncio.sleep(6 * 3600)  # Every 6 hours

    async def _scan_and_report(self):
        """Call local sidecar /os/check, POST results to central /report-updates."""
        async with aiohttp.ClientSession() as sidecar:
            async with sidecar.get(
                f"{SIDECAR_URL}/os/check",
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                updates = data.get("updates", [])

        logger.info("os_scan_result", hostname=self._hostname, count=len(updates))

        # Report to central
        headers = {"Authorization": f"Bearer {self._api_key}"}
        ssl_ctx = None if self._verify_ssl else False
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._central_url}/api/v1/os-packages/report-updates",
                json={"hostname": self._hostname, "updates": updates},
                headers=headers, ssl=ssl_ctx,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("report_updates_failed", status=resp.status, body=body[:200])

    async def _ensure_apt_source(self):
        """Check if apt source is configured; if not, call local sidecar to set it up."""
        # Derive VIP from central URL (strip https:// and any port/path)
        vip = self._central_url.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        async with aiohttp.ClientSession() as sidecar:
            async with sidecar.get(f"{SIDECAR_URL}/os/apt-source-status",
                                   timeout=aiohttp.ClientTimeout(total=5)) as resp:
                status = await resp.json()
            if status.get("configured"):
                logger.info("apt_source_already_configured")
                return
            logger.info("setting_up_apt_source", central_vip=vip)
            async with sidecar.post(
                f"{SIDECAR_URL}/os/setup-apt-source",
                json={"central_vip": vip, "distro": "noble",
                      "components": "main restricted universe multiverse"},
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                result = await resp.json()
                if result.get("success"):
                    logger.info("apt_source_configured")
                else:
                    logger.error("apt_source_setup_failed", output=result.get("output", "")[:500])

    async def _poll_and_execute(self):
        headers = {"Authorization": f"Bearer {self._api_key}"}
        ssl_ctx = None if self._verify_ssl else False

        async with aiohttp.ClientSession() as session:
            # Poll for pending task
            url = f"{self._central_url}/api/v1/os-packages/my-tasks"
            async with session.get(
                url, headers=headers, ssl=ssl_ctx,
                params={"hostname": self._hostname},
            ) as resp:
                if resp.status != 200:
                    return
                body = await resp.json()

            task = body.get("data")
            if not task:
                return

            step_id = task["step_id"]
            action = task["action"]
            package_names = task.get("package_names", [])

            logger.info(
                "os_task_received",
                step_id=step_id,
                action=action,
                packages=package_names,
            )

            try:
                if action == "install":
                    output = await self._install_packages(session, headers, ssl_ctx, package_names)
                    await self._report(session, headers, ssl_ctx, step_id, "completed", output_log=output)
                elif action == "reboot":
                    await self._reboot_host()
                    # Report success before we go down — if the reboot kills us,
                    # the step will be picked up as stale by central eventually.
                    await self._report(session, headers, ssl_ctx, step_id, "completed",
                                       output_log="Reboot initiated")
                elif action == "health_check":
                    await self._report(session, headers, ssl_ctx, step_id, "completed",
                                       output_log="Node healthy (agent running)")
                else:
                    await self._report(session, headers, ssl_ctx, step_id, "failed",
                                       error_message=f"Unknown action: {action}")

            except Exception as exc:
                logger.error("os_task_failed", step_id=step_id, error=str(exc))
                try:
                    await self._report(session, headers, ssl_ctx, step_id, "failed",
                                       error_message=str(exc))
                except Exception:
                    logger.error("os_task_report_failed", exc_info=True)

    async def _install_packages(
        self,
        session: aiohttp.ClientSession,
        headers: dict,
        ssl_ctx,
        package_names: list[str],
    ) -> str:
        """Install packages via local sidecar — apt-get fetches via central apt-proxy."""
        async with aiohttp.ClientSession() as sidecar:
            async with sidecar.post(
                f"{SIDECAR_URL}/os/install",
                json={"packages": package_names},
                timeout=aiohttp.ClientTimeout(total=900),
            ) as resp:
                result = await resp.json()

        output = result.get("output", "")
        installed = result.get("installed", [])
        skipped = result.get("skipped", [])
        failed = result.get("failed", [])
        warnings = result.get("warnings") or []
        # Append postinst warnings detected by the sidecar (e.g. apparmor
        # reload failures, DBus errors) so they reach central's job log.
        if warnings:
            output += "\n[postinst warnings]"
            for w in warnings:
                output += f"\n  {w}"
        if not result.get("success", False):
            # Treat partial success or "already newest" as OK
            if installed or skipped or "is already the newest version" in output:
                if failed:
                    output += f"\nWarning: {len(failed)} package(s) failed: {', '.join(failed)}"
                return output
            raise RuntimeError(f"Install failed: {output[:500]}")
        return output or "Installed"

    async def _reboot_host(self):
        """Tell local sidecar to reboot the host."""
        async with aiohttp.ClientSession() as sidecar_session:
            async with sidecar_session.post(
                f"{SIDECAR_URL}/os/reboot",
                json={"delay_seconds": 5},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()
                logger.info("reboot_initiated", result=result)

    async def _report(
        self,
        session: aiohttp.ClientSession,
        headers: dict,
        ssl_ctx,
        step_id: str,
        status: str,
        output_log: str | None = None,
        error_message: str | None = None,
    ):
        """Report step result back to central."""
        payload = {
            "step_id": step_id,
            "status": status,
            "output_log": output_log,
            "error_message": error_message,
        }
        async with session.post(
            f"{self._central_url}/api/v1/os-packages/step-result",
            json=payload, headers=headers, ssl=ssl_ctx,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning("step_report_error", status=resp.status, body=body[:200])
