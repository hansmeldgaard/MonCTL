#!/usr/bin/env python3
"""Validate every built-in monitoring pack JSON on disk.

Catches the failure modes from F-APP-011/012/013 before the pack
lands in production or on a central startup import:

1. Pack `version` must be >= the highest `version` of any contained
   app or connector (so an operator reading `packs/` can trust the
   pack version as a summary).
2. Every app / connector `source_code` must compile via `compile()`.
3. No obviously-leaked secret literals inside `source_code` /
   `config_schema.default`.
4. `required_connectors` on apps must be a list of strings.

Exit status:
  0 - all packs valid
  1 - at least one pack failed; stderr carries a punch list.

Usage:
  python scripts/validate_packs.py                # validate packs/*.json
  python scripts/validate_packs.py path/to/*.json # or specific files

Run in pre-commit and CI.  A pytest wrapper lives at
`tests/central/test_pack_validation.py` so it also runs with the
regular test suite.
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

# Case-insensitive secret heuristics — applied only inside source_code
# strings and config_schema defaults. Declared at module scope so the
# pytest wrapper can import them for targeted unit tests.
_SECRET_VALUE_RES = [
    re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"]{4,}['\"]"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    re.compile(r"(?i)secret\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
]


def _parse_semver(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) if parts else (0,)


def _scan_for_secrets(label: str, text: str, errors: list[str]) -> None:
    if not isinstance(text, str):
        return
    for pattern in _SECRET_VALUE_RES:
        m = pattern.search(text)
        if m:
            errors.append(f"{label}: possible secret literal: {m.group(0)[:80]}")


def validate_pack(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON — {exc}"]

    pack_uid = pack.get("pack_uid")
    pack_ver = pack.get("version")
    if not pack_uid or not pack_ver:
        errors.append(f"{path}: missing pack_uid or version")
        return errors

    contents = pack.get("contents") or {}
    apps = contents.get("apps") or []
    connectors = contents.get("connectors") or []

    max_contained: tuple[int, ...] = (0,)
    max_contained_label = ""

    def _track(name: str, ver: str) -> None:
        nonlocal max_contained, max_contained_label
        parsed = _parse_semver(ver)
        if parsed > max_contained:
            max_contained = parsed
            max_contained_label = f"{name}@{ver}"

    for app in apps:
        name = app.get("name", "<anonymous app>")
        rc = app.get("required_connectors")
        if rc is not None:
            if not isinstance(rc, list) or not all(isinstance(x, str) for x in rc):
                errors.append(f"{path}:{name}: required_connectors must be list[str]")
        cs_default = ((app.get("config_schema") or {}).get("default"))
        if cs_default is not None:
            _scan_for_secrets(f"{path}:{name}:config_schema.default", json.dumps(cs_default), errors)

        for ver in app.get("versions") or []:
            v = ver.get("version")
            if not v:
                errors.append(f"{path}:{name}: version missing `version` field")
                continue
            _track(name, v)
            src = ver.get("source_code") or ""
            if src:
                try:
                    compile(src, f"{pack_uid}:{name}@{v}", "exec")
                except SyntaxError as exc:
                    errors.append(
                        f"{path}:{name}@{v}: source_code SyntaxError — {exc.msg} at line {exc.lineno}"
                    )
                _scan_for_secrets(f"{path}:{name}@{v}:source_code", src, errors)

    for conn in connectors:
        name = conn.get("name", "<anonymous connector>")
        for ver in conn.get("versions") or []:
            v = ver.get("version")
            if not v:
                errors.append(f"{path}:{name}: connector version missing `version` field")
                continue
            _track(name, v)
            src = ver.get("source_code") or ""
            if src:
                try:
                    compile(src, f"{pack_uid}:{name}@{v}", "exec")
                except SyntaxError as exc:
                    errors.append(
                        f"{path}:{name}@{v}: connector source_code SyntaxError — {exc.msg} at line {exc.lineno}"
                    )
                _scan_for_secrets(f"{path}:{name}@{v}:source_code", src, errors)

    pack_parsed = _parse_semver(pack_ver)
    if max_contained > pack_parsed:
        errors.append(
            f"{path}: pack version {pack_ver} trails max contained {max_contained_label}. "
            "Bump pack.version to match."
        )

    return errors


def main(argv: list[str]) -> int:
    targets = argv[1:] or sorted(
        str(p) for p in (Path(__file__).resolve().parent.parent / "packs").glob("*.json")
    )
    if not targets:
        print("validate_packs: no pack files to validate", file=sys.stderr)
        return 1

    total_errors: list[str] = []
    for t in targets:
        for entry in glob.glob(t) or [t]:
            total_errors.extend(validate_pack(Path(entry)))

    if total_errors:
        print("Pack validation failed:\n", file=sys.stderr)
        for line in total_errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"validate_packs: OK ({len(targets)} pack(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
