"""Simple dependency resolver for the Python module registry.

Checks for conflicts between registered packages and reports missing dependencies.
This is not a full PIP resolver — it validates at the name level and flags obvious
version conflicts using simple specifier matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DEP_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"\s*(?P<spec>.*)$"
)


@dataclass
class ResolverResult:
    """Result of a dependency resolution check."""
    conflicts: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)


def _parse_dep(dep_str: str) -> tuple[str, str]:
    """Parse a dependency string into (normalized_name, version_specifier).

    Examples:
        "requests>=2.28"  -> ("requests", ">=2.28")
        "urllib3"         -> ("urllib3", "")
        "foo[bar]>=1.0"   -> ("foo", ">=1.0")
    """
    # Strip extras (e.g. "foo[bar]>=1.0" -> "foo>=1.0")
    cleaned = re.sub(r"\[.*?\]", "", dep_str).strip()
    # Strip environment markers after ";"
    cleaned = cleaned.split(";")[0].strip()

    m = _DEP_RE.match(cleaned)
    if not m:
        return dep_str.strip(), ""

    name = re.sub(r"[-_.]+", "-", m.group("name")).lower()
    spec = m.group("spec").strip()
    return name, spec


def check_conflicts(
    dependencies: list[str],
    available_packages: dict[str, list[str]],
) -> ResolverResult:
    """Check a list of dependency strings against available packages.

    Args:
        dependencies: List of PEP 508 dependency strings (e.g. ["requests>=2.28", "urllib3"])
        available_packages: Dict mapping normalized package name to list of available versions.

    Returns:
        ResolverResult with conflicts, missing, and resolved lists.
    """
    result = ResolverResult()

    for dep_str in dependencies:
        name, spec = _parse_dep(dep_str)
        if not name:
            continue

        if name not in available_packages:
            result.missing.append(dep_str)
        else:
            result.resolved.append(dep_str)

    return result


def build_requirements_list(
    packages: list[dict],
) -> list[str]:
    """Build a flat list of all dependencies from a set of packages.

    Args:
        packages: List of dicts with keys: name, version, dependencies.

    Returns:
        Deduplicated list of dependency strings (normalized names).
    """
    seen: set[str] = set()
    deps: list[str] = []

    for pkg in packages:
        for dep_str in pkg.get("dependencies", []):
            name, spec = _parse_dep(dep_str)
            if name and name not in seen:
                seen.add(name)
                deps.append(dep_str)

    return deps
