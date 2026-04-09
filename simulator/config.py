"""Configuration loader and dataclasses for the device simulator."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FailureMode:
    """Configures how a simulated device should misbehave."""
    mode: str = "normal"       # normal, slow, timeout, partial, flapping
    delay_ms: int = 3000       # added response delay (for "slow")
    drop_rate: float = 0.3     # fraction of requests to silently drop (for "partial")
    flap_period_s: int = 300   # cycle length for "flapping" mode


@dataclass
class InterfaceProfile:
    """A single simulated network interface."""
    if_index: int
    if_name: str               # e.g. "GigabitEthernet1/0/1"
    if_descr: str = ""         # ifDescr (often same as if_name for simulated)
    if_alias: str = ""         # e.g. "Uplink to core"
    if_speed_mbps: int = 1000
    if_admin_status: int = 1   # 1=up, 2=down
    if_oper_status: int = 1    # 1=up, 2=down, etc.
    traffic_profile: str = "medium"  # high, medium, low, idle, bursty
    error_rate: float = 0.0    # probability of injecting errors per tick

    # Runtime counters (managed by OID tree)
    in_octets_64: int = 0
    out_octets_64: int = 0
    in_ucast_pkts: int = 0
    out_ucast_pkts: int = 0
    in_errors: int = 0
    out_errors: int = 0
    in_discards: int = 0
    out_discards: int = 0

    @property
    def in_octets_32(self) -> int:
        return self.in_octets_64 % (2**32)

    @property
    def out_octets_32(self) -> int:
        return self.out_octets_64 % (2**32)

    def tick(self, elapsed_s: float = 1.0) -> None:
        """Advance counters by one tick."""
        import random

        bytes_per_sec = _traffic_bytes_per_sec(self.traffic_profile, self.if_speed_mbps)
        in_bytes = int(bytes_per_sec * elapsed_s * random.uniform(0.8, 1.2))
        out_bytes = int(bytes_per_sec * elapsed_s * random.uniform(0.6, 1.0))
        avg_pkt = 500

        self.in_octets_64 += in_bytes
        self.out_octets_64 += out_bytes
        self.in_ucast_pkts += max(1, in_bytes // avg_pkt)
        self.out_ucast_pkts += max(1, out_bytes // avg_pkt)

        if self.error_rate > 0 and random.random() < self.error_rate:
            self.in_errors += random.randint(1, 5)
            self.out_errors += random.randint(0, 3)
        if self.error_rate > 0 and random.random() < self.error_rate * 0.5:
            self.in_discards += random.randint(1, 3)
            self.out_discards += random.randint(0, 2)


def _traffic_bytes_per_sec(profile: str, speed_mbps: int) -> float:
    """Return base bytes/sec for a traffic profile."""
    if profile == "high":
        return speed_mbps * 1_000_000 / 8 * 0.7   # 70% utilization
    elif profile == "medium":
        return speed_mbps * 1_000_000 / 8 * 0.1   # 10% utilization
    elif profile == "low":
        return speed_mbps * 1_000_000 / 8 * 0.01  # 1% utilization
    elif profile == "idle":
        return 1024  # ~1 KB/s
    elif profile == "bursty":
        # Sinusoidal: oscillates between low and high over 5 minutes
        t = time.time()
        factor = 0.05 + 0.65 * (math.sin(2 * math.pi * t / 300) + 1) / 2
        return speed_mbps * 1_000_000 / 8 * factor
    return speed_mbps * 1_000_000 / 8 * 0.1  # default: medium


@dataclass
class DeviceProfile:
    """A single simulated device."""
    name: str
    snmp_port: int
    device_type: str           # cisco-switch, cisco-router, juniper-switch, etc.
    sys_object_id: str
    sys_descr: str
    sys_name: str
    sys_location: str = "Simulator Lab"
    sys_contact: str = "monctl-sim@example.com"
    community: str = "public"
    interfaces: list[InterfaceProfile] = field(default_factory=list)
    failure: FailureMode = field(default_factory=FailureMode)
    http_port: int | None = None
    tcp_ports: list[int] = field(default_factory=list)
    # Runtime
    _start_time: float = field(default_factory=time.time, repr=False)

    @property
    def sys_uptime(self) -> int:
        """sysUpTime in hundredths of a second since start."""
        return int((time.time() - self._start_time) * 100)


@dataclass
class SimulatorConfig:
    """Top-level simulator configuration."""
    host_ip: str = "10.145.210.10"
    snmp_port_start: int = 11000
    http_port_start: int = 12000
    tcp_port_start: int = 13000
    default_community: str = "public"
    control_port: int = 9999
    devices: list[DeviceProfile] = field(default_factory=list)


def load_config(path: str | Path) -> SimulatorConfig:
    """Load simulator configuration from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    sim = raw.get("simulator", {})
    cfg = SimulatorConfig(
        host_ip=sim.get("host_ip", "10.145.210.10"),
        snmp_port_start=sim.get("snmp_port_start", 11000),
        http_port_start=sim.get("http_port_start", 12000),
        tcp_port_start=sim.get("tcp_port_start", 13000),
        default_community=sim.get("default_community", "public"),
        control_port=sim.get("control_port", 9999),
    )

    from simulator.device_profiles import DEVICE_TEMPLATES, build_interfaces

    snmp_port = cfg.snmp_port_start
    http_port = cfg.http_port_start
    tcp_port = cfg.tcp_port_start

    failure_map: dict[int, FailureMode] = {}
    for mode_name, indices in raw.get("failure_injection", {}).items():
        if isinstance(indices, list):
            for idx in indices:
                if mode_name == "slow":
                    failure_map[idx] = FailureMode(mode="slow", delay_ms=3000)
                elif mode_name == "partial":
                    failure_map[idx] = FailureMode(mode="partial", drop_rate=0.3)
                elif mode_name == "timeout":
                    failure_map[idx] = FailureMode(mode="timeout")
                elif mode_name == "flapping":
                    failure_map[idx] = FailureMode(mode="flapping")

    device_index = 0
    for group in raw.get("device_profiles", []):
        count = group.get("count", 1)
        dtype = group.get("type", "linux-host")
        num_ifaces = group.get("interfaces", None)
        traffic = group.get("traffic_profile", "medium")
        community = group.get("community", cfg.default_community)
        want_http = group.get("http", False)
        want_tcp = group.get("tcp_ports", [])
        error_rate = group.get("error_rate", 0.001)

        template = DEVICE_TEMPLATES.get(dtype)
        if template is None:
            raise ValueError(f"Unknown device type: {dtype}")

        for i in range(count):
            iface_count = num_ifaces if num_ifaces is not None else template["default_interfaces"]
            seq = device_index + 1
            name = f"sim-{dtype}-{seq:03d}"

            interfaces = build_interfaces(
                dtype, iface_count, traffic, error_rate,
            )

            device = DeviceProfile(
                name=name,
                snmp_port=snmp_port,
                device_type=dtype,
                sys_object_id=template["sys_object_id"],
                sys_descr=template["sys_descr"],
                sys_name=f"{name}.sim.local",
                community=community,
                interfaces=interfaces,
                failure=failure_map.get(device_index, FailureMode()),
                http_port=http_port if want_http else None,
                tcp_ports=[tcp_port + j for j in range(len(want_tcp))] if want_tcp else [],
            )
            cfg.devices.append(device)

            snmp_port += 1
            if want_http:
                http_port += 1
            if want_tcp:
                tcp_port += len(want_tcp)
            device_index += 1

    return cfg
