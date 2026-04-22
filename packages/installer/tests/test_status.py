"""status probe tests — SSHRunner stubbed, no network."""
from __future__ import annotations

import json
from typing import Callable

from monctl_installer.commands.status import run_status
from monctl_installer.inventory.planner import plan_cluster
from monctl_installer.inventory.schema import ClusterConfig, Host, Inventory, SSHConfig, Sizing
from monctl_installer.remote.ssh import CommandResult


class StubRunner:
    def __init__(self, responder: Callable[[Host, str], CommandResult]) -> None:
        self._responder = responder

    def run(self, host: Host, command: str) -> CommandResult:
        return self._responder(host, command)


def _micro_plan():  # type: ignore[no-untyped-def]
    inv = Inventory(
        version=1,
        cluster=ClusterConfig(name="t"),
        hosts=[
            Host(
                name="box",
                address="10.0.0.1",
                ssh=SSHConfig(),
                roles=["postgres", "redis", "clickhouse", "central", "collector", "docker_stats"],
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


def test_all_healthy() -> None:
    def responder(host: Host, cmd: str) -> CommandResult:
        if cmd.startswith("docker ps --format"):
            return CommandResult(host.name, cmd, 0, "central Up 10m (healthy)\nredis Up 10m\n", "")
        if "curl" in cmd and "8443/v1/health" in cmd:
            body = json.dumps({"status": "success", "data": {"overall_status": "healthy"}})
            return CommandResult(host.name, cmd, 0, body, "")
        if "clickhouse-client" in cmd:
            return CommandResult(host.name, cmd, 0, "1", "")
        if "redis-cli" in cmd:
            return CommandResult(host.name, cmd, 0, "role:master\nconnected_slaves:0\n", "")
        return CommandResult(host.name, cmd, 0, "", "")

    summary = run_status(_micro_plan(), StubRunner(responder))  # type: ignore[arg-type]
    assert not summary.has_down
    subsystems = {r.subsystem for r in summary.results}
    assert {"docker", "central", "clickhouse", "redis"} <= subsystems


def test_central_down_surfaced() -> None:
    def responder(host: Host, cmd: str) -> CommandResult:
        if cmd.startswith("docker ps --format"):
            return CommandResult(host.name, cmd, 0, "foo Up 1m\n", "")
        if "curl" in cmd and "8443/v1/health" in cmd:
            return CommandResult(host.name, cmd, 0, "FAIL\n", "")
        if "clickhouse-client" in cmd:
            return CommandResult(host.name, cmd, 0, "1", "")
        if "redis-cli" in cmd:
            return CommandResult(host.name, cmd, 0, "role:master\n", "")
        return CommandResult(host.name, cmd, 0, "", "")

    summary = run_status(_micro_plan(), StubRunner(responder))  # type: ignore[arg-type]
    central = next(r for r in summary.results if r.subsystem == "central")
    assert central.severity == "down"
    assert summary.has_down


def test_unhealthy_containers_warn() -> None:
    def responder(host: Host, cmd: str) -> CommandResult:
        if cmd.startswith("docker ps --format"):
            return CommandResult(
                host.name, cmd, 0, "central Up 10m (healthy)\nch Up 1m (unhealthy)\n", ""
            )
        if "curl" in cmd and "8443/v1/health" in cmd:
            body = json.dumps({"status": "success", "data": {"overall_status": "healthy"}})
            return CommandResult(host.name, cmd, 0, body, "")
        if "clickhouse-client" in cmd:
            return CommandResult(host.name, cmd, 0, "1", "")
        if "redis-cli" in cmd:
            return CommandResult(host.name, cmd, 0, "role:master\n", "")
        return CommandResult(host.name, cmd, 0, "", "")

    summary = run_status(_micro_plan(), StubRunner(responder))  # type: ignore[arg-type]
    docker_row = next(r for r in summary.results if r.subsystem == "docker")
    assert docker_row.severity == "warn"
    assert "unhealthy" in docker_row.detail
