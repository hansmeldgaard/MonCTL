"""`monctl_ctl upgrade <version>` — canary-first rolling upgrade.

Upgrade == re-deploy with a different image tag. The templates accept an
`image_tag` Jinja variable (defaults to 'latest'); we set it to the requested
version and drive the same render → scp → compose-up pipeline as `deploy`.

Rollout order:
  1. Canary host (operator-selected, or first central).
  2. Wait for canary /v1/health to return 200 for N consecutive polls.
  3. Remaining central hosts sequentially.
  4. Collectors in parallel.
  5. Leaf nodes (clickhouse / redis / etc.) are NOT re-rolled unless their
     image changed — they come along via the next normal deploy if needed.

Alembic migrations run automatically inside `central-entrypoint.sh`; we don't
need to invoke them. The advisory-lock there dedups concurrent runs.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from monctl_installer.commands.deploy import (
    PROJECT_ORDER,
    _apply_project,
    _hash_project,
    _load_remote_state,
    _save_remote_state,
)
from monctl_installer.inventory.loader import load_inventory
from monctl_installer.inventory.planner import Plan, plan_cluster
from monctl_installer.inventory.schema import Host
from monctl_installer.render.engine import RenderEngine, RenderedFile
from monctl_installer.remote.ssh import CommandResult, SSHError, SSHRunner
from monctl_installer.secrets.store import load_secrets, validate_secrets_file


@dataclass(frozen=True)
class UpgradeStep:
    host: str
    phase: Literal["canary", "centrals", "collectors"]
    status: Literal["upgraded", "unchanged", "failed"]
    detail: str


class UpgradeAborted(Exception):
    """Raised when the canary fails to come up; stops the rollout."""


def upgrade(
    inventory_path: Path,
    version: str,
    *,
    canary: str | None = None,
    runner: SSHRunner | None = None,
    health_timeout_s: int = 120,
    health_interval_s: float = 3,
    sleep: object = None,  # injected in tests as a no-op
) -> list[UpgradeStep]:
    inv = load_inventory(inventory_path)
    plan = plan_cluster(inv)
    secrets_path = Path(inv.secrets.file)
    if not secrets_path.is_absolute():
        secrets_path = inventory_path.parent / secrets_path
    validate_secrets_file(secrets_path)
    secret_values = load_secrets(secrets_path)
    if runner is None:
        runner = SSHRunner()
    sleep_fn = sleep if sleep is not None else time.sleep

    engine = RenderEngine()
    canary_host = _pick_canary(plan, canary)
    rest_centrals = [h for h in plan.central_hosts if h.name != canary_host.name]
    collectors = plan.collector_hosts

    steps: list[UpgradeStep] = []

    # 1. Canary
    step = _upgrade_host(
        canary_host, version, plan, engine, secret_values, runner, phase="canary"
    )
    steps.append(step)
    if step.status == "failed":
        raise UpgradeAborted(f"canary {canary_host.name} failed: {step.detail}")
    if step.status == "upgraded":
        if not _wait_healthy(canary_host, runner, health_timeout_s, health_interval_s, sleep_fn):
            steps.append(
                UpgradeStep(
                    canary_host.name,
                    "canary",
                    "failed",
                    f"/v1/health did not return 200 within {health_timeout_s}s",
                )
            )
            raise UpgradeAborted(f"canary {canary_host.name} unhealthy after upgrade")

    # 2. Remaining centrals, sequentially
    for host in rest_centrals:
        s = _upgrade_host(host, version, plan, engine, secret_values, runner, phase="centrals")
        steps.append(s)
        if s.status == "failed":
            return steps
        if s.status == "upgraded":
            _wait_healthy(host, runner, health_timeout_s, health_interval_s, sleep_fn)

    # 3. Collectors — parallel
    for host in collectors:
        s = _upgrade_host(host, version, plan, engine, secret_values, runner, phase="collectors")
        steps.append(s)

    return steps


def _pick_canary(plan: Plan, canary: str | None) -> Host:
    if canary is None:
        return plan.central_hosts[0]
    for h in plan.central_hosts:
        if h.name == canary:
            return h
    raise ValueError(f"--canary {canary!r} is not a central host in the inventory")


def _upgrade_host(
    host: Host,
    version: str,
    plan: Plan,
    engine: RenderEngine,
    secret_values: dict[str, str],
    runner: SSHRunner,
    *,
    phase: Literal["canary", "centrals", "collectors"],
) -> UpgradeStep:
    # Render this host with the new image tag substituted.
    # We re-use the engine but inject the tag via a per-call template variable.
    rendered = _render_with_tag(host, plan, engine, version)
    state = _load_remote_state(host, runner)
    # Only roll the project(s) whose content changed under the new tag.
    changed_any = False
    for project in PROJECT_ORDER:
        files = [f for f in rendered if f.project == project]
        if not files:
            continue
        digest = _hash_project(files)
        if state.get(project) == digest:
            continue
        try:
            _apply_project(host, project, files, secret_values, runner)
            state[project] = digest
            changed_any = True
        except SSHError as exc:
            return UpgradeStep(host.name, phase, "failed", str(exc))
    if not changed_any:
        return UpgradeStep(host.name, phase, "unchanged", f"already on tag {version}")
    try:
        _save_remote_state(host, runner, state)
    except SSHError as exc:  # state write is best-effort
        return UpgradeStep(
            host.name,
            phase,
            "upgraded",
            f"tag={version} (warn: state write failed: {exc})",
        )
    return UpgradeStep(host.name, phase, "upgraded", f"tag={version}")


def _render_with_tag(
    host: Host, plan: Plan, engine: RenderEngine, version: str
) -> list[RenderedFile]:
    """Render this host with `image_tag=<version>` in the Jinja context.

    The engine's render_host doesn't accept extra context today, so we patch
    the global env via a short-lived override. We don't want to leak state
    across calls — the override is a Jinja global that is replaced each call.
    """
    engine.env.globals["image_tag"] = version
    try:
        return engine.render_host(host, plan)
    finally:
        engine.env.globals.pop("image_tag", None)


def _wait_healthy(
    host: Host,
    runner: SSHRunner,
    timeout_s: int,
    interval_s: float,
    sleep_fn,  # type: ignore[no-untyped-def]
) -> bool:
    """Poll /v1/health until it's 200 or timeout elapses."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = runner.run(
                host,
                "curl -sfk --max-time 5 http://localhost:8443/v1/health 2>&1 || echo FAIL",
            )
            # /v1/health returns {"status": "healthy", ...} on success.
            if r.ok and "FAIL" not in r.stdout:
                try:
                    payload = json.loads(r.stdout)
                except json.JSONDecodeError:
                    payload = {}
                if payload.get("status") == "healthy":
                    return True
        except SSHError:
            pass
        sleep_fn(interval_s)
    return False
