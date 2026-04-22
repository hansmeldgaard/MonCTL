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


if __name__ == "__main__":  # pragma: no cover
    main()
