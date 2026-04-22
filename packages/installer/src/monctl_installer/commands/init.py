"""`monctl_ctl init` — interactive wizard or YAML-seeded non-interactive run.

Writes:
  * inventory.yaml  (mode 0644)
  * secrets.env     (mode 0600; generated unless secrets.mode=provided)

Prints the admin password once at the end. Never echoes it again.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import click
import yaml

from monctl_installer.inventory.loader import load_inventory
from monctl_installer.inventory.planner import plan_cluster
from monctl_installer.secrets.generator import generate_secrets
from monctl_installer.secrets.store import SecretsFileError, write_secrets


@dataclass(frozen=True)
class InitResult:
    inventory_path: Path
    secrets_path: Path
    admin_password: str
    login_url: str


class InitError(Exception):
    pass


def run_interactive(
    *,
    inventory_path: Path,
    secrets_path: Path,
    overwrite: bool,
) -> InitResult:
    """Walk the operator through a minimal set of questions, write both files."""
    _check_writable(inventory_path, overwrite, "inventory")
    _check_writable(secrets_path, overwrite, "secrets")

    click.echo()
    click.secho("MonCTL installer — cluster setup", fg="cyan", bold=True)
    click.echo("Answer a few questions, then run `monctl_ctl validate` and `monctl_ctl deploy`.")
    click.echo()

    cluster_name = click.prompt("Cluster name", type=str, default="monctl")
    domain = click.prompt("DNS domain (blank to skip)", type=str, default="", show_default=False)
    use_vip = click.confirm("Use a virtual IP for HA?", default=False)
    vip = None
    vip_interface = None
    if use_vip:
        vip = click.prompt("Virtual IP (e.g. 10.0.0.40)", type=str)
        vip_interface = click.prompt("VIP network interface", type=str, default="eth0")

    hosts: list[dict[str, object]] = []
    ssh_user = click.prompt("SSH user for all hosts", type=str, default="monctl")
    click.echo()
    click.echo("Enter hosts one at a time. Blank name ends the list.")
    while True:
        name = click.prompt("Host name", type=str, default="", show_default=False)
        if not name:
            if not hosts:
                click.secho("need at least one host", fg="yellow")
                continue
            break
        address = click.prompt("  IP address", type=str)
        roles_raw = click.prompt(
            "  Roles (comma-separated, e.g. postgres,central,clickhouse)",
            type=str,
        )
        roles = [r.strip() for r in roles_raw.split(",") if r.strip()]
        hosts.append(
            {"name": name, "address": address, "ssh": {"user": ssh_user}, "roles": roles}
        )

    shards = click.prompt("ClickHouse shards", type=int, default=1)
    replicas = click.prompt("ClickHouse replicas per shard", type=int, default=1)
    pg_mode = click.prompt(
        "Postgres mode (auto/standalone/ha)", type=click.Choice(["auto", "standalone", "ha"]),
        default="auto",
    )

    inventory_doc = _build_inventory_doc(
        cluster_name=cluster_name,
        domain=domain or None,
        vip=vip,
        vip_interface=vip_interface,
        hosts=hosts,
        shards=shards,
        replicas=replicas,
        pg_mode=pg_mode,
        secrets_file=secrets_path,
    )
    return _finalize(inventory_doc, inventory_path, secrets_path)


def run_from_yaml(
    *,
    seed_path: Path,
    inventory_path: Path,
    secrets_path: Path,
    overwrite: bool,
) -> InitResult:
    """Non-interactive: the operator hands us a seed inventory, we copy + generate secrets.

    The seed file is a complete inventory.yaml. `init --from` just normalises it
    (writes a clean copy to `inventory_path`) and generates matching secrets.
    Useful for CI, automated installs, reproducing a topology.
    """
    _check_writable(inventory_path, overwrite, "inventory")
    _check_writable(secrets_path, overwrite, "secrets")
    raw = yaml.safe_load(seed_path.read_text())
    if not isinstance(raw, dict):
        raise InitError(f"{seed_path}: top-level must be a mapping")
    # Keep the secrets path consistent with the init run.
    raw.setdefault("secrets", {})["file"] = str(secrets_path)
    return _finalize(raw, inventory_path, secrets_path)


def _build_inventory_doc(  # type: ignore[no-untyped-def]
    *,
    cluster_name,
    domain,
    vip,
    vip_interface,
    hosts,
    shards,
    replicas,
    pg_mode,
    secrets_file: Path,
) -> dict:
    cluster: dict[str, object] = {"name": cluster_name}
    if domain:
        cluster["domain"] = domain
    if vip:
        cluster["vip"] = vip
        if vip_interface:
            cluster["vip_interface"] = vip_interface
    return {
        "version": 1,
        "cluster": cluster,
        "hosts": hosts,
        "sizing": {
            "postgres": {"mode": pg_mode},
            "clickhouse": {"shards": shards, "replicas": replicas, "keeper": "embedded"},
            "redis": {"mode": "auto"},
            "central": {"tls_behind_haproxy": bool(vip)},
        },
        "secrets": {"mode": "auto_generate", "file": str(secrets_file)},
    }


def _finalize(inv_doc: dict, inventory_path: Path, secrets_path: Path) -> InitResult:
    # Write inventory first so validate() has something to parse.
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(yaml.safe_dump(inv_doc, sort_keys=False, default_flow_style=False))

    # Parse + plan to fail loud on a bad inventory before touching secrets.
    try:
        inv = load_inventory(inventory_path)
        plan = plan_cluster(inv)
    except Exception as exc:
        inventory_path.unlink(missing_ok=True)
        raise InitError(f"generated inventory failed validation: {exc}") from exc

    bundle = generate_secrets()
    try:
        write_secrets(bundle, secrets_path, overwrite=True)
    except SecretsFileError as exc:  # pragma: no cover — extremely unlikely after overwrite=True
        raise InitError(str(exc)) from exc

    login_url = _login_url(plan)
    return InitResult(
        inventory_path=inventory_path,
        secrets_path=secrets_path,
        admin_password=bundle.monctl_admin_password,
        login_url=login_url,
    )


def _login_url(plan) -> str:  # type: ignore[no-untyped-def]
    if plan.vip:
        return f"https://{plan.vip}/"
    return f"https://{plan.central_hosts[0].address}:8443/"


def _check_writable(path: Path, overwrite: bool, label: str) -> None:
    if path.exists() and not overwrite:
        raise InitError(
            f"{label} already exists at {path}; re-run with --force to replace"
        )
