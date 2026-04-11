"""Unit tests for connector slot declaration parser."""

from __future__ import annotations

import pytest

from monctl_central.apps.connector_declaration import (
    ConnectorDeclarationError,
    extract_required_connectors,
)


# ── Happy-path ────────────────────────────────────────────────────────────


def test_none_when_not_declared():
    """Legacy app that does not declare required_connectors at all.

    The router uses this to decide "graceful fallback — leave existing
    bindings alone".
    """
    source = """
class Poller:
    async def poll(self, context):
        return None
"""
    assert extract_required_connectors(source) is None


def test_empty_dict_literal_declared():
    """Explicit empty declaration (e.g. ping_check — no connector needed).

    Distinct from "not declared"; the router uses this to orphan any
    existing bindings.
    """
    source = """
class Poller:
    required_connectors = {}
    async def poll(self, context):
        return None
"""
    assert extract_required_connectors(source) == {}


def test_single_connector():
    source = """
class Poller:
    required_connectors = {"snmp": "snmp"}
"""
    assert extract_required_connectors(source) == {"snmp": "snmp"}


def test_multiple_connectors_of_different_types():
    source = """
class Poller:
    required_connectors = {"snmp": "snmp", "ssh": "ssh"}
"""
    assert extract_required_connectors(source) == {"snmp": "snmp", "ssh": "ssh"}


def test_multiple_connectors_of_same_type_with_custom_aliases():
    source = """
class Poller:
    required_connectors = {"primary": "snmp", "backup": "snmp"}
"""
    assert extract_required_connectors(source) == {"primary": "snmp", "backup": "snmp"}


def test_annotated_declaration():
    source = """
from typing import ClassVar
class Poller:
    required_connectors: ClassVar[dict[str, str]] = {"snmp": "snmp"}
"""
    assert extract_required_connectors(source) == {"snmp": "snmp"}


def test_bare_annotation_without_value_treated_as_not_declared():
    source = """
from typing import ClassVar
class Poller:
    required_connectors: ClassVar[dict[str, str]]
"""
    assert extract_required_connectors(source) is None


def test_custom_entry_class_name():
    source = """
class MyCustomPoller:
    required_connectors = {"snmp": "snmp"}
class Poller:
    required_connectors = {"ssh": "ssh"}
"""
    # Entry class is MyCustomPoller — should return that, not Poller
    assert extract_required_connectors(source, entry_class="MyCustomPoller") == {"snmp": "snmp"}
    # Default entry class is "Poller"
    assert extract_required_connectors(source) == {"ssh": "ssh"}


def test_realistic_snmp_check_source():
    source = '''
from monctl_collector.polling.base import BasePoller
from monctl_collector.jobs.models import PollContext, PollResult

class Poller(BasePoller):
    """SNMP check poller."""

    required_connectors = {"snmp": "snmp"}

    async def poll(self, context: PollContext) -> PollResult:
        snmp = context.connectors["snmp"]
        return await snmp.get(["1.3.6.1.2.1.1.3.0"])
'''
    assert extract_required_connectors(source) == {"snmp": "snmp"}


# ── Validation errors ────────────────────────────────────────────────────


def test_rejects_list_literal():
    source = """
class Poller:
    required_connectors = ["snmp"]
"""
    with pytest.raises(ConnectorDeclarationError, match="must be a dict"):
        extract_required_connectors(source)


def test_rejects_set_literal():
    source = """
class Poller:
    required_connectors = {"snmp"}
"""
    with pytest.raises(ConnectorDeclarationError, match="must be a dict"):
        extract_required_connectors(source)


def test_rejects_non_literal_expression():
    source = """
class Poller:
    required_connectors = dict(snmp="snmp")
"""
    with pytest.raises(ConnectorDeclarationError, match="literal dict"):
        extract_required_connectors(source)


def test_rejects_non_string_keys():
    source = """
class Poller:
    required_connectors = {1: "snmp"}
"""
    with pytest.raises(ConnectorDeclarationError, match="keys must be non-empty strings"):
        extract_required_connectors(source)


def test_rejects_non_string_values():
    source = """
class Poller:
    required_connectors = {"snmp": 1}
"""
    with pytest.raises(ConnectorDeclarationError, match="values must be non-empty strings"):
        extract_required_connectors(source)


def test_rejects_empty_alias_key():
    source = """
class Poller:
    required_connectors = {"": "snmp"}
"""
    with pytest.raises(ConnectorDeclarationError, match="keys must be non-empty strings"):
        extract_required_connectors(source)


def test_rejects_empty_connector_type_value():
    source = """
class Poller:
    required_connectors = {"snmp": ""}
"""
    with pytest.raises(ConnectorDeclarationError, match="values must be non-empty strings"):
        extract_required_connectors(source)


def test_raises_syntax_error_on_broken_source():
    source = "class Poller\n    required_connectors = {"
    with pytest.raises(SyntaxError):
        extract_required_connectors(source)


# ── Edge cases ───────────────────────────────────────────────────────────


def test_ignores_declaration_outside_poller_class():
    source = """
required_connectors = {"snmp": "snmp"}

class Poller:
    pass
"""
    assert extract_required_connectors(source) is None


def test_ignores_declaration_on_wrong_class():
    source = """
class Helper:
    required_connectors = {"snmp": "snmp"}

class Poller:
    pass
"""
    assert extract_required_connectors(source) is None


def test_returns_copy_not_reference():
    source = """
class Poller:
    required_connectors = {"snmp": "snmp"}
"""
    result1 = extract_required_connectors(source)
    result1["ssh"] = "ssh"  # mutate
    result2 = extract_required_connectors(source)
    assert result2 == {"snmp": "snmp"}  # unaffected
