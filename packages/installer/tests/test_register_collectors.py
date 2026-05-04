"""Tests for ``monctl_ctl register-collectors`` (Wave 2B).

Network is mocked via ``httpx.MockTransport``; SSH is mocked via the
existing ``FakeRunner`` pattern from ``test_deploy.py``. No host or
central is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx
import pytest
import yaml

from monctl_installer.commands.register_collectors import (
    COLLECTOR_ENV_PATH,
    RegisterError,
    RegisterOutcome,
    _substitute_api_key,
    register_collectors,
)
from monctl_installer.inventory.schema import Host
from monctl_installer.remote.ssh import CommandResult, SSHError
from monctl_installer.secrets.generator import generate_secrets
from monctl_installer.secrets.store import write_secrets


REPO_ROOT = Path(__file__).parents[3]
MICRO = REPO_ROOT / "inventory.example.micro.yaml"


# ── Fakes ──────────────────────────────────────────────────────────────────


class FakeRunner:
    """Same shape as test_deploy.FakeRunner, scoped to register_collectors."""

    def __init__(self, env_content: str = "MONCTL_COLLECTOR_API_KEY=shared\n",
                 responder: Callable[[Host, str], CommandResult] | None = None) -> None:
        self.uploads: dict[tuple[str, str], str] = {}
        self.runs: list[tuple[str, str]] = []
        self._env = env_content
        self._responder = responder

    def run(self, host: Host, cmd: str) -> CommandResult:
        self.runs.append((host.name, cmd))
        if self._responder is not None:
            return self._responder(host, cmd)
        if cmd.startswith(f"cat {COLLECTOR_ENV_PATH}"):
            return CommandResult(host.name, cmd, 0, self._env, "")
        # docker compose up etc. — succeed by default
        return CommandResult(host.name, cmd, 0, "", "")

    def put(self, host: Host, content: str, remote_path: str, mode: int = 0o644) -> None:
        self.uploads[(host.name, remote_path)] = content
        if remote_path == COLLECTOR_ENV_PATH:
            self._env = content

    def close(self) -> None:
        pass


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def seeded_install(tmp_path: Path) -> Path:
    inv = tmp_path / "inventory.yaml"
    doc = yaml.safe_load(MICRO.read_text())
    doc["secrets"]["file"] = str(tmp_path / "secrets.env")
    inv.write_text(yaml.safe_dump(doc, sort_keys=False))
    bundle = generate_secrets()
    write_secrets(bundle, tmp_path / "secrets.env")
    return inv


def _make_http_client(
    api_keys: dict[str, str] | None = None,
    *,
    login_status: int = 200,
    login_cookies: dict[str, str] | None = None,
    keymint_status: int = 201,
) -> httpx.Client:
    """Build an httpx.Client whose transport is a MockTransport responding
    only to /v1/auth/login and /v1/collectors/by-hostname/{h}/api-keys.
    """
    api_keys = api_keys or {}
    cookies = login_cookies if login_cookies is not None else {"access_token": "fake"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/login":
            resp = httpx.Response(login_status, json={"status": "success"})
            for k, v in cookies.items():
                resp.headers["set-cookie"] = f"{k}={v}; Path=/; HttpOnly"
            return resp
        if request.url.path.startswith("/v1/collectors/by-hostname/"):
            host_name = request.url.path.split("/")[-2]
            return httpx.Response(
                keymint_status,
                json={
                    "collector_id": f"id-{host_name}",
                    "api_key": api_keys.get(host_name, f"key-{host_name}"),
                    "name": host_name,
                    "status": "PENDING",
                    "created": True,
                },
            )
        return httpx.Response(404, json={"detail": "no mock"})

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="https://central.test")


# ── _substitute_api_key (pure helper) ──────────────────────────────────────


def test_substitute_replaces_existing_line() -> None:
    env = "PG_PASSWORD=x\nMONCTL_COLLECTOR_API_KEY=old-shared\nPEER_TOKEN=y\n"
    assert _substitute_api_key(env, "new-host-key") == (
        "PG_PASSWORD=x\nMONCTL_COLLECTOR_API_KEY=new-host-key\nPEER_TOKEN=y\n"
    )


def test_substitute_appends_when_line_absent() -> None:
    env = "PG_PASSWORD=x\nPEER_TOKEN=y\n"
    out = _substitute_api_key(env, "first-key")
    assert out.endswith("MONCTL_COLLECTOR_API_KEY=first-key\n")


def test_substitute_preserves_no_trailing_newline() -> None:
    """If input lacks trailing newline, output should too — don't drift."""
    env = "MONCTL_COLLECTOR_API_KEY=old"
    assert _substitute_api_key(env, "new") == "MONCTL_COLLECTOR_API_KEY=new"


def test_substitute_does_not_match_commented_line() -> None:
    """A `# MONCTL_COLLECTOR_API_KEY=...` comment shouldn't be substituted —
    rewrite the active key (or append if none)."""
    env = "# MONCTL_COLLECTOR_API_KEY=old-comment\nOTHER=1\n"
    out = _substitute_api_key(env, "fresh")
    assert "# MONCTL_COLLECTOR_API_KEY=old-comment" in out
    assert out.rstrip().endswith("MONCTL_COLLECTOR_API_KEY=fresh")


