"""Thin paramiko wrapper: open connections on demand, run commands, close when done.

All methods raise SSHError on connection/auth/command failure. The runner is
designed for bounded fan-out (up to ~32 hosts); for larger fleets, swap the
ThreadPoolExecutor concurrency dial.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import paramiko

from monctl_installer.inventory.schema import Host


class SSHError(Exception):
    """Raised when an SSH connection, auth, or command invocation fails."""


@dataclass(frozen=True)
class CommandResult:
    host: str
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class SSHRunner:
    """Connection-per-call SSH executor. Cheap for preflight; deploy should reuse."""

    def __init__(
        self,
        *,
        max_workers: int = 16,
        connect_timeout: int = 10,
        command_timeout: int = 60,
    ) -> None:
        self._max_workers = max_workers
        self._connect_timeout = connect_timeout
        self._command_timeout = command_timeout

    def run(self, host: Host, command: str) -> CommandResult:
        try:
            with self._connect(host) as client:
                stdin, stdout, stderr = client.exec_command(
                    command, timeout=self._command_timeout
                )
                stdin.close()
                out = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
                rc = stdout.channel.recv_exit_status()
                return CommandResult(
                    host=host.name, command=command, exit_code=rc, stdout=out, stderr=err
                )
        except (paramiko.SSHException, OSError) as exc:
            raise SSHError(f"{host.name} ({host.address}): {exc}") from exc

    def run_many(
        self, hosts: list[Host], command_for: Callable[[Host], str]
    ) -> list[CommandResult | SSHError]:
        """Run one command per host in parallel; order of results matches `hosts`."""
        results: list[CommandResult | SSHError | None] = [None] * len(hosts)
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self.run, h, command_for(h)): i for i, h in enumerate(hosts)
            }
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except SSHError as exc:
                    results[idx] = exc
        return [r for r in results if r is not None]  # all slots filled by design

    def put(self, host: Host, content: str, remote_path: str, mode: int = 0o644) -> None:
        """scp content to `remote_path` on `host` with the given mode."""
        try:
            with self._connect(host) as client:
                sftp = client.open_sftp()
                try:
                    _ensure_remote_parent(sftp, remote_path)
                    with sftp.file(remote_path, "w") as rf:
                        rf.write(content)
                    sftp.chmod(remote_path, mode)
                finally:
                    sftp.close()
        except (paramiko.SSHException, OSError) as exc:
            raise SSHError(f"{host.name}: scp {remote_path}: {exc}") from exc

    @contextmanager
    def _connect(self, host: Host) -> Iterator[paramiko.SSHClient]:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict[str, object] = {
            "hostname": host.address,
            "port": host.ssh.port,
            "username": host.ssh.user,
            "timeout": self._connect_timeout,
            "allow_agent": True,
            "look_for_keys": host.ssh.key is None,
        }
        if host.ssh.key is not None:
            kwargs["key_filename"] = str(Path(host.ssh.key).expanduser())
        client.connect(**kwargs)
        try:
            yield client
        finally:
            client.close()


def _ensure_remote_parent(sftp: paramiko.SFTPClient, path: str) -> None:
    parts = path.rstrip("/").split("/")
    accum = ""
    for p in parts[:-1]:
        accum = f"{accum}/{p}" if accum else p if p else "/"
        if accum == "/":
            continue
        try:
            sftp.stat(accum)
        except FileNotFoundError:
            sftp.mkdir(accum, mode=0o755)
