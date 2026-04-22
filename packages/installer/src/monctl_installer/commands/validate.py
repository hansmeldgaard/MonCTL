"""`monctl_ctl validate` — SSH preflight against every host in the inventory."""
from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from monctl_installer.inventory.loader import load_inventory
from monctl_installer.inventory.planner import plan_cluster
from monctl_installer.remote.preflight import PreflightSummary, run_preflight
from monctl_installer.remote.ssh import SSHRunner


def run(inventory_path: Path, console: Console) -> PreflightSummary:
    inv = load_inventory(inventory_path)
    plan = plan_cluster(inv)
    runner = SSHRunner()
    summary = run_preflight(plan, runner)
    _print_table(summary, console)
    return summary


def _print_table(summary: PreflightSummary, console: Console) -> None:
    table = Table(title="Preflight checks", show_lines=False)
    table.add_column("Host", style="cyan", no_wrap=True)
    table.add_column("Check", no_wrap=True)
    table.add_column("Result")
    table.add_column("Detail", overflow="fold")
    for r in summary.results:
        colour = {"pass": "green", "warn": "yellow", "fail": "red"}[r.severity]
        table.add_row(r.host, r.check, f"[{colour}]{r.severity}[/{colour}]", r.detail)
    console.print(table)
    fails = sum(1 for r in summary.results if r.severity == "fail")
    warns = sum(1 for r in summary.results if r.severity == "warn")
    if fails:
        console.print(f"[red]{fails} failure(s)[/red]; deploy will be refused until resolved")
    elif warns:
        console.print(f"[yellow]{warns} warning(s)[/yellow]; deploy will proceed")
    else:
        console.print("[green]all checks passed[/green]")
