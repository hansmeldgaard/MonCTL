"""MonCTL Central Server - FastAPI application."""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from monctl_central.config import settings
from monctl_central.dependencies import get_engine, get_session_factory

logger = structlog.get_logger()


def _get_default_apps():
    """Return list of (name, description, source_code, entry_class, requirements) for default apps."""
    ping_check_code = '''\
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
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[{"name": "packet_loss_pct", "value": 100.0}],
                    config_data=None,
                    status="critical",
                    reachable=False,
                    error_message=f"Ping failed: {stderr.decode().strip() or 'no response'}",
                    execution_time_ms=execution_ms,
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
            )

    def _parse_rtt(self, output: str) -> float:
        """Extract avg RTT from ping output."""
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
        """Extract packet loss percentage from ping output."""
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

    port_check_code = '''\
"""TCP port check — tests if a port is open and measures response time."""
import asyncio
import time
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult


class Poller(BasePoller):
    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "")
        port = int(context.parameters.get("port", 443))
        timeout = context.parameters.get("timeout", 5)
        start = time.time()

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            response_ms = round((time.time() - start) * 1000, 2)
            writer.close()
            await writer.wait_closed()
            execution_ms = int((time.time() - start) * 1000)

            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "response_time_ms", "value": response_ms},
                    {"name": "port_open", "value": 1},
                ],
                config_data=None,
                status="ok",
                reachable=True,
                error_message=None,
                execution_time_ms=execution_ms,
                response_time_ms=response_ms,
            )
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError) as exc:
            execution_ms = int((time.time() - start) * 1000)
            is_timeout = isinstance(exc, asyncio.TimeoutError)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[{"name": "port_open", "value": 0}],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"Port {port} {'timed out' if is_timeout else 'refused/unreachable'}: {exc}",
                execution_time_ms=execution_ms,
            )
'''

    snmp_check_code = '''\
"""SNMP reachability check — SNMP GET on a configurable OID with RTT measurement."""
import time
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult


def _build_v3_auth(cred: dict):
    """Build UsmUserData from credential dict for SNMPv3."""
    from pysnmp.hlapi.asyncio import UsmUserData
    import pysnmp.hlapi.asyncio as hlapi

    username = cred.get("username", "")
    security_level = cred.get("security_level", "authPriv").lower()

    _auth_map = {
        "MD5": "usmHMACMD5AuthProtocol", "SHA": "usmHMACSHAAuthProtocol",
        "SHA224": "usmHMAC128SHA224AuthProtocol", "SHA256": "usmHMAC192SHA256AuthProtocol",
        "SHA384": "usmHMAC256SHA384AuthProtocol", "SHA512": "usmHMAC384SHA512AuthProtocol",
    }
    _priv_map = {
        "DES": "usmDESPrivProtocol", "3DES": "usm3DESEDEPrivProtocol",
        "AES": "usmAesCfb128Protocol", "AES128": "usmAesCfb128Protocol",
        "AES192": "usmAesCfb192Protocol", "AES256": "usmAesCfb256Protocol",
    }

    kwargs: dict = {"userName": username}

    if security_level == "noauthnopriv":
        return UsmUserData(**kwargs)

    auth_proto_name = (cred.get("auth_protocol") or "").upper()
    auth_key = cred.get("auth_password") or cred.get("auth_key") or ""
    auth_proto = getattr(hlapi, _auth_map.get(auth_proto_name, ""), None) if auth_proto_name else None
    if auth_proto and auth_key:
        kwargs["authKey"] = auth_key
        kwargs["authProtocol"] = auth_proto

    if security_level == "authpriv":
        priv_proto_name = (cred.get("priv_protocol") or "").upper()
        priv_key = cred.get("priv_password") or cred.get("priv_key") or ""
        priv_proto = getattr(hlapi, _priv_map.get(priv_proto_name, ""), None) if priv_proto_name else None
        if priv_proto and priv_key:
            kwargs["privKey"] = priv_key
            kwargs["privProtocol"] = priv_proto

    return UsmUserData(**kwargs)


