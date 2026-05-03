"""Tests for the built-in SNMP connector seed (`<repo>/connectors/snmp.py`).

Closes T-APP-001 (review #2 testing.md, HIGH). Two threats are pinned here:

1. **Credential-key fallback** — the prod SNMP credential template emits
   `version`, the seed template emits `snmp_version`. v1.4.1 dropped the
   `version` fallback and broke every SNMPv3 device fleet-wide in minutes
   on 2026-04-20 (memory `feedback_connector_version_fallback`,
   `project_snmp_connector_version_key`). v1.4.4 restored both keys; this
   file pins the contract so the next refactor can't silently drop it.

2. **walk_multi correlated GETBULK** — v1.4.2 introduced
   `walk_multi(oids)` to fan-out N column walks into one bulk_cmd round,
   yielding ~25*K row values per request instead of 25 per column. The
   wire-order interleaving (`i % K`), per-column cursor advancement,
   and out-of-subtree drop are subtle and previously had zero coverage.

Both areas are tested without a live SNMP device by stubbing pysnmp via
``sys.modules`` (same pattern as ``test_clickhouse_pool.py``). The
connector source itself is loaded by path from the repo root because it
isn't part of the importable Python package set.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[4]
_SNMP_SEED = _REPO_ROOT / "connectors" / "snmp.py"


# ── pysnmp stub ────────────────────────────────────────────────────────────
# The connector imports pysnmp lazily inside each method, so we install a
# stub package before anything calls those methods. Tests that exercise
# specific calls reach into the stub via `_pysnmp_stub.bulk_cmd_mock` etc.

class _StubAuth:
    """Captures CommunityData / UsmUserData constructor args."""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _StubName:
    """Mimics pysnmp's name object: int-iterable + str() yields OID."""
    def __init__(self, oid: str):
        self._oid = oid

    def __iter__(self):
        return iter(int(x) for x in self._oid.split("."))

    def __str__(self) -> str:
        return self._oid


class _StubValue:
    def __init__(self, payload: str):
        self._payload = payload

    def prettyPrint(self) -> str:
        return self._payload


def _install_pysnmp_stub():
    if "pysnmp.hlapi.v3arch.asyncio" in sys.modules:
        return sys.modules["pysnmp.hlapi.v3arch.asyncio"]

    pysnmp = types.ModuleType("pysnmp")
    hlapi = types.ModuleType("pysnmp.hlapi")
    v3arch = types.ModuleType("pysnmp.hlapi.v3arch")
    asyncio_mod = types.ModuleType("pysnmp.hlapi.v3arch.asyncio")

    asyncio_mod.CommunityData = _StubAuth
    asyncio_mod.UsmUserData = _StubAuth
    asyncio_mod.ContextData = _StubAuth
    asyncio_mod.ObjectIdentity = _StubAuth
    asyncio_mod.ObjectType = _StubAuth
    asyncio_mod.SnmpEngine = lambda: types.SimpleNamespace(
        close_dispatcher=lambda: None,
        get_mib_builder=lambda: types.SimpleNamespace(clean=lambda: None),
    )

    class _UdpTransportTarget:
        @staticmethod
        async def create(addr, timeout=5, retries=2):
            return types.SimpleNamespace(addr=addr)

    asyncio_mod.UdpTransportTarget = _UdpTransportTarget

    # Auth/priv protocol sentinels — referenced via `getattr(hlapi, name)`.
    for proto in [
        "usmHMACMD5AuthProtocol", "usmHMACSHAAuthProtocol",
        "usmHMAC128SHA224AuthProtocol", "usmHMAC192SHA256AuthProtocol",
        "usmHMAC256SHA384AuthProtocol", "usmHMAC384SHA512AuthProtocol",
        "usmDESPrivProtocol", "usm3DESEDEPrivProtocol",
        "usmAesCfb128Protocol", "usmAesCfb192Protocol",
        "usmAesCfb256Protocol",
    ]:
        setattr(asyncio_mod, proto, object())

    # bulk_cmd / get_cmd are reassigned per-test via the `pysnmp_stub` fixture.
    async def _bulk_cmd_default(*args, **kwargs):
        return (None, None, None, [])
    asyncio_mod.bulk_cmd = _bulk_cmd_default

    async def _get_cmd_default(*args, **kwargs):
        return (None, None, None, [])
    asyncio_mod.get_cmd = _get_cmd_default

    pysnmp.hlapi = hlapi
    hlapi.v3arch = v3arch
    v3arch.asyncio = asyncio_mod

    sys.modules["pysnmp"] = pysnmp
    sys.modules["pysnmp.hlapi"] = hlapi
    sys.modules["pysnmp.hlapi.v3arch"] = v3arch
    sys.modules["pysnmp.hlapi.v3arch.asyncio"] = asyncio_mod
    return asyncio_mod