# ── register_collectors flow ───────────────────────────────────────────────


def test_register_collectors_mints_and_writes_env(seeded_install: Path) -> None:
    runner = FakeRunner()
    client = _make_http_client()
    outcomes = register_collectors(
        seeded_install, runner=runner, http_client=client,
    )
    assert outcomes, "no collector hosts found in seeded micro inventory"
    assert all(o.status == "registered" for o in outcomes), outcomes
    # The collector .env on each host has its per-host key written
    for o in outcomes:
        env = next(
            content for (h, p), content in runner.uploads.items()
            if h == o.host and p == COLLECTOR_ENV_PATH
        )
        assert f"MONCTL_COLLECTOR_API_KEY=key-{o.host}" in env
    # docker compose up was issued for each registered host
    restarts = [
        cmd for (_, cmd) in runner.runs
        if "docker compose up" in cmd and "/opt/monctl/collector" in cmd
    ]
    assert len(restarts) == len(outcomes)


def test_register_collectors_skips_non_collector_hosts(seeded_install: Path) -> None:
    """A host without `collector` in roles is silently skipped — the
    subcommand only touches hosts that actually run a collector."""
    inv_doc = yaml.safe_load(seeded_install.read_text())
    # Strip the collector role from every host — should yield zero outcomes.
    for h in inv_doc["hosts"]:
        h["roles"] = [r for r in h["roles"] if r != "collector"]
    seeded_install.write_text(yaml.safe_dump(inv_doc, sort_keys=False))

    runner = FakeRunner()
    client = _make_http_client()
    outcomes = register_collectors(
        seeded_install, runner=runner, http_client=client,
    )
    assert outcomes == []
    assert runner.runs == []


def test_register_collectors_propagates_keymint_failure(seeded_install: Path) -> None:
    """A 500 from the key-mint endpoint surfaces as `failed`, not silently."""
    runner = FakeRunner()
    client = _make_http_client(keymint_status=500)
    outcomes = register_collectors(
        seeded_install, runner=runner, http_client=client,
    )
    assert outcomes, "test fixture should have at least one collector host"
    assert all(o.status == "failed" for o in outcomes), outcomes
    assert all("key-mint" in o.detail.lower() for o in outcomes), outcomes


def test_register_collectors_treats_ssh_failure_as_failed(seeded_install: Path) -> None:
    """If `cat .env` returns non-zero rc, the host is marked failed and the
    .env is left untouched (no partial write)."""
    def responder(host: Host, cmd: str) -> CommandResult:
        if cmd.startswith(f"cat {COLLECTOR_ENV_PATH}"):
            return CommandResult(host.name, cmd, 1, "", "no such file")
        return CommandResult(host.name, cmd, 0, "", "")

    runner = FakeRunner(responder=responder)
    client = _make_http_client()
    outcomes = register_collectors(
        seeded_install, runner=runner, http_client=client,
    )
    assert all(o.status == "failed" for o in outcomes)
    # No .env was written because the read failed
    written_envs = [
        p for (_, p) in runner.uploads if p == COLLECTOR_ENV_PATH
    ]
    assert written_envs == []


def test_register_collectors_raises_when_admin_password_missing(seeded_install: Path) -> None:
    """secrets.env lacking MONCTL_ADMIN_PASSWORD blocks before any work."""
    inv_doc = yaml.safe_load(seeded_install.read_text())
    secrets_path = Path(inv_doc["secrets"]["file"])
    # Strip the line
    text = secrets_path.read_text()
    new_text = "\n".join(
        line for line in text.splitlines()
        if not line.startswith("MONCTL_ADMIN_PASSWORD=")
    ) + "\n"
    secrets_path.write_text(new_text)

    runner = FakeRunner()
    client = _make_http_client()
    with pytest.raises(RegisterError, match="MONCTL_ADMIN_PASSWORD"):
        register_collectors(seeded_install, runner=runner, http_client=client)


def test_register_collectors_revoke_existing_propagates_to_endpoint(
    seeded_install: Path,
) -> None:
    """`revoke_existing=True` must make it onto the key-mint POST body so
    central rotates rather than appends."""
    received_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/login":
            r = httpx.Response(200, json={"status": "success"})
            r.headers["set-cookie"] = "access_token=fake; Path=/; HttpOnly"
            return r
        if request.url.path.startswith("/v1/collectors/by-hostname/"):
            received_bodies.append(json.loads(request.content))
            host_name = request.url.path.split("/")[-2]
            return httpx.Response(
                201, json={
                    "collector_id": f"id-{host_name}",
                    "api_key": "k",
                    "name": host_name,
                    "status": "PENDING",
                    "created": False,
                },
            )
        return httpx.Response(404)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://central.test",
    )
    register_collectors(
        seeded_install,
        runner=FakeRunner(),
        http_client=client,
        revoke_existing=True,
    )
    assert all(b.get("revoke_existing") is True for b in received_bodies)
    assert received_bodies, "no key-mint POST observed"
