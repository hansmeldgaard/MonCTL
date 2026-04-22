from __future__ import annotations

import pytest

from monctl_installer.inventory.planner import PlanError, plan_cluster
from monctl_installer.inventory.schema import (
    ClusterConfig,
    Host,
    Inventory,
    Sizing,
    SSHConfig,
)


def _host(name: str, address: str, roles: list[str]) -> Host:
    return Host(name=name, address=address, ssh=SSHConfig(), roles=roles)  # type: ignore[arg-type]


def _inv(hosts: list[Host], **sizing_overrides) -> Inventory:  # type: ignore[no-untyped-def]
    return Inventory(
        version=1,
        cluster=ClusterConfig(name="test"),
        hosts=hosts,
        sizing=Sizing(**sizing_overrides),
    )


def test_single_host_appliance() -> None:
    inv = _inv(
        hosts=[
            _host(
                "box",
                "10.0.0.1",
                [
                    "postgres",
                    "redis",
                    "clickhouse",
                    "central",
                    "collector",
                    "docker_stats",
                ],
            )
        ]
    )
    plan = plan_cluster(inv)
    assert plan.pg_ha is False
    assert plan.redis_sentinel is False
    assert plan.haproxy_enabled is False
    assert len(plan.postgres) == 1
    assert plan.postgres[0].role == "standalone"
    assert plan.etcd_hosts == []
    assert len(plan.clickhouse) == 1
    assert plan.clickhouse[0].embedded_keeper is True
    assert len(plan.clickhouse_keepers) == 1
    assert plan.redis[0].role == "standalone"


def test_three_host_small() -> None:
    inv = _inv(
        hosts=[
            _host("mon1", "10.0.0.11", ["postgres", "etcd", "redis", "central", "clickhouse"]),
            _host("mon2", "10.0.0.12", ["postgres", "etcd"]),
            _host("mon3", "10.0.0.13", ["etcd"]),
        ]
    )
    plan = plan_cluster(inv)
    assert plan.pg_ha is True
    assert len(plan.postgres) == 2
    assert plan.postgres[0].role == "primary_seed"
    assert plan.postgres[1].role == "replica"
    assert len(plan.etcd_hosts) == 3
    assert plan.redis_sentinel is False  # only one central → single-node redis
    assert len(plan.clickhouse) == 1
    assert plan.clickhouse[0].embedded_keeper is True
    assert plan.haproxy_enabled is False


def test_large_topology() -> None:
    hosts = [
        _host("mon1", "10.0.0.11", ["postgres", "etcd", "redis", "central", "haproxy"]),
        _host("mon2", "10.0.0.12", ["postgres", "etcd", "redis", "central", "haproxy"]),
        _host("mon3", "10.0.0.13", ["postgres", "etcd", "central", "haproxy"]),
    ]
    for i in range(8):
        hosts.append(_host(f"ch{i + 1}", f"10.0.0.{21 + i}", ["clickhouse"]))
    for i in range(4):
        hosts.append(_host(f"col{i + 1}", f"10.0.0.{31 + i}", ["collector"]))

    inv = Inventory(
        version=1,
        cluster=ClusterConfig(name="large", vip="10.0.0.40"),
        hosts=hosts,
        sizing=Sizing.model_validate(
            {
                "postgres": {"mode": "ha"},
                "clickhouse": {"shards": 4, "replicas": 2, "keeper": "embedded"},
                "redis": {"mode": "auto"},
            }
        ),
    )
    plan = plan_cluster(inv)
    assert plan.pg_ha is True
    assert plan.redis_sentinel is True
    assert plan.haproxy_enabled is True
    assert len(plan.etcd_hosts) == 3
    assert len(plan.clickhouse) == 8
    # Embedded keeper on first 3 CH nodes (quorum)
    assert sum(1 for n in plan.clickhouse if n.embedded_keeper) == 3
    assert len(plan.collector_hosts) == 4
    # shard/replica layout: row-major
    assert plan.clickhouse[0].shard == 1 and plan.clickhouse[0].replica == 1
    assert plan.clickhouse[1].shard == 1 and plan.clickhouse[1].replica == 2
    assert plan.clickhouse[2].shard == 2 and plan.clickhouse[2].replica == 1
    assert plan.clickhouse[7].shard == 4 and plan.clickhouse[7].replica == 2


def test_ch_sizing_mismatch_rejected() -> None:
    inv = _inv(
        hosts=[
            _host("a", "10.0.0.1", ["postgres", "central", "clickhouse"]),
            _host("b", "10.0.0.2", ["clickhouse"]),
        ],
        clickhouse={"shards": 2, "replicas": 2, "keeper": "embedded"},
    )
    with pytest.raises(PlanError, match="shards\\*replicas"):
        plan_cluster(inv)


def test_two_node_ch_embedded_rejected() -> None:
    inv = _inv(
        hosts=[
            _host("a", "10.0.0.1", ["postgres", "central", "clickhouse"]),
            _host("b", "10.0.0.2", ["clickhouse"]),
        ],
        clickhouse={"shards": 1, "replicas": 2, "keeper": "embedded"},
    )
    with pytest.raises(PlanError, match="Raft quorum"):
        plan_cluster(inv)


def test_ha_without_enough_pg_rejected() -> None:
    inv = _inv(
        hosts=[_host("a", "10.0.0.1", ["postgres", "central", "clickhouse"])],
        postgres={"mode": "ha"},
    )
    with pytest.raises(PlanError, match="at least 2 postgres"):
        plan_cluster(inv)


def test_ha_without_etcd_rejected() -> None:
    inv = _inv(
        hosts=[
            _host("a", "10.0.0.1", ["postgres", "central", "clickhouse"]),
            _host("b", "10.0.0.2", ["postgres"]),
        ]
    )
    with pytest.raises(PlanError, match="etcd requires 3 or 5"):
        plan_cluster(inv)


def test_vip_requires_haproxy_role() -> None:
    inv = Inventory(
        version=1,
        cluster=ClusterConfig(name="t", vip="10.0.0.40"),
        hosts=[
            _host("a", "10.0.0.1", ["postgres", "etcd", "central", "clickhouse"]),
            _host("b", "10.0.0.2", ["postgres", "etcd", "central"]),
            _host("c", "10.0.0.3", ["etcd", "central"]),
        ],
    )
    with pytest.raises(PlanError, match="haproxy"):
        plan_cluster(inv)