class Poller(BasePoller):
    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "")
        oid = context.parameters.get("oid", "1.3.6.1.2.1.1.3.0")
        timeout = int(context.parameters.get("timeout", 5))
        snmp_port = int(context.credential.get("port", context.parameters.get("port", 161)))
        cred = context.credential
        snmp_version = str(cred.get("version", "2c")).lower()
        start = time.time()

        try:
            from pysnmp.hlapi.asyncio import (
                CommunityData, ContextData, ObjectIdentity, ObjectType,
                SnmpEngine, UdpTransportTarget, getCmd,
            )

            engine = SnmpEngine()
            if snmp_version == "3":
                auth_data = _build_v3_auth(cred)
            else:
                auth_data = CommunityData(
                    cred.get("community", "public"),
                    mpModel=0 if snmp_version == "1" else 1,
                )

            transport = UdpTransportTarget(
                (host, snmp_port), timeout=timeout, retries=1,
            )

            error_indication, error_status, error_index, var_binds = await getCmd(
                engine, auth_data, transport, ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )

            rtt_ms = round((time.time() - start) * 1000, 2)
            execution_ms = int((time.time() - start) * 1000)

            if error_indication:
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[{"name": "snmp_reachable", "value": 0.0, "labels": {"oid": oid}}],
                    config_data=None,
                    status="critical",
                    reachable=False,
                    error_message=f"SNMP error: {error_indication}",
                    execution_time_ms=execution_ms,
                )

            if error_status:
                return PollResult(
                    job_id=context.job.job_id,
                    device_id=context.job.device_id,
                    collector_node=context.node_id,
                    timestamp=time.time(),
                    metrics=[{"name": "snmp_reachable", "value": 0.0, "labels": {"oid": oid}}],
                    config_data=None,
                    status="critical",
                    reachable=False,
                    error_message=f"SNMP error: {error_status.prettyPrint()} at {error_index}",
                    execution_time_ms=execution_ms,
                )

            value = var_binds[0][1].prettyPrint() if var_binds else "(no value)"

            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[
                    {"name": "snmp_reachable", "value": 1.0, "labels": {"oid": oid}},
                    {"name": "snmp_rtt_ms", "value": rtt_ms, "unit": "ms", "labels": {"oid": oid}},
                ],
                config_data={"snmp_oid_value": value, "snmp_oid": oid},
                status="ok",
                reachable=True,
                error_message=None,
                execution_time_ms=execution_ms,
                rtt_ms=rtt_ms,
                response_time_ms=rtt_ms,
            )

        except ImportError:
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
                error_message="pysnmp not installed — add pysnmp>=6.0 to app requirements",
                execution_time_ms=execution_ms,
            )
        except Exception as exc:
            execution_ms = int((time.time() - start) * 1000)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[{"name": "snmp_reachable", "value": 0.0, "labels": {"oid": oid}}],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"{type(exc).__name__}: {exc}",
                execution_time_ms=execution_ms,
            )
'''

    snmp_interface_code = '''\
"""SNMP interface poller — targeted GET or full walk of ifTable/ifXTable."""
import asyncio
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
    "ifOutUcastPkts":"1.3.6.1.2.1.2.2.1.17",
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
_OPER_STATUS = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant", 6: "notPresent", 7: "lowerLayerDown"}

# OID groups per poll_metrics mode
_IDENTITY_OIDS = ["ifIndex", "ifDescr", "ifName", "ifAlias", "ifOperStatus", "ifAdminStatus", "ifHighSpeed", "ifSpeed"]
_METRIC_OIDS = {
    "all": list(_ALL_OIDS.keys()),
    "traffic": ["ifHCInOctets", "ifHCOutOctets", "ifInOctets", "ifOutOctets"],
    "errors": ["ifInErrors", "ifOutErrors"],
    "discards": ["ifInDiscards", "ifOutDiscards"],
    "status": [],
}

