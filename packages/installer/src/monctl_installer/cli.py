from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console

from monctl_installer.version import __version__

console = Console()
err_console = Console(stderr=True)


def _activate_accept_new_hostkeys(flag: bool) -> None:
    """Toggle ``MONCTL_ACCEPT_NEW_HOSTKEYS`` for the rest of this CLI run.

    SSHRunner reads this env var as a fallback when its own constructor arg
    is not explicit. Setting it at the CLI entry point propagates to every
    SSH-using subcommand without having to thread the flag through each one.
    """
    if flag:
        os.environ["MONCTL_ACCEPT_NEW_HOSTKEYS"] = "1"


@click.group()
@click.version_option(__version__, prog_name="monctl_ctl")
def main() -> None:
    """MonCTL cluster control — provision, deploy, and upgrade MonCTL installations."""


@main.command()
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to inventory.yaml",
)
@click.option(
    "--out",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("./out"),
    show_default=True,
    help="Output directory for rendered per-host compose bundles",
)
def render(inventory: Path, out: Path) -> None:
    """Render per-host compose bundles to ./out/<host>/ from inventory.yaml.

    Does not touch remote hosts. Useful for dry-run inspection and hand-delivery.
    """
    from monctl_installer.commands.render import run as run_render
    from monctl_installer.inventory.loader import InventoryValidationError

    try:
        written = run_render(inventory_path=inventory, out_dir=out)
    except InventoryValidationError as exc:
        err_console.print(f"[red]inventory validation failed:[/red] {exc}")
        sys.exit(1)

    console.print(f"[green]rendered[/green] {len(written)} host bundles to {out}")
    for host, files in written.items():
        console.print(f"  [cyan]{host}[/cyan]: {len(files)} files")


@main.command()
@click.option(
    "--inventory",
    "-i",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
    help="Where to write the generated inventory.yaml",
)
@click.option(
    "--secrets",
    "-s",
    "secrets_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("./secrets.env"),
    show_default=True,
    help="Where to write the generated secrets.env",
)
@click.option(
    "--from",
    "seed_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Non-interactive: seed from an existing inventory YAML",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing inventory.yaml. Does NOT rotate an existing "
    "secrets.env — use --regenerate-secrets for that.",
)
@click.option(
    "--regenerate-secrets",
    is_flag=True,
    help="DESTRUCTIVE: rotate every value in secrets.env. Invalidates all "
    "session tokens, all encrypted credentials at rest, every collector's "
    "API key, and the OAuth client_secret. Only use when you intentionally "
    "want a full key rotation.",
)
def init(
    inventory: Path,
    secrets_path: Path,
    seed_path: Path | None,
    force: bool,
    regenerate_secrets: bool,
) -> None:
    """Wizard: collect cluster layout, generate secrets, write inventory + secrets.env."""
    from monctl_installer.commands.init import (
        InitError,
        run_from_yaml,
        run_interactive,
    )

    try:
        if seed_path is not None:
            result = run_from_yaml(
                seed_path=seed_path,
                inventory_path=inventory,
                secrets_path=secrets_path,
                overwrite=force,
                regenerate_secrets=regenerate_secrets,
            )
        else:
            result = run_interactive(
                inventory_path=inventory,
                secrets_path=secrets_path,
                overwrite=force,
                regenerate_secrets=regenerate_secrets,
            )
    except InitError as exc:
        err_console.print(f"[red]init failed:[/red] {exc}")
        sys.exit(1)

    console.print()
    console.print(f"[green]wrote[/green] inventory → {result.inventory_path}")
    if regenerate_secrets or not result.secrets_path.exists() or _is_freshly_written(
        result.secrets_path
    ):
        # Either a fresh install or operator explicitly rotated.
        console.print(f"[green]wrote[/green] secrets   → {result.secrets_path} (mode 0600)")
        console.print()
        console.print("[bold red]── ADMIN CREDENTIALS — SAVE THIS NOW ──[/bold red]")
        console.print(f"URL:      [cyan]{result.login_url}[/cyan]")
        console.print("Username: [cyan]admin[/cyan]")
        console.print(f"Password: [yellow]{result.admin_password}[/yellow]")
        console.print("[dim]This password is also in secrets.env but will never be printed again.[/dim]")
    else:
        # Existing secrets preserved — no destructive rotation.
        console.print(
            f"[dim]preserved[/dim] secrets → {result.secrets_path} "
            "([yellow]re-run with --regenerate-secrets to rotate[/yellow])"
        )
    console.print()
    console.print("Next: [cyan]monctl_ctl validate[/cyan] to pre-flight the target hosts")