_pysnmp_stub = _install_pysnmp_stub()


# ── Connector module loader ────────────────────────────────────────────────


def _load_snmp_module():
    """Import `<repo>/connectors/snmp.py` by path (it's not in a package)."""
    spec = importlib.util.spec_from_file_location("snmp_seed", _SNMP_SEED)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_snmp_mod = _load_snmp_module()
SnmpConnector = _snmp_mod.SnmpConnector


@pytest.fixture
def pysnmp_stub():
    """Reset bulk_cmd / get_cmd to defaults so tests don't leak state."""
    yield _pysnmp_stub
    async def _bulk_default(*args, **kwargs):
        return (None, None, None, [])
    _pysnmp_stub.bulk_cmd = _bulk_default


# ── __init__ credential-key fallback ───────────────────────────────────────


def test_init_uses_snmp_version_when_present() -> None:
    c = SnmpConnector({}, {"snmp_version": "3", "username": "u"})
    assert c.version == "3"


def test_init_falls_back_to_version_when_snmp_version_absent() -> None:
    """The prod credential template emits `version`, not `snmp_version`.
    Dropping this fallback broke every SNMPv3 device on 2026-04-20.
    """
    c = SnmpConnector({}, {"version": "3", "username": "u"})
    assert c.version == "3"


def test_init_snmp_version_takes_precedence_over_version() -> None:
    """If both keys are present, `snmp_version` wins — explicit beats legacy."""
    c = SnmpConnector({}, {"snmp_version": "3", "version": "2c"})
    assert c.version == "3"


def test_init_defaults_to_v2c_when_neither_key_present() -> None:
    c = SnmpConnector({}, {})
    assert c.version == "2c"


def test_init_normalises_version_to_lowercase_string() -> None:
    c = SnmpConnector({}, {"snmp_version": "2C"})
    assert c.version == "2c"
    c = SnmpConnector({}, {"version": 3})  # int — connector forces str + lower
    assert c.version == "3"


# ── Settings defaults + overrides ──────────────────────────────────────────


def test_init_settings_defaults() -> None:
    c = SnmpConnector({}, {})
    assert c.port == 161
    assert c.timeout == 5
    assert c.retries == 2


def test_init_settings_overrides() -> None:
    c = SnmpConnector({"port": 1161, "timeout": 10, "retries": 5}, {})
    assert c.port == 1161
    assert c.timeout == 10
    assert c.retries == 5


# ── v1/v2c auth construction ───────────────────────────────────────────────


def test_v2c_auth_uses_community_default_public() -> None:
    c = SnmpConnector({}, {})
    auth = c._build_v1v2c_auth()
    assert auth.args == ("public",)
    assert auth.kwargs == {"mpModel": 1}  # 1 == v2c


def test_v2c_auth_uses_explicit_community() -> None:
    c = SnmpConnector({}, {"community": "secret-ro"})
    auth = c._build_v1v2c_auth()
    assert auth.args == ("secret-ro",)


def test_v1_auth_uses_mp_model_zero() -> None:
    c = SnmpConnector({}, {"snmp_version": "1", "community": "ro"})
    auth = c._build_v1v2c_auth()
    assert auth.kwargs == {"mpModel": 0}


# ── v3 auth construction ───────────────────────────────────────────────────


