"""End-to-end render tests: load example inventory, run planner, render, validate."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from monctl_installer.commands.render import run as run_render

REPO_ROOT = Path(__file__).parents[3]
EXAMPLES = [
    REPO_ROOT / "inventory.example.micro.yaml",
    REPO_ROOT / "inventory.example.small.yaml",
    REPO_ROOT / "inventory.example.large.yaml",
]


@pytest.mark.parametrize("inventory", EXAMPLES, ids=lambda p: p.stem)
def test_example_renders_cleanly(inventory: Path, tmp_path: Path) -> None:
    assert inventory.exists(), f"example inventory missing: {inventory}"
    written = run_render(inventory_path=inventory, out_dir=tmp_path)
    assert written, "no hosts rendered"

    for files in written.values():
        for f in files:
            assert f.exists()
            if f.name.endswith((".yml", ".yaml")):
                yaml.safe_load(f.read_text())  # must parse
            elif f.suffix == ".xml":
                ET.parse(f)  # must parse


def test_micro_produces_standalone_postgres(tmp_path: Path) -> None:
    written = run_render(
        inventory_path=REPO_ROOT / "inventory.example.micro.yaml", out_dir=tmp_path
    )
    pg_compose = [f for f in written["box"] if f.parent.name == "postgres" and f.name.endswith(".yml")]
    assert len(pg_compose) == 1
    content = pg_compose[0].read_text()
    assert "postgres:16-alpine" in content
    assert "patroni" not in content


def test_small_produces_patroni(tmp_path: Path) -> None:
    written = run_render(
        inventory_path=REPO_ROOT / "inventory.example.small.yaml", out_dir=tmp_path
    )
    pg_compose = next(
        f for f in written["mon1"] if f.parent.name == "postgres" and f.name.endswith(".yml")
    )
    content = pg_compose.read_text()
    assert "patroni" in content
    assert "postgres:16-alpine" not in content  # Patroni uses timescale image


def test_large_has_haproxy_and_sentinel(tmp_path: Path) -> None:
    written = run_render(
        inventory_path=REPO_ROOT / "inventory.example.large.yaml", out_dir=tmp_path
    )
    assert any(f.parent.name == "haproxy" for f in written["mon1"])
    central = next(
        f for f in written["mon1"] if f.parent.name == "central" and f.name.endswith(".yml")
    )
    content = central.read_text()
    assert "MONCTL_REDIS_SENTINEL_HOSTS" in content
    assert "MONCTL_PATRONI_NODES" in content
    assert "MONCTL_TLS_SAN_IPS: 10.0.0.40" in content


def test_large_ch_shard_layout(tmp_path: Path) -> None:
    written = run_render(
        inventory_path=REPO_ROOT / "inventory.example.large.yaml", out_dir=tmp_path
    )
    ch1_xml = next(f for f in written["ch1"] if f.name == "clickhouse-config.xml")
    tree = ET.parse(ch1_xml)
    shards = tree.findall(".//remote_servers/monctl_cluster/shard")
    assert len(shards) == 4
    for shard in shards:
        replicas = shard.findall("replica")
        assert len(replicas) == 2
