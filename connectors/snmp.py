"""Built-in SNMP connector for MonCTL.

Supports SNMP v1, v2c, and v3 via pysnmp 7.x async API.

v1.4.4: Accept BOTH `snmp_version` and `version` credential-template keys
        when selecting the SNMP version. The SNMP credential template in
        prod supplies `version`, not `snmp_version`; v1.4.1 (seed-only)
        dropped the `version` fallback, so after v1.4.2 forced a fresh
        fetch of that seed source onto the collectors (superseding a
        previously-cached real-v1.4.1 that still had the fallback), every
        SNMPv3 device started getting plain SNMPv2c with community
        "public" and silently timing out. Re-add the fallback so the
        existing credential template continues to work.
v1.4.3: Fix venv-hash regression caused by v1.4.2's requirements shape.
        v1.4.2 uploaded requirements as {"pysnmp": ">=7.1"}; the collector's
        _venv_hash/_validate_requirements iterate the dict as a sequence, so
        it saw just "pysnmp" (no version pin) and built a fresh venv with
        the latest pysnmp — breaking every SNMP poll fleet-wide. v1.4.3
        carries the same source but encodes requirements so sorted(dict)
        yields the full requirement string as a key, matching v1.4.1's venv
        hash and reusing the already-installed pysnmp 7.x venv.
v1.4.2: Add walk_multi(oids) — one correlated GETBULK stream across multiple
        base OIDs with maxRepetitions=25. Yields up to 25*K row values per
        request instead of 25 per request-per-column, cutting round-trips
        ~K× on tables with K correlated columns (ENTITY-MIB, CISCO-ENVMON-MIB,
        IF-MIB ifXTable). Each column advances its own cursor and drops when
        its cursor falls out of its base subtree or stops advancing.
v1.3.0: Fix UDP socket leak — reuse SnmpEngine + UdpTransportTarget across
        all operations within a single connect/close lifecycle instead of
        creating new ones per get/walk call.

Credential keys (v1/v2c):
    snmp_version   "1" or "2c" (default "2c")
    community      Community string (default "public")

Credential keys (v3):
    snmp_version    "3"
    username        USM username
    auth_protocol   "MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512", or ""
    auth_password   Auth passphrase
    priv_protocol   "DES", "3DES", "AES", "AES192", "AES256", or ""
    priv_password   Privacy passphrase
    security_level  "noauthnopriv", "authnopriv", or "authpriv" (default "authpriv")

Settings keys:
    port      SNMP port (default 161)
    timeout   Timeout in seconds (default 5)
    retries   Retry count (default 2)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_AUTH_PROTOCOLS = {
    "MD5": "usmHMACMD5AuthProtocol",
    "SHA": "usmHMACSHAAuthProtocol",
    "SHA224": "usmHMAC128SHA224AuthProtocol",
    "SHA256": "usmHMAC192SHA256AuthProtocol",
    "SHA384": "usmHMAC256SHA384AuthProtocol",
    "SHA512": "usmHMAC384SHA512AuthProtocol",
}

_PRIV_PROTOCOLS = {
    "DES": "usmDESPrivProtocol",
    "3DES": "usm3DESEDEPrivProtocol",
    "AES": "usmAesCfb128Protocol",
    "AES192": "usmAesCfb192Protocol",
    "AES256": "usmAesCfb256Protocol",
}


class SnmpConnector:
    """SNMP v1/v2c/v3 connector that polls OIDs from a target device."""

    def __init__(self, settings: dict[str, Any], credential: dict[str, Any] | None = None):
        self.settings = settings
        self.credential = credential or {}
        # Accept both `snmp_version` and legacy `version` credential keys —
        # the prod SNMP credential template supplies `version`.
        raw_version = self.credential.get("snmp_version")
        if raw_version is None:
            raw_version = self.credential.get("version", "2c")
        self.version = str(raw_version).lower()
        self.port = int(self.settings.get("port", 161))
        self.timeout = int(self.settings.get("timeout", 5))
        self.retries = int(self.settings.get("retries", 2))
        self._host: str = ""
        self._engine = None
        self._transport = None
        self._auth = None

    def _build_auth(self):
        """Build the appropriate pysnmp auth object for the configured version."""
        if self.version == "3":
            return self._build_v3_auth()
        return self._build_v1v2c_auth()

    def _build_v1v2c_auth(self):
        from pysnmp.hlapi.v3arch.asyncio import CommunityData
        community = self.credential.get("community", "public")
        mp_model = 0 if self.version == "1" else 1
        return CommunityData(community, mpModel=mp_model)

    def _build_v3_auth(self):
        from pysnmp.hlapi.v3arch.asyncio import UsmUserData
        import pysnmp.hlapi.v3arch.asyncio as hlapi

        username = self.credential.get("username", "")
        auth_proto_name = (self.credential.get("auth_protocol") or "").upper()
        auth_key = self.credential.get("auth_password", "")
        priv_proto_name = (self.credential.get("priv_protocol") or "").upper()
        priv_key = self.credential.get("priv_password", "")
        security_level = (self.credential.get("security_level") or "authpriv").lower()

        auth_proto = None
        if auth_proto_name in _AUTH_PROTOCOLS:
            auth_proto = getattr(hlapi, _AUTH_PROTOCOLS[auth_proto_name], None)

        priv_proto = None
        if priv_proto_name in _PRIV_PROTOCOLS:
            priv_proto = getattr(hlapi, _PRIV_PROTOCOLS[priv_proto_name], None)

        kwargs: dict[str, Any] = {"userName": username}

        if security_level == "noauthnopriv":
            return UsmUserData(**kwargs)

        if auth_proto and auth_key:
            kwargs["authKey"] = auth_key
            kwargs["authProtocol"] = auth_proto

        if security_level == "authpriv" and priv_proto and priv_key and auth_proto:
            kwargs["privKey"] = priv_key
            kwargs["privProtocol"] = priv_proto

        return UsmUserData(**kwargs)

    async def connect(self, host: str) -> None:
        """Create SNMP engine + transport — reused for all operations until close()."""
        # Idempotent: if already connected to same host, reuse. If different host
        # or called again (e.g. by apps that predate engine-managed lifecycle),
        # close the previous engine first to prevent memory leaks.
        if self._engine is not None:
            if self._host == host:
                return  # Already connected to this host
            await self.close()
        from pysnmp.hlapi.v3arch.asyncio import SnmpEngine, UdpTransportTarget
        self._host = host
        self._engine = SnmpEngine()
        self._transport = await UdpTransportTarget.create(
            (host, self.port), timeout=self.timeout, retries=self.retries,
        )
        self._auth = self._build_auth()
        logger.debug("snmp_connect host=%s port=%s version=%s", host, self.port, self.version)

    async def get(self, oids: list[str]) -> dict[str, Any]:
        """Perform SNMP GET for a list of OID strings."""
        from pysnmp.hlapi.v3arch.asyncio import (
            ContextData, ObjectIdentity, ObjectType, get_cmd,
        )
        obj_types = [ObjectType(ObjectIdentity(oid)) for oid in oids]
        error_indication, error_status, error_index, var_binds = await get_cmd(
            self._engine, self._auth, self._transport, ContextData(), *obj_types,
        )
        if error_indication:
            raise RuntimeError(f"SNMP error: {error_indication}")
        if error_status:
            raise RuntimeError(f"SNMP error at {error_index}: {error_status.prettyPrint()}")
        result: dict[str, Any] = {}
        for oid_val, val in var_binds:
            result[str(oid_val)] = val.prettyPrint()
        return result

    async def get_many(self, oid_batches: list[list[str]]) -> dict[str, Any]:
        """Execute multiple SNMP GET batches reusing the same session."""
        from pysnmp.hlapi.v3arch.asyncio import (
            ContextData, ObjectIdentity, ObjectType, get_cmd,
        )
        result: dict[str, Any] = {}
        for batch in oid_batches:
            try:
                obj_types = [ObjectType(ObjectIdentity(oid)) for oid in batch]
                err_ind, err_st, err_idx, var_binds = await get_cmd(
                    self._engine, self._auth, self._transport, ContextData(), *obj_types,
                )
                if not err_ind and not err_st:
                    for oid_val, val in var_binds:
                        result[str(oid_val)] = val.prettyPrint()
            except Exception:
                continue
        return result

    async def walk(self, oid: str) -> list[tuple[str, Any]]:
        """Perform SNMP WALK (GETBULK) with numeric OID boundary checking."""
        from pysnmp.hlapi.v3arch.asyncio import (
            ContextData, ObjectIdentity, ObjectType, bulk_cmd,
        )
        rows: list[tuple[str, Any]] = []
        current_oid = oid
        base_tuple = tuple(int(x) for x in oid.split("."))
        base_len = len(base_tuple)

        while len(rows) < 10000:
            error_indication, error_status, error_index, var_bind_table = await bulk_cmd(
                self._engine, self._auth, self._transport, ContextData(), 0, 25,
                ObjectType(ObjectIdentity(current_oid)),
            )
            if error_indication or error_status:
                break
            if not var_bind_table:
                break
            out_of_tree = False
            last_oid = None
            for name, val in var_bind_table:
                oid_tuple = tuple(name)
                if oid_tuple[:base_len] != base_tuple:
                    out_of_tree = True
                    break
                name_str = str(name)
                rows.append((name_str, val.prettyPrint()))
                last_oid = name_str
            if out_of_tree or last_oid is None or last_oid == current_oid:
                break
            current_oid = last_oid
        return rows

    async def walk_multi(self, oids: list[str]) -> dict[str, list[tuple[str, Any]]]:
        """Walk multiple base OID subtrees in one correlated GETBULK stream.

        Each iteration sends one GETBULK PDU carrying every still-active
        column as a repeater (nonRepeaters=0, maxRepetitions=25). pysnmp
        returns varBindTable as a flat sequence in wire order: for index
        ``i`` the column is ``i % K`` (K = number of active repeaters that
        round), groups lock-stepped across columns. Each column advances
        its own cursor and drops when its varbind falls out of the base
        subtree or stops advancing. Result is keyed by the input base OID
        strings and carries the same ``list[(oid_str, value_str)]`` shape
        as single-column :meth:`walk`.
        """
        from pysnmp.hlapi.v3arch.asyncio import (
            ContextData, ObjectIdentity, ObjectType, bulk_cmd,
        )
        if not oids:
            return {}

        result: dict[str, list[tuple[str, Any]]] = {base: [] for base in oids}
        base_tuples: dict[str, tuple[int, ...]] = {
            base: tuple(int(x) for x in base.split(".")) for base in oids
        }
        cursors: dict[str, str] = {base: base for base in oids}
        active: list[str] = list(oids)

        total_rows = 0
        for _ in range(500):  # safety cap
            if not active:
                break
            obj_types = [ObjectType(ObjectIdentity(cursors[b])) for b in active]
            err_ind, err_st, _err_idx, var_bind_table = await bulk_cmd(
                self._engine, self._auth, self._transport, ContextData(),
                0, 25, *obj_types,
            )
            if err_ind or err_st or not var_bind_table:
                break

            k = len(active)
            last_cursors: dict[str, str] = {b: cursors[b] for b in active}
            dropped: set[str] = set()

            for i, (name, val) in enumerate(var_bind_table):
                base = active[i % k]
                if base in dropped:
                    continue
                oid_tuple = tuple(name)
                base_tuple = base_tuples[base]
                if oid_tuple[:len(base_tuple)] != base_tuple:
                    dropped.add(base)
                    continue
                name_str = str(name)
                result[base].append((name_str, val.prettyPrint()))
                last_cursors[base] = name_str
                total_rows += 1

            next_active: list[str] = []
            for b in active:
                if b in dropped:
                    continue
                if last_cursors[b] == cursors[b]:
                    continue
                cursors[b] = last_cursors[b]
                next_active.append(b)
            active = next_active

            if total_rows >= 20000:
                break

        return result

    async def close(self) -> None:
        """Close SNMP engine and release all internal pysnmp state."""
        if self._engine is not None:
            try:
                self._engine.close_dispatcher()
            except Exception:
                pass
            # Clear internal MIB/security registrations that accumulate
            try:
                mib = self._engine.get_mib_builder()
                mib.clean()
            except Exception:
                pass
            self._engine = None
        self._transport = None
        self._auth = None
