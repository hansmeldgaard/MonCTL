"""`add-host` + `remove-host` — incremental inventory changes.

These commands mutate `inventory.yaml` in place, then drive the normal
`deploy` pipeline. Because `deploy` is idempotent (state-hash short-circuit),
unchanged hosts are untouched; only the added/removed host actually runs
docker compose.

Scope:
  * `add-host` accepts only pure **leaf** roles today: `collector` and
    `docker_stats`. Adding a new `postgres`/`etcd`/`clickhouse` changes
    quorum membership and shard topology — handled by a future subcommand
    with per-case logic (Patroni member register, etcd member add, CH
    replica bootstrap).
  * `remove-host` supports any role but warns loudly on non-leaf roles
    and requires `--force`. Removing a quorum member without first
    deregistering it from Patroni/etcd/CH leaves a zombie member that
    the healthy hosts keep voting on.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from monctl_installer.commands.deploy import (
    PROJECT_ORDER,
    _apply_project,
    _hash_project,
    _load_remote_state,
    _save_remote_state,
    deploy as full_deploy,
)
from monctl_installer.inventory.loader import load_inventory
from monctl_installer.inventory.planner import plan_cluster
from monctl_installer.inventory.schema import Host
from monctl_installer.render.engine import RenderEngine
from monctl_installer.remote.ssh import SSHError, SSHRunner
from monctl_installer.secrets.store import load_secrets, validate_secrets_file

LEAF_ROLES = frozenset({"collector", "docker_stats"})


@dataclass(frozen=True)
class HostChange:
    host: str
    action: Literal["added", "removed", "failed"]
    detail: str


class TopologyError(Exception):
    """Raised when an add/remove request is rejected before any host is touched."""


# ── add-host ──────────────────────────────────────────────────────────────

def add_host(
    inventory_path: Path,
    *,
    name: str,
    address: str,
    roles: list[str],
    ssh_user: str = "monctl",
    runner: SSHRunner | None = None,
) -> list[HostChange]:
    non_leaf = set(roles) - LEAF_ROLES
    if non_leaf:
        raise TopologyError(
            f"add-host currently supports leaf roles only ({sorted(LEAF_ROLES)}); "
            f"refusing to add non-leaf roles {sorted(non_leaf)}. Edit "
            "inventory.yaml by hand + monctl_ctl deploy for quorum changes."
        )

    doc = yaml.safe_load(inventory_path.read_text())
    if not isinstance(doc, dict):
        raise TopologyError(f"{inventory_path}: malformed (top-level must be a mapping)")

    existing_names = {h["name"] for h in doc.get("hosts", [])}
    existing_addrs = {h["address"] for h in doc.get("hosts", [])}
    if name in existing_names:
        raise TopologyError(f"host {name!r} already present in inventory")
    if address in existing_addrs:
        raise TopologyError(f"address {address!r} already present in inventory")

    new_host = {
        "name": name,
        "address": address,
        "ssh": {"user": ssh_user},
        "roles": roles,
    }
    doc.setdefault("hosts", []).append(new_host)
    # Validate by parsing the modified doc before writing it back.
    tmp = inventory_path.parent / f".{inventory_path.name}.tmp"
    tmp.write_text(yaml.safe_dump(doc, sort_keys=False))
    try:
        load_inventory(tmp)
        plan = plan_cluster(load_inventory(tmp))
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise TopologyError(f"inventory would become invalid: {exc}") from exc

    # Commit the inventory change; no undo path after this, but deploy below
    # is idempotent so re-runs are safe.
    tmp.replace(inventory_path)

    # Deploy only the new host.
    host = next(h for h in plan.inventory.hosts if h.name == name)
    return _deploy_one(host, inventory_path, runner)


def _deploy_one(
    host: Host, inventory_path: Path, runner: SSHRunner | None
) -> list[HostChange]:
    inv = load_inventory(inventory_path)
    plan = plan_cluster(inv)
    secrets_path = Path(inv.secrets.file)
    if not secrets_path.is_absolute():
        secrets_path = inventory_path.parent / secrets_path
    validate_secrets_file(secrets_path)
    secret_values = load_secrets(secrets_path)

    runner = runner or SSHRunner()
    engine = RenderEngine()
    rendered = engine.render_host(host, plan)
    by_project: dict[str, list] = {}
    for f in rendered:
        by_project.setdefault(f.project, []).append(f)

    state = _load_remote_state(host, runner)
    for project in PROJECT_ORDER:
        files = by_project.get(project)
        if not files:
            continue
        digest = _hash_project(files)
        if state.get(project) == digest:
            continue
        try:
            _apply_project(host, project, files, secret_values, runner)
            state[project] = digest
        except SSHError as exc:
            return [HostChange(host.name, "failed", str(exc))]
    try:
        _save_remote_state(host, runner, state)
    except SSHError:
        pass
    return [HostChange(host.name, "added", f"roles={','.join(host.roles)}")]


# ── remove-host ───────────────────────────────────────────────────────────

def remove_host(
    inventory_path: Path,
    *,
    name: str,
    force: bool = False,
    runner: SSHRunner | None = None,
) -> list[HostChange]:
    doc = yaml.safe_load(inventory_path.read_text())
    if not isinstance(doc, dict):
        raise TopologyError(f"{inventory_path}: malformed")

    victim = None
    for h in doc.get("hosts", []):
        if h["name"] == name:
            victim = h
            break
    if victim is None:
        raise TopologyError(f"no host named {name!r} in inventory")

    non_leaf = set(victim.get("roles", [])) - LEAF_ROLES
    if non_leaf and not force:
        raise TopologyError(
            f"{name} carries non-leaf roles {sorted(non_leaf)}; removing it without "
            "first deregistering from Patroni/etcd/ClickHouse leaves zombie members. "
            "Pass --force once you've deregistered upstream."
        )

    # Stop containers on the host, in reverse dependency order.
    runner = runner or SSHRunner()
    host_obj = Host(
        name=victim["name"],
        address=victim["address"],
        ssh=_build_ssh(victim.get("ssh", {})),
        roles=victim.get("roles", []),
    )
    for project in reversed(PROJECT_ORDER):
        # Not every project lands on every host — compose projects that don't
        # exist just return an error on `down`; swallow it.
        try:
            runner.run(
                host_obj,
                f"cd /opt/monctl/{project} 2>/dev/null && docker compose down --remove-orphans || true",
            )
        except SSHError:
            # Host may already be unreachable (that's often why it's being removed).
            pass

    # Strip from inventory.
    doc["hosts"] = [h for h in doc["hosts"] if h["name"] != name]
    inventory_path.write_text(yaml.safe_dump(doc, sort_keys=False))

    # Re-plan to catch any resulting invalidity.
    try:
        plan_cluster(load_inventory(inventory_path))
    except Exception as exc:
        return [
            HostChange(
                name,
                "failed",
                f"removed but remaining inventory is now invalid: {exc}",
            )
        ]

    return [HostChange(name, "removed", f"was: {','.join(victim.get('roles', []))}")]


def _build_ssh(d: dict) -> object:
    from monctl_installer.inventory.schema import SSHConfig

    return SSHConfig(**d) if d else SSHConfig()
