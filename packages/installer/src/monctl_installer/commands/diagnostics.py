"""`monctl_ctl logs` and `monctl_ctl ssh` — thin SSH passthroughs.

These shell out to the system's `ssh` binary instead of using paramiko, so the
operator gets a real TTY / TERM-aware session + key-agent forwarding / all the
usual niceties. Paramiko would require a lot of glue for interactive work.
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path

from monctl_installer.inventory.loader import load_inventory
from monctl_installer.inventory.schema import Host


def find_host(inventory_path: Path, name: str) -> Host:
    inv = load_inventory(inventory_path)
    for h in inv.hosts:
        if h.name == name:
            return h
    raise ValueError(f"no host named {name!r} in inventory (known: {[h.name for h in inv.hosts]})")


def ssh_exec(host: Host) -> int:
    """Replace the current process with `ssh <user>@<addr>`. Never returns on success."""
    args = _ssh_args(host)
    os.execvp("ssh", args)  # pragma: no cover  (process replaced)
    return 1  # unreachable


def logs_exec(
    host: Host,
    *,
    project: str,
    service: str | None,
    tail: int,
    follow: bool,
) -> int:
    """Tail `docker compose logs` for a project on a host via `ssh <host> <cmd>`."""
    cmd_parts = [
        "cd",
        f"/opt/monctl/{project}",
        "&&",
        "docker",
        "compose",
        "logs",
        "--tail",
        str(tail),
    ]
    if follow:
        cmd_parts.insert(-2, "--follow")
    if service:
        cmd_parts.append(service)
    remote_cmd = " ".join(shlex.quote(p) if p not in ("&&",) else p for p in cmd_parts)
    args = _ssh_args(host, remote_cmd)
    os.execvp("ssh", args)  # pragma: no cover
    return 1  # unreachable


def _ssh_args(host: Host, remote_cmd: str | None = None) -> list[str]:
    args = ["ssh", "-p", str(host.ssh.port)]
    if host.ssh.key is not None:
        args += ["-i", str(Path(host.ssh.key).expanduser())]
    args.append(f"{host.ssh.user}@{host.address}")
    if remote_cmd is not None:
        args.append(remote_cmd)
    return args
