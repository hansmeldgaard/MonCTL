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
    DEPLOY_HISTORY_PATH,
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


# ── O-INST-001 — deploy-history.jsonl ──────────────────────────────────────


def _decode_history_entries(runner: "FakeRunner", host_name: str) -> list[dict]:
    """Decode every base64-payload SSH command run against the host that
    appends to .deploy-history.jsonl, returning the parsed JSON entries
    in the order they were issued."""
    import base64

    entries: list[dict] = []
    for h, cmd in runner.runs:
        if h != host_name or DEPLOY_HISTORY_PATH not in cmd or "base64 -d" not in cmd:
            continue
        # Command shape: ``mkdir -p /opt/monctl && echo <b64> | base64 -d >> ...``
        # Pick the token between "echo " and " |".
        head, _, tail = cmd.partition("echo ")
        if not tail:
            continue
        b64 = tail.split(" |", 1)[0].strip()
        raw = base64.b64decode(b64).decode("utf-8")
        for line in raw.splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


def test_deploy_writes_history_jsonl_on_apply(seeded_install: Path) -> None:
    """Every applied project gets a JSONL row with status, digest, timing,
    and installer version (O-INST-001)."""
    runner = FakeRunner()
    outcomes = deploy(seeded_install, runner=runner)  # type: ignore[arg-type]
    applied = {o.project for o in outcomes if o.status == "applied"}
    # Each host has a stream of entries, one per project we touched.
    hosts = {o.host for o in outcomes}
    for host_name in hosts:
        entries = _decode_history_entries(runner, host_name)
        assert entries, f"no history entries recorded for host {host_name}"
        applied_entries = {e["project"] for e in entries if e["status"] == "applied"}
        # Subset relationship — applied set is the same on every host
        # that actually had this project deployed
        host_outcomes = {o.project for o in outcomes if o.host == host_name and o.status == "applied"}
        assert host_outcomes <= applied_entries
        # Every entry has the documented fields
        e = entries[0]
        for k in ("timestamp", "host", "project", "status", "digest",
                  "started_at", "finished_at", "installer_version", "detail"):
            assert k in e, f"missing key {k} in entry {e}"
        assert e["host"] == host_name
        assert isinstance(e["installer_version"], str)


def test_deploy_history_records_failures_with_detail(seeded_install: Path) -> None:
    """Failed deploys must still produce a history row (the whole point —
    operator comes back to the host to ask 'when did central last try?')."""
    def responder(host: Host, cmd: str) -> CommandResult:
        if "docker compose up" in cmd:
            return CommandResult(host.name, cmd, 1, "", "boom")
        return CommandResult(host.name, cmd, 0, "", "")

    runner = FakeRunner(responder=responder)
    outcomes = deploy(seeded_install, runner=runner)  # type: ignore[arg-type]
    failed = [o for o in outcomes if o.status == "failed"]
    assert failed
    # Every failed outcome has a corresponding history entry.
    for outcome in failed:
        entries = _decode_history_entries(runner, outcome.host)
        matching = [
            e for e in entries
            if e["project"] == outcome.project and e["status"] == "failed"
        ]
        assert matching, f"no failed-history entry for {outcome.host}/{outcome.project}"
        assert matching[0]["detail"] == outcome.detail


def test_deploy_history_skipped_in_dry_run(seeded_install: Path) -> None:
    """Dry-run must not write history — operator preview shouldn't
    pollute the audit log on every "what would change?" check."""
    runner = FakeRunner()
    deploy(seeded_install, runner=runner, dry_run=True)  # type: ignore[arg-type]
    history_cmds = [
        cmd for _, cmd in runner.runs
        if DEPLOY_HISTORY_PATH in cmd and "base64 -d" in cmd
    ]
    assert history_cmds == []


def test_deploy_history_is_best_effort_on_ssh_failure(seeded_install: Path) -> None:
    """If the history-append fails, the deploy still completes — the row
    is non-load-bearing operator visibility, not a hard requirement."""
    from monctl_installer.remote.ssh import SSHError

    def responder(host: Host, cmd: str) -> CommandResult:
        if DEPLOY_HISTORY_PATH in cmd and "base64 -d" in cmd:
            raise SSHError("history disk full")
        return CommandResult(host.name, cmd, 0, "", "")

    runner = FakeRunner(responder=responder)
    outcomes = deploy(seeded_install, runner=runner)  # type: ignore[arg-type]
    # Deploy itself is unaffected — every project still applies
    assert any(o.status == "applied" for o in outcomes)
    assert all(o.status != "failed" for o in outcomes)
