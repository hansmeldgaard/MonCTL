"""F-APP-011 / F-APP-012 / F-APP-013: pack JSON sanity in CI.

Wraps `scripts/validate_packs.py` so the checks run as part of the
regular pytest suite, and adds a few targeted unit tests on the
internal helpers so regressions in the secret-scan heuristics or
semver parser surface with a useful diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import validate_packs  # noqa: E402  (sys.path manipulated above)


def test_builtin_packs_validate() -> None:
    errors: list[str] = []
    for pack_file in sorted((_REPO_ROOT / "packs").glob("*.json")):
        errors.extend(validate_packs.validate_pack(pack_file))
    assert errors == [], "Built-in packs failed validation:\n" + "\n".join(errors)


def test_pack_version_trails_detection(tmp_path: Path) -> None:
    pack = {
        "monctl_pack": "1.0",
        "pack_uid": "test",
        "version": "1.0.0",
        "contents": {
            "apps": [
                {
                    "name": "demo",
                    "versions": [{"version": "2.0.0", "source_code": "x = 1\n"}],
                }
            ],
        },
    }
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack))
    errors = validate_packs.validate_pack(path)
    assert any("trails max contained" in e for e in errors), errors


def test_syntax_error_in_source_code(tmp_path: Path) -> None:
    pack = {
        "monctl_pack": "1.0",
        "pack_uid": "test",
        "version": "1.0.0",
        "contents": {
            "apps": [
                {
                    "name": "broken",
                    "versions": [{"version": "1.0.0", "source_code": "def x(:\n"}],
                }
            ],
        },
    }
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack))
    errors = validate_packs.validate_pack(path)
    assert any("SyntaxError" in e for e in errors), errors


def test_secret_in_source_code(tmp_path: Path) -> None:
    pack = {
        "monctl_pack": "1.0",
        "pack_uid": "test",
        "version": "1.0.0",
        "contents": {
            "apps": [
                {
                    "name": "leaky",
                    "versions": [
                        {
                            "version": "1.0.0",
                            "source_code": "password = 'hunter2rocks'\n",
                        }
                    ],
                }
            ],
        },
    }
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack))
    errors = validate_packs.validate_pack(path)
    assert any("possible secret literal" in e for e in errors), errors


def test_required_connectors_shape(tmp_path: Path) -> None:
    pack = {
        "monctl_pack": "1.0",
        "pack_uid": "test",
        "version": "1.0.0",
        "contents": {
            "apps": [
                {
                    "name": "bad_rc",
                    "required_connectors": "snmp",
                    "versions": [{"version": "1.0.0", "source_code": "x = 1\n"}],
                }
            ],
        },
    }
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack))
    errors = validate_packs.validate_pack(path)
    assert any("required_connectors must be list[str]" in e for e in errors), errors


@pytest.mark.parametrize(
    "v,expected",
    [
        ("1.2.3", (1, 2, 3)),
        ("2.1.0", (2, 1, 0)),
        ("1.3.2", (1, 3, 2)),
        ("v1.2", (1, 2)),
    ],
)
def test_parse_semver(v: str, expected: tuple[int, ...]) -> None:
    assert validate_packs._parse_semver(v) == expected