def _resolve_poll_metrics(mode: str) -> list[str]:
    """Resolve a poll_metrics value (possibly comma-separated) into a list of OID names."""
    if mode == "all":
        return list(_ALL_OIDS.keys())
    parts = [p.strip() for p in mode.split(",") if p.strip()]
    oids = set(_IDENTITY_OIDS)
    for part in parts:
        oids.update(_METRIC_OIDS.get(part, []))
    return list(oids)

def _has_metric(mode: str, metric: str) -> bool:
    """Check if a metrics mode includes a specific metric type."""
    return mode == "all" or metric in mode.split(",")


class Poller(BasePoller):
    @staticmethod
    def _build_auth(cred: dict):
        """Build pysnmp auth object from credential data. Supports v1, v2c, and v3."""
        from pysnmp.hlapi.asyncio import CommunityData, UsmUserData
        import pysnmp.hlapi.asyncio as hlapi

        version = str(cred.get("version", "2c")).lower()

        if version != "3":
            community = cred.get("community", "public")
            return CommunityData(community, mpModel=0 if version == "1" else 1)

        username = cred.get("username", "")
        security_level = cred.get("security_level", "authPriv").lower()

        _AUTH_MAP = {
            "MD5": "usmHMACMD5AuthProtocol", "SHA": "usmHMACSHAAuthProtocol",
            "SHA224": "usmHMAC128SHA224AuthProtocol", "SHA256": "usmHMAC192SHA256AuthProtocol",
            "SHA384": "usmHMAC256SHA384AuthProtocol", "SHA512": "usmHMAC384SHA512AuthProtocol",
        }
        _PRIV_MAP = {
            "DES": "usmDESPrivProtocol", "3DES": "usm3DESEDEPrivProtocol",
            "AES": "usmAesCfb128Protocol", "AES128": "usmAesCfb128Protocol",
            "AES192": "usmAesCfb192Protocol", "AES256": "usmAesCfb256Protocol",
        }

        kwargs: dict = {"userName": username}

        if security_level == "noauthnopriv":
            return UsmUserData(**kwargs)

        auth_proto_name = (cred.get("auth_protocol") or "").upper()
        auth_key = cred.get("auth_password") or cred.get("auth_key") or ""
        auth_proto = getattr(hlapi, _AUTH_MAP.get(auth_proto_name, ""), None) if auth_proto_name else None
        if auth_proto and auth_key:
            kwargs["authKey"] = auth_key
            kwargs["authProtocol"] = auth_proto

        if security_level == "authpriv":
            priv_proto_name = (cred.get("priv_protocol") or "").upper()
            priv_key = cred.get("priv_password") or cred.get("priv_key") or ""
            priv_proto = getattr(hlapi, _PRIV_MAP.get(priv_proto_name, ""), None) if priv_proto_name else None
            if priv_proto and priv_key:
                kwargs["privKey"] = priv_key
                kwargs["privProtocol"] = priv_proto

        return UsmUserData(**kwargs)

    async def poll(self, context: PollContext) -> PollResult:
        host = context.device_host or context.parameters.get("host", "")
        timeout = context.parameters.get("timeout", 10)
        include_filter = context.parameters.get("include_interfaces", [])
        exclude_filter = context.parameters.get("exclude_interfaces", [])
        exclude_oper = set(context.parameters.get("exclude_oper_status", []))
        monitored = context.parameters.get("monitored_interfaces")
        poll_interval = context.job.interval
        start = time.time()

        try:
            from pysnmp.hlapi.asyncio import (
                CommunityData, ContextData, ObjectIdentity, ObjectType,
                SnmpEngine, UdpTransportTarget, UsmUserData, bulkCmd, getCmd,
            )

            engine = SnmpEngine()
            auth_data = self._build_auth(context.credential)
            port = int(context.credential.get("port", 161))
            transport = UdpTransportTarget((host, port), timeout=timeout, retries=1)

            raw: dict[str, dict[int, str | int]] = {}

            if monitored:
                # ── Targeted GET mode ──────────────────────────────────────
                # Build OID requests per interface based on poll_metrics
                oid_requests = []  # list of (oid_name, if_index, full_oid_str)
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
                for i in range(0, len(oid_requests), batch_size):
                    batch = oid_requests[i:i + batch_size]
                    varbinds = [ObjectType(ObjectIdentity(oid)) for _, _, oid in batch]
                    try:
                        err_ind, err_st, err_idx, var_binds = await getCmd(
                            engine, auth_data, transport, ContextData(),
                            *varbinds,
                        )
                        if err_ind or err_st:
                            continue
                        # var_binds is a list of ObjectType (oid, val) pairs
                        for j, (oid, val) in enumerate(var_binds):
                            if j < len(batch):
                                oid_name, if_index, _ = batch[j]
                                val_str = val.prettyPrint() if hasattr(val, "prettyPrint") else str(val)
                                raw.setdefault(oid_name, {})[if_index] = val_str
                    except Exception:
                        continue  # Skip failed batch

                # Use monitored list as the if_indices
                if_indices = [int(iface["if_index"]) for iface in monitored]
                # Build poll_metrics lookup
                metrics_lookup = {int(iface["if_index"]): iface.get("poll_metrics", "all") for iface in monitored}
            else:
                # ── Walk mode (discovery / first run) ──────────────────────
                async def _manual_bulk_walk(base_oid_str, max_rows=500):
                    """Walk an OID tree using repeated bulkCmd."""
                    results = {}
                    current_oid = base_oid_str
                    base_tuple = tuple(int(x) for x in base_oid_str.split("."))
                    base_len = len(base_tuple)
                    while len(results) < max_rows:
                        err_ind, err_st, err_idx, var_binds = await bulkCmd(
                            engine, auth_data, transport, ContextData(),
                            0, 25,
                            ObjectType(ObjectIdentity(current_oid)),
                        )
                        if err_ind or err_st:
                            break
                        if not var_binds:
                            break
                        out_of_tree = False
                        last_oid = None
                        for row in var_binds:
                            for oid, val in row:
                                oid_tuple = tuple(oid)
                                if oid_tuple[:base_len] != base_tuple:
                                    out_of_tree = True
                                    break
                                if_index = oid_tuple[-1]
                                results[if_index] = val.prettyPrint() if hasattr(val, "prettyPrint") else str(val)
                                last_oid = ".".join(str(x) for x in oid_tuple)
                            if out_of_tree:
                                break
                        if out_of_tree or last_oid is None or last_oid == current_oid:
                            break
                        current_oid = last_oid
                    return results

                all_oids = list(_IF_OIDS.items()) + list(_IFX_OIDS.items())
                for oid_name, oid_str in all_oids:
                    try:
                        raw[oid_name] = await _manual_bulk_walk(oid_str)
                    except Exception:
                        raw[oid_name] = {}

                if_indices = sorted(raw.get("ifIndex", {}).keys())
                metrics_lookup = {}  # Walk mode: all metrics for all interfaces

            # Build per-interface rows
            interface_rows = []
            for idx in if_indices:
                if_name = str(raw.get("ifName", {}).get(idx, raw.get("ifDescr", {}).get(idx, f"if{idx}")))
                if_alias = str(raw.get("ifAlias", {}).get(idx, ""))
                oper_status = _OPER_STATUS.get(int(raw.get("ifOperStatus", {}).get(idx, 4)), "unknown")

                # Apply filters (walk mode only — targeted mode is pre-filtered)
                if not monitored:
                    if exclude_oper and oper_status in exclude_oper:
                        continue
                    if include_filter and not any(p in if_name for p in include_filter):
                        continue
                    if exclude_filter and any(p in if_name for p in exclude_filter):
                        continue

                metrics_mode = metrics_lookup.get(idx, "all")

                # Use HC counters if available, else fall back to 32-bit
                in_octets = int(raw.get("ifHCInOctets", {}).get(idx, raw.get("ifInOctets", {}).get(idx, 0)))
                out_octets = int(raw.get("ifHCOutOctets", {}).get(idx, raw.get("ifOutOctets", {}).get(idx, 0)))

                # Speed in Mbps (ifHighSpeed preferred over ifSpeed)
                high_speed = raw.get("ifHighSpeed", {}).get(idx)
                if high_speed and int(high_speed) > 0:
                    speed_mbps = int(high_speed)
                else:
                    speed_raw = raw.get("ifSpeed", {}).get(idx, 0)
                    speed_mbps = int(int(speed_raw) / 1_000_000) if speed_raw else 0

                admin_status = _ADMIN_STATUS.get(int(raw.get("ifAdminStatus", {}).get(idx, 3)), "unknown")

                row = {
                    "if_index": idx,
                    "if_name": if_name,
                    "if_alias": if_alias,
                    "if_speed_mbps": speed_mbps,
                    "if_admin_status": admin_status,
                    "if_oper_status": oper_status,
                    "in_octets": in_octets if _has_metric(metrics_mode, "traffic") else 0,
                    "out_octets": out_octets if _has_metric(metrics_mode, "traffic") else 0,
                    "in_errors": int(raw.get("ifInErrors", {}).get(idx, 0)) if _has_metric(metrics_mode, "errors") else 0,
                    "out_errors": int(raw.get("ifOutErrors", {}).get(idx, 0)) if _has_metric(metrics_mode, "errors") else 0,
                    "in_discards": int(raw.get("ifInDiscards", {}).get(idx, 0)) if _has_metric(metrics_mode, "discards") else 0,
                    "out_discards": int(raw.get("ifOutDiscards", {}).get(idx, 0)) if _has_metric(metrics_mode, "discards") else 0,
                    "in_unicast_pkts": int(raw.get("ifInUcastPkts", {}).get(idx, 0)) if metrics_mode == "all" else 0,
                    "out_unicast_pkts": int(raw.get("ifOutUcastPkts", {}).get(idx, 0)) if metrics_mode == "all" else 0,
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
                metrics=[],
                config_data=None,
                status="critical",
                reachable=False,
                error_message=f"{type(exc).__name__}: {exc}",
                execution_time_ms=execution_ms,
            )
