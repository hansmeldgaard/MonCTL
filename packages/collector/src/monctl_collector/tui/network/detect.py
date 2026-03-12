"""Detect which network backend to use (netplan vs /etc/network/interfaces)."""

from __future__ import annotations

import glob
import os
import subprocess


def detect_backend() -> str:
    """Return 'netplan', 'interfaces', or 'unknown'."""
    if glob.glob("/etc/netplan/*.yaml") or glob.glob("/etc/netplan/*.yml"):
        return "netplan"
    if os.path.exists("/etc/network/interfaces"):
        return "interfaces"
    return "unknown"


_FILTERED_PREFIXES = ("lo", "docker", "br-", "veth", "docker_gwbridge")


def list_interfaces() -> list[tuple[str, str]]:
    """Return [(name, ip_or_empty), ...] — filters out docker/veth/br- interfaces."""
    interfaces: list[tuple[str, str]] = []
    try:
        result = subprocess.run(
            ["ip", "-o", "addr", "show"],
            capture_output=True, text=True, timeout=5,
        )
        seen: set[str] = set()
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            name = parts[1].split("@")[0]
            if name in seen:
                continue
            if any(name == p or name.startswith(p) for p in _FILTERED_PREFIXES):
                continue
            # Extract IPv4 address if present
            ip = ""
            if "inet " in line:
                for i, tok in enumerate(parts):
                    if tok == "inet" and i + 1 < len(parts):
                        ip = parts[i + 1].split("/")[0]
                        break
            seen.add(name)
            interfaces.append((name, ip))
    except Exception:
        pass
    return interfaces


def detect_interface() -> str:
    """Return the name of the primary non-loopback network interface."""
    try:
        result = subprocess.run(
            ["ip", "-o", "link", "show"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split(": ")
            if len(parts) >= 2:
                name = parts[1].split("@")[0]
                if name != "lo":
                    return name
    except Exception:
        pass

    # Fallback: check common names
    for name in ("ens192", "ens160", "eth0", "ens33", "enp0s3"):
        if os.path.exists(f"/sys/class/net/{name}"):
            return name

    return "eth0"


def get_current_ip(interface: str) -> dict[str, str]:
    """Get current IP config for an interface from the system."""
    info: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", interface],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                parts = line.split()
                addr_prefix = parts[1]  # e.g. "192.168.1.10/24"
                if "/" in addr_prefix:
                    ip, prefix = addr_prefix.split("/")
                    info["ip_address"] = ip
                    info["subnet_mask"] = prefix
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if "via" in parts:
                idx = parts.index("via")
                if idx + 1 < len(parts):
                    info["gateway"] = parts[idx + 1]
                break
    except Exception:
        pass

    try:
        if os.path.exists("/etc/resolv.conf"):
            with open("/etc/resolv.conf") as f:
                dns_servers = []
                for line in f:
                    if line.strip().startswith("nameserver"):
                        dns_servers.append(line.strip().split()[1])
                if dns_servers:
                    info["dns1"] = dns_servers[0]
                if len(dns_servers) > 1:
                    info["dns2"] = dns_servers[1]
    except Exception:
        pass

    return info