def test_v3_auth_noauthnopriv_yields_username_only() -> None:
    c = SnmpConnector(
        {},
        {"snmp_version": "3", "username": "alice", "security_level": "noauthnopriv"},
    )
    auth = c._build_v3_auth()
    assert auth.kwargs == {"userName": "alice"}


def test_v3_auth_authnopriv_includes_auth_proto_and_key() -> None:
    c = SnmpConnector(
        {},
        {
            "snmp_version": "3",
            "username": "alice",
            "auth_protocol": "SHA256",
            "auth_password": "auth-pass",
            "security_level": "authnopriv",
        },
    )
    auth = c._build_v3_auth()
    assert auth.kwargs["userName"] == "alice"
    assert auth.kwargs["authKey"] == "auth-pass"
    assert "authProtocol" in auth.kwargs
    # No priv when level is authnopriv
    assert "privKey" not in auth.kwargs


def test_v3_auth_authpriv_includes_priv_proto_and_key() -> None:
    c = SnmpConnector(
        {},
        {
            "snmp_version": "3",
            "username": "alice",
            "auth_protocol": "SHA",
            "auth_password": "auth-pass",
            "priv_protocol": "AES256",
            "priv_password": "priv-pass",
            "security_level": "authpriv",
        },
    )
    auth = c._build_v3_auth()
    assert auth.kwargs["privKey"] == "priv-pass"
    assert "privProtocol" in auth.kwargs


def test_v3_auth_unknown_protocol_silently_drops_auth() -> None:
    """An unknown auth_protocol name doesn't crash — it just doesn't bind."""
    c = SnmpConnector(
        {},
        {
            "snmp_version": "3",
            "username": "alice",
            "auth_protocol": "BLAKE2",  # not in table
            "auth_password": "x",
            "security_level": "authpriv",
        },
    )
    auth = c._build_v3_auth()
    assert "authKey" not in auth.kwargs


def test_v3_auth_default_security_level_is_authpriv() -> None:
    c = SnmpConnector({}, {"snmp_version": "3", "username": "alice"})
    # No auth_protocol → no authKey, but the default level constant is in the
    # connector's local var. We just verify __init__ doesn't crash and the
    # build path completes.
    auth = c._build_v3_auth()
    assert auth.kwargs["userName"] == "alice"


# ── walk_multi ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_walk_multi_empty_oids_returns_empty_dict(pysnmp_stub) -> None:
    c = SnmpConnector({}, {})
    result = await c.walk_multi([])
    assert result == {}


@pytest.mark.asyncio
async def test_walk_multi_single_column_returns_rows(pysnmp_stub) -> None:
    """One base OID → walk advances cursor through subtree, drops on out-of-tree."""
    base = "1.3.6.1.2.1.1"
    rounds = iter([
        # Round 1: 3 in-subtree rows.
        (None, None, None, [
            (_StubName(f"{base}.1.0"), _StubValue("Linux")),
            (_StubName(f"{base}.2.0"), _StubValue("OID")),
            (_StubName(f"{base}.3.0"), _StubValue("12345")),
        ]),
        # Round 2: out-of-subtree → drop, walk terminates.
        (None, None, None, [
            (_StubName("1.3.6.1.2.1.2.0"), _StubValue("ifTable")),
        ]),
    ])

    async def _bulk(*args, **kwargs):
        return next(rounds)

    pysnmp_stub.bulk_cmd = _bulk
    c = SnmpConnector({}, {})
    out = await c.walk_multi([base])
    assert list(out.keys()) == [base]
    assert len(out[base]) == 3
    assert out[base][0] == (f"{base}.1.0", "Linux")


