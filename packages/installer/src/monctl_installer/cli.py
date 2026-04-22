from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from monctl_installer.version import __version__

console = Console()
err_console = Console(stderr=True)


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
    "--force", is_flag=True, help="Overwrite existing inventory.yaml / secrets.env"
)
def init(
    inventory: Path,
    secrets_path: Path,
    seed_path: Path | None,
    force: bool,
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
            )
        else:
            result = run_interactive(
                inventory_path=inventory,
                secrets_path=secrets_path,
                overwrite=force,
            )
    except InitError as exc:
        err_console.print(f"[red]init failed:[/red] {exc}")
        sys.exit(1)

    console.print()
    console.print(f"[green]wrote[/green] inventory → {result.inventory_path}")
    console.print(f"[green]wrote[/green] secrets   → {result.secrets_path} (mode 0600)")
    console.print()
    console.print("[bold red]── ADMIN CREDENTIALS — SAVE THIS NOW ──[/bold red]")
    console.print(f"URL:      [cyan]{result.login_url}[/cyan]")
    console.print("Username: [cyan]admin[/cyan]")
    console.print(f"Password: [yellow]{result.admin_password}[/yellow]")
    console.print("[dim]This password is also in secrets.env but will never be printed again.[/dim]")
    console.print()
    console.print("Next: [cyan]monctl_ctl validate[/cyan] to pre-flight the target hosts")


@main.command()
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./inventory.yaml"),
    show_default=True,
    help="Path to inventory.yaml",
)
def validate(inventory: Path) -> None:
    """SSH-reachability + Docker + ports + RAM + disk + time-sync preflight."""
    from monctl_installer.commands.validate import run as run_validate
    from monctl_installer.inventory.loader import InventoryValidationError

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
def deploy(inventory: Path, dry_run: bool) -> None:
    """SSH-distribute compose bundles and `docker compose up -d` on every host."""
    from monctl_installer.commands.deploy import deploy as run_deploy
    from monctl_installer.inventory.loader import InventoryValidationError
    from monctl_installer.secrets.store import SecretsFileError

    try:
        outcomes = run_deploy(inventory, dry_run=dry_run)
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
def status(inventory: Path) -> None:
    """Probe each host and print cluster health summary."""
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
def upgrade(version: str, inventory: Path, canary: str | None) -> None:
    """Rolling upgrade to <version>: canary → remaining centrals → collectors."""
    from monctl_installer.commands.upgrade import UpgradeAborted, upgrade as run_upgrade
    from monctl_installer.inventory.loader import InventoryValidationError
    from monctl_installer.secrets.store import SecretsFileError

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
