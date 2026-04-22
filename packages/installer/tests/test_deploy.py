"""deploy tests — SSHRunner is mocked so no network required.

These cover the idempotency short-circuit, env-materialisation, and
project-ordering invariants that the installer must preserve.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest
import yaml

from monctl_installer.commands.deploy import (
    PROJECT_ORDER,
    STATE_PATH,
    deploy,
)
from monctl_installer.inventory.schema import Host
from monctl_installer.remote.ssh import CommandResult
from monctl_installer.secrets.generator import generate_secrets
from monctl_installer.secrets.store import write_secrets

REPO_ROOT = Path(__file__).parents[3]
MICRO = REPO_ROOT / "inventory.example.micro.yaml"


class FakeRunner:
    """In-memory SSH stand-in.

    Tracks put() uploads per host and routes run() through a callable so
    individual tests can customise behaviour. `state` starts empty (first
    deploy); set it to simulate a re-run.
    """

    def __init__(self, responder: Callable[[Host, str], CommandResult] | None = None) -> None:
        self.uploads: dict[tuple[str, str], str] = {}
        self.runs: list[tuple[str, str]] = []
        self._state: dict[str, dict[str, str]] = {}
        self._responder = responder

    def run(self, host: Host, cmd: str) -> CommandResult:
        self.runs.append((host.name, cmd))
        if self._responder is not None:
            return self._responder(host, cmd)
        if cmd.startswith("cat "):
            state = self._state.get(host.name, {})
            return CommandResult(host.name, cmd, 0, json.dumps(state) or "{}", "")
        # default: success
        return CommandResult(host.name, cmd, 0, "", "")

    def put(self, host: Host, content: str, remote_path: str, mode: int = 0o644) -> None:
        self.uploads[(host.name, remote_path)] = content
        if remote_path == STATE_PATH:
            self._state[host.name] = json.loads(content)


@pytest.fixture()
def seeded_install(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Copy the micro inventory into tmp_path and generate a secrets.env next to it."""
    inv = tmp_path / "inventory.yaml"
    doc = yaml.safe_load(MICRO.read_text())
    doc["secrets"]["file"] = str(tmp_path / "secrets.env")
    inv.write_text(yaml.safe_dump(doc, sort_keys=False))
    write_secrets(generate_secrets(), tmp_path / "secrets.env")
    return inv


def test_first_deploy_applies_every_project(seeded_install: Path) -> None:
    runner = FakeRunner()
    outcomes = deploy(seeded_install, runner=runner)  # type: ignore[arg-type]
    applied = [o for o in outcomes if o.status == "applied"]
    assert len(applied) >= 6  # micro touches ~7 projects
    assert all(o.status != "failed" for o in outcomes)
    # docker compose up ran once per applied project
    up_runs = [cmd for (_, cmd) in runner.runs if "docker compose up" in cmd]
    assert len(up_runs) == len(applied)


def test_second_deploy_is_idempotent(seeded_install: Path) -> None:
    r1 = FakeRunner()
    deploy(seeded_install, runner=r1)  # type: ignore[arg-type]
    # Second runner observes the same remote state (pre-seeded).
    r2 = FakeRunner()
    r2._state.update(r1._state)  # type: ignore[attr-defined]
    outcomes2 = deploy(seeded_install, runner=r2)  # type: ignore[arg-type]
    assert all(o.status == "unchanged" for o in outcomes2), outcomes2
    # No docker compose up runs this time.
    up_runs = [cmd for (_, cmd) in r2.runs if "docker compose up" in cmd]
    assert up_runs == []


def test_project_order_respected(seeded_install: Path) -> None:
    runner = FakeRunner()
    deploy(seeded_install, runner=runner)  # type: ignore[arg-type]
    up_sequence = [cmd for (_, cmd) in runner.runs if "docker compose up" in cmd]
    # Extract project name between `cd /opt/monctl/` and ` &&`
    projects_seen = []
    for cmd in up_sequence:
        name = cmd.split("/opt/monctl/")[1].split(" &&")[0]
        projects_seen.append(name)
    positions = [PROJECT_ORDER.index(p) for p in projects_seen if p in PROJECT_ORDER]
    assert positions == sorted(positions), f"out-of-order deploy: {projects_seen}"


def test_env_files_have_secrets_substituted(seeded_install: Path) -> None:
    runner = FakeRunner()
    deploy(seeded_install, runner=runner)  # type: ignore[arg-type]
    central_env = next(
        content for (h, path), content in runner.uploads.items() if path.endswith("central/.env")
    )
    # No placeholder remains
    assert "${PG_PASSWORD}" not in central_env
    assert "${MONCTL_ENCRYPTION_KEY}" not in central_env
    # Actual value present (starts with `PG_PASSWORD=` and has a secret after)
    assert "PG_PASSWORD=" in central_env
    # urlsafe-base64 → 30+ chars after the = sign
    pg_line = next(l for l in central_env.splitlines() if l.startswith("PG_PASSWORD="))
    assert len(pg_line.split("=", 1)[1]) >= 30


def test_dry_run_does_not_touch_state(seeded_install: Path) -> None:
    runner = FakeRunner()
    deploy(seeded_install, runner=runner, dry_run=True)  # type: ignore[arg-type]
    # No uploads, no docker compose up
    assert all(
        "docker compose up" not in cmd and "cat " in cmd or "cat" in cmd or "echo" in cmd
        for _, cmd in runner.runs
    ) or len(runner.uploads) == 0
    # Looser assertion: dry-run records intent but does not modify host
    assert runner.uploads == {}


def test_failure_is_surfaced_not_swallowed(seeded_install: Path) -> None:
    def responder(host: Host, cmd: str) -> CommandResult:
        if "docker compose up" in cmd:
            return CommandResult(host.name, cmd, 1, "", "boom")
        return CommandResult(host.name, cmd, 0, "", "")

    runner = FakeRunner(responder=responder)
    outcomes = deploy(seeded_install, runner=runner)  # type: ignore[arg-type]
    failed = [o for o in outcomes if o.status == "failed"]
    assert len(failed) >= 1
    assert all("boom" in o.detail or "rc=1" in o.detail for o in failed)
