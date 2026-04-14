"""Unit tests for connector slot declaration parser."""

from __future__ import annotations

import logging

import pytest

from monctl_central.apps.connector_declaration import (
    ConnectorDeclarationError,
    extract_required_connectors,
)


# ── Happy-path ────────────────────────────────────────────────────────────


def test_none_when_not_declared():
    """Legacy app that does not declare required_connectors at all."""
    source = """
class Poller:
    async def poll(self, context):
        return None
"""
    assert extract_required_connectors(source) is None


def test_empty_list_literal_declared():
    """Explicit empty declaration (e.g. ping_check — no connector needed)."""
    source = """
class Poller:
    required_connectors = []
    async def poll(self, context):
        return None
"""
    assert extract_required_connectors(source) == []


def test_single_connector():
    source = """
class Poller:
    required_connectors = ["snmp"]
"""
    assert extract_required_connectors(source) == ["snmp"]


def test_multiple_connectors():
    source = """
class Poller:
    required_connectors = ["snmp", "ssh"]
"""
    assert extract_required_connectors(source) == ["snmp", "ssh"]


def test_tuple_literal_accepted():
    source = """
class Poller:
    required_connectors = ("snmp", "ssh")
"""
    assert extract_required_connectors(source) == ["snmp", "ssh"]


def test_annotated_declaration():
    source = """
from typing import ClassVar
class Poller:
    required_connectors: ClassVar[list[str]] = ["snmp"]
"""
    assert extract_required_connectors(source) == ["snmp"]


def test_bare_annotation_without_value_treated_as_not_declared():
    source = """
from typing import ClassVar
class Poller:
    required_connectors: ClassVar[list[str]]
"""
    assert extract_required_connectors(source) is None


def test_custom_entry_class_name():
    source = """
class MyCustomPoller:
    required_connectors = ["snmp"]
class Poller:
    required_connectors = ["ssh"]
"""
    assert extract_required_connectors(source, entry_class="MyCustomPoller") == ["snmp"]
    assert extract_required_connectors(source) == ["ssh"]


def test_realistic_snmp_check_source():
    source = '''
from monctl_collector.polling.base import BasePoller

class Poller(BasePoller):
    """SNMP check poller."""

    required_connectors = ["snmp"]

    async def poll(self, context):
        snmp = context.connectors["snmp"]
        return await snmp.get(["1.3.6.1.2.1.1.3.0"])
'''
    assert extract_required_connectors(source) == ["snmp"]


# ── Backward compatibility with dict form ───────────────────────────────


def test_dict_form_accepted_with_deprecation_warning(caplog):
    source = """
class Poller:
    required_connectors = {"snmp": "snmp", "ssh": "ssh"}
"""
    with caplog.at_level(logging.WARNING, logger="monctl_central.apps.connector_declaration"):
        result = extract_required_connectors(source)
    assert result == ["snmp", "ssh"]
    assert any("deprecated" in rec.message for rec in caplog.records)


def test_dict_form_dedupes_duplicate_values():
    source = """
class Poller:
    required_connectors = {"primary": "snmp", "backup": "snmp"}
"""
    with pytest.raises(ConnectorDeclarationError, match="duplicate connector type"):
        extract_required_connectors(source)


# ── Validation errors ────────────────────────────────────────────────────


def test_rejects_duplicate_types():
    source = """
class Poller:
    required_connectors = ["snmp", "snmp"]
"""
    with pytest.raises(ConnectorDeclarationError, match="duplicate"):
        extract_required_connectors(source)


def test_rejects_set_literal():
    source = """
class Poller:
    required_connectors = {"snmp"}
"""
    with pytest.raises(ConnectorDeclarationError, match="must be a list"):
        extract_required_connectors(source)


def test_rejects_non_literal_expression():
    source = """
class Poller:
    required_connectors = list(x for x in range(1))
"""
    with pytest.raises(ConnectorDeclarationError, match="literal list"):
        extract_required_connectors(source)


def test_rejects_non_string_entry():
    source = """
class Poller:
    required_connectors = [1]
"""
    with pytest.raises(ConnectorDeclarationError, match="must be non-empty strings"):
        extract_required_connectors(source)


def test_rejects_empty_string_entry():
    source = """
class Poller:
    required_connectors = [""]
"""
    with pytest.raises(ConnectorDeclarationError, match="must be non-empty strings"):
        extract_required_connectors(source)


def test_raises_syntax_error_on_broken_source():
    source = "class Poller\n    required_connectors = ["
    with pytest.raises(SyntaxError):
        extract_required_connectors(source)


# ── Edge cases ───────────────────────────────────────────────────────────


def test_ignores_declaration_outside_poller_class():
    source = """
required_connectors = ["snmp"]

class Poller:
    pass
"""
    assert extract_required_connectors(source) is None


def test_ignores_declaration_on_wrong_class():
    source = """
class Helper:
    required_connectors = ["snmp"]

class Poller:
    pass
"""
    assert extract_required_connectors(source) is None
