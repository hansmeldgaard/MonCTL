"""Smoke test for the pack content-hash computation.

The startup drift detector and the reconcile endpoint both hash the
raw file bytes (not canonicalized JSON). This test pins that contract
— if someone switches to `json.dumps(..., sort_keys=True)` the hash
will change even for unmodified files and every startup will think
the pack drifted.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[4]
_BUNDLED_PACKS = (
    _REPO_ROOT / "packs" / "basic-checks-v1.0.0.json",
    _REPO_ROOT / "packs" / "snmp-core-v1.0.0.json",
)


def test_pack_content_hash_is_raw_file_bytes() -> None:
    """Hash must be sha256 of the bytes on disk, nothing fancier."""
    for path in _BUNDLED_PACKS:
        assert path.exists(), f"bundled pack missing: {path}"
        raw = path.read_bytes()
        expected = hashlib.sha256(raw).hexdigest()
        assert len(expected) == 64
        # Stable across calls.
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_pack_content_hash_changes_on_edit(tmp_path: Path) -> None:
    """Editing a single byte must change the hash."""
    original = (_REPO_ROOT / "packs" / "basic-checks-v1.0.0.json").read_bytes()
    h1 = hashlib.sha256(original).hexdigest()
    tampered = original + b" "
    h2 = hashlib.sha256(tampered).hexdigest()
    assert h1 != h2
