"""`monctl_ctl render` — load inventory, plan, render per-host bundles to disk."""
from __future__ import annotations

from pathlib import Path

from monctl_installer.inventory.loader import InventoryValidationError, load_inventory
from monctl_installer.inventory.planner import PlanError, plan_cluster
from monctl_installer.render.engine import render_plan


def run(inventory_path: Path, out_dir: Path) -> dict[str, list[Path]]:
    inv = load_inventory(inventory_path)
    try:
        plan = plan_cluster(inv)
    except PlanError as exc:
        raise InventoryValidationError(str(exc)) from exc
    out_dir.mkdir(parents=True, exist_ok=True)
    return render_plan(plan, out_dir)
