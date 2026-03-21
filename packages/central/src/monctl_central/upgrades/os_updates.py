"""OS update management via SSH."""

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()


@dataclass
class AvailableOsUpdate:
    package_name: str
    current_version: str
    new_version: str
    severity: str
    architecture: str


async def check_os_updates_via_ssh(
    host_ip: str, ssh_user: str = "monctl", ssh_timeout: int = 30,
) -> list[AvailableOsUpdate]:
    updates: list[AvailableOsUpdate] = []
    cmd = (
        f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "
        f"{ssh_user}@{host_ip} "
        f"'sudo apt-get update -qq 2>/dev/null && apt list --upgradable 2>/dev/null'"
    )
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=ssh_timeout)
    if proc.returncode != 0:
        logger.warning("os_update_check_failed", host=host_ip, stderr=stderr.decode())
        return updates

    for line in stdout.decode().splitlines():
        if "[upgradable from:" not in line:
            continue
        try:
            parts = line.split("/")
            pkg_name = parts[0]
            rest = "/".join(parts[1:])
            tokens = rest.split()
            new_version = tokens[1] if len(tokens) > 1 else "unknown"
            arch = tokens[2] if len(tokens) > 2 else "amd64"
            severity = "security" if "-security" in rest.split()[0] else "normal"
            old_version = ""
            if "from:" in line:
                old_version = line.split("from:")[1].strip().rstrip("]")
            updates.append(AvailableOsUpdate(
                package_name=pkg_name, current_version=old_version,
                new_version=new_version, severity=severity, architecture=arch,
            ))
        except Exception:
            logger.warning("parse_os_update_line_failed", line=line)
    return updates


async def download_os_packages_via_ssh(
    host_ip: str, package_names: list[str], dest_dir: Path, ssh_user: str = "monctl",
) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    pkg_list = " ".join(package_names)
    remote_dir = "/tmp/monctl-os-dl"

    dl_cmd = (
        f"ssh -o StrictHostKeyChecking=no {ssh_user}@{host_ip} "
        f"'mkdir -p {remote_dir} && cd {remote_dir} && sudo apt-get download {pkg_list} 2>&1'"
    )
    proc = await asyncio.create_subprocess_shell(
        dl_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(proc.communicate(), timeout=120)

    ls_cmd = f"ssh {ssh_user}@{host_ip} 'ls {remote_dir}/*.deb 2>/dev/null'"
    proc = await asyncio.create_subprocess_shell(
        ls_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)

    for remote_path in stdout.decode().strip().splitlines():
        filename = remote_path.split("/")[-1]
        local_path = dest_dir / filename
        scp_cmd = f"scp {ssh_user}@{host_ip}:{remote_path} {local_path}"
        proc = await asyncio.create_subprocess_shell(
            scp_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
        if local_path.exists():
            downloaded.append(local_path)

    await asyncio.create_subprocess_shell(f"ssh {ssh_user}@{host_ip} 'rm -rf {remote_dir}'")
    return downloaded


def compute_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()
