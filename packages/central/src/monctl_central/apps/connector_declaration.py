"""Parse connector-slot declarations from Poller source code.

Apps declare their connector requirements via a ``required_connectors``
class attribute on their ``Poller`` class — a list of connector types
(e.g. ``["snmp"]``, ``["snmp", "ssh"]``). We read it at version-upload
time so the operator only has to pick a concrete connector per slot.

We parse with the ``ast`` module and evaluate the RHS with
``ast.literal_eval`` — we never ``exec`` or import the source, so
arbitrary code at upload time cannot run.
"""

from __future__ import annotations

import ast
import logging

log = logging.getLogger(__name__)


class ConnectorDeclarationError(ValueError):
    """Raised when ``required_connectors`` is declared but invalid."""


def extract_required_connectors(
    source: str,
    entry_class: str = "Poller",
) -> list[str] | None:
    """Extract the ``required_connectors`` declaration from app source.

    Returns:
        * ``None`` — the Poller class does **not** declare
          ``required_connectors`` at all. The caller should treat this as
          a legacy app and leave any existing bindings alone.
        * ``[]`` — the Poller class declares ``required_connectors = []``
          explicitly (e.g. ``ping_check``: no connectors needed).
        * ``["snmp", ...]`` — normal case, list of connector types.

    For backward compatibility, a dict RHS is also accepted: only its
    values (the connector types) are used, keys are ignored, duplicates
    deduped while preserving order. A deprecation warning is logged.

    Raises:
        ConnectorDeclarationError: If the value is not a literal
            list/dict of connector-type strings, or contains duplicates.
        SyntaxError: If the source code itself cannot be parsed.
    """
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != entry_class:
            continue

        for stmt in node.body:
            target_names = _targets(stmt)
            if "required_connectors" not in target_names:
                continue

            rhs = _rhs(stmt)
            if rhs is None:
                return None

            try:
                value = ast.literal_eval(rhs)
            except (ValueError, SyntaxError) as exc:
                raise ConnectorDeclarationError(
                    "required_connectors must be a literal list of connector-type "
                    f"strings (got expression that cannot be evaluated): {exc}"
                ) from exc

            if isinstance(value, dict):
                log.warning(
                    "required_connectors declared as dict is deprecated; "
                    "use a list of connector types instead (keys are ignored)"
                )
                types = list(value.values())
            elif isinstance(value, (list, tuple)):
                types = list(value)
            else:
                raise ConnectorDeclarationError(
                    f"required_connectors must be a list, got {type(value).__name__}"
                )

            seen: set[str] = set()
            result: list[str] = []
            for ctype in types:
                if not isinstance(ctype, str) or not ctype:
                    raise ConnectorDeclarationError(
                        f"required_connectors entries must be non-empty strings "
                        f"(got {ctype!r})"
                    )
                if ctype in seen:
                    raise ConnectorDeclarationError(
                        f"required_connectors contains duplicate connector type {ctype!r}"
                    )
                seen.add(ctype)
                result.append(ctype)

            return result

    return None


def _targets(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, ast.Assign):
        return [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return [stmt.target.id]
    return []


def _rhs(stmt: ast.stmt) -> ast.expr | None:
    if isinstance(stmt, ast.Assign):
        return stmt.value
    if isinstance(stmt, ast.AnnAssign):
        return stmt.value
    return None
