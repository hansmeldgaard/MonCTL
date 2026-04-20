"""SNMP device uptime monitor — polls snmpEngineTime or sysUpTime for uptime tracking.

Tries snmpEngineTime (1.3.6.1.6.3.10.2.1.3.0) first — it reports seconds and
wraps at ~68 years.  Falls back to sysUpTime.0 (1.3.6.1.2.1.1.3.0) which
reports centiseconds and wraps at ~497 days.

Connector binding required:
    alias "snmp" → SNMP connector with credential providing auth parameters

Writes to: performance table
    uptime_seconds   Device uptime in seconds (gauge)
    uptime_days      Device uptime in days (gauge)
"""

from __future__ import annotations

import asyncio
import time

import structlog

from monctl_collector.jobs.models import PollContext, PollResult
from monctl_collector.polling.base import BasePoller

logger = structlog.get_logger()

# snmpEngineTime — seconds since SNMP engine boot, wraps at ~68 years
_OID_ENGINE_TIME = "1.3.6.1.6.3.10.2.1.3.0"
# sysUpTime — centiseconds since last re-init, wraps at ~497 days
_OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"


def _classify_error(exc: BaseException) -> str:
    """See apps/snmp_check.py for the full rationale — kept in-sync across apps."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return "device"
    if exc.__class__.__name__ in {"NoResponseError", "RequestTimeout"}:
        return "device"
    if isinstance(exc, (KeyError, TypeError)):
        return "config"
    return "app"


def _parse_timeticks(raw: object) -> float | None:
    """Parse an SNMP TimeTicks / integer value to a raw numeric value.

    Handles both plain integers and the ``TimeTicks: (12345)`` string
    representation that some SNMP libraries return.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    # Strip "TimeTicks: (nnn)" wrapper if present
    if "(" in s and ")" in s:
        s = s[s.index("(") + 1 : s.index(")")]
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


class Poller(BasePoller):
    """SNMP uptime poller — prefers snmpEngineTime, falls back to sysUpTime."""

    async def poll(self, context: PollContext) -> PollResult:
        start = time.time()
        host = context.device_host or context.parameters.get("host", "localhost")
        logger.debug("snmp_uptime_start", host=host, job_id=context.job.job_id)

        snmp = context.connectors.get("snmp")
        if snmp is None:
            logger.debug("snmp_uptime_no_connector", job_id=context.job.job_id)
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
            result = await snmp.get([_OID_ENGINE_TIME, _OID_SYS_UPTIME])
            elapsed_ms = (time.time() - start) * 1000

            uptime_seconds: float | None = None
            source = ""

            engine_val = _parse_timeticks(result.get(_OID_ENGINE_TIME))
            if engine_val is not None and engine_val > 0:
                uptime_seconds = engine_val
                source = "snmpEngineTime"

            if uptime_seconds is None:
                sys_val = _parse_timeticks(result.get(_OID_SYS_UPTIME))
                if sys_val is not None and sys_val >= 0:
                    uptime_seconds = sys_val / 100.0
                    source = "sysUpTime"

            if uptime_seconds is None:
                # Device reachable but neither OID returned a usable value —
                # that's a bug in the app (or a broken SNMP stack we don't
                # handle), not a device-down signal.
                logger.debug(
                    "snmp_uptime_parse_failed",
                    host=host,
                    engine_raw=str(result.get(_OID_ENGINE_TIME))[:40],
                    sys_raw=str(result.get(_OID_SYS_UPTIME))[:40],
                )
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[],
                    config_data=None,
                    status="critical",
                    reachable=True,
                    error_message=f"Could not parse uptime from {host}",
                    error_category="app",
                    execution_time_ms=int(elapsed_ms),
                )

            uptime_days = uptime_seconds / 86400.0
            logger.debug(
                "snmp_uptime_ok",
                host=host,
                source=source,
                uptime_seconds=uptime_seconds,
                elapsed_ms=round(elapsed_ms, 3),
            )

            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {
                        "name": "uptime_seconds",
                        "value": uptime_seconds,
                        "labels": {"host": host, "source": source},
                        "unit": "seconds",
                        "component": "uptime",
                        "component_type": "system",
                    },
                    {
                        "name": "uptime_days",
                        "value": round(uptime_days, 2),
                        "labels": {"host": host, "source": source},
                        "unit": "days",
                        "component": "uptime",
                        "component_type": "system",
                    },
                ],
                config_data=None,
                status="ok",
                reachable=True,
                error_message=None,
                execution_time_ms=int(elapsed_ms),
            )

        except Exception as exc:
            elapsed_ms = (time.time() - start) * 1000
            category = _classify_error(exc)
            logger.debug(
                "snmp_uptime_failed",
                host=host,
                exc=type(exc).__name__,
                category=category,
                elapsed_ms=round(elapsed_ms, 3),
            )
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"SNMP uptime check failed — {host}: {type(exc).__name__}: {exc}",
                error_category=category,
                execution_time_ms=int(elapsed_ms),
            )
