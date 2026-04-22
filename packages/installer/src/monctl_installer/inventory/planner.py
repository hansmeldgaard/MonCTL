"""Turn an Inventory into a fully-resolved deployment Plan.

The planner is the single source of truth for topology decisions:
  * Patroni vs standalone Postgres
  * Redis single vs Sentinel
  * ClickHouse shard×replica layout + keeper placement
  * etcd quorum membership
  * HAProxy + keepalived emission

Rules are deterministic: the same inventory always produces the same plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from monctl_installer.inventory.schema import Host, Inventory


@dataclass(frozen=True)
class PostgresNode:
    host: Host
    role: Literal["primary_seed", "replica", "standalone"]


@dataclass(frozen=True)
class RedisNode:
    host: Host
    role: Literal["primary", "replica", "standalone"]
    sentinel: bool


@dataclass(frozen=True)
class ClickHouseNode:
    host: Host
    shard: int  # 1-indexed
    replica: int  # 1-indexed
    embedded_keeper: bool
    keeper_id: int | None  # 1-indexed; set only on keeper hosts


@dataclass(frozen=True)
class Plan:
    inventory: Inventory
    postgres: list[PostgresNode]
    etcd_hosts: list[Host]
    redis: list[RedisNode]
    clickhouse: list[ClickHouseNode]
    clickhouse_keepers: list[Host]  # dedicated OR embedded carriers
    central_hosts: list[Host]
    haproxy_hosts: list[Host]
    collector_hosts: list[Host]
    # derived flags
    pg_ha: bool = field(default=False)
    redis_sentinel: bool = field(default=False)
    haproxy_enabled: bool = field(default=False)
    keeper_mode: Literal["embedded", "dedicated"] = "embedded"

    @property
    def cluster_name(self) -> str:
        return self.inventory.cluster.name

    @property
    def vip(self) -> str | None:
        return self.inventory.cluster.vip


class PlanError(Exception):
    """Raised when the inventory describes an unsatisfiable topology."""


def plan_cluster(inv: Inventory) -> Plan:
    pg_hosts = inv.hosts_with("postgres")
    ch_hosts = inv.hosts_with("clickhouse")
    central_hosts = inv.hosts_with("central")
    collector_hosts = inv.hosts_with("collector")

    pg_ha = _resolve_pg_ha(inv, pg_hosts)
    pg_nodes = _plan_postgres(pg_hosts, pg_ha)

    etcd_hosts = _plan_etcd(inv, pg_ha) if pg_ha else []

    redis_sentinel = _resolve_redis_sentinel(inv, central_hosts)
    redis_nodes = _plan_redis(inv, central_hosts, redis_sentinel)

    _validate_ch_sizing(inv, ch_hosts)
    keeper_mode = _resolve_keeper_mode(inv, ch_hosts)
    ch_nodes, keeper_hosts = _plan_clickhouse(inv, ch_hosts, keeper_mode)

    haproxy_enabled = _resolve_haproxy(inv, central_hosts)
    haproxy_hosts = inv.hosts_with("haproxy") if haproxy_enabled else []

    _validate_plan(
        inv=inv,
        pg_nodes=pg_nodes,
        etcd_hosts=etcd_hosts,
        central_hosts=central_hosts,
        ch_nodes=ch_nodes,
        haproxy_enabled=haproxy_enabled,
    )

    return Plan(
        inventory=inv,
        postgres=pg_nodes,
        etcd_hosts=etcd_hosts,
        redis=redis_nodes,
        clickhouse=ch_nodes,
        clickhouse_keepers=keeper_hosts,
        central_hosts=central_hosts,
        haproxy_hosts=haproxy_hosts,
        collector_hosts=collector_hosts,
        pg_ha=pg_ha,
        redis_sentinel=redis_sentinel,
        haproxy_enabled=haproxy_enabled,
        keeper_mode=keeper_mode,
    )


def _resolve_pg_ha(inv: Inventory, pg_hosts: list[Host]) -> bool:
    mode = inv.sizing.postgres.mode
    if mode == "standalone":
        return False
    if mode == "ha":
        if len(pg_hosts) < 2:
            raise PlanError(
                f"postgres.mode=ha requires at least 2 postgres hosts (got {len(pg_hosts)})"
            )
        return True
    # auto
    if not pg_hosts:
        raise PlanError("at least one host must carry the 'postgres' role")
    return len(pg_hosts) > 1


def _plan_postgres(pg_hosts: list[Host], ha: bool) -> list[PostgresNode]:
    if not pg_hosts:
        return []
    if not ha:
        return [PostgresNode(host=pg_hosts[0], role="standalone")]
    first, *rest = pg_hosts
    return [PostgresNode(host=first, role="primary_seed")] + [
        PostgresNode(host=h, role="replica") for h in rest
    ]


def _plan_etcd(inv: Inventory, pg_ha: bool) -> list[Host]:
    if not pg_ha:
        return []
    etcd_hosts = inv.hosts_with("etcd")
    if len(etcd_hosts) not in (3, 5):
        raise PlanError(
            f"etcd requires 3 or 5 hosts for quorum (got {len(etcd_hosts)}); "
            "add 'etcd' role to enough hosts"
        )
    return etcd_hosts


def _resolve_redis_sentinel(inv: Inventory, central_hosts: list[Host]) -> bool:
    mode = inv.sizing.redis.mode
    if mode == "single":
        return False
    if mode == "sentinel":
        if len(central_hosts) < 2:
            raise PlanError(
                "redis.mode=sentinel requires >= 2 central hosts "
                f"(got {len(central_hosts)})"
            )
        return True
    # auto
    return len(central_hosts) > 1


def _plan_redis(
    inv: Inventory, central_hosts: list[Host], sentinel: bool
) -> list[RedisNode]:
    redis_hosts = inv.hosts_with("redis")
    if not redis_hosts:
        # Default: redis co-locates with central hosts if no explicit role.
        redis_hosts = central_hosts
    if not redis_hosts:
        raise PlanError("no host carries redis or central role; at least one required")

    if not sentinel:
        return [RedisNode(host=redis_hosts[0], role="standalone", sentinel=False)]

    # HA: first=primary, rest=replicas; sentinel on every central host.
    primary, *replicas = redis_hosts
    nodes = [RedisNode(host=primary, role="primary", sentinel=True)]
    for h in replicas:
        nodes.append(RedisNode(host=h, role="replica", sentinel=True))
    # Sentinels also run on any central hosts not already in the list.
    seen = {n.host.name for n in nodes}
    for c in central_hosts:
        if c.name not in seen:
            nodes.append(RedisNode(host=c, role="replica", sentinel=True))
            seen.add(c.name)
    return nodes


def _validate_ch_sizing(inv: Inventory, ch_hosts: list[Host]) -> None:
    if not ch_hosts:
        raise PlanError("at least one host must carry the 'clickhouse' role")
    shards = inv.sizing.clickhouse.shards
    replicas = inv.sizing.clickhouse.replicas
    expected = shards * replicas
    if len(ch_hosts) != expected:
        raise PlanError(
            f"clickhouse sizing mismatch: shards*replicas={shards}*{replicas}={expected}, "
            f"but {len(ch_hosts)} hosts carry the clickhouse role"
        )


def _resolve_keeper_mode(inv: Inventory, ch_hosts: list[Host]) -> Literal["embedded", "dedicated"]:
    requested = inv.sizing.clickhouse.keeper
    if requested == "dedicated":
        if not inv.hosts_with("clickhouse_keeper"):
            raise PlanError(
                "clickhouse.keeper=dedicated requires at least one host with "
                "clickhouse_keeper role"
            )
        return "dedicated"
    # embedded: need odd count ≥ 3 CH hosts OR extra clickhouse_keeper hosts
    if len(ch_hosts) >= 3:
        return "embedded"
    # Fewer than 3 CH hosts and embedded requested → fall back to dedicated if available
    if inv.hosts_with("clickhouse_keeper"):
        return "dedicated"
    if len(ch_hosts) == 1:
        # Single-node CH → embedded keeper on that one host is allowed (no quorum needed).
        return "embedded"
    # 2 CH hosts with no extra keeper — unsupported.
    raise PlanError(
        "2 clickhouse hosts with embedded keeper is not a valid Raft quorum; "
        "add a third clickhouse_keeper host or set clickhouse.keeper=dedicated"
    )


def _plan_clickhouse(
    inv: Inventory,
    ch_hosts: list[Host],
    keeper_mode: Literal["embedded", "dedicated"],
) -> tuple[list[ClickHouseNode], list[Host]]:
    shards = inv.sizing.clickhouse.shards
    replicas = inv.sizing.clickhouse.replicas

    # Keeper host selection
    if keeper_mode == "dedicated":
        keeper_hosts = inv.hosts_with("clickhouse_keeper")
    else:
        # Embedded: first min(3, len(ch_hosts)) CH nodes OR all of them if < 3.
        if len(ch_hosts) == 1:
            keeper_hosts = ch_hosts[:1]
        else:
            keeper_hosts = ch_hosts[:3] if len(ch_hosts) >= 3 else ch_hosts

    keeper_ids = {h.name: i + 1 for i, h in enumerate(keeper_hosts)}

    nodes: list[ClickHouseNode] = []
    idx = 0
    for s in range(1, shards + 1):
        for r in range(1, replicas + 1):
            host = ch_hosts[idx]
            embed = keeper_mode == "embedded" and host.name in keeper_ids
            nodes.append(
                ClickHouseNode(
                    host=host,
                    shard=s,
                    replica=r,
                    embedded_keeper=embed,
                    keeper_id=keeper_ids.get(host.name),
                )
            )
            idx += 1
    return nodes, keeper_hosts


def _resolve_haproxy(inv: Inventory, central_hosts: list[Host]) -> bool:
    if inv.cluster.vip:
        if len(central_hosts) < 2:
            raise PlanError("cluster.vip requires >= 2 central hosts for meaningful HA")
        if not inv.hosts_with("haproxy"):
            raise PlanError(
                "cluster.vip set but no host carries the 'haproxy' role"
            )
        return True
    if len(central_hosts) > 1 and inv.hosts_with("haproxy"):
        return True
    return False


def _validate_plan(
    *,
    inv: Inventory,
    pg_nodes: list[PostgresNode],
    etcd_hosts: list[Host],
    central_hosts: list[Host],
    ch_nodes: list[ClickHouseNode],
    haproxy_enabled: bool,
) -> None:
    if not pg_nodes:
        raise PlanError("no postgres nodes resolved")
    if not central_hosts:
        raise PlanError("at least one host must carry the 'central' role")
    if not ch_nodes:
        raise PlanError("no clickhouse nodes resolved")
    if haproxy_enabled and not inv.cluster.vip and len(central_hosts) > 1:
        # HAProxy without a VIP is still useful (local LB) but a warning makes sense.
        # We accept it; customer may front with external LB.
        pass
