"""Collector-side upgrade agent.

Polls central for available upgrades. When found:
1. Download docker image tarball
2. docker load the image
3. Write upgrade marker file for host-level watcher
4. Report result to central

Note: Container self-restart is handled by a host-level script that
watches for the marker file and runs docker compose up -d.
"""

import asyncio
import hashlib
import subprocess
from pathlib import Path

import aiohttp
import structlog

logger = structlog.get_logger()

UPGRADE_MARKER = "/opt/monctl/collector/.upgrade-pending"


class UpgradeAgent:
    def __init__(
        self,
        central_url: str,
        api_key: str,
        collector_id: str = "",
        verify_ssl: bool = True,
        check_interval: int = 60,
    ):
        self._central_url = central_url.rstrip("/")
        self._api_key = api_key
        self._collector_id = collector_id
        self._verify_ssl = verify_ssl
        self._check_interval = check_interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> asyncio.Task:
        """Start polling for upgrades as a background task."""
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("upgrade_agent_started", interval=self._check_interval)
        return self._task

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        # Initial delay to let collector fully start
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._check_and_apply()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("upgrade_check_error", exc_info=True)
            await asyncio.sleep(self._check_interval)

    async def _check_and_apply(self):
        """Check for available upgrades and apply if found."""
        headers = {"Authorization": f"Bearer {self._api_key}"}
        ssl_ctx = None if self._verify_ssl else False

        async with aiohttp.ClientSession() as session:
            # 1. Check for available upgrade
            params = {}
            if self._collector_id:
                params["collector_id"] = self._collector_id
            async with session.get(
                f"{self._central_url}/api/v1/upgrade/available",
                headers=headers, ssl=ssl_ctx, params=params,
            ) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()

            upgrade_data = data.get("data", {})
            if not upgrade_data.get("upgrade_available"):
                return

            version = upgrade_data["version"]
            download_url = upgrade_data["download_url"]
            expected_sha256 = upgrade_data.get("sha256", "")

            logger.info("upgrade_available", version=version)

            # 2. Download image
            download_path = Path(f"/tmp/monctl-upgrade-{version}.tar")
            try:
                async with session.get(
                    f"{self._central_url}{download_url}",
                    headers=headers, ssl=ssl_ctx,
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Download failed: HTTP {resp.status}")
                    with open(download_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)

                logger.info("upgrade_downloaded", path=str(download_path))

                # 3. Verify SHA256 if provided
                if expected_sha256:
                    h = hashlib.sha256()
                    with open(download_path, "rb") as f:
                        while chunk := f.read(8192):
                            h.update(chunk)
                    if h.hexdigest() != expected_sha256:
                        raise RuntimeError(
                            f"SHA256 mismatch: expected {expected_sha256}, got {h.hexdigest()}"
                        )

                # 4. Docker load
                result = subprocess.run(
                    ["docker", "load", "-i", str(download_path)],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"docker load failed: {result.stderr}")

                load_output = result.stdout
                logger.info("upgrade_image_loaded", output=load_output.strip())

                # 5. Write marker file for host-level watcher
                Path(UPGRADE_MARKER).write_text(version)
                logger.info("upgrade_marker_written", marker=UPGRADE_MARKER)

                # 6. Report success
                await self._report(session, headers, ssl_ctx, "completed",
                                   output_log=load_output)

            except Exception as e:
                logger.error("upgrade_failed", error=str(e))
                try:
                    await self._report(session, headers, ssl_ctx, "failed",
                                       error_message=str(e))
                except Exception:
                    logger.error("upgrade_report_failed", exc_info=True)
            finally:
                download_path.unlink(missing_ok=True)

    async def _report(self, session, headers, ssl_ctx, status,
                      output_log=None, error_message=None):
        """Report upgrade result to central."""
        payload = {
            "collector_id": self._collector_id,
            "upgrade_type": "monctl",
            "target_version": "",
            "status": status,
            "output_log": output_log,
            "error_message": error_message,
        }
        async with session.post(
            f"{self._central_url}/api/v1/upgrade/report",
            json=payload, headers=headers, ssl=ssl_ctx,
        ) as resp:
            if resp.status != 200:
                logger.warning("upgrade_report_http_error", status=resp.status)
