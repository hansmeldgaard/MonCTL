"""add-host / remove-host tests — SSHRunner stubbed, no network."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest
import yaml

from monctl_installer.commands.deploy import STATE_PATH
from monctl_installer.commands.topology import (
    LEAF_ROLES,
    TopologyError,
    add_host,
    remove_host,
)
from monctl_installer.inventory.schema import Host
from monctl_installer.remote.ssh import CommandResult
from monctl_installer.secrets.generator import generate_secrets
from monctl_installer.secrets.store import write_secrets

REPO_ROOT = Path(__file__).parents[3]
LARGE = REPO_ROOT / "inventory.example.large.yaml"


class FakeRunner:
    def __init__(self, responder: Callable[[Host, str], CommandResult] | None = None) -> None:
        self.uploads: dict[tuple[str, str], str] = {}
        self.runs: list[tuple[str, str]] = []
        self._state: dict[str, dict[str, str]] = {}
        self._responder = responder

    def run(self, host: Host, cmd: str) -> CommandResult:
        self.runs.append((host.name, cmd))
        if cmd.startswith("cat "):
            state = self._state.get(host.name, {})
            return CommandResult(host.name, cmd, 0, json.dumps(state) or "{}", "")
        if self._responder:
            return self._responder(host, cmd)
        return CommandResult(host.name, cmd, 0, "", "")

    def put(self, host: Host, content: str, remote_path: str, mode: int = 0o644) -> None:
        self.uploads[(host.name, remote_path)] = content
        if remote_path == STATE_PATH:
            self._state[host.name] = json.loads(content)


@pytest.fixture()
def seeded(tmp_path: Path):  # type: ignore[no-untyped-def]
    inv = tmp_path / "inventory.yaml"
    doc = yaml.safe_load(LARGE.read_text())
    doc["secrets"]["file"] = str(tmp_path / "secrets.env")
    inv.write_text(yaml.safe_dump(doc, sort_keys=False))
    write_secrets(generate_secrets(), tmp_path / "secrets.env")
    return inv


def test_add_collector_host_appends_and_deploys(seeded: Path) -> None:
    runner = FakeRunner()
    changes = add_host(
        seeded,
        name="col5",
        address="10.0.0.35",
        roles=["collector", "docker_stats"],
        runner=runner,  # type: ignore[arg-type]
    )
    assert changes == changes  # just sanity
    assert changes[0].action == "added"
    # Inventory now has 16 hosts (15 original + col5)
    doc = yaml.safe_load(seeded.read_text())
    assert any(h["name"] == "col5" for h in doc["hosts"])
    # Only the new host received uploads
    uploaded_hosts = {h for (h, _) in runner.uploads}
    assert uploaded_hosts == {"col5"}
    # docker compose up ran at least once on col5
    up_runs = [cmd for (h, cmd) in runner.runs if h == "col5" and "docker compose up" in cmd]
    assert up_runs


def test_add_rejects_non_leaf_roles(seeded: Path) -> None:
    runner = FakeRunner()
    with pytest.raises(TopologyError, match="leaf roles only"):
        add_host(
            seeded,
            name="ch9",
            address="10.0.0.29",
            roles=["clickhouse"],
            runner=runner,  # type: ignore[arg-type]
        )
    # Inventory must not have been mutated
    doc = yaml.safe_load(seeded.read_text())
    assert not any(h["name"] == "ch9" for h in doc["hosts"])


def test_add_rejects_duplicate_name(seeded: Path) -> None:
    runner = FakeRunner()
    with pytest.raises(TopologyError, match="already present"):
        add_host(
            seeded,
            name="col1",  # already exists
            address="10.0.0.99",
            roles=["collector"],
            runner=runner,  # type: ignore[arg-type]
        )


def test_add_rejects_duplicate_address(seeded: Path) -> None:
    runner = FakeRunner()
    with pytest.raises(TopologyError, match="address.*already present"):
        add_host(
            seeded,
            name="col9",
            address="10.0.0.31",  # col1's address
            roles=["collector"],
            runner=runner,  # type: ignore[arg-type]
        )


def test_remove_collector_host(seeded: Path) -> None:
    runner = FakeRunner()
    changes = remove_host(seeded, name="col4", runner=runner)  # type: ignore[arg-type]
    assert changes[0].action == "removed"
    doc = yaml.safe_load(seeded.read_text())
    assert not any(h["name"] == "col4" for h in doc["hosts"])
    # docker compose down ran on col4 (in reverse order)
    down_runs = [cmd for (h, cmd) in runner.runs if h == "col4" and "docker compose down" in cmd]
    assert down_runs


def test_remove_non_leaf_requires_force(seeded: Path) -> None:
    runner = FakeRunner()
    with pytest.raises(TopologyError, match="non-leaf roles"):
        remove_host(seeded, name="mon1", runner=runner)  # type: ignore[arg-type]
    # Inventory unchanged
    doc = yaml.safe_load(seeded.read_text())
    assert any(h["name"] == "mon1" for h in doc["hosts"])


def test_remove_missing_host_rejected(seeded: Path) -> None:
    runner = FakeRunner()
    with pytest.raises(TopologyError, match="no host named"):
        remove_host(seeded, name="ghost", runner=runner)  # type: ignore[arg-type]


def test_leaf_roles_constant_stable() -> None:
    # Guard against accidental widening that would let add-host plaster
    # new postgres/ch nodes without the required quorum dance.
    assert LEAF_ROLES == frozenset({"collector", "docker_stats"})
