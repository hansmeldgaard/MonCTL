"""Severity rank helpers for the tiered-alert model.

`AlertDefinition.severity_tiers` is an ordered list (lowest severity
first), but the engine needs to compare two arbitrary severity strings
to decide whether a transition is an escalate, a downgrade, or a
same-severity no-op. Ranks are defined here in one place so the pack
format, engine, and UI agree on ordering.

Unknown severities default to rank -1 (below `info`) so they sort
below everything and never accidentally supersede a known severity.
"""

from __future__ import annotations

SEVERITY_RANK: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "critical": 2,
}


def rank(severity: str | None) -> int:
    if severity is None:
        return -1
    return SEVERITY_RANK.get(severity, -1)


def compare(a: str | None, b: str | None) -> int:
    """Return <0 if a < b, 0 if equal, >0 if a > b."""
    return rank(a) - rank(b)


def highest(severities: list[str]) -> str | None:
    """Return the highest-ranked severity in the list, or None if empty."""
    if not severities:
        return None
    return max(severities, key=rank)
