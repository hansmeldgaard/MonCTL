"""Tests for the `connectors` system-health subsystem (O-CEN-008).

The startup `_check_connector_drift` path persists drifted connector
names to the Redis set ``monctl:connectors:drifted`` whenever the
installed `is_latest` source bytes don't match the seed. This test
file pins the read side: that
``system/router.py:_check_connectors_drift`` correctly summarises the
set as a health subsystem.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from monctl_central.system.router import _check_connectors_drift


class _StubRedis:
    def __init__(self, members):
        self._members = set(members)

    async def smembers(self, key):  # noqa: ARG002
        return set(self._members)


@pytest.mark.asyncio
async def test_check_returns_healthy_when_redis_unavailable(monkeypatch) -> None:
    """If `_redis is None` (cache layer not initialised), report healthy
    rather than treating the absence as a drift signal."""
    monkeypatch.setattr("monctl_central.cache._redis", None)
    result = await _check_connectors_drift()
    assert result["status"] == "healthy"
    assert result["details"] == {}


@pytest.mark.asyncio
async def test_check_returns_healthy_when_set_is_empty(monkeypatch) -> None:
    monkeypatch.setattr("monctl_central.cache._redis", _StubRedis([]))
    result = await _check_connectors_drift()
    assert result["status"] == "healthy"


@pytest.mark.asyncio
async def test_check_returns_degraded_with_sorted_names(monkeypatch) -> None:
    """A non-empty set turns the subsystem degraded; details surface
    the sorted name list + count so operators can see exactly which
    connectors are drifted."""
    monkeypatch.setattr(
        "monctl_central.cache._redis", _StubRedis(["ssh", "snmp", "winrm"])
    )
    result = await _check_connectors_drift()
    assert result["status"] == "degraded"
    assert result["details"]["drifted"] == ["snmp", "ssh", "winrm"]
    assert result["details"]["count"] == 3
    # `reason` is consumed by the system-health top-bar tooltip; pin it
    assert result["reason"] == "drifted=snmp,ssh,winrm"


@pytest.mark.asyncio
async def test_check_decodes_bytes_member_names(monkeypatch) -> None:
    """redis.asyncio returns bytes by default unless ``decode_responses=True``
    is set on the client. The check must decode either form without crashing."""
    monkeypatch.setattr(
        "monctl_central.cache._redis",
        _StubRedis([b"snmp", b"ssh"]),
    )
    result = await _check_connectors_drift()
    assert result["status"] == "degraded"
    assert result["details"]["drifted"] == ["snmp", "ssh"]


@pytest.mark.asyncio
async def test_check_swallows_redis_errors_as_healthy(monkeypatch) -> None:
    """Redis hiccup must not cascade into the health endpoint returning
    a degraded subsystem (would be a misleading false-positive)."""
    class _BoomRedis:
        async def smembers(self, key):  # noqa: ARG002
            raise ConnectionError("redis down")

    monkeypatch.setattr("monctl_central.cache._redis", _BoomRedis())
    result = await _check_connectors_drift()
    assert result["status"] == "healthy"
    assert result["details"] == {"redis_unavailable": True}
