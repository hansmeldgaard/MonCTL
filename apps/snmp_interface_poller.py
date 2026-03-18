"""SNMP interface poller — targeted GET or full walk of ifTable/ifXTable.

Uses the built-in SNMP connector (bound as "snmp" on the assignment) for all
protocol operations. The connector handles authentication (v1/v2c/v3) and
transport — this app only contains the monitoring/parsing logic.

Connector binding required:
    alias "snmp" → SNMP connector with credential providing auth parameters
"""

import time
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult

# SNMP OIDs for interface data (base OIDs, append .ifIndex for GET)
_IF_OIDS = {
    "ifIndex":       "1.3.6.1.2.1.2.2.1.1",
    "ifDescr":       "1.3.6.1.2.1.2.2.1.2",
    "ifSpeed":       "1.3.6.1.2.1.2.2.1.5",
    "ifAdminStatus": "1.3.6.1.2.1.2.2.1.7",
    "ifOperStatus":  "1.3.6.1.2.1.2.2.1.8",
    "ifInOctets":    "1.3.6.1.2.1.2.2.1.10",
    "ifOutOctets":   "1.3.6.1.2.1.2.2.1.16",
    "ifInErrors":    "1.3.6.1.2.1.2.2.1.14",
    "ifOutErrors":   "1.3.6.1.2.1.2.2.1.20",
    "ifInDiscards":  "1.3.6.1.2.1.2.2.1.13",
    "ifOutDiscards": "1.3.6.1.2.1.2.2.1.19",
    "ifInUcastPkts": "1.3.6.1.2.1.2.2.1.11",
    "ifOutUcastPkts": "1.3.6.1.2.1.2.2.1.17",
}
_IFX_OIDS = {
    "ifName":        "1.3.6.1.2.1.31.1.1.1.1",
    "ifAlias":       "1.3.6.1.2.1.31.1.1.1.18",
    "ifHighSpeed":   "1.3.6.1.2.1.31.1.1.1.15",
    "ifHCInOctets":  "1.3.6.1.2.1.31.1.1.1.6",
    "ifHCOutOctets": "1.3.6.1.2.1.31.1.1.1.10",
}
_ALL_OIDS = {**_IF_OIDS, **_IFX_OIDS}
_ADMIN_STATUS = {1: "up", 2: "down", 3: "testing"}
_OPER_STATUS = {
    1: "up", 2: "down", 3: "testing", 4: "unknown",
    5: "dormant", 6: "notPresent", 7: "lowerLayerDown",
}

# OID groups per poll_metrics mode
_IDENTITY_OIDS = [
    "ifIndex", "ifDescr", "ifName", "ifAlias",
    "ifOperStatus", "ifAdminStatus", "ifHighSpeed", "ifSpeed",
]
_METRIC_OIDS = {
    "all": list(_ALL_OIDS.keys()),
    "traffic": ["ifHCInOctets", "ifHCOutOctets", "ifInOctets", "ifOutOctets"],
    "errors": ["ifInErrors", "ifOutErrors"],
    "discards": ["ifInDiscards", "ifOutDiscards"],
    "status": [],
}


def _resolve_poll_metrics(mode: str) -> list[str]:
    if mode == "all":
        return list(_ALL_OIDS.keys())
    parts = [p.strip() for p in mode.split(",") if p.strip()]
    oids = set(_IDENTITY_OIDS)
    for part in parts:
        oids.update(_METRIC_OIDS.get(part, []))
    return list(oids)


def _has_metric(mode: str, metric: str) -> bool:
    return mode == "all" or metric in mode.split(",")