def _is_freshly_written(path: Path, *, threshold_seconds: int = 5) -> bool:
    """Heuristic: was ``path`` modified within the last ``threshold_seconds``?

    Used to differentiate "we just wrote this in _finalize" from "we read an
    existing file unchanged." Avoids threading a flag back through InitResult.
    """
    try:
        import time
        return (time.time() - path.stat().st_mtime) < threshold_seconds
    except OSError:
        return False


@main.command()
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
    help="Path to inventory.yaml",
)
@click.option(
    "--accept-new-hostkeys",
    is_flag=True,
    help="Trust unknown SSH host keys on first contact and write them to "
    "~/.ssh/known_hosts. After that, strict-mode is restored. Use this "
    "ONCE during initial cluster onboarding.",
)
def validate(inventory: Path, accept_new_hostkeys: bool) -> None:
    """SSH-reachability + Docker + ports + RAM + disk + time-sync preflight."""
    from monctl_installer.commands.validate import run as run_validate
    from monctl_installer.inventory.loader import InventoryValidationError

    _activate_accept_new_hostkeys(accept_new_hostkeys)
    try:
        summary = run_validate(inventory, console)
    except InventoryValidationError as exc:
        err_console.print(f"[red]inventory validation failed:[/red] {exc}")
        sys.exit(1)
    if summary.has_failures:
        sys.exit(1)


@main.command()
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
    help="Path to inventory.yaml",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Render + diff against remote state but don't upload or restart containers",
)
@click.option(
    "--accept-new-hostkeys",
    is_flag=True,
    help="Trust unknown SSH host keys on first contact (initial onboarding only).",
)
@click.option(
    "--skip-register-collectors",
    is_flag=True,
    help="Skip the post-deploy step that mints per-host collector API keys "
    "(M-INST-011 / S-COL-002 / S-X-002). Use during a partial deploy where "
    "central isn't reachable yet, then run `monctl_ctl register-collectors` "
    "manually once the cluster is up.",
)
def deploy(
    inventory: Path,
    dry_run: bool,
    accept_new_hostkeys: bool,
    skip_register_collectors: bool,
) -> None:
    """SSH-distribute compose bundles and `docker compose up -d` on every host."""
    from monctl_installer.commands.deploy import deploy as run_deploy
    from monctl_installer.inventory.loader import InventoryValidationError
    from monctl_installer.secrets.store import SecretsFileError

    _activate_accept_new_hostkeys(accept_new_hostkeys)
    try:
        outcomes = run_deploy(
            inventory,
            dry_run=dry_run,
            register_collectors=not skip_register_collectors,
        )
    except (InventoryValidationError, SecretsFileError) as exc:
        err_console.print(f"[red]deploy precondition failed:[/red] {exc}")
        sys.exit(1)

    applied = sum(1 for o in outcomes if o.status == "applied")
    unchanged = sum(1 for o in outcomes if o.status == "unchanged")
    failed = sum(1 for o in outcomes if o.status == "failed")
    for o in outcomes:
        colour = {"applied": "green", "unchanged": "dim", "failed": "red"}[o.status]
        console.print(
            f"[{colour}]{o.status:9}[/{colour}] "
            f"[cyan]{o.host}[/cyan] / {o.project} — {o.detail}"
        )
    console.print()
    console.print(
        f"[green]{applied} applied[/green], "
        f"[dim]{unchanged} unchanged[/dim], "
        f"[red]{failed} failed[/red]"
    )
    if failed:
        sys.exit(1)


@main.command()
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
)
@click.option(
    "--accept-new-hostkeys",
    is_flag=True,
    help="Trust unknown SSH host keys on first contact (initial onboarding only).",
)
def status(inventory: Path, accept_new_hostkeys: bool) -> None:
    """Probe each host and print cluster health summary."""
    _activate_accept_new_hostkeys(accept_new_hostkeys)
    from monctl_installer.commands.status import print_table, run_status
    from monctl_installer.inventory.loader import (
        InventoryValidationError,
        load_inventory,
    )
    from monctl_installer.inventory.planner import plan_cluster
    from monctl_installer.remote.ssh import SSHRunner

    try:
        inv = load_inventory(inventory)
        plan = plan_cluster(inv)
    except InventoryValidationError as exc:
        err_console.print(f"[red]inventory validation failed:[/red] {exc}")
        sys.exit(1)
    summary = run_status(plan, SSHRunner())
    print_table(summary, console)
    if summary.has_down:
        sys.exit(1)


