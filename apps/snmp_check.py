#!/usr/bin/env python3
"""SNMP monitoring app — checks reachability via SNMP GET and measures response time.

Supports SNMP v1, v2c, and v3. The version and authentication parameters are driven
entirely by the resolved credential fields injected into the config by central before
this script is executed.

Protocol:
  stdin:  JSON config (see Config keys below)
  stdout: JSON result with check_result (including performance_data) and metrics
  exit:   0=OK, 2=CRITICAL

Config keys (device address is injected as "host" when a device is linked):
  host           str  Target IP or hostname (default: "localhost")
  oid            str  OID to poll (default: "1.3.6.1.2.1.1.3.0" — sysUpTime)
  timeout        int  SNMP timeout in seconds (default: 5)

  -- v1 / v2c (injected from credential) --
  version        str  "1" or "2c" (default when no version field: "2c")
  community      str  Community string (default: "public")

  -- v3 (injected from credential) --
  version        str  "3"
  username       str  USM username
  auth_protocol  str  "MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512", or "" (no auth)
  auth_password  str  Auth passphrase (omit or empty string for no auth)
  priv_protocol  str  "DES", "3DES", "AES", "AES192", "AES256", or "" (no privacy)
  priv_password  str  Privacy passphrase (omit or empty string for no privacy)

Performance data (always present in check_result.performance_data):
  rtt_ms     SNMP response time in milliseconds (0 if unreachable)
  reachable  1.0 if SNMP responded successfully, 0.0 if not
"""
from __future__ import annotations

import asyncio
import json
import sys
import time


def _build_v1v2c_auth(community: str, version: str):
    from pysnmp.hlapi.asyncio import CommunityData
    # mpModel: 0 = SNMPv1, 1 = SNMPv2c
    mp_model = 0 if version == "1" else 1
    return CommunityData(community, mpModel=mp_model)


def _build_v3_auth(config: dict):
    from pysnmp.hlapi.asyncio import UsmUserData
    import pysnmp.hlapi.asyncio as hlapi

    username = config.get("username", "")
    auth_proto_name = (config.get("auth_protocol") or "").upper()
    auth_key = config.get("auth_password") or config.get("auth_key") or ""
    priv_proto_name = (config.get("priv_protocol") or "").upper()
    priv_key = config.get("priv_password") or config.get("priv_key") or ""

    # Map protocol names to pysnmp constants
    _auth_map = {
        "": None,
        "MD5":    "usmHMACMD5AuthProtocol",
        "SHA":    "usmHMACSHAAuthProtocol",
        "SHA224": "usmHMAC128SHA224AuthProtocol",
        "SHA256": "usmHMAC192SHA256AuthProtocol",
        "SHA384": "usmHMAC256SHA384AuthProtocol",
        "SHA512": "usmHMAC384SHA512AuthProtocol",
    }
    _priv_map = {
        "": None,
        "DES":    "usmDESPrivProtocol",
        "3DES":   "usm3DESEDEPrivProtocol",
        "AES":    "usmAesCfb128Protocol",
        "AES192": "usmAesCfb192Protocol",
        "AES256": "usmAesCfb256Protocol",
    }

    auth_proto = None
    if auth_proto_name and auth_proto_name in _auth_map and _auth_map[auth_proto_name]:
        auth_proto = getattr(hlapi, _auth_map[auth_proto_name], None)

    priv_proto = None
    if priv_proto_name and priv_proto_name in _priv_map and _priv_map[priv_proto_name]:
        priv_proto = getattr(hlapi, _priv_map[priv_proto_name], None)

    kwargs: dict = {"userName": username}
    if auth_proto and auth_key:
        kwargs["authKey"] = auth_key
        kwargs["authProtocol"] = auth_proto
    if priv_proto and priv_key and auth_proto:
        kwargs["privKey"] = priv_key
        kwargs["privProtocol"] = priv_proto

    return UsmUserData(**kwargs)


async def _snmp_get_async(
    host: str,
    oid: str,
    config: dict,
    timeout: int,
) -> tuple[bool, float | None, str | None, str]:
    from pysnmp.hlapi.asyncio import (
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        getCmd,
    )

    version = str(config.get("version", "2c")).lower()

    if version == "3":
        auth_data = _build_v3_auth(config)
    else:
        community = config.get("community", "public")
        auth_data = _build_v1v2c_auth(community, version)

    start = time.monotonic()
    error_indication, error_status, error_index, var_binds = await getCmd(
        SnmpEngine(),
        auth_data,
        UdpTransportTarget((host, int(config.get("snmp_port", 161))), timeout=timeout, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    rtt_ms = (time.monotonic() - start) * 1000

    if error_indication:
        return False, None, None, str(error_indication)
    if error_status:
        return False, None, None, f"SNMP error: {error_status.prettyPrint()} at {error_index}"

    value = var_binds[0][1].prettyPrint() if var_binds else "(no value)"
    return True, rtt_ms, value, f"OID {oid} = {value}"


def snmp_get(
    host: str,
    oid: str,
    config: dict,
    timeout: int,
) -> tuple[bool, float | None, str | None, str]:
    """Perform an SNMP GET and return (success, rtt_ms, value, detail).

    Returns:
        (True, rtt_ms, oid_value, description) on success
        (False, None, None, error_msg) on failure
    """
    try:
        return asyncio.run(_snmp_get_async(host, oid, config, timeout))
    except ImportError:
        return False, None, None, "pysnmp not installed on this collector"
    except Exception as exc:
        return False, None, None, f"SNMP error: {exc}"


def main() -> None:
    raw = sys.stdin.read().strip()
    config: dict = json.loads(raw) if raw else {}

    host: str = config.get("host", "localhost")
    oid: str = config.get("oid", "1.3.6.1.2.1.1.3.0")
    timeout: int = int(config.get("timeout", 5))

    success, rtt_ms, value, detail = snmp_get(host, oid, config, timeout)

    if success:
        state = 0  # OK
        rtt_display = f"{rtt_ms:.3f}ms" if rtt_ms is not None else "unknown RTT"
        output = f"SNMP OK — {host} responded, {detail}, RTT {rtt_display}"
        performance_data = {
            "rtt_ms": rtt_ms if rtt_ms is not None else 0.0,
            "reachable": 1.0,
        }
        metrics = [
            {"name": "snmp_reachable", "value": 1.0, "labels": {"host": host, "oid": oid}},
        ]
        if rtt_ms is not None:
            metrics.append({
                "name": "snmp_rtt_ms",
                "value": rtt_ms,
                "labels": {"host": host, "oid": oid},
                "unit": "ms",
            })
    else:
        state = 2  # CRITICAL
        output = f"SNMP CRITICAL — {host} unreachable: {detail}"
        performance_data = {
            "rtt_ms": 0.0,
            "reachable": 0.0,
        }
        metrics = [
            {"name": "snmp_reachable", "value": 0.0, "labels": {"host": host, "oid": oid}},
        ]

    result = {
        "check_result": {
            "state": state,
            "output": output,
            "performance_data": performance_data,
        },
        "metrics": metrics,
    }

    print(json.dumps(result))
    sys.exit(state)


if __name__ == "__main__":
    main()