'''

    # Each tuple: (name, description, source_code, entry_class, requirements, config_schema, target_table)
    # target_table defaults to "availability_latency" when omitted (6-element tuple)
    return [
        ("ping_check", "ICMP ping check", ping_check_code, "Poller", [], {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "title": "Packet Count", "default": 3, "minimum": 1, "maximum": 20},
                "timeout": {"type": "integer", "title": "Timeout (s)", "default": 2, "minimum": 1, "maximum": 30},
            },
        }),
        ("port_check", "TCP port check", port_check_code, "Poller", [], {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "title": "Port", "default": 443, "minimum": 1, "maximum": 65535},
            },
        }),
        ("snmp_check", "SNMP check (v1/v2c/v3)", snmp_check_code, "Poller", ["pysnmp>=6.0"], {
            "type": "object",
            "properties": {
                "snmp_credential": {"type": "string", "title": "SNMP Credential", "x-widget": "credential"},
                "oid": {"type": "string", "title": "OID", "default": "1.3.6.1.2.1.1.3.0", "x-widget": "snmp-oid"},
                "timeout": {"type": "integer", "title": "SNMP Timeout (s)", "default": 5, "minimum": 1, "maximum": 30},
            },
        }),
        ("snmp_interface_poller", "SNMP interface poller (ifTable/ifXTable)", snmp_interface_code, "Poller",
         ["pysnmp>=6.0"], {
            "type": "object",
            "properties": {
                "snmp_credential": {"type": "string", "title": "SNMP Credential", "x-widget": "credential"},
                "timeout": {"type": "integer", "title": "SNMP Timeout (s)", "default": 10, "minimum": 1, "maximum": 60},
                "include_interfaces": {
                    "type": "array", "title": "Include Interfaces (substring match)",
                    "items": {"type": "string"}, "default": [],
                },
                "exclude_interfaces": {
                    "type": "array", "title": "Exclude Interfaces (substring match)",
                    "items": {"type": "string"}, "default": [],
                },
                "exclude_oper_status": {
                    "type": "array", "title": "Exclude Oper Status",
                    "items": {"type": "string", "enum": ["down", "notPresent", "lowerLayerDown", "dormant"]},
                    "default": ["notPresent", "lowerLayerDown"],
                },
            },
        }, "interface"),
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    # Generate instance ID if not set
    if not settings.instance_id:
        settings.instance_id = str(uuid.uuid4())[:8]

    role = settings.role  # "api", "scheduler", or "all"
    logger.info(
        "central_starting",
        instance_id=settings.instance_id,
        role=role,
        host=settings.host,
        port=settings.port,
    )

    from sqlalchemy import select
    from monctl_central.storage.models import App, AppVersion, DeviceType, LabelKey, User

    factory = get_session_factory()

    # Seed defaults (only on api/all roles)
    if role in ("api", "all"):
        # Seed admin user
        if settings.admin_password:
            from monctl_central.auth.service import hash_password

            async with factory() as session:
                existing = (await session.execute(select(User).limit(1))).scalar_one_or_none()
                if existing is None:
                    admin = User(
                        username=settings.admin_username,
                        password_hash=hash_password(settings.admin_password),
                        role="admin",
                        display_name="Administrator",
                    )
                    session.add(admin)
                    await session.commit()
                    logger.info("admin_user_created", username=settings.admin_username)

        # Seed device types (name, description, category)
        _DEFAULT_DEVICE_TYPES = [
            ("host", "Generic server, VM, or physical machine", "server"),
            ("network", "Network device — router, switch, firewall, access point", "network"),
            ("api", "HTTP API endpoint or web service", "service"),
            ("database", "Database server — PostgreSQL, MySQL, Redis, etc.", "database"),
            ("service", "Application service or microservice", "service"),
            ("container", "Docker container or Kubernetes pod", "server"),
            ("virtual-machine", "Hypervisor-managed virtual machine", "server"),
            ("storage", "Storage array, NAS, or SAN device", "storage"),
            ("printer", "Printer or print server", "printer"),
            ("iot", "IoT or embedded device", "iot"),
        ]
        async with factory() as session:
            count = (await session.execute(select(DeviceType).limit(1))).scalar_one_or_none()
            if count is None:
                for name, description, category in _DEFAULT_DEVICE_TYPES:
                    session.add(DeviceType(name=name, description=description, category=category))
                await session.commit()
                logger.info("device_types_seeded", count=len(_DEFAULT_DEVICE_TYPES))

        # Seed default label keys
        async with factory() as session:
            existing_lk = (await session.execute(select(LabelKey).limit(1))).scalar_one_or_none()
            if existing_lk is None:
                default_label_keys = [
                    LabelKey(key="site", description="Lokation", show_description=True,
                             predefined_values=["aarhus", "copenhagen"]),
                    LabelKey(key="env", description="Miljø", show_description=True,
                             predefined_values=["production", "staging", "development", "test"]),
                    LabelKey(key="role", description="Rolle", show_description=True,
                             predefined_values=["web", "db", "cache", "proxy", "monitoring"]),
                    LabelKey(key="owner", description="Ansvarlig", show_description=True),
                    LabelKey(key="criticality", description="Kritikalitet", show_description=True,
                             predefined_values=["critical", "high", "medium", "low"]),
                ]
                session.add_all(default_label_keys)
                await session.commit()
                logger.info("label_keys_seeded", count=len(default_label_keys))

        # Seed default apps with source code
        _DEFAULT_APPS = _get_default_apps()
        async with factory() as session:
            for app_tuple in _DEFAULT_APPS:
                app_name, desc, source_code, entry_class, requirements, config_schema = app_tuple[:6]
                target_table = app_tuple[6] if len(app_tuple) > 6 else "availability_latency"
                existing_app = (
                    await session.execute(select(App).where(App.name == app_name))
                ).scalar_one_or_none()
                if existing_app is None:
                    app_obj = App(
                        name=app_name, description=desc, app_type="script",
                        config_schema=config_schema,
                        target_table=target_table,
                    )
                    session.add(app_obj)
                    await session.flush()
                    import hashlib as _hl
                    checksum = _hl.sha256(source_code.encode()).hexdigest()
                    session.add(AppVersion(
                        app_id=app_obj.id,
                        version="1.0.0",
                        checksum_sha256=checksum,
                        source_code=source_code,
                        entry_class=entry_class,
                        requirements=requirements,
                    ))
                else:
                    # Always sync config_schema from seed definition
                    if config_schema and existing_app.config_schema != config_schema:
                        existing_app.config_schema = config_schema
                    # Always sync target_table from seed definition
                    if existing_app.target_table != target_table:
                        existing_app.target_table = target_table
                    # Always sync source_code, entry_class, requirements for built-in apps
                    from sqlalchemy.orm import selectinload
                    stmt = select(App).options(selectinload(App.versions)).where(App.name == app_name)
                    app_row = (await session.execute(stmt)).scalar_one_or_none()
                    if app_row and app_row.versions:
                        import hashlib as _hl
                        v = app_row.versions[0]
                        new_checksum = _hl.sha256(source_code.encode()).hexdigest()
                        if v.checksum_sha256 != new_checksum:
                            v.source_code = source_code
                            v.entry_class = entry_class
                            v.requirements = requirements
                            v.checksum_sha256 = new_checksum
            await session.commit()
            logger.info("default_apps_seeded")

    # ── Seed default RBAC roles ────────────────────────────────────────────
    from monctl_central.storage.models import Role, RolePermission

    async with factory() as session:
        existing_role = (await session.execute(select(Role).limit(1))).scalar_one_or_none()
        if existing_role is None:
            viewer = Role(name="Viewer", description="Read-only access to all resources", is_system=True)
            session.add(viewer)
            await session.flush()
            for res in ["device", "app", "assignment", "credential", "alert", "collector",
                        "tenant", "user", "template", "settings", "result"]:
                session.add(RolePermission(role_id=viewer.id, resource=res, action="view"))

            operator = Role(
                name="Operator",
                description="Can view and edit devices, apps, and assignments",
                is_system=True,
            )
            session.add(operator)
            await session.flush()
            for res, act in [
                ("device", "view"), ("device", "create"), ("device", "edit"),
                ("app", "view"), ("app", "create"), ("app", "edit"),
                ("assignment", "view"), ("assignment", "create"), ("assignment", "edit"),
                ("credential", "view"),
                ("alert", "view"), ("alert", "create"), ("alert", "edit"),
                ("collector", "view"),
                ("template", "view"), ("template", "create"), ("template", "edit"),
                ("result", "view"),
            ]:
                session.add(RolePermission(role_id=operator.id, resource=res, action=act))

            await session.commit()
            logger.info("default_roles_seeded")

    # ── ClickHouse schema init ─────────────────────────────────────────────
    from monctl_central.dependencies import get_clickhouse

    ch = None
    try:
        ch = get_clickhouse()
        ch.ensure_tables()
        logger.info("clickhouse_tables_ensured")
    except Exception:
        logger.warning("clickhouse_init_failed", exc_info=True)

    # ── Redis connection ───────────────────────────────────────────────────
    from monctl_central.cache import get_redis

    try:
        await get_redis(settings.redis_url)
        logger.info("redis_connected")
    except Exception:
        logger.warning("redis_connect_failed", exc_info=True)

    # ── Scheduler with leader election (health monitor + alert engine) ─────
    leader = None
    scheduler_runner = None
    if role in ("scheduler", "all"):
        try:
            from monctl_central.cache import _redis
            from monctl_central.scheduler.leader import LeaderElection
            from monctl_central.scheduler.tasks import SchedulerRunner

            if _redis is not None:
                leader = LeaderElection(_redis, settings.instance_id)
                await leader.start()
                scheduler_runner = SchedulerRunner(
                    leader=leader,
                    session_factory=factory,
                    clickhouse_client=ch,
                )
                await scheduler_runner.start()
                logger.info("scheduler_started", instance_id=settings.instance_id)
            else:
                logger.warning("scheduler_skipped_no_redis")
        except Exception:
            logger.warning("scheduler_start_failed", exc_info=True)

    yield

    # Shutdown
    if scheduler_runner:
        await scheduler_runner.stop()
    if leader:
        await leader.stop()

    from monctl_central.cache import close_redis
    await close_redis()

    if ch:
        ch.close()

    engine = get_engine()
    await engine.dispose()
    logger.info("central_stopped", instance_id=settings.instance_id)


_DESCRIPTION = """
MonCTL is a distributed monitoring platform. Collectors run monitoring apps and push
results to this central server, which stores them and exposes query and management APIs.

## Authentication

**Web UI**: Login at `/` with username and password.

**API**: All endpoints except `/v1/health` require a Bearer token in the `Authorization` header:

```
Authorization: Bearer monctl_m_<key>   \u2190 management operations
Authorization: Bearer monctl_c_<key>   \u2190 collector communication
```

Management keys are created via the database seed script or the admin CLI.
Collector keys are issued automatically during collector registration.

## Quick start

1. **Register devices** \u2014 `POST /v1/devices`
2. **Create credentials** (if needed) \u2014 `POST /v1/credentials`
3. **Assign an app to a collector** \u2014 `POST /v1/apps/assignments` (link `device_id` for auto host injection)
4. **Query results** \u2014 `GET /v1/results/by-device/{device_id}` for per-device status

## Credential references in app config

Use `"$credential:name"` in any assignment config value. Central resolves it to the
decrypted secret before sending config to the collector:

```json
{"host": "192.168.1.1", "community": "$credential:snmp-prod"}
```
"""

_TAGS = [
    {"name": "system",      "description": "Health check and system status. No auth required for `/v1/health`."},
    {"name": "auth",        "description": "User authentication for the web UI (login, logout, token refresh)."},
    {"name": "collectors",  "description": "Collector registration, heartbeat, and config snapshot delivery."},
    {"name": "ingestion",   "description": "Data ingestion endpoint used by collectors to push check results and events."},
    {"name": "devices",     "description": "Device inventory \u2014 the things you want to monitor (servers, routers, APIs, etc.)."},
    {"name": "apps",        "description": "Monitoring apps, versions, and assignments (which app runs on which collector/device)."},
    {"name": "credentials", "description": "Encrypted credential storage. Secrets are AES-256-GCM encrypted at rest and never returned by the API."},
    {"name": "results",     "description": "Query check results. Use `/v1/results/by-device/{id}` for a per-device status dashboard."},
    {"name": "alerting",    "description": "Alert rules and active alerts."},
]

app = FastAPI(
    title="MonCTL Central",
    description=_DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=_TAGS,
    contact={"name": "MonCTL", "url": "https://github.com/your-org/monctl"},
    license_info={"name": "MIT"},
)


@app.get("/v1/health", tags=["system"])
async def health_check():
    """Health check endpoint (no authentication required)."""
    return {"status": "healthy", "version": "0.1.0", "instance_id": settings.instance_id}


@app.get("/v1/status", tags=["system"])
async def system_status():
    """System status overview (requires authentication)."""
    return {
        "status": "success",
        "data": {
            "version": "0.1.0",
            "instance_id": settings.instance_id,
        },
    }


# Import and mount API routers
from monctl_central.api.router import api_router  # noqa: E402
app.include_router(api_router, prefix="/v1")

# Collector API — job-pull model (new distributed collector system)
from monctl_central.collector_api.router import router as collector_api_router  # noqa: E402
app.include_router(collector_api_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Serve the frontend SPA (built React app)
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(os.environ.get("MONCTL_STATIC_DIR", "/app/static"))

if _STATIC_DIR.exists() and (_STATIC_DIR / "index.html").exists():
    # Serve Vite-built assets (JS, CSS, images)
    _assets_dir = _STATIC_DIR / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """SPA fallback: serve static files or index.html for client-side routing."""
        file_path = _STATIC_DIR / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_STATIC_DIR / "index.html"))
