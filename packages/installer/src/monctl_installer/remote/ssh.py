"""Thin paramiko wrapper: open connections on demand, run commands, close when done.

All methods raise SSHError on connection/auth/command failure. The runner is
designed for bounded fan-out (up to ~32 hosts); for larger fleets, swap the
ThreadPoolExecutor concurrency dial.

Host-key policy:
  Default behaviour rejects unknown host keys (S-INST-004). The operator must
  pre-populate ``~/.ssh/known_hosts`` (e.g. via ``ssh-keyscan``) before deploy
  or pass ``accept_new_hostkeys=True`` once for first-time onboarding. The
  flag maps to ``--accept-new-hostkeys`` on the CLI; in that mode unknown
  keys are added to the operator's local ``known_hosts`` so subsequent runs
  fall back to strict reject.
"""
from __future__ import annotations

import secrets as _secrets
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
        accept_new_hostkeys: bool | None = None,
        known_hosts_path: Path | None = None,
    ) -> None:
        self._max_workers = max_workers
        self._connect_timeout = connect_timeout
        self._command_timeout = command_timeout
        # ``accept_new_hostkeys`` resolution order:
        #   1. Explicit constructor arg.
        #   2. ``MONCTL_ACCEPT_NEW_HOSTKEYS`` env var (set by ``--accept-new-hostkeys``).
        #   3. Default ``False`` → reject unknown keys.
        if accept_new_hostkeys is None:
            import os as _os
            accept_new_hostkeys = _os.environ.get(
                "MONCTL_ACCEPT_NEW_HOSTKEYS", ""
            ).lower() in {"1", "true", "yes"}
        self._accept_new_hostkeys = accept_new_hostkeys
        self._known_hosts_path = known_hosts_path or Path("~/.ssh/known_hosts").expanduser()

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
        """Upload content to ``remote_path`` on ``host`` with the given mode.

        Atomic write: the file is staged at ``remote_path.<rand>.tmp`` with
        the requested mode set *before* the rename, then ``posix_rename``'d
        into place. This closes the chmod-after-write race the previous
        non-atomic implementation had on ``.env`` files (S-INST-014).
        """
        try:
            with self._connect(host) as client:
                sftp = client.open_sftp()
                try:
                    _ensure_remote_parent(sftp, remote_path)
                    tmp_path = f"{remote_path}.{_secrets.token_hex(6)}.tmp"
                    try:
                        with sftp.file(tmp_path, "w") as rf:
                            rf.write(content)
                        # chmod the tmp file BEFORE the rename so the final
                        # path is never observable with default umask.
                        sftp.chmod(tmp_path, mode)
                        try:
                            sftp.posix_rename(tmp_path, remote_path)
                        except (AttributeError, OSError):
                            # posix_rename unsupported on the remote (very
                            # old OpenSSH). Fall back to plain rename —
                            # tmp's mode is already correct so a brief
                            # presence of the final path under default
                            # umask is impossible.
                            try:
                                sftp.remove(remote_path)
                            except (FileNotFoundError, OSError):
                                pass
                            sftp.rename(tmp_path, remote_path)
                    except Exception:
                        # Best-effort cleanup of stale tmp on any failure.
                        try:
                            sftp.remove(tmp_path)
                        except (FileNotFoundError, OSError):
                            pass
                        raise
                finally:
                    sftp.close()
        except (paramiko.SSHException, OSError) as exc:
            raise SSHError(f"{host.name}: scp {remote_path}: {exc}") from exc

    @contextmanager
    def _connect(self, host: Host) -> Iterator[paramiko.SSHClient]:
        client = paramiko.SSHClient()
        # Strict by default: reject unknown host keys. First-time onboarding
        # must pass ``accept_new_hostkeys=True`` (CLI: --accept-new-hostkeys)
        # which adds keys to the operator's local known_hosts so subsequent
        # runs are strict again.
        if self._accept_new_hostkeys:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        # Load known hosts (system + project-level) so strict policy can
        # actually accept previously-trusted hosts.
        try:
            client.load_system_host_keys()
        except (FileNotFoundError, OSError):
            pass
        try:
            if self._known_hosts_path.exists():
                client.load_host_keys(str(self._known_hosts_path))
        except OSError:
            pass

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
        try:
            client.connect(**kwargs)
        except paramiko.SSHException as exc:
            # Wrap host-key-mismatch errors with a clear remediation hint —
            # operators hit this any time a remote host's SSH key changes
            # (reinstall, key rotation) or on first-time onboarding.
            msg = str(exc)
            if "host key" in msg.lower() or isinstance(exc, paramiko.BadHostKeyException):
                raise SSHError(
                    f"{host.name} ({host.address}): host key not in known_hosts. "
                    f"Add it via `ssh-keyscan -H {host.address} >> {self._known_hosts_path}` "
                    f"or re-run with --accept-new-hostkeys for first-time onboarding."
                ) from exc
            raise
        # In accept-new-hostkeys mode, persist any newly-trusted key to disk
        # so subsequent runs are strict again. ``AutoAddPolicy`` only stages
        # the key in memory.
        if self._accept_new_hostkeys:
            try:
                self._known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
                client.save_host_keys(str(self._known_hosts_path))
            except OSError:
                pass
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