@main.command(name="register-collectors")
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
    help="Path to inventory.yaml",
)
@click.option(
    "--central-url",
    type=str,
    default=None,
    help="Override the central base URL (default: derive from cluster.vip "
    "or the first host with the `central` role).",
)
@click.option(
    "--revoke-existing",
    is_flag=True,
    help="Delete prior keys for each collector before minting the new one. "
    "Use during a rotation to invalidate any leaked keys immediately.",
)
@click.option(
    "--accept-new-hostkeys",
    is_flag=True,
    help="Trust unknown SSH host keys on first contact (initial onboarding only).",
)
def register_collectors_cmd(
    inventory: Path,
    central_url: str | None,
    revoke_existing: bool,
    accept_new_hostkeys: bool,
) -> None:
    """Mint per-host collector API keys + write to each host's collector .env.

    Run after `monctl_ctl deploy` brings the cluster up. Closes the
    install-time gap where every collector shipped with the same
    cluster-wide MONCTL_COLLECTOR_API_KEY (M-INST-011 / S-COL-002 /
    S-X-002).
    """
    _activate_accept_new_hostkeys(accept_new_hostkeys)
    from monctl_installer.commands.register_collectors import (
        RegisterError,
        register_collectors,
    )
    from monctl_installer.inventory.loader import InventoryValidationError
    from monctl_installer.secrets.store import SecretsFileError

    try:
        outcomes = register_collectors(
            inventory,
            central_url=central_url,
            revoke_existing=revoke_existing,
        )
    except (InventoryValidationError, SecretsFileError, RegisterError) as exc:
        err_console.print(f"[red]register-collectors precondition failed:[/red] {exc}")
        sys.exit(1)

    if not outcomes:
        console.print(
            "[yellow]no collector hosts in inventory — nothing to do[/yellow]"
        )
        return

    registered = sum(1 for o in outcomes if o.status == "registered")
    failed = sum(1 for o in outcomes if o.status == "failed")
    for o in outcomes:
        colour = {"registered": "green", "skipped": "dim", "failed": "red"}[o.status]
        console.print(
            f"[{colour}]{o.status:11}[/{colour}] "
            f"[cyan]{o.host}[/cyan] — {o.detail}"
        )
    console.print()
    console.print(
        f"[green]{registered} registered[/green], [red]{failed} failed[/red]"
    )
    if failed:
        sys.exit(1)


@main.command()
@click.argument("version")
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
)
@click.option(
    "--canary",
    default=None,
    help="Name of the central host to upgrade first (default: first central)",
)
@click.option(
    "--accept-new-hostkeys",
    is_flag=True,
    help="Trust unknown SSH host keys on first contact (initial onboarding only).",
)
def upgrade(
    version: str, inventory: Path, canary: str | None, accept_new_hostkeys: bool
) -> None:
    """Rolling upgrade to <version>: canary → remaining centrals → collectors."""
    from monctl_installer.commands.upgrade import UpgradeAborted, upgrade as run_upgrade
    from monctl_installer.inventory.loader import InventoryValidationError
    from monctl_installer.secrets.store import SecretsFileError

    _activate_accept_new_hostkeys(accept_new_hostkeys)
    try:
        steps = run_upgrade(inventory, version, canary=canary)
    except (InventoryValidationError, SecretsFileError, ValueError) as exc:
        err_console.print(f"[red]upgrade precondition failed:[/red] {exc}")
        sys.exit(1)
    except UpgradeAborted as exc:
        err_console.print(f"[red]upgrade aborted:[/red] {exc}")
        sys.exit(1)

    for s in steps:
        colour = {"upgraded": "green", "unchanged": "dim", "failed": "red"}[s.status]
        console.print(
            f"[{colour}]{s.status:9}[/{colour}] [cyan]{s.host}[/cyan] "
            f"({s.phase}) — {s.detail}"
        )


@main.command()
@click.argument("host")
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
)
@click.option("--project", "-p", default="central", show_default=True)
@click.option("--service", "-s", default=None, help="Filter to a single service")
@click.option("--tail", "-n", default=200, show_default=True, type=int)
@click.option("--follow", "-f", is_flag=True, help="Stream new log lines")
def logs(
    host: str,
    inventory: Path,
    project: str,
    service: str | None,
    tail: int,
    follow: bool,
) -> None:
    """Tail `docker compose logs` for a project on a host."""
    from monctl_installer.commands.diagnostics import find_host, logs_exec

    try:
        h = find_host(inventory, host)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    logs_exec(h, project=project, service=service, tail=tail, follow=follow)


