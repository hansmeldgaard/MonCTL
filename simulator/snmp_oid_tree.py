"""OID tree for a simulated SNMP device.

Uses a SortedDict keyed by OID tuple for efficient GET and GETNEXT operations.
Populates MIB-II system group + ifTable + ifXTable from DeviceProfile data.
"""
from __future__ import annotations

from typing import Any

from sortedcontainers import SortedDict

from simulator.config import DeviceProfile, InterfaceProfile

OidKey = tuple[int, ...]


def _oid_to_tuple(oid: str) -> OidKey:
    return tuple(int(x) for x in oid.strip(".").split("."))


def _tuple_to_oid(t: OidKey) -> str:
    return ".".join(str(x) for x in t)


class OidTree:
    """Sorted OID tree supporting GET, GETNEXT, and GETBULK."""

    def __init__(self, device: DeviceProfile):
        self.device = device
        self._tree: SortedDict = SortedDict()
        self._populate_system()
        self._populate_interfaces()

    def _set(self, oid: str, value: Any) -> None:
        self._tree[_oid_to_tuple(oid)] = value

    def _populate_system(self) -> None:
        d = self.device
        self._set("1.3.6.1.2.1.1.1.0", d.sys_descr)            # sysDescr
        self._set("1.3.6.1.2.1.1.2.0", d.sys_object_id)        # sysObjectID
        # sysUpTime is dynamic — handled in get()
        self._set("1.3.6.1.2.1.1.3.0", 0)                       # placeholder
        self._set("1.3.6.1.2.1.1.4.0", d.sys_contact)           # sysContact
        self._set("1.3.6.1.2.1.1.5.0", d.sys_name)              # sysName
        self._set("1.3.6.1.2.1.1.6.0", d.sys_location)          # sysLocation

    def _populate_interfaces(self) -> None:
        for iface in self.device.interfaces:
            idx = iface.if_index
            # ifTable (MIB-II)
            self._set(f"1.3.6.1.2.1.2.2.1.1.{idx}", idx)                      # ifIndex
            self._set(f"1.3.6.1.2.1.2.2.1.2.{idx}", iface.if_descr)           # ifDescr
            self._set(f"1.3.6.1.2.1.2.2.1.5.{idx}", iface.if_speed_mbps * 1_000_000)  # ifSpeed (bps)
            self._set(f"1.3.6.1.2.1.2.2.1.7.{idx}", iface.if_admin_status)    # ifAdminStatus
            self._set(f"1.3.6.1.2.1.2.2.1.8.{idx}", iface.if_oper_status)     # ifOperStatus
            self._set(f"1.3.6.1.2.1.2.2.1.10.{idx}", 0)                       # ifInOctets (32-bit)
            self._set(f"1.3.6.1.2.1.2.2.1.11.{idx}", 0)                       # ifInUcastPkts
            self._set(f"1.3.6.1.2.1.2.2.1.13.{idx}", 0)                       # ifInDiscards
            self._set(f"1.3.6.1.2.1.2.2.1.14.{idx}", 0)                       # ifInErrors
            self._set(f"1.3.6.1.2.1.2.2.1.16.{idx}", 0)                       # ifOutOctets (32-bit)
            self._set(f"1.3.6.1.2.1.2.2.1.17.{idx}", 0)                       # ifOutUcastPkts
            self._set(f"1.3.6.1.2.1.2.2.1.19.{idx}", 0)                       # ifOutDiscards
            self._set(f"1.3.6.1.2.1.2.2.1.20.{idx}", 0)                       # ifOutErrors
            # ifXTable (MIB-II Extensions)
            self._set(f"1.3.6.1.2.1.31.1.1.1.1.{idx}", iface.if_name)         # ifName
            self._set(f"1.3.6.1.2.1.31.1.1.1.6.{idx}", 0)                     # ifHCInOctets (64-bit)
            self._set(f"1.3.6.1.2.1.31.1.1.1.10.{idx}", 0)                    # ifHCOutOctets (64-bit)
            self._set(f"1.3.6.1.2.1.31.1.1.1.15.{idx}", iface.if_speed_mbps)  # ifHighSpeed
            self._set(f"1.3.6.1.2.1.31.1.1.1.18.{idx}", iface.if_alias)       # ifAlias

    def refresh_counters(self) -> None:
        """Update OID tree values from the live interface counters."""
        for iface in self.device.interfaces:
            idx = iface.if_index
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.2.2.1.10.{idx}")] = iface.in_octets_32
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.2.2.1.11.{idx}")] = iface.in_ucast_pkts
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.2.2.1.13.{idx}")] = iface.in_discards
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.2.2.1.14.{idx}")] = iface.in_errors
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.2.2.1.16.{idx}")] = iface.out_octets_32
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.2.2.1.17.{idx}")] = iface.out_ucast_pkts
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.2.2.1.19.{idx}")] = iface.out_discards
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.2.2.1.20.{idx}")] = iface.out_errors
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.31.1.1.1.6.{idx}")] = iface.in_octets_64
            self._tree[_oid_to_tuple(f"1.3.6.1.2.1.31.1.1.1.10.{idx}")] = iface.out_octets_64
        # Dynamic sysUpTime
        self._tree[_oid_to_tuple("1.3.6.1.2.1.1.3.0")] = self.device.sys_uptime

    def get(self, oid: str) -> tuple[str, Any] | None:
        """SNMP GET: exact OID lookup."""
        key = _oid_to_tuple(oid)
        val = self._tree.get(key)
        if val is None:
            return None
        return (_tuple_to_oid(key), val)

    def get_next(self, oid: str) -> tuple[str, Any] | None:
        """SNMP GETNEXT: return the first OID strictly after the given one."""
        key = _oid_to_tuple(oid)
        idx = self._tree.bisect_right(key)
        if idx >= len(self._tree):
            return None
        next_key = self._tree.keys()[idx]
        return (_tuple_to_oid(next_key), self._tree[next_key])

    def get_bulk(self, oid: str, max_repetitions: int = 25) -> list[tuple[str, Any]]:
        """SNMP GETBULK: return up to max_repetitions OIDs after the given one."""
        key = _oid_to_tuple(oid)
        idx = self._tree.bisect_right(key)
        results = []
        for i in range(idx, min(idx + max_repetitions, len(self._tree))):
            k = self._tree.keys()[i]
            results.append((_tuple_to_oid(k), self._tree[k]))
        return results

    def walk(self, base_oid: str) -> list[tuple[str, Any]]:
        """Walk all OIDs under a base OID prefix."""
        base = _oid_to_tuple(base_oid)
        results = []
        idx = self._tree.bisect_left(base)
        for i in range(idx, len(self._tree)):
            k = self._tree.keys()[i]
            if k[:len(base)] != base:
                break
            results.append((_tuple_to_oid(k), self._tree[k]))
        return results