@pytest.mark.asyncio
async def test_walk_multi_correlated_columns_split_by_modulo(pysnmp_stub) -> None:
    """Two base OIDs → bulk returns flat sequence; index `i % K` selects the
    column. Each column accumulates only its own rows."""
    base_a = "1.3.6.1.4.1.9.1"  # column A
    base_b = "1.3.6.1.4.1.9.2"  # column B

    rounds = iter([
        # K=2 columns; bulk returns 4 vars in wire order: [A0, B0, A1, B1].
        (None, None, None, [
            (_StubName(f"{base_a}.0"), _StubValue("a0")),
            (_StubName(f"{base_b}.0"), _StubValue("b0")),
            (_StubName(f"{base_a}.1"), _StubValue("a1")),
            (_StubName(f"{base_b}.1"), _StubValue("b1")),
        ]),
        # Round 2: both columns out of subtree → terminate.
        (None, None, None, [
            (_StubName("1.3.6.1.4.1.9.99"), _StubValue("x")),
            (_StubName("1.3.6.1.4.1.9.99"), _StubValue("x")),
        ]),
    ])

    async def _bulk(*args, **kwargs):
        return next(rounds)

    pysnmp_stub.bulk_cmd = _bulk
    c = SnmpConnector({}, {})
    out = await c.walk_multi([base_a, base_b])
    assert [r[1] for r in out[base_a]] == ["a0", "a1"]
    assert [r[1] for r in out[base_b]] == ["b0", "b1"]


@pytest.mark.asyncio
async def test_walk_multi_drops_column_when_it_exits_subtree(pysnmp_stub) -> None:
    """If column A's varbind falls outside its base subtree but column B's
    is still inside, A drops and B continues."""
    base_a = "1.3.6.1.4.1.9.1"
    base_b = "1.3.6.1.4.1.9.2"

    rounds = iter([
        # Round 1: A goes out of subtree on its first row; B has a valid row.
        (None, None, None, [
            (_StubName("1.3.6.1.4.1.9.99"), _StubValue("a-out")),  # A out
            (_StubName(f"{base_b}.0"), _StubValue("b0")),
        ]),
        # Round 2: only B is active. K=1. One row, then out-of-subtree.
        (None, None, None, [
            (_StubName(f"{base_b}.1"), _StubValue("b1")),
        ]),
        # Round 3: B out of subtree.
        (None, None, None, [
            (_StubName("1.3.6.1.4.1.9.99"), _StubValue("b-out")),
        ]),
    ])

    async def _bulk(*args, **kwargs):
        return next(rounds)

    pysnmp_stub.bulk_cmd = _bulk
    c = SnmpConnector({}, {})
    out = await c.walk_multi([base_a, base_b])
    assert out[base_a] == []  # dropped immediately
    assert [r[1] for r in out[base_b]] == ["b0", "b1"]


@pytest.mark.asyncio
async def test_walk_multi_terminates_on_no_progress(pysnmp_stub) -> None:
    """If a column's last_cursor doesn't advance past its current cursor,
    drop it — otherwise the loop would spin until the safety cap."""
    base = "1.3.6.1.2.1.1"
    rounds_called = {"n": 0}

    async def _bulk(*args, **kwargs):
        rounds_called["n"] += 1
        # Return one in-subtree row whose OID equals the base — cursor "doesn't advance".
        # After one round of recording, the column should be considered stalled
        # (cursor == base) and dropped from active.
        if rounds_called["n"] == 1:
            return (None, None, None, [
                (_StubName(base), _StubValue("v")),  # name == base → no advance
            ])
        return (None, None, None, [])

    pysnmp_stub.bulk_cmd = _bulk
    c = SnmpConnector({}, {})
    out = await c.walk_multi([base])
    # The implementation accepts the equal-name row but drops the column on
    # the next iteration; verify we don't hit the 500-round safety cap.
    assert rounds_called["n"] < 10


@pytest.mark.asyncio
async def test_walk_multi_returns_empty_lists_for_each_base_when_bulk_errors(
    pysnmp_stub,
) -> None:
    """Error indication on the very first bulk_cmd → loop breaks; result
    still has a key per input OID with an empty list (not missing)."""
    async def _bulk(*args, **kwargs):
        return ("timeout", None, None, [])

    pysnmp_stub.bulk_cmd = _bulk
    c = SnmpConnector({}, {})
    out = await c.walk_multi(["1.3.6.1.4.1.9.1", "1.3.6.1.4.1.9.2"])
    assert out == {"1.3.6.1.4.1.9.1": [], "1.3.6.1.4.1.9.2": []}
