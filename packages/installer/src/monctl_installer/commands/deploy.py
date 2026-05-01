"""`monctl_ctl deploy` — render bundles, scp per-project to each host, `docker compose up -d`.

Idempotency: a sha256 of the rendered files is written to
`/opt/monctl/.state.json` on the host. A re-run that produces the same hash
short-circuits the scp + compose-up steps for that project.

Order within a host: postgres → etcd → redis → clickhouse → clickhouse-keeper →
central → superset → haproxy → collector → docker-stats. That mirrors the
dependency chain: nothing that depends on the DB starts before the DB's compose
stack is up. Superset comes after central (it OAuths against central) and before
haproxy (which routes /bi/ traffic to it).
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from monctl_installer.inventory.loader import load_inventory
from monctl_installer.inventory.planner import plan_cluster
from monctl_installer.inventory.schema import Host
from monctl_installer.render.engine import RenderEngine, RenderedFile
from monctl_installer.remote.ssh import CommandResult, SSHError, SSHRunner
from monctl_installer.secrets.store import load_secrets, validate_secrets_file
from monctl_installer.version import __version__

STATE_PATH = "/opt/monctl/.state.json"
PROJECT_ROOT = "/opt/monctl"

# Deterministic deploy order — upstreams first.
PROJECT_ORDER: list[str] = [
    "postgres",
    "etcd",
    "redis",
    "clickhouse",
    "clickhouse-keeper",
    "central",
    "superset",
    "haproxy",
    "collector",
    "docker-stats",
]


@dataclass(frozen=True)
class DeployOutcome:
    host: str
    project: str
    status: Literal["applied", "unchanged", "failed"]
    detail: str


def deploy(
    inventory_path: Path,
    *,
    runner: SSHRunner | None = None,
    dry_run: bool = False,
) -> list[DeployOutcome]:
    inv = load_inventory(inventory_path)
    plan = plan_cluster(inv)
    secrets_path = Path(inv.secrets.file)
    if not secrets_path.is_absolute():
        secrets_path = inventory_path.parent / secrets_path
    validate_secrets_file(secrets_path)
    secret_values = load_secrets(secrets_path)
    if runner is None:
        runner = SSHRunner()

    engine = RenderEngine()
    outcomes: list[DeployOutcome] = []
    for host in inv.hosts:
        files = engine.render_host(host, plan)
        by_project: dict[str, list[RenderedFile]] = {}
        for f in files:
            by_project.setdefault(f.project, []).append(f)
        prior_state = _load_remote_state(host, runner)
        for project in PROJECT_ORDER:
            pf = by_project.get(project)
            if not pf:
                continue
            digest = _hash_project(pf)
            if prior_state.get(project) == digest:
                outcomes.append(
                    DeployOutcome(host.name, project, "unchanged", f"sha={digest[:12]}")
                )
                continue
            try:
                if dry_run:
                    outcomes.append(
                        DeployOutcome(host.name, project, "applied", "dry-run")
                    )
                else:
                    _apply_project(host, project, pf, secret_values, runner)
                    prior_state[project] = digest
                    _save_remote_state(host, runner, prior_state)
                    outcomes.append(
                        DeployOutcome(host.name, project, "applied", f"sha={digest[:12]}")
                    )
            except SSHError as exc:
                outcomes.append(DeployOutcome(host.name, project, "failed", str(exc)))
    return outcomes


# ── remote operations ─────────────────────────────────────────────────────

def _apply_project(
    host: Host,
    project: str,
    files: list[RenderedFile],
    secret_values: dict[str, str],
    runner: SSHRunner,
) -> None:
    """Upload compose + configs, append secrets into .env, docker compose up."""
    project_dir = f"{PROJECT_ROOT}/{project}"
    # Derive per-host secret overrides (M-INST-012). PEER_TOKEN is computed
    # from PEER_TOKEN_SEED so cache-node and poll-worker on the *same* host
    # agree, but a leak from one host doesn't compromise others.
    host_secrets = _per_host_secret_overrides(host, secret_values)
    for f in files:
        mode = 0o600 if f.filename == ".env" else 0o644
        content = f.content
        if f.filename == ".env":
            content = _materialise_env(content, host_secrets)
        runner.put(host, content, f"{project_dir}/{f.filename}", mode=mode)
    r = runner.run(host, f"cd {project_dir} && docker compose up -d --remove-orphans")
    if not r.ok:
        raise SSHError(
            f"docker compose up failed in {project_dir}: rc={r.exit_code} stderr={r.stderr!r}"
        )


def _per_host_secret_overrides(host: Host, secret_values: dict[str, str]) -> dict[str, str]:
    """Return a per-host copy of ``secret_values`` with derived overrides.

    Currently overrides ``PEER_TOKEN`` only — derived from ``PEER_TOKEN_SEED``
    via HMAC-SHA256(seed, host.name). Falls back to the legacy single-value
    ``PEER_TOKEN`` from secrets.env if no seed is present (preserves existing
    customer installs that haven't been re-rendered yet).
    """
    import base64
    import hashlib
    import hmac

    overrides = dict(secret_values)
    seed = secret_values.get("PEER_TOKEN_SEED") or secret_values.get("PEER_TOKEN", "")
    if not seed:
        return overrides
    digest = hmac.new(
        seed.encode("utf-8"), host.name.encode("utf-8"), hashlib.sha256
    ).digest()
    overrides["PEER_TOKEN"] = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return overrides


def _materialise_env(template_rendered: str, secret_values: dict[str, str]) -> str:
    """Replace `${KEY}` placeholders in the env template with real secret values.

    Our env templates (packages/installer/.../templates/env/*.j2) emit literal
    `${KEY}` strings expecting `docker compose` to expand them from a sibling
    file. We resolve them here instead so the on-host `.env` carries real values;
    compose then uses it directly without a second env source.
    """
    out = template_rendered
    for key, value in secret_values.items():
        out = out.replace(f"${{{key}}}", value)
    return out


def _load_remote_state(host: Host, runner: SSHRunner) -> dict[str, str]:
    try:
        r = runner.run(host, f"cat {STATE_PATH} 2>/dev/null || echo '{{}}'")
        if r.ok and r.stdout.strip():
            parsed = json.loads(r.stdout)
            if isinstance(parsed, dict):
                return {k: str(v) for k, v in parsed.items()}
    except (SSHError, json.JSONDecodeError):
        pass
    return {}


def _save_remote_state(host: Host, runner: SSHRunner, state: dict[str, str]) -> None:
    payload = json.dumps(
        {**state, "__installer_version__": __version__, "__updated_at__": int(time.time())},
        indent=2,
        sort_keys=True,
    )
    runner.put(host, payload, STATE_PATH, mode=0o600)


# ── helpers ───────────────────────────────────────────────────────────────

def _hash_project(files: list[RenderedFile]) -> str:
    """Stable hash of a project's rendered output (order-independent)."""
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: x.filename):
        h.update(f.filename.encode())
        h.update(b"\x00")
        h.update(f.content.encode())
        h.update(b"\x00")
    return h.hexdigest()
