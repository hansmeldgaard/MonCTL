"""SNMP simulator — lightweight UDP responder for multiple virtual devices.

Each device listens on its own UDP port. Handles SNMPv2c GET, GETNEXT, and
GETBULK requests using pysnmp's ASN.1 codec for packet encoding/decoding.

Compatible with both pysnmp 6.x (camelCase) and pysnmp 7.x (snake_case).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from pysnmp.proto import api as snmp_api
from pysnmp.proto.api import v2c
from pyasn1.codec.ber import decoder as ber_decoder
from pyasn1.codec.ber import encoder as ber_encoder
from pyasn1.type import univ

from simulator.config import DeviceProfile, FailureMode, SimulatorConfig
from simulator.snmp_oid_tree import OidTree

logger = logging.getLogger(__name__)

# pysnmp 7.x uses snake_case, 6.x uses camelCase — detect and alias
_api_msg = v2c.apiMessage
_api_pdu = v2c.apiPDU
_api_bulk = v2c.apiBulkPDU

_get_pdu = getattr(_api_msg, "get_pdu", None) or getattr(_api_msg, "getPDU")
_set_pdu = getattr(_api_msg, "set_pdu", None) or getattr(_api_msg, "setPDU")
_get_community = getattr(_api_msg, "get_community", None) or getattr(_api_msg, "getCommunity")
_set_community = getattr(_api_msg, "set_community", None) or getattr(_api_msg, "setCommunity")
_set_msg_defaults = getattr(_api_msg, "set_defaults", None) or getattr(_api_msg, "setDefaults")

_get_varbinds = getattr(_api_pdu, "get_varbinds", None) or getattr(_api_pdu, "getVarBinds")
_set_varbinds = getattr(_api_pdu, "set_varbinds", None) or getattr(_api_pdu, "setVarBinds")
_get_request_id = getattr(_api_pdu, "get_request_id", None) or getattr(_api_pdu, "getRequestID")
_set_request_id = getattr(_api_pdu, "set_request_id", None) or getattr(_api_pdu, "setRequestID")
_set_error_status = getattr(_api_pdu, "set_error_status", None) or getattr(_api_pdu, "setErrorStatus")
_set_error_index = getattr(_api_pdu, "set_error_index", None) or getattr(_api_pdu, "setErrorIndex")
_set_pdu_defaults = getattr(_api_pdu, "set_defaults", None) or getattr(_api_pdu, "setDefaults")

_get_non_repeaters = getattr(_api_bulk, "get_non_repeaters", None) or getattr(_api_bulk, "getNonRepeaters")
_get_max_reps = getattr(_api_bulk, "get_max_repetitions", None) or getattr(_api_bulk, "getMaxRepetitions")


def _python_to_asn1(value: Any, oid_str: str = "") -> univ.OctetString:
    """Convert a Python value to an appropriate ASN.1 type for SNMP response."""
    if isinstance(value, int):
        # Use Counter64 for HC counters (ifHCInOctets, ifHCOutOctets)
        if "31.1.1.1.6." in oid_str or "31.1.1.1.10." in oid_str:
            return v2c.Counter64(value)
        # Use Counter32 for 32-bit counters (ifInOctets, ifOutOctets, etc.)
        if "2.2.1.10." in oid_str or "2.2.1.16." in oid_str:
            return v2c.Counter32(value % (2**32))
        # Use TimeTicks for sysUpTime
        if oid_str == "1.3.6.1.2.1.1.3.0":
            return v2c.TimeTicks(value)
        # Use Gauge32 for ifSpeed, ifHighSpeed
        if "2.2.1.5." in oid_str or "31.1.1.1.15." in oid_str:
            return v2c.Gauge32(value)
        if value > 2**31 - 1:
            return v2c.Counter64(value)
        if value >= 0:
            return v2c.Integer(value)
        return v2c.Integer(value)
    if isinstance(value, str):
        # Check if it looks like an OID (for sysObjectID)
        if value and all(c.isdigit() or c == "." for c in value) and "." in value:
            return v2c.ObjectIdentifier(value)
        return v2c.OctetString(value.encode())
    return v2c.OctetString(str(value).encode())


class SnmpDeviceHandler:
    """Handles SNMP requests for a single virtual device."""

    def __init__(self, device: DeviceProfile):
        self.device = device
        self.tree = OidTree(device)
        self.stats = {"requests": 0, "errors_injected": 0}

    def should_drop(self) -> bool:
        """Check if this request should be dropped (for failure simulation)."""
        fm = self.device.failure
        if fm.mode == "timeout":
            return True
        if fm.mode == "partial" and random.random() < fm.drop_rate:
            return True
        if fm.mode == "flapping":
            cycle = time.time() % fm.flap_period_s
            if cycle > fm.flap_period_s / 2:
                return True
        return False

    def get_delay(self) -> float:
        """Return response delay in seconds."""
        fm = self.device.failure
        if fm.mode == "slow":
            return fm.delay_ms / 1000.0
        return 0.0

    def handle_get(self, oids: list[str]) -> list[tuple[str, Any]]:
        """Handle SNMP GET request."""
        self.tree.refresh_counters()
        results = []
        for oid in oids:
            result = self.tree.get(oid)
            if result:
                results.append(result)
            else:
                results.append((oid, v2c.NoSuchObject()))
        return results

    def handle_get_next(self, oids: list[str]) -> list[tuple[str, Any]]:
        """Handle SNMP GETNEXT request."""
        self.tree.refresh_counters()
        results = []
        for oid in oids:
            result = self.tree.get_next(oid)
            if result:
                results.append(result)
            else:
                results.append((oid, v2c.EndOfMibView()))
        return results

    def handle_get_bulk(self, non_repeaters: int, max_reps: int,
                        oids: list[str]) -> list[tuple[str, Any]]:
        """Handle SNMP GETBULK request."""
        self.tree.refresh_counters()
        results = []
        for i, oid in enumerate(oids):
            if i < non_repeaters:
                result = self.tree.get_next(oid)
                if result:
                    results.append(result)
                else:
                    results.append((oid, v2c.EndOfMibView()))
            else:
                bulk = self.tree.get_bulk(oid, max_reps)
                if bulk:
                    results.extend(bulk)
                else:
                    results.append((oid, v2c.EndOfMibView()))
        return results


class SnmpProtocol(asyncio.DatagramProtocol):
    """asyncio UDP protocol for a single SNMP device."""

    def __init__(self, handler: SnmpDeviceHandler):
        self.handler = handler
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        handler = self.handler
        handler.stats["requests"] += 1

        if handler.should_drop():
            handler.stats["errors_injected"] += 1
            return  # silently drop

        delay = handler.get_delay()
        if delay > 0:
            asyncio.get_event_loop().call_later(
                delay, self._process_and_reply, data, addr,
            )
        else:
            self._process_and_reply(data, addr)

    def _process_and_reply(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            response = self._build_response(data)
            if response and self.transport:
                self.transport.sendto(response, addr)
        except Exception:
            logger.exception("SNMP processing error for %s", self.handler.device.name)

    def _build_response(self, data: bytes) -> bytes | None:
        """Parse SNMP request and build response."""
        try:
            msg, _ = ber_decoder.decode(data, asn1Spec=v2c.Message())
        except Exception:
            return None

        # Verify community string
        community = str(msg.getComponentByPosition(1))
        if community != self.handler.device.community:
            return None

        pdu = _get_pdu(msg)
        pdu_type = pdu.tagSet

        # Extract requested OIDs
        var_binds = _get_varbinds(pdu)
        oids = [str(oid) for oid, _ in var_binds]

        # Dispatch based on PDU type
        if pdu_type == v2c.GetRequestPDU.tagSet:
            results = self.handler.handle_get(oids)
        elif pdu_type == v2c.GetNextRequestPDU.tagSet:
            results = self.handler.handle_get_next(oids)
        elif pdu_type == v2c.GetBulkRequestPDU.tagSet:
            non_rep = _get_non_repeaters(pdu)
            max_rep = _get_max_reps(pdu)
            results = self.handler.handle_get_bulk(
                int(non_rep), int(max_rep), oids,
            )
        else:
            return None

        # Build response PDU
        resp_pdu = v2c.ResponsePDU()
        _set_request_id(resp_pdu, _get_request_id(pdu))
        _set_error_status(resp_pdu, 0)
        _set_error_index(resp_pdu, 0)

        resp_var_binds = []
        for oid_str, val in results:
            oid = v2c.ObjectIdentifier(oid_str)
            if isinstance(val, (univ.OctetString, univ.Integer, univ.ObjectIdentifier,
                                v2c.NoSuchObject, v2c.EndOfMibView, v2c.Counter64)):
                asn1_val = val
            else:
                asn1_val = _python_to_asn1(val, oid_str)
            resp_var_binds.append((oid, asn1_val))

        _set_varbinds(resp_pdu, resp_var_binds)

        resp_msg = v2c.Message()
        _set_msg_defaults(resp_msg)
        _set_community(resp_msg, community)
        _set_pdu(resp_msg, resp_pdu)

        return ber_encoder.encode(resp_msg)


async def counter_tick_loop(handlers: list[SnmpDeviceHandler], interval: float = 1.0) -> None:
    """Background loop that ticks interface counters for all devices."""
    while True:
        for handler in handlers:
            for iface in handler.device.interfaces:
                if iface.if_oper_status == 1:  # only tick active interfaces
                    iface.tick(interval)
        await asyncio.sleep(interval)


async def start_snmp_simulator(config: SimulatorConfig) -> list[SnmpDeviceHandler]:
    """Start SNMP UDP listeners for all configured devices."""
    loop = asyncio.get_event_loop()
    handlers: list[SnmpDeviceHandler] = []

    for device in config.devices:
        handler = SnmpDeviceHandler(device)
        handlers.append(handler)

        transport, _ = await loop.create_datagram_endpoint(
            lambda h=handler: SnmpProtocol(h),
            local_addr=("0.0.0.0", device.snmp_port),
        )
        logger.info(
            "SNMP agent started: %s on UDP :%d (%d interfaces, failure=%s)",
            device.name, device.snmp_port, len(device.interfaces),
            device.failure.mode,
        )

    # Start counter increment loop
    asyncio.create_task(counter_tick_loop(handlers))

    logger.info("SNMP simulator ready: %d devices on ports %d-%d",
                len(handlers),
                config.snmp_port_start,
                config.snmp_port_start + len(handlers) - 1)

    return handlers