@main.command(name="add-host")
@click.argument("name")
@click.option("--address", required=True, help="IP address of the new host")
@click.option(
    "--roles",
    required=True,
    help="Comma-separated roles (leaf only today: collector, docker_stats)",
)
@click.option("--ssh-user", default="monctl", show_default=True)
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
)
def add_host_cmd(
    name: str, address: str, roles: str, ssh_user: str, inventory: Path
) -> None:
    """Append a host to the inventory and deploy to it (collectors only)."""
    from monctl_installer.commands.topology import TopologyError, add_host
    from monctl_installer.secrets.store import SecretsFileError

    try:
        changes = add_host(
            inventory,
            name=name,
            address=address,
            roles=[r.strip() for r in roles.split(",") if r.strip()],
            ssh_user=ssh_user,
        )
    except (TopologyError, SecretsFileError) as exc:
        err_console.print(f"[red]add-host failed:[/red] {exc}")
        sys.exit(1)
    for c in changes:
        colour = {"added": "green", "removed": "yellow", "failed": "red"}[c.action]
        console.print(f"[{colour}]{c.action}[/{colour}] [cyan]{c.host}[/cyan] — {c.detail}")
    if any(c.action == "failed" for c in changes):
        sys.exit(1)


@main.command(name="remove-host")
@click.argument("name")
@click.option(
    "--force",
    is_flag=True,
    help="Allow removing hosts that carry non-leaf roles "
    "(you must have deregistered from Patroni/etcd/CH first)",
)
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
)
def remove_host_cmd(name: str, force: bool, inventory: Path) -> None:
    """Stop + strip a host from the inventory."""
    from monctl_installer.commands.topology import TopologyError, remove_host

    try:
        changes = remove_host(inventory, name=name, force=force)
    except TopologyError as exc:
        err_console.print(f"[red]remove-host failed:[/red] {exc}")
        sys.exit(1)
    for c in changes:
        colour = {"added": "green", "removed": "yellow", "failed": "red"}[c.action]
        console.print(f"[{colour}]{c.action}[/{colour}] [cyan]{c.host}[/cyan] — {c.detail}")


@main.group()
def bundle() -> None:
    """Air-gapped install bundle: `create` on internet-connected host, `load` on target."""


@bundle.command("create")
@click.option("--version", required=True, help="Image tag to snapshot (e.g. v1.0.0)")
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Path to write the tarball (e.g. monctl-airgap-v1.0.0.tar.gz)",
)
@click.option(
    "--namespace",
    default="hansmeldgaard",
    show_default=True,
    help="GHCR owner/org namespace",
)
@click.option(
    "--registry", default="ghcr.io", show_default=True, help="Image registry host"
)
def bundle_create(version: str, out_path: Path, namespace: str, registry: str) -> None:
    """Pull + save images + docs + inventory examples into a self-contained tarball."""
    from monctl_installer.commands.bundle import BundleError, create_bundle

    repo_root = Path(__file__).resolve().parents[4]
    try:
        result = create_bundle(
            version=version,
            out_path=out_path,
            namespace=namespace,
            registry=registry,
            extras={"docs": repo_root, "inventory_examples": repo_root},
        )
    except BundleError as exc:
        err_console.print(f"[red]bundle create failed:[/red] {exc}")
        sys.exit(1)
    size_mb = result.size_bytes / (1024 * 1024)
    console.print(
        f"[green]bundle created[/green] → {result.path} ({size_mb:.1f} MB, "
        f"{len(result.components)} images)"
    )


@bundle.command("load")
@click.argument(
    "path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def bundle_load(path: Path) -> None:
    """Extract a bundle and `docker load` its images on this machine."""
    from monctl_installer.commands.bundle import BundleError, load_bundle

    try:
        loaded = load_bundle(path)
    except BundleError as exc:
        err_console.print(f"[red]bundle load failed:[/red] {exc}")
        sys.exit(1)
    for ref in loaded:
        console.print(f"[green]loaded[/green] {ref}")


@main.command(name="ssh")
@click.argument("host")
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
)
def ssh_cmd(host: str, inventory: Path) -> None:
    """Open an interactive SSH session to a host from the inventory."""
    from monctl_installer.commands.diagnostics import find_host, ssh_exec

    try:
        h = find_host(inventory, host)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    ssh_exec(h)


if __name__ == "__main__":  # pragma: no cover
    main()
