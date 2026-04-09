"""Fix ping_check v2.0.0 to be BasePoller with error_category."""
import asyncio
import hashlib
from monctl_central.config import settings
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select
from monctl_central.storage.models import App, AppVersion

PING_CODE = '''\
"""ICMP ping check — measures reachability and round-trip time."""
import asyncio
import time
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult


class Poller(BasePoller):
    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "")
        count = context.parameters.get("count", 3)
        timeout = context.parameters.get("timeout", 5)
        start = time.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", str(count), "-W", str(timeout), host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout * count + 5
            )
            output = stdout.decode()
            execution_ms = int((time.time() - start) * 1000)

            if proc.returncode == 0:
                rtt = self._parse_rtt(output)
                loss = self._parse_loss(output)
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[
                        {"name": "rtt_ms", "value": rtt},
                        {"name": "packet_loss_pct", "value": loss},
                    ],
                    config_data=None,
                    status="ok" if loss < 100 else "critical",
                    reachable=True,
                    error_message=None,
                    execution_time_ms=execution_ms,
                    rtt_ms=rtt,
                )
            else:
                detail = stderr.decode().strip() or "no response"
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[{"name": "packet_loss_pct", "value": 100.0}],
                    config_data=None,
                    status="critical",
                    reachable=False,
                    error_message=f"Ping failed: {detail}",
                    execution_time_ms=execution_ms,
                    error_category="device",
                )
        except asyncio.TimeoutError:
            execution_ms = int((time.time() - start) * 1000)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"Ping timed out after {timeout * count}s",
                execution_time_ms=execution_ms,
                error_category="device",
            )

    def _parse_rtt(self, output: str) -> float:
        for line in output.splitlines():
            if "avg" in line and "/" in line:
                parts = line.split("=")
                if len(parts) >= 2:
                    vals = parts[-1].strip().split("/")
                    if len(vals) >= 2:
                        try:
                            return float(vals[1])
                        except ValueError:
                            pass
        return 0.0

    def _parse_loss(self, output: str) -> float:
        for line in output.splitlines():
            if "packet loss" in line or "loss" in line:
                for part in line.split(","):
                    part = part.strip()
                    if "%" in part:
                        try:
                            return float(part.split("%")[0].strip().split()[-1])
                        except (ValueError, IndexError):
                            pass
        return 0.0
'''

PORT_CODE = '''\
"""TCP port check — measures reachability and connect time."""
import asyncio
import socket
import time
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult


class Poller(BasePoller):
    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "")
        port = int(context.parameters.get("port", 80))
        timeout = float(context.parameters.get("timeout", 5))
        start = time.time()

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            rtt_ms = (time.time() - start) * 1000
            writer.close()
            await writer.wait_closed()

            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "port_rtt_ms", "value": rtt_ms},
                    {"name": "port_reachable", "value": 1.0},
                ],
                config_data=None,
                status="ok",
                reachable=True,
                error_message=None,
                execution_time_ms=int(rtt_ms),
                rtt_ms=rtt_ms,
            )
        except asyncio.TimeoutError:
            execution_ms = int((time.time() - start) * 1000)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[{"name": "port_reachable", "value": 0.0}],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"Port {port} timed out: ",
                execution_time_ms=execution_ms,
                error_category="device",
            )
        except OSError as exc:
            execution_ms = int((time.time() - start) * 1000)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[{"name": "port_reachable", "value": 0.0}],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"Port {port} refused/unreachable: {exc}",
                execution_time_ms=execution_ms,
                error_category="device",
            )
'''


async def main():
    engine = create_async_engine(settings.database_url)
    async with AsyncSession(engine) as s:
        for app_name, code in [("ping_check", PING_CODE), ("port_check", PORT_CODE)]:
            ver = (await s.execute(
                select(AppVersion)
                .join(App, AppVersion.app_id == App.id)
                .where(App.name == app_name, AppVersion.is_latest == True)
            )).scalar_one_or_none()
            if ver:
                ver.source_code = code
                ver.checksum_sha256 = hashlib.sha256(code.encode()).hexdigest()
                print(f"{app_name} v{ver.version} updated, checksum={ver.checksum_sha256[:12]}")
        await s.commit()
    await engine.dispose()


asyncio.run(main())
