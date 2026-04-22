"""`monctl_ctl validate` — pre-deploy sanity checks, all run over SSH in parallel.

Each check returns a CheckResult; the CLI prints them as a table and exits 1 if
any are critical failures. Warnings don't block deploy but surface in output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from monctl_installer.inventory.planner import Plan
from monctl_installer.inventory.schema import Host, Role
from monctl_installer.remote.ssh import CommandResult, SSHError, SSHRunner

Severity = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class CheckResult:
    host: str
    check: str
    severity: Severity
    detail: str


@dataclass(frozen=True)
class PreflightSummary:
    results: list[CheckResult]

    @property
    def has_failures(self) -> bool:
        return any(r.severity == "fail" for r in self.results)

    @property
    def has_warnings(self) -> bool:
        return any(r.severity == "warn" for r in self.results)


# Minimum RAM/disk recommendations per role — heuristic, override via --min-ram-mb.
_RAM_MB_PER_ROLE: dict[Role, int] = {
    "postgres": 2048,
    "clickhouse": 4096,
    "clickhouse_keeper": 512,
    "etcd": 512,
    "redis": 512,
    "central": 1024,
    "haproxy": 256,
    "collector": 1024,
    "docker_stats": 128,
}

_DISK_GB_PER_ROLE: dict[Role, int] = {
    "postgres": 20,
    "clickhouse": 100,
    "collector": 5,
}


def run_preflight(plan: Plan, runner: SSHRunner) -> PreflightSummary:
    """Execute every preflight check across every host; gather results."""
    results: list[CheckResult] = []
    for host in plan.inventory.hosts:
        results.extend(_check_host(host, plan, runner))
    return PreflightSummary(results=results)


# ── per-host orchestration ─────────────────────────────────────────────────

def _check_host(host: Host, plan: Plan, runner: SSHRunner) -> list[CheckResult]:
    # First: can we SSH at all? If not, bail early with one "fail" row.
    try:
        hello = runner.run(host, "echo ok")
    except SSHError as exc:
        return [CheckResult(host.name, "ssh.reachable", "fail", str(exc))]
    if not hello.ok or "ok" not in hello.stdout:
        return [
            CheckResult(
                host.name,
                "ssh.reachable",
                "fail",
                f"unexpected reply: exit={hello.exit_code} out={hello.stdout!r}",
            )
        ]

    checks: list[CheckResult] = [CheckResult(host.name, "ssh.reachable", "pass", "connected")]
    checks.append(_check_docker(host, runner))
    checks.append(_check_compose(host, runner))
    checks.append(_check_time_sync(host, runner))
    checks.extend(_check_ports(host, runner, _required_ports_for(host, plan)))
    checks.append(_check_ram(host, runner, _min_ram_mb(host)))
    checks.extend(_check_disk(host, runner, _min_disk_gb(host)))
    return checks


# ── individual checks ──────────────────────────────────────────────────────

def _check_docker(host: Host, runner: SSHRunner) -> CheckResult:
    r = runner.run(host, "docker version --format '{{.Server.Version}}' 2>/dev/null")
    if not r.ok or not r.stdout.strip():
        return CheckResult(host.name, "docker.installed", "fail", "docker not installed or daemon down")
    version = r.stdout.strip()
    major = _major_version(version)
    if major is not None and major < 24:
        return CheckResult(
            host.name, "docker.installed", "warn", f"docker {version} (recommend >= 24.x)"
        )
    return CheckResult(host.name, "docker.installed", "pass", version)


def _check_compose(host: Host, runner: SSHRunner) -> CheckResult:
    r = runner.run(host, "docker compose version --short 2>/dev/null")
    if not r.ok or not r.stdout.strip():
        return CheckResult(
            host.name,
            "docker.compose_plugin",
            "fail",
            "docker compose plugin missing (install docker-compose-plugin)",
        )
    return CheckResult(host.name, "docker.compose_plugin", "pass", r.stdout.strip())


def _check_time_sync(host: Host, runner: SSHRunner) -> CheckResult:
    r = runner.run(host, "timedatectl show -p NTPSynchronized --value 2>/dev/null || echo unknown")
    val = r.stdout.strip().lower()
    if val == "yes":
        return CheckResult(host.name, "time.synced", "pass", "NTP synchronized")
    if val in ("no", ""):
        return CheckResult(
            host.name,
            "time.synced",
            "warn",
            "NTP not synchronized — Patroni + ClickHouse replication need synced clocks",
        )
    return CheckResult(host.name, "time.synced", "warn", f"timedatectl unavailable ({val!r})")


def _check_ports(host: Host, runner: SSHRunner, ports: list[int]) -> list[CheckResult]:
    if not ports:
        return []
    cmd = "ss -tlnH 2>/dev/null || netstat -tln 2>/dev/null"
    r = runner.run(host, cmd)
    listening = set(_parse_listening_ports(r.stdout))
    out: list[CheckResult] = []
    for p in ports:
        if p in listening:
            out.append(
                CheckResult(
                    host.name,
                    f"port.{p}",
                    "fail",
                    f"port {p} already in use; stop the process or change the port",
                )
            )
        else:
            out.append(CheckResult(host.name, f"port.{p}", "pass", "free"))
    return out


def _check_ram(host: Host, runner: SSHRunner, min_mb: int) -> CheckResult:
    r = runner.run(host, "free -m | awk '/^Mem:/ {print $2}'")
    try:
        total = int(r.stdout.strip())
    except ValueError:
        return CheckResult(host.name, "ram.total", "warn", "could not parse free -m")
    if total < min_mb:
        return CheckResult(
            host.name, "ram.total", "fail", f"{total} MB < recommended {min_mb} MB"
        )
    return CheckResult(host.name, "ram.total", "pass", f"{total} MB")


def _check_disk(host: Host, runner: SSHRunner, disk_specs: dict[str, int]) -> list[CheckResult]:
    out: list[CheckResult] = []
    for mount, min_gb in disk_specs.items():
        r = runner.run(host, f"df -BG --output=avail {mount} 2>/dev/null | tail -1")
        val = r.stdout.strip().rstrip("G")
        try:
            avail = int(val)
        except ValueError:
            out.append(
                CheckResult(
                    host.name,
                    f"disk.{mount}",
                    "warn",
                    f"could not read df for {mount}",
                )
            )
            continue
        if avail < min_gb:
            out.append(
                CheckResult(
                    host.name,
                    f"disk.{mount}",
                    "fail",
                    f"{avail} GB free < recommended {min_gb} GB",
                )
            )
        else:
            out.append(
                CheckResult(host.name, f"disk.{mount}", "pass", f"{avail} GB free")
            )
    return out


# ── helpers ────────────────────────────────────────────────────────────────

def _required_ports_for(host: Host, plan: Plan) -> list[int]:
    ports: set[int] = set()
    if host.has_role("postgres"):
        ports.update({5432, 5433, 8008} if plan.pg_ha else {5432})
    if host.has_role("etcd"):
        ports.update({2379, 2380})
    if host.has_role("redis"):
        ports.add(6379)
        if plan.redis_sentinel:
            ports.add(26379)
    if host.has_role("clickhouse"):
        ports.update({8123, 9000})
        if any(n.host.name == host.name and n.embedded_keeper for n in plan.clickhouse):
            ports.update({9181, 9234})
    if host.has_role("central"):
        ports.add(8443)
    if host.has_role("haproxy") and plan.haproxy_enabled:
        ports.update({443, 8404})
    if host.has_role("docker_stats"):
        ports.add(9100)
    return sorted(ports)


def _min_ram_mb(host: Host) -> int:
    return max((_RAM_MB_PER_ROLE.get(r, 0) for r in host.roles), default=512)


def _min_disk_gb(host: Host) -> dict[str, int]:
    specs: dict[str, int] = {}
    if any(r in host.roles for r in ("postgres", "clickhouse", "collector")):
        root_gb = max(_DISK_GB_PER_ROLE.get(r, 0) for r in host.roles if r in _DISK_GB_PER_ROLE)
        specs["/"] = root_gb
    else:
        specs["/"] = 5
    return specs


def _parse_listening_ports(output: str) -> list[int]:
    ports: list[int] = []
    for line in output.splitlines():
        parts = line.split()
        if not parts:
            continue
        addr = parts[3] if len(parts) >= 4 else parts[-1]
        if ":" not in addr:
            continue
        port_str = addr.rsplit(":", 1)[-1]
        try:
            ports.append(int(port_str))
        except ValueError:
            pass
    return ports


def _major_version(v: str) -> int | None:
    digits = ""
    for ch in v:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else None