def _safe_int(val, default: int = 0) -> int:
    """Convert SNMP value to int, returning default for non-numeric values."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


class Poller(BasePoller):
    """SNMP interface poller — uses the SNMP connector for protocol operations."""

    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "")
        include_filter = context.parameters.get("include_interfaces", [])
        exclude_filter = context.parameters.get("exclude_interfaces", [])
        exclude_oper = set(context.parameters.get("exclude_oper_status", []))
        monitored = context.parameters.get("monitored_interfaces")
        poll_interval = context.job.interval
        start = time.time()

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
                              "Assign an SNMP connector with alias 'snmp' to this app assignment.",
                execution_time_ms=0,
            )

        try:
            raw: dict[str, dict[int, str | int]] = {}

            if monitored:
                # ── Targeted GET mode ──────────────────────────────────────
                oid_requests = []
                for iface in monitored:
                    idx = int(iface["if_index"])
                    metrics_mode = iface.get("poll_metrics", "all")
                    oid_names = _resolve_poll_metrics(metrics_mode)
                    for oid_name in oid_names:
                        base_oid = _ALL_OIDS.get(oid_name)
                        if base_oid:
                            oid_requests.append((oid_name, idx, f"{base_oid}.{idx}"))

                # Batch into chunks of 20 OIDs per SNMP GET
                batch_size = 20
                oid_batches = []
                batch_meta = []  # list of lists of (oid_name, if_index, full_oid)
                for i in range(0, len(oid_requests), batch_size):
                    batch = oid_requests[i:i + batch_size]
                    oid_batches.append([oid for _, _, oid in batch])
                    batch_meta.append(batch)

                # Use get_many if available (single session), else fallback
                if hasattr(snmp, "get_many"):
                    try:
                        all_results = await snmp.get_many(oid_batches)
                        for batch in batch_meta:
                            for oid_name, if_index, full_oid in batch:
                                val = all_results.get(full_oid)
                                if val is not None:
                                    raw.setdefault(oid_name, {})[if_index] = val
                    except Exception:
                        pass
                else:
                    for i, batch in enumerate(batch_meta):
                        try:
                            result = await snmp.get(oid_batches[i])
                            for oid_name, if_index, full_oid in batch:
                                val = result.get(full_oid)
                                if val is not None:
                                    raw.setdefault(oid_name, {})[if_index] = val
                        except Exception:
                            continue

                if_indices = [int(iface["if_index"]) for iface in monitored]
                metrics_lookup = {
                    int(iface["if_index"]): iface.get("poll_metrics", "all")
                    for iface in monitored
                }
            else:
                # ── Walk mode (discovery / first run) ──────────────────────
                all_oids = list(_IF_OIDS.items()) + list(_IFX_OIDS.items())
                for oid_name, oid_str in all_oids:
                    try:
                        rows = await snmp.walk(oid_str)
                        oid_data = {}
                        for full_oid, val in rows:
                            # Extract ifIndex from the last component of the OID
                            if_index = int(full_oid.rsplit(".", 1)[-1])
                            oid_data[if_index] = val
                        raw[oid_name] = oid_data
                    except Exception:
                        raw[oid_name] = {}

                if_indices = sorted(raw.get("ifIndex", {}).keys())
                metrics_lookup = {}

            # Build per-interface rows
            interface_rows = []
            for idx in if_indices:
                if_name = str(raw.get("ifName", {}).get(idx, raw.get("ifDescr", {}).get(idx, f"if{idx}")))
                if_alias = str(raw.get("ifAlias", {}).get(idx, ""))
                oper_status = _OPER_STATUS.get(_safe_int(raw.get("ifOperStatus", {}).get(idx, 4), 4), "unknown")

                if not monitored:
                    if exclude_oper and oper_status in exclude_oper:
                        continue
                    if include_filter and not any(p in if_name for p in include_filter):
                        continue
                    if exclude_filter and any(p in if_name for p in exclude_filter):
                        continue

                metrics_mode = metrics_lookup.get(idx, "all")

                in_octets = _safe_int(raw.get("ifHCInOctets", {}).get(idx, raw.get("ifInOctets", {}).get(idx, 0)))
                out_octets = _safe_int(raw.get("ifHCOutOctets", {}).get(idx, raw.get("ifOutOctets", {}).get(idx, 0)))

                high_speed = raw.get("ifHighSpeed", {}).get(idx)
                if high_speed and _safe_int(high_speed) > 0:
                    speed_mbps = _safe_int(high_speed)
                else:
                    speed_raw = raw.get("ifSpeed", {}).get(idx, 0)
                    speed_mbps = _safe_int(speed_raw) // 1_000_000 if speed_raw else 0

                admin_status = _ADMIN_STATUS.get(_safe_int(raw.get("ifAdminStatus", {}).get(idx, 3), 3), "unknown")

                row = {
                    "if_index": idx,
                    "if_name": if_name,
                    "if_alias": if_alias,
                    "if_speed_mbps": speed_mbps,
                    "if_admin_status": admin_status,
                    "if_oper_status": oper_status,
                    "in_octets": in_octets if _has_metric(metrics_mode, "traffic") else 0,
                    "out_octets": out_octets if _has_metric(metrics_mode, "traffic") else 0,
                    "in_errors": _safe_int(raw.get("ifInErrors", {}).get(idx, 0)) if _has_metric(metrics_mode, "errors") else 0,
                    "out_errors": _safe_int(raw.get("ifOutErrors", {}).get(idx, 0)) if _has_metric(metrics_mode, "errors") else 0,
                    "in_discards": _safe_int(raw.get("ifInDiscards", {}).get(idx, 0)) if _has_metric(metrics_mode, "discards") else 0,
                    "out_discards": _safe_int(raw.get("ifOutDiscards", {}).get(idx, 0)) if _has_metric(metrics_mode, "discards") else 0,
                    "in_unicast_pkts": _safe_int(raw.get("ifInUcastPkts", {}).get(idx, 0)) if metrics_mode == "all" else 0,
                    "out_unicast_pkts": _safe_int(raw.get("ifOutUcastPkts", {}).get(idx, 0)) if metrics_mode == "all" else 0,
                    "poll_interval_sec": poll_interval,
                }
                interface_rows.append(row)

            execution_ms = int((time.time() - start) * 1000)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "interface_count", "value": len(interface_rows)},
                    {"name": "poll_mode", "value": 1 if monitored else 0},
                ],
                config_data=None,
                status="ok" if interface_rows else "unknown",
                reachable=True,
                error_message=None,
                execution_time_ms=execution_ms,
                interface_rows=interface_rows,
            )
        except Exception as exc:
            execution_ms = int((time.time() - start) * 1000)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[], config_data=None,
                status="critical", reachable=False,
                error_message=f"{type(exc).__name__}: {exc}",
                execution_time_ms=execution_ms,
            )
