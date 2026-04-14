"""Negatable ILIKE filter helper.

All list endpoints accept free-text filter values. By convention a value
that starts with `!` is a negation — the matching rows are EXCLUDED
rather than included. Otherwise the value matches as a case-insensitive
substring (ILIKE `%value%`).

Leading `!` is consumed; to literally match a string beginning with `!`,
escape it as `\\!`.

Examples (applied to Device.name):

    ilike_filter(Device.name, "cisco")     # name ILIKE '%cisco%'
    ilike_filter(Device.name, "!cisco")    # name NOT ILIKE '%cisco%' OR name IS NULL
    ilike_filter(Device.name, "")          # returns None (no filter)
    ilike_filter(Device.name, "\\!literal") # name ILIKE '%!literal%'

The NULL-safe handling matters for outer-joined columns (Tenant.name,
CollectorGroup.name) — a plain `NOT ILIKE` would drop rows whose joined
value is NULL, which is surprising for a "name != X" filter.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement


def ilike_filter(column: ColumnElement, value: str | None) -> ColumnElement | None:
    """Build a negatable ILIKE clause.

    Returns None when value is None or empty, so callers can skip the
    ``.where()`` entirely. Returns a NOT-ILIKE-with-NULL-allowed clause
    when the value starts with an unescaped `!`.
    """
    if value is None:
        return None
    if value == "":
        return None
    negate = False
    if value.startswith("!"):
        negate = True
        value = value[1:]
    elif value.startswith("\\!"):
        value = value[1:]  # drop the escape char
    pattern = f"%{value}%"
    if negate:
        return sa.or_(column.is_(None), sa.not_(column.ilike(pattern)))
    return column.ilike(pattern)
