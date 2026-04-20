"""SNMP monitoring app — checks reachability via SNMP GET and measures response time.

Uses the built-in SNMP connector (bound as "snmp" on the assignment) for all
protocol operations. The connector handles authentication (v1/v2c/v3) and
transport — this app only contains the monitoring logic.

Config keys (device address is injected as "host" when a device is linked):
    oid       str  OID to poll (default: "1.3.6.1.2.1.1.3.0" — sysUpTime)

Connector binding required:
    alias "snmp" → SNMP connector with credential providing auth parameters

Performance data (always present in check_result.performance_data):
    rtt_ms     SNMP response time in milliseconds (0 if unreachable)
    reachable  1.0 if SNMP responded successfully, 0.0 if not
"""

from __future__ import annotations

import asyncio
import time

import structlog

from monctl_collector.jobs.models import PollContext, PollResult
from monctl_collector.polling.base import BasePoller

logger = structlog.get_logger()


def _classify_error(exc: BaseException) -> str:
    """Typed categorisation for exceptions surfaced from the poll path.

    - `device` — target timed out, refused connection, or didn't respond.
      Drives device-down alerting, so reserved for genuine target problems.
    - `config` — missing connector, missing/invalid config keys on the
      assignment, type mismatch pulling params from context.parameters.
    - `app` — catch-all for bugs in the poller itself (parse errors,
      unexpected value shapes). Triaged separately from device outages.
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return "device"
    # PySNMP-specific "no response" types live under pysnmp.hlapi.*; match by
    # class name so we don't import pysnmp at the top level of a reference app.
    if exc.__class__.__name__ in {"NoResponseError", "RequestTimeout"}:
        return "device"
    if isinstance(exc, (KeyError, TypeError)):
        return "config"
    return "app"


class Poller(BasePoller):
    """SNMP check poller — uses the SNMP connector for protocol operations."""

    async def poll(self, context: PollContext) -> PollResult:
        start = time.time()
        host = context.device_host or context.parameters.get("host", "localhost")
        oid = context.parameters.get("oid", "1.3.6.1.2.1.1.3.0")
        logger.debug("snmp_check_start", host=host, oid=oid, job_id=context.job.job_id)

        snmp = context.connectors.get("snmp")
        if snmp is None:
            logger.debug("snmp_check_no_connector", job_id=context.job.job_id)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[],
                config_data=None,
                status="error",
                reachable=False,
                error_message="No SNMP connector bound (expected alias 'snmp')",
                error_category="config",
                execution_time_ms=int((time.time() - start) * 1000),
            )

        try:
            result = await snmp.get([oid])
            rtt_ms = (time.time() - start) * 1000
            value = result.get(oid, "(no value)")
            logger.debug(
                "snmp_check_ok",
                host=host,
                oid=oid,
                rtt_ms=round(rtt_ms, 3),
                value=str(value)[:60],
            )

            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "snmp_reachable", "value": 1.0, "labels": {"host": host, "oid": oid}},
                    {"name": "snmp_rtt_ms", "value": rtt_ms, "labels": {"host": host, "oid": oid}, "unit": "ms"},
                ],
                config_data=None,
                status="ok",
                reachable=True,
                error_message=None,
                execution_time_ms=int(rtt_ms),
                rtt_ms=rtt_ms,
            )

        except Exception as exc:
            rtt_ms = (time.time() - start) * 1000
            category = _classify_error(exc)
            logger.debug(
                "snmp_check_failed",
                host=host,
                oid=oid,
                exc=type(exc).__name__,
                category=category,
                rtt_ms=round(rtt_ms, 3),
            )
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "snmp_reachable", "value": 0.0, "labels": {"host": host, "oid": oid}},
                ],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"SNMP CRITICAL — {host} unreachable: {exc}",
                error_category=category,
                execution_time_ms=int(rtt_ms),
                rtt_ms=0.0,
            )
