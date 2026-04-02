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

import time

from monctl_collector.jobs.models import PollContext, PollResult
from monctl_collector.polling.base import BasePoller


class Poller(BasePoller):
    """SNMP check poller — uses the SNMP connector for protocol operations."""

    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "localhost")
        oid = context.parameters.get("oid", "1.3.6.1.2.1.1.3.0")

        snmp = context.connectors.get("snmp")
        if snmp is None:
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
                execution_time_ms=0,
            )

        start = time.monotonic()
        try:
            result = await snmp.get([oid])
            rtt_ms = (time.monotonic() - start) * 1000

            value = result.get(oid, "(no value)")
            output = f"SNMP OK — {host} responded, OID {oid} = {value}, RTT {rtt_ms:.3f}ms"

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
            rtt_ms = (time.monotonic() - start) * 1000
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
                error_category="device",
                execution_time_ms=int(rtt_ms),
                rtt_ms=0.0,
            )
