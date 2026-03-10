"""Ubuntu netplan backend."""

from __future__ import annotations

import glob
import shutil
import subprocess
from pathlib import Path

import yaml

from .common import NetworkConfig

NETPLAN_DIR = Path("/etc/netplan")
BACKUP_SUFFIX = ".monctl-backup"


def _find_config_file(interface: str) -> Path | None:
    """Find the netplan YAML that configures the given interface."""
    for path in sorted(NETPLAN_DIR.glob("*.yaml")) + sorted(NETPLAN_DIR.glob("*.yml")):
        try:
            data = yaml.safe_load(path.read_text()) or {}
            ethernets = data.get("network", {}).get("ethernets", {})
            if interface in ethernets:
                return path
        except Exception:
            continue
    # Return first config file if interface not found
    files = sorted(glob.glob(str(NETPLAN_DIR / "*.yaml"))) + sorted(glob.glob(str(NETPLAN_DIR / "*.yml")))
    return Path(files[0]) if files else None


def read_config(interface: str) -> NetworkConfig:
    """Parse current config from netplan YAML."""
    cfg = NetworkConfig(interface=interface)
    config_file = _find_config_file(interface)
    if not config_file or not config_file.exists():
        return cfg

    try:
        data = yaml.safe_load(config_file.read_text()) or {}
    except Exception:
        return cfg

    ethernets = data.get("network", {}).get("ethernets", {})
    iface_cfg = ethernets.get(interface, {})

    if iface_cfg.get("dhcp4", True):
        cfg.dhcp = True
    else:
        cfg.dhcp = False

    addresses = iface_cfg.get("addresses", [])
    if addresses:
        addr = addresses[0]
        if "/" in str(addr):
            cfg.ip_address, cfg.subnet_mask = str(addr).split("/")
        else:
            cfg.ip_address = str(addr)

    routes = iface_cfg.get("routes", [])
    for route in routes:
        if route.get("to") in ("default", "0.0.0.0/0"):
            cfg.gateway = route.get("via", "")
            break
    # Legacy gateway4 support
    if not cfg.gateway and "gateway4" in iface_cfg:
        cfg.gateway = iface_cfg["gateway4"]

    nameservers = iface_cfg.get("nameservers", {})
    dns_list = nameservers.get("addresses", [])
    if dns_list:
        cfg.dns1 = str(dns_list[0])
    if len(dns_list) > 1:
        cfg.dns2 = str(dns_list[1])

    # Read NTP from timesyncd config (netplan doesn't have native NTP)
    try:
        ts_conf = Path("/etc/systemd/timesyncd.conf")
        if ts_conf.exists():
            for line in ts_conf.read_text().splitlines():
                line = line.strip()
                if line.startswith("NTP="):
                    servers = line.removeprefix("NTP=").strip().split()
                    if servers:
                        cfg.ntp1 = servers[0]
                    if len(servers) > 1:
                        cfg.ntp2 = servers[1]
                    break
    except Exception:
        pass

    return cfg


def write_config(cfg: NetworkConfig) -> str:
    """Write netplan config and return summary."""
    config_file = _find_config_file(cfg.interface)
    if config_file is None:
        config_file = NETPLAN_DIR / "01-monctl.yaml"

    # Backup
    if config_file.exists():
        shutil.copy2(config_file, config_file.with_suffix(config_file.suffix + BACKUP_SUFFIX))

    # Build netplan structure
    iface_cfg: dict = {}
    if cfg.dhcp:
        iface_cfg["dhcp4"] = True
    else:
        iface_cfg["dhcp4"] = False
        prefix = cfg.subnet_mask or "24"
        iface_cfg["addresses"] = [f"{cfg.ip_address}/{prefix}"]
        if cfg.gateway:
            iface_cfg["routes"] = [{"to": "default", "via": cfg.gateway}]
        dns_servers = [s for s in [cfg.dns1, cfg.dns2] if s]
        if dns_servers:
            iface_cfg["nameservers"] = {"addresses": dns_servers}

    data = {
        "network": {
            "version": 2,
            "ethernets": {
                cfg.interface: iface_cfg,
            },
        }
    }

    config_file.write_text(yaml.dump(data, default_flow_style=False))

    # Write NTP to systemd-timesyncd (netplan doesn't handle NTP natively)
    ntp_servers = [s for s in [cfg.ntp1, cfg.ntp2] if s]
    ts_conf = Path("/etc/systemd/timesyncd.conf")
    try:
        lines = ts_conf.read_text().splitlines() if ts_conf.exists() else ["[Time]"]
        new_lines = [l for l in lines if not l.strip().startswith("NTP=")]
        if ntp_servers:
            # Insert after [Time] section header
            idx = next((i for i, l in enumerate(new_lines) if l.strip() == "[Time]"), -1)
            if idx >= 0:
                new_lines.insert(idx + 1, f"NTP={' '.join(ntp_servers)}")
            else:
                new_lines.extend(["[Time]", f"NTP={' '.join(ntp_servers)}"])
        ts_conf.write_text("\n".join(new_lines) + "\n")
    except Exception:
        pass

    return f"Wrote {config_file}"


def apply_config() -> str:
    """Apply via netplan apply + restart timesyncd for NTP changes."""
    try:
        result = subprocess.run(
            ["netplan", "apply"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        # Restart timesyncd to pick up NTP changes
        subprocess.run(
            ["systemctl", "restart", "systemd-timesyncd"],
            capture_output=True, timeout=10,
        )
        return "Netplan applied successfully"
    except subprocess.TimeoutExpired:
        return "Error: netplan apply timed out"
    except Exception as e:
        return f"Error: {e}"


def revert_config() -> str:
    """Revert to backup."""
    for path in NETPLAN_DIR.glob("*" + BACKUP_SUFFIX):
        original = Path(str(path).removesuffix(BACKUP_SUFFIX))
        shutil.copy2(path, original)
    return apply_config()
