"""SNMP device discovery app — collects system identity OIDs for device classification.

Runs on collectors via the existing job system. Uses the SNMP connector
(bound as alias "snmp") to query MIB-II system group OIDs. Returns the
raw values as config_data — central's ingestion pipeline handles rule
matching and device classification.

This app is NOT scheduled on an interval. It runs as a one-shot job
triggered by a Redis discovery flag. Central injects it into the job list
when the flag is set, and the flag is cleared atomically.

Connector binding required:
    alias "snmp" → SNMP connector with credential providing auth parameters

config_data keys returned:
    sys_object_id   — sysObjectID.0 (1.3.6.1.2.1.1.2.0)
    sys_descr       — sysDescr.0 (1.3.6.1.2.1.1.1.0)
    sys_name        — sysName.0 (1.3.6.1.2.1.1.5.0)
    sys_location    — sysLocation.0 (1.3.6.1.2.1.1.6.0)
    sys_contact     — sysContact.0 (1.3.6.1.2.1.1.4.0)
    sys_uptime      — sysUpTime.0 (1.3.6.1.2.1.1.3.0)
"""

from __future__ import annotations

import binascii
import time

from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult


def _decode_snmp_value(value) -> str:
    """Decode an SNMP value to a readable string.

    pysnmp v7 may return OCTET STRING values as hex-prefixed strings
    (e.g., "0x436973636f...") instead of decoded text. This detects and
    decodes such values.
    """
    val_str = str(value)
    if val_str.startswith("0x") and len(val_str) > 2:
        try:
            return binascii.unhexlify(val_str[2:]).decode("utf-8", errors="replace").rstrip("\x00")
        except (ValueError, UnicodeDecodeError):
            pass
    return val_str


# MIB-II system group OIDs
_SYS_OIDS = {
    "sys_object_id": "1.3.6.1.2.1.1.2.0",
    "sys_descr":     "1.3.6.1.2.1.1.1.0",
    "sys_name":      "1.3.6.1.2.1.1.5.0",
    "sys_location":  "1.3.6.1.2.1.1.6.0",
    "sys_contact":   "1.3.6.1.2.1.1.4.0",
    "sys_uptime":    "1.3.6.1.2.1.1.3.0",
}


class Poller(BasePoller):
    """SNMP discovery poller — collects system identity for device classification."""

    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "localhost")

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
                error_message="No SNMP connector bound (expected alias 'snmp'). "
                              "Bind the built-in 'snmp' connector with alias 'snmp' on this assignment.",
                execution_time_ms=0,
            )

        start = time.monotonic()
        try:
            await snmp.connect(host)

            # Query all system OIDs in one GET
            oid_list = list(_SYS_OIDS.values())
            raw = await snmp.get(oid_list)

            rtt_ms = (time.monotonic() - start) * 1000

            # Map OID values back to friendly names
            oid_to_key = {v: k for k, v in _SYS_OIDS.items()}
            config_data = {}
            for oid, value in raw.items():
                key = oid_to_key.get(oid)
                if key:
                    val_str = _decode_snmp_value(value)
                    # Normalize sysObjectID: strip leading dot if present
                    if key == "sys_object_id" and val_str.startswith("."):
                        val_str = val_str[1:]
                    config_data[key] = val_str

            # Probe eligibility OIDs if passed via parameters
            eligibility_oid_list = context.parameters.get("_eligibility_oids", [])
            if eligibility_oid_list:
                try:
                    elig_raw = await snmp.get(eligibility_oid_list)
                    elig_results = {}
                    for oid in eligibility_oid_list:
                        value = elig_raw.get(oid)
                        if value is not None:
                            val_str = _decode_snmp_value(value)
                            val_lower = val_str.lower()
                            if "nosuchobject" in val_lower or "nosuchinstance" in val_lower or "no such object" in val_lower or "no such instance" in val_lower:
                                elig_results[oid] = None
                            else:
                                elig_results[oid] = val_str
                        else:
                            elig_results[oid] = None
                    config_data["_eligibility_results"] = elig_results
                except Exception as elig_exc:
                    config_data["_eligibility_error"] = str(elig_exc)

            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "discovery_reachable", "value": 1.0, "labels": {"host": host}},
                    {"name": "discovery_rtt_ms", "value": rtt_ms, "labels": {"host": host}, "unit": "ms"},
                ],
                config_data=config_data,
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
                    {"name": "discovery_reachable", "value": 0.0, "labels": {"host": host}},
                ],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"SNMP discovery failed — {host}: {exc}",
                execution_time_ms=int(rtt_ms),
                rtt_ms=0.0,
            )
