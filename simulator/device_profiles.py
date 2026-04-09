"""Built-in device templates for the simulator.

Each template defines a realistic sysObjectID, sysDescr, interface naming,
and default interface count for a common device type.
"""
from __future__ import annotations

from simulator.config import InterfaceProfile

# Device templates keyed by type name
DEVICE_TEMPLATES: dict[str, dict] = {
    "cisco-switch": {
        "sys_object_id": "1.3.6.1.4.1.9.1.2494",
        "sys_descr": (
            "Cisco IOS Software, Catalyst 9300 Software (CAT9K_IOSXE), "
            "Version 17.9.4a, RELEASE SOFTWARE (fc3)"
        ),
        "default_interfaces": 24,
        "interface_prefix": "GigabitEthernet1/0/",
        "extra_interfaces": [
            {"name": "Vlan1", "descr": "Vlan1", "speed": 1000, "oper": 1},
            {"name": "Loopback0", "descr": "Loopback0", "speed": 0, "oper": 1},
        ],
    },
    "cisco-router": {
        "sys_object_id": "1.3.6.1.4.1.9.1.1227",
        "sys_descr": (
            "Cisco IOS Software, ISR Software (ISR4451-X/K9), "
            "Version 17.6.5, RELEASE SOFTWARE (fc2)"
        ),
        "default_interfaces": 8,
        "interface_prefix": "GigabitEthernet0/0/",
        "extra_interfaces": [
            {"name": "Loopback0", "descr": "Loopback0", "speed": 0, "oper": 1},
        ],
    },
    "juniper-switch": {
        "sys_object_id": "1.3.6.1.4.1.2636.1.1.1.2.57",
        "sys_descr": (
            "Juniper Networks, Inc. ex4300-48t Ethernet Switch, "
            "kernel JUNOS 22.4R3-S2, Build date: 2024-01-10"
        ),
        "default_interfaces": 48,
        "interface_prefix": "ge-0/0/",
        "extra_interfaces": [
            {"name": "ae0", "descr": "ae0", "speed": 10000, "oper": 1},
            {"name": "lo0", "descr": "lo0", "speed": 0, "oper": 1},
        ],
    },
    "juniper-router": {
        "sys_object_id": "1.3.6.1.4.1.2636.1.1.1.2.143",
        "sys_descr": (
            "Juniper Networks, Inc. mx204 internet router, "
            "kernel JUNOS 23.2R1-S1, Build date: 2024-03-15"
        ),
        "default_interfaces": 12,
        "interface_prefix": "et-0/0/",
        "extra_interfaces": [
            {"name": "ae0", "descr": "ae0", "speed": 100000, "oper": 1},
            {"name": "lo0", "descr": "lo0", "speed": 0, "oper": 1},
        ],
    },
    "linux-host": {
        "sys_object_id": "1.3.6.1.4.1.8072.3.2.10",
        "sys_descr": (
            "Linux sim-host 5.15.0-91-generic #101-Ubuntu SMP "
            "x86_64 GNU/Linux"
        ),
        "default_interfaces": 2,
        "interface_prefix": "eth",
        "extra_interfaces": [
            {"name": "lo", "descr": "lo", "speed": 0, "oper": 1},
        ],
    },
}


def build_interfaces(
    device_type: str,
    count: int,
    traffic_profile: str = "medium",
    error_rate: float = 0.001,
) -> list[InterfaceProfile]:
    """Generate interface profiles for a device type."""
    template = DEVICE_TEMPLATES[device_type]
    prefix = template["interface_prefix"]
    interfaces: list[InterfaceProfile] = []
    idx = 1

    # Main interfaces
    speed_map = {
        "cisco-switch": 1000,
        "cisco-router": 1000,
        "juniper-switch": 1000,
        "juniper-router": 10000,
        "linux-host": 10000,
    }
    speed = speed_map.get(device_type, 1000)

    for i in range(count):
        if device_type == "linux-host":
            name = f"{prefix}{i}"
        elif "0/0/" in prefix:
            # Juniper/Cisco with slot notation: ge-0/0/0, et-0/0/0, GigabitEthernet0/0/0
            name = f"{prefix}{i}"
        else:
            # Cisco access ports: GigabitEthernet1/0/1, 1/0/2, ...
            name = f"{prefix}{i + 1}"
        interfaces.append(InterfaceProfile(
            if_index=idx,
            if_name=name,
            if_descr=name,
            if_alias=f"Port {i + 1}" if device_type != "linux-host" else "",
            if_speed_mbps=speed,
            if_admin_status=1,
            if_oper_status=1 if i < count - 2 else 2,  # last 2 ports are down
            traffic_profile=traffic_profile if i < count - 2 else "idle",
            error_rate=error_rate,
        ))
        idx += 1

    # Extra interfaces (Vlan, Loopback, ae, lo, etc.)
    for extra in template.get("extra_interfaces", []):
        interfaces.append(InterfaceProfile(
            if_index=idx,
            if_name=extra["name"],
            if_descr=extra["descr"],
            if_alias="",
            if_speed_mbps=extra["speed"],
            if_admin_status=1,
            if_oper_status=extra["oper"],
            traffic_profile="idle",
            error_rate=0.0,
        ))
        idx += 1

    return interfaces
