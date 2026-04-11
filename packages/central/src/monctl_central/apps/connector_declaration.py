"""Parse connector-slot declarations from Poller source code.

Apps declare their connector requirements via a ``required_connectors``
class attribute on their ``Poller`` class (alias → connector_type). We
read it at version-upload time so the operator only has to pick a
concrete connector per slot instead of typing magic aliases.

We parse with the ``ast`` module and evaluate the RHS with
``ast.literal_eval`` — we never ``exec`` or import the source, so
arbitrary code at upload time cannot run.
"""

from __future__ import annotations

import ast


class ConnectorDeclarationError(ValueError):
    """Raised when ``required_connectors`` is declared but invalid."""


def extract_required_connectors(
    source: str,
    entry_class: str = "Poller",
) -> dict[str, str]:
    """Extract the ``required_connectors`` declaration from app source code.

    Returns a dict mapping alias → connector_type. Returns an empty dict if
    the class does not declare ``required_connectors`` (this is a valid
    state — the app simply does not use any connector, like ``ping_check``).

    Raises:
        ConnectorDeclarationError: If ``required_connectors`` is declared
            but is not a literal dict of ``str`` → ``str``.
        SyntaxError: If the source code itself cannot be parsed as Python.
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
                # Bare annotation (``required_connectors: dict[str, str]``)
                # without a value — treat as "not declared".
                return {}

            try:
                value = ast.literal_eval(rhs)
            except (ValueError, SyntaxError) as exc:
                raise ConnectorDeclarationError(
                    f"required_connectors must be a literal dict of str→str "
                    f"(got expression that cannot be evaluated): {exc}"
                ) from exc

            if not isinstance(value, dict):
                raise ConnectorDeclarationError(
                    f"required_connectors must be a dict, got {type(value).__name__}"
                )

            for alias, ctype in value.items():
                if not isinstance(alias, str) or not alias:
                    raise ConnectorDeclarationError(
                        f"required_connectors keys must be non-empty strings (got {alias!r})"
                    )
                if not isinstance(ctype, str) or not ctype:
                    raise ConnectorDeclarationError(
                        f"required_connectors values must be non-empty strings "
                        f"(alias {alias!r} → {ctype!r})"
                    )

            return dict(value)

    return {}


def _targets(stmt: ast.stmt) -> list[str]:
    """Return the list of simple target names assigned to by this statement.

    Handles both plain assignments and annotated assignments. Returns an
    empty list for other statement types.
    """
    if isinstance(stmt, ast.Assign):
        return [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return [stmt.target.id]
    return []


def _rhs(stmt: ast.stmt) -> ast.expr | None:
    """Return the right-hand-side expression of an assignment statement.

    For annotated assignments without a value (e.g. ``x: int``), returns
    ``None``.
    """
    if isinstance(stmt, ast.Assign):
        return stmt.value
    if isinstance(stmt, ast.AnnAssign):
        return stmt.value
    return None
