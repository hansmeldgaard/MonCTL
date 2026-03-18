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


class _InlineSnmpClient:
    """Fallback SNMP client when no connector is bound.

    Runs pysnmp in a dedicated asyncio event loop inside a thread to avoid
    pysnmp 7.x transport hanging the main event loop. Each operation is
    fully isolated and times out reliably.
    """

    def __init__(self, host: str, credential: dict):
        self._host = host
        self._cred = credential
        self._timeout = int(credential.get("timeout", 10))
        self._port = int(credential.get("port", 161))

    def _build_auth(self):
        from pysnmp.hlapi.asyncio import CommunityData, UsmUserData
        import pysnmp.hlapi.asyncio as hlapi

        version = str(self._cred.get("version", self._cred.get("snmp_version", "2c"))).lower()
        if version != "3":
            community = self._cred.get("community", "public")
            return CommunityData(community, mpModel=0 if version == "1" else 1)

        username = self._cred.get("username", "")
        security_level = self._cred.get("security_level", "authPriv").lower()
        _AUTH = {"MD5": "usmHMACMD5AuthProtocol", "SHA": "usmHMACSHAAuthProtocol",
                 "SHA224": "usmHMAC128SHA224AuthProtocol", "SHA256": "usmHMAC192SHA256AuthProtocol",
                 "SHA384": "usmHMAC256SHA384AuthProtocol", "SHA512": "usmHMAC384SHA512AuthProtocol"}
        _PRIV = {"DES": "usmDESPrivProtocol", "3DES": "usm3DESEDEPrivProtocol",
                 "AES": "usmAesCfb128Protocol", "AES128": "usmAesCfb128Protocol",
                 "AES192": "usmAesCfb192Protocol", "AES256": "usmAesCfb256Protocol"}

        kwargs = {"userName": username}
        if security_level == "noauthnopriv":
            return UsmUserData(**kwargs)

        auth_name = (self._cred.get("auth_protocol") or "").upper()
        auth_key = self._cred.get("auth_password") or self._cred.get("auth_key") or ""
        auth_proto = getattr(hlapi, _AUTH.get(auth_name, ""), None) if auth_name else None
        if auth_proto and auth_key:
            kwargs["authKey"] = auth_key
            kwargs["authProtocol"] = auth_proto

        if security_level == "authpriv":
            priv_name = (self._cred.get("priv_protocol") or "").upper()
            priv_key = self._cred.get("priv_password") or self._cred.get("priv_key") or ""
            priv_proto = getattr(hlapi, _PRIV.get(priv_name, ""), None) if priv_name else None
            if priv_proto and priv_key:
                kwargs["privKey"] = priv_key
                kwargs["privProtocol"] = priv_proto

        return UsmUserData(**kwargs)

    def _run_in_thread(self, coro_fn):
        """Run an async function in a NEW event loop in a thread.

        This isolates pysnmp's transport from the main event loop so that
        timeouts and cancellation work reliably.
        """
        import asyncio
        import concurrent.futures

        def _thread_target():
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro_fn())
            finally:
                loop.close()

        return _thread_target

    async def get(self, oids: list[str]) -> dict:
        import asyncio

        async def _do_get():
            from pysnmp.hlapi.asyncio import (
                ContextData, ObjectIdentity, ObjectType, SnmpEngine,
                UdpTransportTarget, get_cmd,
            )
            engine = SnmpEngine()
            transport = await UdpTransportTarget.create(
                (self._host, self._port), timeout=self._timeout, retries=1,
            )
            auth = self._build_auth()
            obj_types = [ObjectType(ObjectIdentity(oid)) for oid in oids]
            err_ind, err_st, err_idx, var_binds = await get_cmd(
                engine, auth, transport, ContextData(), *obj_types,
            )
            engine.close_dispatcher()
            if err_ind:
                raise RuntimeError(f"SNMP error: {err_ind}")
            if err_st:
                raise RuntimeError(f"SNMP error at {err_idx}: {err_st.prettyPrint()}")
            result = {}
            for oid, val in var_binds:
                result[str(oid)] = val.prettyPrint()
            return result

        return await asyncio.wait_for(
            asyncio.to_thread(self._run_in_thread(_do_get)),
            timeout=self._timeout + 10,
        )

    async def walk(self, oid: str) -> list[tuple[str, str]]:
        import asyncio

        async def _do_walk():
            from pysnmp.hlapi.asyncio import (
                ContextData, ObjectIdentity, ObjectType, SnmpEngine,
                UdpTransportTarget, bulk_cmd,
            )
            engine = SnmpEngine()
            transport = await UdpTransportTarget.create(
                (self._host, self._port), timeout=self._timeout, retries=1,
            )
            auth = self._build_auth()
            rows = []
            current_oid = oid
            base_tuple = tuple(int(x) for x in oid.split("."))
            base_len = len(base_tuple)
            while len(rows) < 500:
                err_ind, err_st, err_idx, var_binds = await bulk_cmd(
                    engine, auth, transport, ContextData(), 0, 25,
                    ObjectType(ObjectIdentity(current_oid)),
                )
                if err_ind or err_st:
                    break
                if not var_binds:
                    break
                out_of_tree = False
                last_oid = None
                for row in var_binds:
                    for name, val in row:
                        oid_tuple = tuple(name)
                        if oid_tuple[:base_len] != base_tuple:
                            out_of_tree = True
                            break
                        name_str = str(name)
                        rows.append((name_str, val.prettyPrint()))
                        last_oid = name_str
                    if out_of_tree:
                        break
                if out_of_tree or last_oid is None or last_oid == current_oid:
                    break
                current_oid = last_oid
            engine.close_dispatcher()
            return rows

        return await asyncio.wait_for(
            asyncio.to_thread(self._run_in_thread(_do_walk)),
            timeout=self._timeout * 3 + 10,
        )

    async def close(self):
        pass


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
            # Fallback: create an inline SNMP client from credential
            snmp = _InlineSnmpClient(host, context.credential)

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
                for i in range(0, len(oid_requests), batch_size):
                    batch = oid_requests[i:i + batch_size]
                    try:
                        result = await snmp.get([oid for _, _, oid in batch])
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
                oper_status = _OPER_STATUS.get(int(raw.get("ifOperStatus", {}).get(idx, 4)), "unknown")

                if not monitored:
                    if exclude_oper and oper_status in exclude_oper:
                        continue
                    if include_filter and not any(p in if_name for p in include_filter):
                        continue
                    if exclude_filter and any(p in if_name for p in exclude_filter):
                        continue

                metrics_mode = metrics_lookup.get(idx, "all")

                in_octets = int(raw.get("ifHCInOctets", {}).get(idx, raw.get("ifInOctets", {}).get(idx, 0)))
                out_octets = int(raw.get("ifHCOutOctets", {}).get(idx, raw.get("ifOutOctets", {}).get(idx, 0)))

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
                metrics=[], config_data=None,
                status="critical", reachable=False,
                error_message=f"{type(exc).__name__}: {exc}",
                execution_time_ms=execution_ms,
            )
