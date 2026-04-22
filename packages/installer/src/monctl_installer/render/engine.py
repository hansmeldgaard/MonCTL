"""Jinja2 render engine — turns a Plan into per-host compose project bundles.

Output layout mirrors prod: `out/<host>/<project>/{docker-compose.yml,.env,<configs>}`.
Each project maps to a directory under `/opt/monctl/<project>/` on the target host.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from monctl_installer.inventory.planner import (
    ClickHouseNode,
    Host,
    Plan,
    PostgresNode,
    RedisNode,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class RenderedFile:
    project: str  # directory name, e.g. "central", "postgres"
    filename: str  # file within that directory, e.g. "docker-compose.yml"
    content: str


class RenderEngine:
    def __init__(self, templates_dir: Path | None = None) -> None:
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir or TEMPLATES_DIR)),
            autoescape=select_autoescape(disabled_extensions=("j2",)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["comma_join"] = lambda xs: ",".join(xs)

    def render_host(self, host: Host, plan: Plan) -> list[RenderedFile]:
        out: list[RenderedFile] = []

        # Each role on this host may contribute one or more files.
        if host.has_role("postgres"):
            out += self._render_postgres(host, plan)
        if host.has_role("etcd") and plan.pg_ha:
            out += self._render_etcd(host, plan)
        if self._redis_on_host(host, plan):
            out += self._render_redis(host, plan)
        if host.has_role("clickhouse"):
            out += self._render_clickhouse(host, plan)
        if host.has_role("clickhouse_keeper") and plan.keeper_mode == "dedicated":
            out += self._render_clickhouse_keeper(host, plan)
        if host.has_role("central"):
            out += self._render_central(host, plan)
        if host.has_role("haproxy") and plan.haproxy_enabled:
            out += self._render_haproxy(host, plan)
        if host.has_role("collector"):
            out += self._render_collector(host, plan)
        # docker-stats sidecar is implicit on every host that has any other role
        out += self._render_docker_stats(host, plan)
        return out

    # ── per-role renderers ────────────────────────────────────────────────

    def _render_postgres(self, host: Host, plan: Plan) -> list[RenderedFile]:
        node = next((n for n in plan.postgres if n.host.name == host.name), None)
        if node is None:
            return []
        ctx = self._base_ctx(host, plan) | {"pg_node": node}
        files = [
            RenderedFile(
                "postgres",
                "docker-compose.yml",
                self._render("compose/postgres.yml.j2", ctx),
            ),
            RenderedFile(
                "postgres",
                ".env",
                self._render("env/postgres.env.j2", ctx),
            ),
        ]
        if plan.pg_ha:
            files.append(
                RenderedFile(
                    "postgres",
                    "patroni.yml",
                    self._render("config/patroni.yml.j2", ctx),
                )
            )
        return files

    def _render_etcd(self, host: Host, plan: Plan) -> list[RenderedFile]:
        ctx = self._base_ctx(host, plan)
        return [
            RenderedFile("etcd", "docker-compose.yml", self._render("compose/etcd.yml.j2", ctx)),
            RenderedFile("etcd", ".env", self._render("env/etcd.env.j2", ctx)),
        ]

    def _redis_on_host(self, host: Host, plan: Plan) -> bool:
        return any(r.host.name == host.name for r in plan.redis)

    def _render_redis(self, host: Host, plan: Plan) -> list[RenderedFile]:
        node = next(r for r in plan.redis if r.host.name == host.name)
        ctx = self._base_ctx(host, plan) | {"redis_node": node}
        files = [
            RenderedFile("redis", "docker-compose.yml", self._render("compose/redis.yml.j2", ctx)),
            RenderedFile("redis", ".env", self._render("env/redis.env.j2", ctx)),
        ]
        if plan.redis_sentinel:
            files.append(
                RenderedFile(
                    "redis",
                    "sentinel.conf",
                    self._render("config/sentinel.conf.j2", ctx),
                )
            )
        return files

    def _render_clickhouse(self, host: Host, plan: Plan) -> list[RenderedFile]:
        node = next(n for n in plan.clickhouse if n.host.name == host.name)
        ctx = self._base_ctx(host, plan) | {"ch_node": node}
        return [
            RenderedFile(
                "clickhouse",
                "docker-compose.yml",
                self._render("compose/clickhouse.yml.j2", ctx),
            ),
            RenderedFile("clickhouse", ".env", self._render("env/clickhouse.env.j2", ctx)),
            RenderedFile(
                "clickhouse",
                "clickhouse-config.xml",
                self._render("config/clickhouse-config.xml.j2", ctx),
            ),
        ]

    def _render_clickhouse_keeper(self, host: Host, plan: Plan) -> list[RenderedFile]:
        ctx = self._base_ctx(host, plan)
        return [
            RenderedFile(
                "clickhouse-keeper",
                "docker-compose.yml",
                self._render("compose/clickhouse-keeper.yml.j2", ctx),
            ),
            RenderedFile(
                "clickhouse-keeper",
                "clickhouse-keeper-config.xml",
                self._render("config/clickhouse-keeper-config.xml.j2", ctx),
            ),
        ]

    def _render_central(self, host: Host, plan: Plan) -> list[RenderedFile]:
        ctx = self._base_ctx(host, plan)
        return [
            RenderedFile(
                "central", "docker-compose.yml", self._render("compose/central.yml.j2", ctx)
            ),
            RenderedFile("central", ".env", self._render("env/central.env.j2", ctx)),
        ]

    def _render_haproxy(self, host: Host, plan: Plan) -> list[RenderedFile]:
        ctx = self._base_ctx(host, plan)
        return [
            RenderedFile(
                "haproxy", "docker-compose.yml", self._render("compose/haproxy.yml.j2", ctx)
            ),
            RenderedFile("haproxy", ".env", self._render("env/haproxy.env.j2", ctx)),
            RenderedFile("haproxy", "haproxy.cfg", self._render("config/haproxy.cfg.j2", ctx)),
            RenderedFile(
                "haproxy",
                "keepalived.conf",
                self._render("config/keepalived.conf.j2", ctx),
            ),
        ]

    def _render_collector(self, host: Host, plan: Plan) -> list[RenderedFile]:
        ctx = self._base_ctx(host, plan)
        return [
            RenderedFile(
                "collector",
                "docker-compose.yml",
                self._render("compose/collector.yml.j2", ctx),
            ),
            RenderedFile("collector", ".env", self._render("env/collector.env.j2", ctx)),
        ]

    def _render_docker_stats(self, host: Host, plan: Plan) -> list[RenderedFile]:
        ctx = self._base_ctx(host, plan)
        return [
            RenderedFile(
                "docker-stats",
                "docker-compose.yml",
                self._render("compose/docker-stats.yml.j2", ctx),
            ),
            RenderedFile("docker-stats", ".env", self._render("env/docker-stats.env.j2", ctx)),
        ]

    # ── helpers ──────────────────────────────────────────────────────────

    def _render(self, template_name: str, ctx: dict[str, object]) -> str:
        return self.env.get_template(template_name).render(**ctx)

    def _base_ctx(self, host: Host, plan: Plan) -> dict[str, object]:
        pg_primary_host = _pg_primary_host(plan)
        central_api_url = _central_api_url(plan, host)
        return {
            "host": host,
            "plan": plan,
            "cluster": plan.inventory.cluster,
            "hosts": plan.inventory.hosts,
            "sizing": plan.inventory.sizing,
            "pg_primary_host": pg_primary_host,
            "pg_host_for_central": _pg_host_for_central(plan, host),
            "redis_host_for_central": _redis_host_for_central(plan, host),
            "clickhouse_hosts_csv": ",".join(n.host.address for n in plan.clickhouse),
            "central_hosts_csv": ",".join(h.address for h in plan.central_hosts),
            "etcd_hosts_csv": ",".join(f"{h.address}:2379" for h in plan.etcd_hosts),
            "redis_sentinel_hosts_csv": ",".join(
                f"{r.host.address}:26379" for r in plan.redis if r.sentinel
            ),
            "patroni_nodes_csv": ",".join(
                f"{n.host.name}:{n.host.address}" for n in plan.postgres
            ),
            "etcd_nodes_csv": ",".join(f"{h.name}:{h.address}" for h in plan.etcd_hosts),
            "docker_stats_hosts_csv": ",".join(
                f"{h.name}:{h.address}" for h in plan.inventory.hosts
            ),
            "central_api_url": central_api_url,
            "central_role": _central_role(plan, host),
        }


def _pg_primary_host(plan: Plan) -> Host:
    """First postgres node is the primary (or the only standalone)."""
    return plan.postgres[0].host


def _pg_host_for_central(plan: Plan, central_host: Host) -> str:
    """DB host the central app connects to.

    HA: via HAProxy-local TCP (5432) when central and haproxy co-locate on any host;
    else directly to primary address.
    Standalone: primary host address.
    """
    if plan.pg_ha and plan.haproxy_enabled:
        return "127.0.0.1"  # HAProxy front-ends PG on port 5432 per current setup
    return _pg_primary_host(plan).address


def _redis_host_for_central(plan: Plan, central_host: Host) -> str:
    if plan.redis_sentinel:
        # Central resolves via Sentinel — first sentinel address is fine as bootstrap.
        return plan.redis[0].host.address
    return plan.redis[0].host.address


def _central_api_url(plan: Plan, host: Host) -> str:
    if plan.vip:
        return f"https://{plan.vip}"
    return f"https://{plan.central_hosts[0].address}:8443"


def _central_role(plan: Plan, host: Host) -> str:
    """Only one central should run the scheduler; pick the first central host."""
    if plan.central_hosts and plan.central_hosts[0].name == host.name:
        return "all"
    return "api"


def render_plan(plan: Plan, out_dir: Path) -> dict[str, list[Path]]:
    """Render plan to disk. Returns map of host name → list of files written."""
    engine = RenderEngine()
    written: dict[str, list[Path]] = {}
    for host in plan.inventory.hosts:
        files = engine.render_host(host, plan)
        host_dir = out_dir / host.name
        paths: list[Path] = []
        for f in files:
            target = host_dir / f.project / f.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content)
            paths.append(target)
        written[host.name] = paths
    return written
