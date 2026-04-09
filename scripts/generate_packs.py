#!/usr/bin/env python3
"""Generate pack JSON files from apps/ source code."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APPS_DIR = REPO / "apps"
PACKS_DIR = REPO / "packs"
PACKS_DIR.mkdir(exist_ok=True)


def read_source(name: str) -> str:
    return (APPS_DIR / f"{name}.py").read_text()


# ── SNMP Core Pack ────────────────────────────────────────────────────────────

snmp_core = {
    "monctl_pack": "1.0",
    "pack_uid": "snmp-core",
    "name": "SNMP Core Monitoring",
    "version": "1.0.0",
    "description": "Core SNMP monitoring apps: reachability check, interface polling, device discovery, and uptime tracking.",
    "author": "MonCTL",
    "changelog": "v1.0.0 - Initial pack release with error_category support",
    "exported_at": None,
    "contents": {
        "apps": [
            {
                "name": "snmp_check",
                "description": "SNMP reachability check — measures response time via SNMP GET on a configurable OID.",
                "app_type": "script",
                "target_table": "availability_latency",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "oid": {
                            "type": "string",
                            "title": "SNMP OID",
                            "default": "1.3.6.1.2.1.1.3.0",
                            "description": "OID to query for availability check",
                            "x-widget": "snmp-oid",
                        },
                    },
                },
                "connector_bindings": [
                    {"alias": "snmp", "connector_name": "snmp"},
                ],
                "versions": [
                    {
                        "version": "2.1.0",
                        "source_code": read_source("snmp_check"),
                        "requirements": [],
                        "entry_class": "Poller",
                        "is_latest": True,
                    },
                ],
            },
            {
                "name": "snmp_interface_poller",
                "description": "SNMP interface monitoring — collects IF-MIB/IF-MIB-X counters for all or targeted interfaces.",
                "app_type": "script",
                "target_table": "interface",
                "connector_bindings": [
                    {"alias": "snmp", "connector_name": "snmp"},
                ],
                "versions": [
                    {
                        "version": "1.3.0",
                        "source_code": read_source("snmp_interface_poller"),
                        "requirements": [],
                        "entry_class": "Poller",
                        "is_latest": True,
                    },
                ],
            },
            {
                "name": "snmp_discovery",
                "description": "SNMP device discovery — collects system identity OIDs for auto-classification. One-shot job triggered by discovery flag.",
                "app_type": "script",
                "target_table": "config",
                "connector_bindings": [
                    {"alias": "snmp", "connector_name": "snmp"},
                ],
                "versions": [
                    {
                        "version": "1.4.0",
                        "source_code": read_source("snmp_discovery"),
                        "requirements": [],
                        "entry_class": "Poller",
                        "is_latest": True,
                    },
                ],
            },
            {
                "name": "snmp_uptime",
                "description": "SNMP uptime monitor — polls snmpEngineTime or sysUpTime for device uptime tracking.",
                "app_type": "script",
                "target_table": "performance",
                "connector_bindings": [
                    {"alias": "snmp", "connector_name": "snmp"},
                ],
                "versions": [
                    {
                        "version": "1.1.0",
                        "source_code": read_source("snmp_uptime"),
                        "requirements": [],
                        "entry_class": "Poller",
                        "is_latest": True,
                    },
                ],
            },
        ],
    },
}

(PACKS_DIR / "snmp-core-v1.0.0.json").write_text(
    json.dumps(snmp_core, indent=2, ensure_ascii=False) + "\n"
)
print(f"Created packs/snmp-core-v1.0.0.json ({len(snmp_core['contents']['apps'])} apps)")


# ── Basic Checks Pack ─────────────────────────────────────────────────────────
# Source code from the BasePoller versions running in the DB

PING_SOURCE = '''\
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

PORT_SOURCE = '''\
"""TCP port check — measures reachability and connect time."""
import asyncio
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

HTTP_SOURCE = '''\
"""HTTP/HTTPS check — measures reachability and response time."""
import asyncio
import time
import ssl
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult

try:
    import aiohttp
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False


class Poller(BasePoller):
    async def poll(self, context: PollContext) -> PollResult:
        url = context.parameters.get("url") or context.device_host or ""
        if not url:
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[], config_data=None,
                status="error", reachable=False,
                error_message="No URL or host configured",
                execution_time_ms=0,
                error_category="config",
            )
        if not url.startswith(("http://", "https://")):
            url = "http://" + url

        timeout = int(context.parameters.get("timeout", 10))
        expected = context.parameters.get("expected_status", [200, 201, 204, 301, 302])
        verify_ssl = bool(context.parameters.get("verify_ssl", True))
        start = time.time()

        try:
            if _HAS_AIOHTTP:
                ssl_ctx = None if verify_ssl else ssl.create_default_context()
                if not verify_ssl:
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout), ssl=ssl_ctx) as resp:
                        status_code = resp.status
                        elapsed_ms = (time.time() - start) * 1000
            else:
                import urllib.request, urllib.error
                ssl_ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
                req = urllib.request.Request(url, method="GET", headers={"User-Agent": "monctl-http-check/2.0"})
                opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_ctx))
                loop = asyncio.get_event_loop()
                resp = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: opener.open(req, timeout=timeout)),
                    timeout=timeout + 2,
                )
                status_code = resp.status
                elapsed_ms = (time.time() - start) * 1000
                resp.close()

            reachable = status_code in expected
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "http_reachable", "value": 1.0 if reachable else 0.0},
                    {"name": "http_response_time_ms", "value": elapsed_ms, "unit": "ms"},
                    {"name": "http_status_code", "value": float(status_code)},
                ],
                config_data=None,
                status="ok" if reachable else "critical",
                reachable=reachable,
                error_message=None if reachable else f"HTTP {status_code} (expected {expected})",
                execution_time_ms=int(elapsed_ms),
                rtt_ms=elapsed_ms,
                error_category="" if reachable else "device",
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.time() - start) * 1000
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[{"name": "http_reachable", "value": 0.0}],
                config_data=None,
                status="critical", reachable=False,
                error_message=f"HTTP timed out after {timeout}s",
                execution_time_ms=int(elapsed_ms),
                error_category="device",
            )
        except Exception as exc:
            elapsed_ms = (time.time() - start) * 1000
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[{"name": "http_reachable", "value": 0.0}],
                config_data=None,
                status="critical", reachable=False,
                error_message=f"HTTP error: {type(exc).__name__}: {exc}",
                execution_time_ms=int(elapsed_ms),
                error_category="device",
            )
'''

basic_checks = {
    "monctl_pack": "1.0",
    "pack_uid": "basic-checks",
    "name": "Basic Checks (Ping, Port, HTTP)",
    "version": "1.0.0",
    "description": "Fundamental reachability checks: ICMP ping, TCP port, and HTTP/HTTPS endpoint monitoring.",
    "author": "MonCTL",
    "changelog": "v1.0.0 - Initial pack release with error_category support",
    "exported_at": None,
    "contents": {
        "apps": [
            {
                "name": "ping_check",
                "description": "ICMP ping check — measures reachability and round-trip time via system ping command.",
                "app_type": "script",
                "target_table": "availability_latency",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "title": "Ping Count",
                            "default": 3,
                            "description": "Number of ICMP packets to send",
                        },
                        "timeout": {
                            "type": "integer",
                            "title": "Timeout",
                            "default": 5,
                            "description": "Per-ping timeout in seconds",
                        },
                    },
                },
                "versions": [
                    {
                        "version": "2.1.0",
                        "source_code": PING_SOURCE,
                        "requirements": [],
                        "entry_class": "Poller",
                        "is_latest": True,
                    },
                ],
            },
            {
                "name": "port_check",
                "description": "TCP port check — measures whether a TCP port is open and connect time.",
                "app_type": "script",
                "target_table": "availability_latency",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "port": {
                            "type": "integer",
                            "title": "Port",
                            "default": 80,
                            "description": "TCP port to check",
                        },
                        "timeout": {
                            "type": "number",
                            "title": "Timeout",
                            "default": 5,
                            "description": "Connection timeout in seconds",
                        },
                    },
                },
                "versions": [
                    {
                        "version": "1.1.0",
                        "source_code": PORT_SOURCE,
                        "requirements": [],
                        "entry_class": "Poller",
                        "is_latest": True,
                    },
                ],
            },
            {
                "name": "http_check",
                "description": "HTTP/HTTPS endpoint check — measures reachability, response time, and status code.",
                "app_type": "script",
                "target_table": "availability_latency",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "title": "URL",
                            "description": "Full URL to check (e.g. https://example.com/health)",
                        },
                        "timeout": {
                            "type": "integer",
                            "title": "Timeout",
                            "default": 10,
                            "description": "Request timeout in seconds",
                        },
                        "expected_status": {
                            "type": "array",
                            "title": "Expected Status Codes",
                            "default": [200, 201, 204, 301, 302],
                            "description": "HTTP status codes considered OK",
                        },
                        "verify_ssl": {
                            "type": "boolean",
                            "title": "Verify SSL",
                            "default": True,
                            "description": "Verify TLS certificate",
                        },
                    },
                },
                "versions": [
                    {
                        "version": "1.0.0",
                        "source_code": HTTP_SOURCE,
                        "requirements": [],
                        "entry_class": "Poller",
                        "is_latest": True,
                    },
                ],
            },
        ],
    },
}

(PACKS_DIR / "basic-checks-v1.0.0.json").write_text(
    json.dumps(basic_checks, indent=2, ensure_ascii=False) + "\n"
)
print(f"Created packs/basic-checks-v1.0.0.json ({len(basic_checks['contents']['apps'])} apps)")
