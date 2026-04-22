"""upgrade tests — SSHRunner stubbed + sleep injected, no network + no real waits."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest
import yaml

from monctl_installer.commands.deploy import STATE_PATH
from monctl_installer.commands.upgrade import UpgradeAborted, upgrade
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
        if "curl" in cmd and "/v1/health" in cmd:
            # Default: healthy. Tests can override via responder.
            if self._responder:
                return self._responder(host, cmd)
            return CommandResult(host.name, cmd, 0, '{"status":"success"}', "")
        if self._responder:
            return self._responder(host, cmd)
        return CommandResult(host.name, cmd, 0, "", "")

    def put(self, host: Host, content: str, remote_path: str, mode: int = 0o644) -> None:
        self.uploads[(host.name, remote_path)] = content
        if remote_path == STATE_PATH:
            self._state[host.name] = json.loads(content)


@pytest.fixture()
def seeded_install(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Large inventory → tmp + secrets.env next to it."""
    inv = tmp_path / "inventory.yaml"
    doc = yaml.safe_load(LARGE.read_text())
    doc["secrets"]["file"] = str(tmp_path / "secrets.env")
    inv.write_text(yaml.safe_dump(doc, sort_keys=False))
    write_secrets(generate_secrets(), tmp_path / "secrets.env")
    return inv


def _noop_sleep(_: float) -> None:
    return None


def test_upgrade_uses_new_tag_in_central_compose(seeded_install: Path) -> None:
    runner = FakeRunner()
    steps = upgrade(
        seeded_install,
        version="v1.2.3",
        runner=runner,  # type: ignore[arg-type]
        sleep=_noop_sleep,
    )
    assert not any(s.status == "failed" for s in steps), steps
    # The rendered central compose that was uploaded must reference v1.2.3
    canary_central = next(
        content
        for (host, path), content in runner.uploads.items()
        if host == "mon1" and path.endswith("central/docker-compose.yml")
    )
    assert "monctl-central:v1.2.3" in canary_central
    assert ":latest" not in canary_central


def test_upgrade_canary_first(seeded_install: Path) -> None:
    runner = FakeRunner()
    steps = upgrade(
        seeded_install,
        version="v1.2.3",
        canary="mon2",
        runner=runner,  # type: ignore[arg-type]
        sleep=_noop_sleep,
    )
    first_upgraded = next(s for s in steps if s.status == "upgraded")
    assert first_upgraded.host == "mon2"
    assert first_upgraded.phase == "canary"


def test_upgrade_aborts_if_canary_unhealthy(seeded_install: Path) -> None:
    # Simulate /v1/health never returning healthy.
    def responder(host: Host, cmd: str) -> CommandResult:
        if "/v1/health" in cmd:
            return CommandResult(host.name, cmd, 0, "FAIL\n", "")
        return CommandResult(host.name, cmd, 0, "", "")

    runner = FakeRunner(responder=responder)
    with pytest.raises(UpgradeAborted):
        upgrade(
            seeded_install,
            version="v1.2.3",
            runner=runner,  # type: ignore[arg-type]
            health_timeout_s=1,
            health_interval_s=0.01,
            sleep=_noop_sleep,
        )


def test_upgrade_unchanged_on_same_tag(seeded_install: Path) -> None:
    """If the cluster is already on the target tag, upgrade is a no-op."""
    r1 = FakeRunner()
    upgrade(
        seeded_install,
        version="v1.2.3",
        runner=r1,  # type: ignore[arg-type]
        sleep=_noop_sleep,
    )
    # Second run with same tag should see no changes.
    r2 = FakeRunner()
    r2._state.update(r1._state)  # type: ignore[attr-defined]
    steps2 = upgrade(
        seeded_install,
        version="v1.2.3",
        runner=r2,  # type: ignore[arg-type]
        sleep=_noop_sleep,
    )
    assert all(s.status == "unchanged" for s in steps2), steps2
    # No docker compose up ran at all
    assert not any("docker compose up" in cmd for _, cmd in r2.runs)


def test_upgrade_invalid_canary_rejected(seeded_install: Path) -> None:
    runner = FakeRunner()
    with pytest.raises(ValueError, match="not a central host"):
        upgrade(
            seeded_install,
            version="v1.2.3",
            canary="nope",
            runner=runner,  # type: ignore[arg-type]
            sleep=_noop_sleep,
        )
