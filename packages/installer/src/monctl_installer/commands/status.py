"""`monctl_ctl status` — probe every host and summarise cluster health.

Runs in parallel: SSH to each host, fire a role-appropriate probe, collect
results into a Rich table.

Probes:
  * central → GET http://localhost:8443/v1/health (via curl from inside the host)
  * postgres (HA) → GET http://localhost:8008/ (Patroni REST) and parse role
  * clickhouse → clickhouse-client --query "SELECT 1"
  * redis → redis-cli PING + INFO replication role line
  * collector → docker compose ps service state count
  * any host → `docker ps` count as a fallback liveness signal
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from rich.console import Console
from rich.table import Table

from monctl_installer.inventory.planner import Plan, plan_cluster
from monctl_installer.inventory.schema import Host
from monctl_installer.remote.ssh import CommandResult, SSHError, SSHRunner

Severity = Literal["ok", "warn", "down"]


@dataclass(frozen=True)
class ProbeResult:
    host: str
    subsystem: str
    severity: Severity
    detail: str


@dataclass(frozen=True)
class StatusSummary:
    results: list[ProbeResult]

    @property
    def has_down(self) -> bool:
        return any(r.severity == "down" for r in self.results)


def run_status(plan: Plan, runner: SSHRunner) -> StatusSummary:
    results: list[ProbeResult] = []
    for host in plan.inventory.hosts:
        try:
            results.extend(_probe_host(host, plan, runner))
        except SSHError as exc:
            results.append(ProbeResult(host.name, "ssh", "down", str(exc)))
    return StatusSummary(results=results)


def _probe_host(host: Host, plan: Plan, runner: SSHRunner) -> list[ProbeResult]:
    out: list[ProbeResult] = []
    out.append(_probe_containers(host, runner))
    if host.has_role("central"):
        out.append(_probe_central(host, runner))
    if host.has_role("postgres") and plan.pg_ha:
        out.append(_probe_patroni(host, runner))
    if host.has_role("clickhouse"):
        out.append(_probe_clickhouse(host, runner))
    if host.has_role("redis") and any(
        r.host.name == host.name for r in plan.redis
    ):
        out.append(_probe_redis(host, runner))
    if host.has_role("superset"):
        out.append(_probe_superset(host, runner))
    return out


def _probe_containers(host: Host, runner: SSHRunner) -> ProbeResult:
    r = runner.run(host, "docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null")
    if not r.ok:
        return ProbeResult(host.name, "docker", "down", "docker ps failed")
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    unhealthy = [l for l in lines if "unhealthy" in l.lower()]
    if unhealthy:
        return ProbeResult(
            host.name, "docker", "warn", f"{len(unhealthy)} unhealthy / {len(lines)} containers"
        )
    return ProbeResult(host.name, "docker", "ok", f"{len(lines)} containers up")


def _probe_central(host: Host, runner: SSHRunner) -> ProbeResult:
    r = runner.run(
        host,
        "curl -sfk --max-time 5 http://localhost:8443/v1/health 2>&1 || echo FAIL",
    )
    body = r.stdout.strip()
    if "FAIL" in body or not r.ok:
        return ProbeResult(host.name, "central", "down", "HTTP 8443 /v1/health unreachable")
    # Body is JSON: {"status":"success","data":{"overall_status":"healthy",...}}
    try:
        parsed = json.loads(body)
        status = parsed.get("data", {}).get("overall_status") or parsed.get("status")
    except json.JSONDecodeError:
        status = None
    if status in ("healthy", "success"):
        return ProbeResult(host.name, "central", "ok", "/v1/health=200 healthy")
    if status in ("degraded",):
        return ProbeResult(host.name, "central", "warn", "degraded")
    return ProbeResult(host.name, "central", "warn", f"health body unparsed ({body[:80]})")


def _probe_patroni(host: Host, runner: SSHRunner) -> ProbeResult:
    r = runner.run(host, "curl -sf --max-time 5 http://localhost:8008/ 2>&1 || echo FAIL")
    if "FAIL" in r.stdout:
        return ProbeResult(host.name, "patroni", "down", ":8008 unreachable")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return ProbeResult(host.name, "patroni", "warn", "unparseable response")
    role = data.get("role", "?")
    state = data.get("state", "?")
    if state != "running":
        return ProbeResult(host.name, "patroni", "down", f"state={state}")
    return ProbeResult(host.name, "patroni", "ok", f"role={role} state={state}")


def _probe_clickhouse(host: Host, runner: SSHRunner) -> ProbeResult:
    # docker exec into the ch container; container_name is 'clickhouse' per our template.
    r = runner.run(
        host,
        "docker exec clickhouse clickhouse-client --query 'SELECT 1' 2>&1 || echo FAIL",
    )
    body = r.stdout.strip()
    if "FAIL" in body or body != "1":
        return ProbeResult(host.name, "clickhouse", "down", f"SELECT 1 failed: {body[:80]}")
    return ProbeResult(host.name, "clickhouse", "ok", "SELECT 1 → 1")


def _probe_superset(host: Host, runner: SSHRunner) -> ProbeResult:
    r = runner.run(
        host,
        "curl -sf --max-time 5 http://localhost:8088/bi/health 2>&1 || echo FAIL",
    )
    body = r.stdout.strip()
    if "FAIL" in body or not r.ok:
        return ProbeResult(host.name, "superset", "down", ":8088 /bi/health unreachable")
    if body == "OK":
        return ProbeResult(host.name, "superset", "ok", "/bi/health=OK")
    return ProbeResult(host.name, "superset", "warn", f"unexpected body: {body[:80]}")


def _probe_redis(host: Host, runner: SSHRunner) -> ProbeResult:
    r = runner.run(
        host,
        "docker exec redis redis-cli INFO replication 2>&1 | head -10 || echo FAIL",
    )
    if "FAIL" in r.stdout or not r.ok:
        return ProbeResult(host.name, "redis", "down", "redis-cli failed")
    # INFO output includes `role:master` or `role:slave`; modern redis uses `role:replica`.
    m = re.search(r"^role:(\S+)", r.stdout, flags=re.MULTILINE)
    role = m.group(1) if m else "?"
    return ProbeResult(host.name, "redis", "ok", f"role={role}")


def print_table(summary: StatusSummary, console: Console) -> None:
    table = Table(title="MonCTL cluster status", show_lines=False)
    table.add_column("Host", style="cyan", no_wrap=True)
    table.add_column("Subsystem", no_wrap=True)
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for r in summary.results:
        colour = {"ok": "green", "warn": "yellow", "down": "red"}[r.severity]
        table.add_row(r.host, r.subsystem, f"[{colour}]{r.severity}[/{colour}]", r.detail)
    console.print(table)
    down = sum(1 for r in summary.results if r.severity == "down")
    warn = sum(1 for r in summary.results if r.severity == "warn")
    if down:
        console.print(f"[red]{down} subsystem(s) down[/red]")
    elif warn:
        console.print(f"[yellow]{warn} warning(s)[/yellow]")
    else:
        console.print("[green]all subsystems healthy[/green]")
