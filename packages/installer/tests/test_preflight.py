"""Preflight logic tests — SSHRunner is stubbed so no network required."""
from __future__ import annotations

from typing import Callable

import pytest

from monctl_installer.inventory.planner import plan_cluster
from monctl_installer.inventory.schema import ClusterConfig, Host, Inventory, SSHConfig, Sizing
from monctl_installer.remote.preflight import run_preflight
from monctl_installer.remote.ssh import CommandResult, SSHError


class StubRunner:
    """Route commands through a user-supplied callable for deterministic tests."""

    def __init__(self, responder: Callable[[Host, str], CommandResult | SSHError]) -> None:
        self._responder = responder

    def run(self, host: Host, command: str) -> CommandResult:
        result = self._responder(host, command)
        if isinstance(result, SSHError):
            raise result
        return result


def _host(name: str, address: str, roles: list[str]) -> Host:
    return Host(name=name, address=address, ssh=SSHConfig(), roles=roles)  # type: ignore[arg-type]


def _small_plan():  # type: ignore[no-untyped-def]
    inv = Inventory(
        version=1,
        cluster=ClusterConfig(name="t"),
        hosts=[
            _host(
                "box",
                "10.0.0.1",
                ["postgres", "redis", "clickhouse", "central", "collector", "docker_stats"],
            )
        ],
        sizing=Sizing.model_validate(
            {
                "postgres": {"mode": "standalone"},
                "clickhouse": {"shards": 1, "replicas": 1, "keeper": "embedded"},
                "redis": {"mode": "single"},
                "central": {"tls_behind_haproxy": False},
            }
        ),
    )
    return plan_cluster(inv)


def test_ssh_unreachable_short_circuits() -> None:
    def responder(host: Host, cmd: str) -> CommandResult | SSHError:
        return SSHError(f"{host.name}: connection refused")

    summary = run_preflight(_small_plan(), StubRunner(responder))  # type: ignore[arg-type]
    # Exactly one row per host when SSH fails — no deeper checks attempted.
    assert len(summary.results) == 1
    assert summary.results[0].severity == "fail"
    assert summary.results[0].check == "ssh.reachable"


def test_full_pass_path() -> None:
    def responder(host: Host, cmd: str) -> CommandResult:
        out = ""
        if cmd.startswith("echo ok"):
            out = "ok\n"
        elif cmd.startswith("docker version"):
            out = "26.1.4\n"
        elif cmd.startswith("docker compose version"):
            out = "v2.27.0\n"
        elif cmd.startswith("timedatectl"):
            out = "yes\n"
        elif cmd.startswith("ss -tln"):
            out = ""  # no ports listening
        elif cmd.startswith("free -m"):
            out = "8192\n"
        elif cmd.startswith("df -BG"):
            out = "200G\n"
        return CommandResult(host=host.name, command=cmd, exit_code=0, stdout=out, stderr="")

    summary = run_preflight(_small_plan(), StubRunner(responder))  # type: ignore[arg-type]
    assert not summary.has_failures
    assert any(r.check == "docker.installed" and r.severity == "pass" for r in summary.results)
    assert any(r.check == "time.synced" and r.severity == "pass" for r in summary.results)
    # Ports: expect 5432 (pg standalone), 6379 (redis), 8123 (ch), 9000 (ch), 9181 (embedded keeper),
    # 9234 (keeper raft), 8443 (central), 9100 (docker_stats)
    port_rows = [r for r in summary.results if r.check.startswith("port.")]
    assert len(port_rows) >= 6
    assert all(r.severity == "pass" for r in port_rows)


def test_port_in_use_fails() -> None:
    def responder(host: Host, cmd: str) -> CommandResult:
        if cmd.startswith("echo ok"):
            return CommandResult(host.name, cmd, 0, "ok\n", "")
        if cmd.startswith("ss -tln"):
            return CommandResult(host.name, cmd, 0, "LISTEN 0 128 0.0.0.0:5432 0.0.0.0:*\n", "")
        if cmd.startswith("docker version"):
            return CommandResult(host.name, cmd, 0, "26.1.4\n", "")
        if cmd.startswith("docker compose"):
            return CommandResult(host.name, cmd, 0, "v2.27.0\n", "")
        if cmd.startswith("timedatectl"):
            return CommandResult(host.name, cmd, 0, "yes\n", "")
        if cmd.startswith("free -m"):
            return CommandResult(host.name, cmd, 0, "8192\n", "")
        if cmd.startswith("df -BG"):
            return CommandResult(host.name, cmd, 0, "200G\n", "")
        return CommandResult(host.name, cmd, 0, "", "")

    summary = run_preflight(_small_plan(), StubRunner(responder))  # type: ignore[arg-type]
    port_5432 = next(r for r in summary.results if r.check == "port.5432")
    assert port_5432.severity == "fail"
    assert summary.has_failures


def test_low_ram_fails() -> None:
    def responder(host: Host, cmd: str) -> CommandResult:
        if cmd.startswith("echo ok"):
            return CommandResult(host.name, cmd, 0, "ok\n", "")
        if cmd.startswith("docker version"):
            return CommandResult(host.name, cmd, 0, "26.1.4\n", "")
        if cmd.startswith("docker compose"):
            return CommandResult(host.name, cmd, 0, "v2.27.0\n", "")
        if cmd.startswith("timedatectl"):
            return CommandResult(host.name, cmd, 0, "yes\n", "")
        if cmd.startswith("ss -tln"):
            return CommandResult(host.name, cmd, 0, "", "")
        if cmd.startswith("free -m"):
            return CommandResult(host.name, cmd, 0, "1024\n", "")  # too low
        if cmd.startswith("df -BG"):
            return CommandResult(host.name, cmd, 0, "200G\n", "")
        return CommandResult(host.name, cmd, 0, "", "")

    summary = run_preflight(_small_plan(), StubRunner(responder))  # type: ignore[arg-type]
    ram = next(r for r in summary.results if r.check == "ram.total")
    assert ram.severity == "fail"


def test_time_not_synced_warns() -> None:
    def responder(host: Host, cmd: str) -> CommandResult:
        if cmd.startswith("echo ok"):
            return CommandResult(host.name, cmd, 0, "ok\n", "")
        if cmd.startswith("docker version"):
            return CommandResult(host.name, cmd, 0, "26.1.4\n", "")
        if cmd.startswith("docker compose"):
            return CommandResult(host.name, cmd, 0, "v2.27.0\n", "")
        if cmd.startswith("timedatectl"):
            return CommandResult(host.name, cmd, 0, "no\n", "")
        if cmd.startswith("ss -tln"):
            return CommandResult(host.name, cmd, 0, "", "")
        if cmd.startswith("free -m"):
            return CommandResult(host.name, cmd, 0, "8192\n", "")
        if cmd.startswith("df -BG"):
            return CommandResult(host.name, cmd, 0, "200G\n", "")
        return CommandResult(host.name, cmd, 0, "", "")

    summary = run_preflight(_small_plan(), StubRunner(responder))  # type: ignore[arg-type]
    time_sync = next(r for r in summary.results if r.check == "time.synced")
    assert time_sync.severity == "warn"
    # Warn doesn't block
    assert not summary.has_failures
