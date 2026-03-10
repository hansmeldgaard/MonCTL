"""Persistent TUI state — saved to /etc/monctl/setup.yaml (0600 permissions)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

STATE_PATH = Path(os.environ.get("MONCTL_SETUP_STATE", "/etc/monctl/setup.yaml"))


@dataclass
class SetupState:
    central_url: str = ""
    collector_id: str = ""
    api_key: str = ""
    fingerprint: str = ""
    status: str = ""

    def save(self) -> None:
        """Persist state to disk with restrictive permissions."""
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in asdict(self).items() if v}
        STATE_PATH.write_text(yaml.dump(data, default_flow_style=False))
        try:
            os.chmod(STATE_PATH, 0o600)
        except OSError:
            pass

    @classmethod
    def load(cls) -> "SetupState":
        """Load state from disk, return empty state if file doesn't exist."""
        if not STATE_PATH.exists():
            return cls()
        try:
            data = yaml.safe_load(STATE_PATH.read_text()) or {}
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            return cls()
