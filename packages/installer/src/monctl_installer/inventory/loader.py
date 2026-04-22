"""Load inventory.yaml → validated Inventory model."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from monctl_installer.inventory.schema import Inventory


class InventoryValidationError(Exception):
    """Raised when inventory.yaml cannot be parsed or fails schema validation."""


def load_inventory(path: Path) -> Inventory:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise InventoryValidationError(f"{path}: invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise InventoryValidationError(f"{path}: top-level must be a mapping")

    try:
        return Inventory.model_validate(raw)
    except ValidationError as exc:
        raise InventoryValidationError(f"{path}:\n{exc}") from exc
