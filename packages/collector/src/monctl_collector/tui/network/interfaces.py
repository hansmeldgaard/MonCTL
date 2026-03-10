"""Debian /etc/network/interfaces backend."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .common import NetworkConfig

INTERFACES_PATH = Path("/etc/network/interfaces")
BACKUP_PATH = Path("/etc/network/interfaces.monctl-backup")


def read_config(interface: str) -> NetworkConfig:
    """Parse current config from /etc/network/interfaces."""
    cfg = NetworkConfig(interface=interface)
    if not INTERFACES_PATH.exists():
        return cfg

    content = INTERFACES_PATH.read_text()
    in_iface = False

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"iface {interface}"):
            in_iface = True
            if "dhcp" in stripped:
                cfg.dhcp = True
            elif "static" in stripped:
                cfg.dhcp = False
            continue
        if in_iface:
            if stripped.startswith("iface ") or stripped.startswith("auto ") or stripped == "":
                if stripped.startswith("iface ") or stripped.startswith("auto "):
                    in_iface = False
                continue
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                key, val = parts
                if key == "address":
                    if "/" in val:
                        cfg.ip_address, cfg.subnet_mask = val.split("/")
                    else:
                        cfg.ip_address = val
                elif key == "netmask":
                    cfg.subnet_mask = val
                elif key == "gateway":
                    cfg.gateway = val
                elif key == "dns-nameservers":
                    servers = val.split()
                    if servers:
                        cfg.dns1 = servers[0]
                    if len(servers) > 1:
                        cfg.dns2 = servers[1]
                elif key == "dns-search":
                    pass  # ignore

    return cfg


def write_config(cfg: NetworkConfig) -> str:
    """Write config and return diff-like summary of changes."""
    # Backup current file
    if INTERFACES_PATH.exists():
        shutil.copy2(INTERFACES_PATH, BACKUP_PATH)

    method = "dhcp" if cfg.dhcp else "static"
    lines = [
        "# Managed by monctl-setup",
        f"auto {cfg.interface}",
        f"iface {cfg.interface} inet {method}",
    ]

    if not cfg.dhcp:
        prefix = cfg.subnet_mask or "24"
        lines.append(f"    address {cfg.ip_address}/{prefix}")
        if cfg.gateway:
            lines.append(f"    gateway {cfg.gateway}")
        dns_parts = [s for s in [cfg.dns1, cfg.dns2] if s]
        if dns_parts:
            lines.append(f"    dns-nameservers {' '.join(dns_parts)}")

    # Preserve other interfaces from the original file
    other_lines: list[str] = []
    if INTERFACES_PATH.exists():
        content = INTERFACES_PATH.read_text()
        skip = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"auto {cfg.interface}") or stripped.startswith(f"iface {cfg.interface}"):
                skip = True
                continue
            if skip and (stripped.startswith("auto ") or stripped.startswith("iface ")):
                skip = False
            if skip and stripped and not stripped.startswith("#"):
                continue
            if not skip:
                other_lines.append(line)

    final = "\n".join(other_lines + [""] + lines) + "\n"
    INTERFACES_PATH.write_text(final)

    return f"Wrote {INTERFACES_PATH} ({method})"


def apply_config() -> str:
    """Apply by restarting networking service."""
    try:
        result = subprocess.run(
            ["systemctl", "restart", "networking"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return "Networking restarted successfully"
    except subprocess.TimeoutExpired:
        return "Error: restart timed out"
    except Exception as e:
        return f"Error: {e}"


def revert_config() -> str:
    """Revert to backup."""
    if not BACKUP_PATH.exists():
        return "No backup found"
    shutil.copy2(BACKUP_PATH, INTERFACES_PATH)
    return apply_config()
