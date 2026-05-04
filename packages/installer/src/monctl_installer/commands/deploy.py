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

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
DEPLOY_HISTORY_PATH = "/opt/monctl/.deploy-history.jsonl"
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
    max_parallel_hosts: int = 4,
    register_collectors: bool = True,
    http_client: "object | None" = None,
) -> list[DeployOutcome]:
    """Render bundles, scp per-project to each host, ``docker compose up -d``.

    P-INST-005 — host loop runs in parallel up to ``max_parallel_hosts``.
    Within a host, the project order (postgres → etcd → redis → … → central
    → … → collector → docker-stats) is preserved sequentially because
    those projects have inter-project dependencies on the same host.
    Different hosts are independent; running them in parallel cuts a
    cold cluster deploy from ~5–10 min wall-clock to ~1–2 min on a
    typical 4–8 host inventory. Combined with SSHRunner's per-host
    connection cache, the auth overhead also drops from N×200 ms to a
    single round per host.

    Wave 2C — when ``register_collectors`` is True (the default) and at
    least one collector host applied/unchanged successfully, run the
    register-collectors post-step automatically. Each collector host
    gets a unique ``MONCTL_COLLECTOR_API_KEY`` and the container is
    restarted to pick it up. Outcomes are appended to the returned
    list with project=``register-collectors``. Skipped on
    ``dry_run=True``.
    """
    inv = load_inventory(inventory_path)
    plan = plan_cluster(inv)
    secrets_path = Path(inv.secrets.file)
    if not secrets_path.is_absolute():
        secrets_path = inventory_path.parent / secrets_path
    validate_secrets_file(secrets_path)
    secret_values = load_secrets(secrets_path)
    owns_runner = runner is None
    if runner is None:
        runner = SSHRunner()

    engine = RenderEngine()

    def _deploy_host(host: Host) -> list[DeployOutcome]:
        host_outcomes: list[DeployOutcome] = []
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
            started_at = _now_iso()
            if prior_state.get(project) == digest:
                outcome = DeployOutcome(
                    host.name, project, "unchanged", f"sha={digest[:12]}"
                )
                host_outcomes.append(outcome)
                _record_deploy_event(
                    host, runner, project, "unchanged", digest,
                    started_at, _now_iso(), outcome.detail, dry_run,
                )
                continue
            try:
                if dry_run:
                    outcome = DeployOutcome(
                        host.name, project, "applied", "dry-run"
                    )
                else:
                    _apply_project(host, project, pf, secret_values, runner)
                    prior_state[project] = digest
                    _save_remote_state(host, runner, prior_state)
                    outcome = DeployOutcome(
                        host.name, project, "applied", f"sha={digest[:12]}"
                    )
                host_outcomes.append(outcome)
                _record_deploy_event(
                    host, runner, project, outcome.status, digest,
                    started_at, _now_iso(), outcome.detail, dry_run,
                )
            except SSHError as exc:
                outcome = DeployOutcome(host.name, project, "failed", str(exc))
                host_outcomes.append(outcome)
                _record_deploy_event(
                    host, runner, project, "failed", digest,
                    started_at, _now_iso(), str(exc), dry_run,
                )
        return host_outcomes

    outcomes: list[DeployOutcome] = []
    try:
        if max_parallel_hosts <= 1 or len(inv.hosts) <= 1:
            # Either explicit serial mode or trivially one host —
            # avoid the executor overhead.
            for host in inv.hosts:
                outcomes.extend(_deploy_host(host))
        else:
            # Bounded host fan-out. Project order within a host stays
            # sequential because role compositions on the same machine
            # depend on each other (postgres before central, etc.).
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=max_parallel_hosts) as pool:
                futures = {
                    pool.submit(_deploy_host, h): h for h in inv.hosts
                }
                for fut in as_completed(futures):
                    host = futures[fut]
                    try:
                        outcomes.extend(fut.result())
                    except Exception as exc:
                        outcomes.append(
                            DeployOutcome(
                                host.name,
                                "<unknown>",
                                "failed",
                                f"unexpected error: {exc}",
                            )
                        )
    finally:
        if owns_runner:
            runner.close()

    # Wave 2C — register-collectors post-step. Skip on dry-run, and skip
    # if the deploy itself failed on every collector host (no point trying
    # to provision keys for hosts that aren't reachable / aren't running
    # the collector container yet). Failures here are non-fatal — the
    # cluster is still up on the shared-secret path.
    if register_collectors and not dry_run:
        collector_outcomes = [
            o for o in outcomes
            if o.project == "collector" and o.status in ("applied", "unchanged")
        ]
        if collector_outcomes:
            outcomes.extend(
                _post_step_register_collectors(
                    inventory_path, http_client=http_client
                )
            )

    return outcomes


def _post_step_register_collectors(
    inventory_path: Path, *, http_client: "object | None" = None,
) -> list[DeployOutcome]:
    """Run register-collectors and translate its outcomes into
    DeployOutcome rows so the caller sees them alongside per-project
    deploy results.
    """
    from monctl_installer.commands.register_collectors import (
        RegisterError,
        register_collectors,
    )

    try:
        results = register_collectors(
            inventory_path, http_client=http_client,
        )
    except RegisterError as exc:
        return [DeployOutcome(
            "<cluster>", "register-collectors", "failed", str(exc),
        )]

    # Map register status → DeployOutcome status:
    #   registered → applied (key minted + .env updated + restart)
    #   skipped    → unchanged
    #   failed     → failed
    _status_map = {"registered": "applied", "skipped": "unchanged", "failed": "failed"}
    return [
        DeployOutcome(
            r.host,
            "register-collectors",
            _status_map.get(r.status, "failed"),  # type: ignore[arg-type]
            r.detail,
        )
        for r in results
    ]


# ── remote operations ─────────────────────────────────────────────────────


def _now_iso() -> str:
    """UTC ISO-8601 timestamp suitable for the deploy-history log line."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record_deploy_event(
    host: Host,
    runner: SSHRunner,
    project: str,
    status: str,
    digest: str,
    started_at: str,
    finished_at: str,
    detail: str,
    dry_run: bool,
) -> None:
    """Append one JSONL row to ``/opt/monctl/.deploy-history.jsonl`` per
    project per host per run (O-INST-001).

    Best-effort: if the host filesystem is unwritable or SSH fails, we log
    nothing and continue — the deploy itself already returned an outcome
    object to the caller. The history line is for the operator who comes
    back later to ask "when did central last deploy on host3, and did it
    succeed?".

    Encoded via base64 + ``base64 -d`` because the JSON line may contain
    quotes and shell metacharacters from `detail` (an SSH stderr blob),
    and we don't want to invent another shell-escape ladder.
    """
    if dry_run:
        return  # only record real deploys; dry-run is operator preview
    entry = {
        "timestamp": finished_at,
        "host": host.name,
        "project": project,
        "status": status,
        "digest": digest[:12],
        "started_at": started_at,
        "finished_at": finished_at,
        "installer_version": __version__,
        "detail": detail,
    }
    line = json.dumps(entry, sort_keys=True) + "\n"
    encoded = base64.b64encode(line.encode("utf-8")).decode("ascii")
    cmd = (
        f"mkdir -p {PROJECT_ROOT} && "
        f"echo {encoded} | base64 -d >> {DEPLOY_HISTORY_PATH}"
    )
    try:
        runner.run(host, cmd)
    except SSHError:
        # Don't let history-logging failures mask the deploy outcome.
        pass


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
