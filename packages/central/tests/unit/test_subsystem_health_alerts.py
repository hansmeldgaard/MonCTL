"""Tests for the platform-self alerting helper (O-X-001).

Closes the operability.md HIGH that observed `_evaluate_system_health`
fired alert_log rows for threshold breaches but never for subsystem
status changes — so a critical Patroni / Redis sentinel / ClickHouse
keeper status produced no alert, no email, and no automation hook.

Two layers tested:
  * `_shape_subsystem_check` — pure status-to-check-row mapping
  * `_subsystem_health_checks` — gathers every `_check_*` and returns
    the shaped list, swallowing per-subsystem exceptions so one bad
    check doesn't blank the whole batch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from monctl_central.scheduler.tasks import (
    _shape_subsystem_check,
    _subsystem_health_checks,
)


# ── _shape_subsystem_check ─────────────────────────────────────────────────


def test_shape_returns_none_for_unknown_status() -> None:
    assert _shape_subsystem_check("postgresql", {"status": "unknown"}) is None


def test_shape_returns_none_for_non_dict_result() -> None:
    """gather may surface exceptions; the helper has to skip those rather
    than synthesising a phantom check row."""
    assert _shape_subsystem_check("postgresql", Exception("boom")) is None
    assert _shape_subsystem_check("postgresql", "garbage") is None


def test_shape_critical_status_emits_breached_critical_row() -> None:
    out = _shape_subsystem_check(
        "patroni", {"status": "critical", "reason": "no primary"}
    )
    assert out is not None
    assert out["breached"] is True
    assert out["severity"] == "critical"
    assert out["entity_key"] == "subsystem|patroni"
    assert out["name"] == "Subsystem health: patroni"
    assert "no primary" in out["message"]
    assert out["current_value"] == 1.0


def test_shape_degraded_status_uses_warning_severity() -> None:
    out = _shape_subsystem_check("redis", {"status": "degraded"})
    assert out is not None
    assert out["severity"] == "warning"
    assert out["breached"] is True


def test_shape_healthy_status_emits_clear_signal() -> None:
    """Healthy → breached=False so the Redis prev_state machine in the
    scheduler emits a clear when a previously firing subsystem
    recovers."""
    out = _shape_subsystem_check("postgresql", {"status": "healthy"})
    assert out is not None
    assert out["breached"] is False
    assert out["current_value"] == 0.0
    assert "healthy" in out["message"]


def test_shape_uses_status_text_when_reason_missing() -> None:
    """If the subsystem doesn't supply a reason, the message still
    carries something operator-actionable (the status itself)."""
    out = _shape_subsystem_check("clickhouse", {"status": "critical"})
    assert out is not None
    assert "status=critical" in out["message"]


# ── _subsystem_health_checks ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gathers_every_subsystem_and_shapes_them() -> None:
    """The helper calls each `_check_*` and returns one row per non-unknown
    subsystem. Patch the imports inside the helper so no real DB / CH /
    Redis connection is opened."""
    statuses = {
        "central": "healthy",
        "postgresql": "healthy",
        "patroni": "critical",       # firing
        "etcd": "healthy",
        "clickhouse": "degraded",    # firing
        "redis": "healthy",
        "collectors": "healthy",
        "scheduler": "healthy",
        "alerts": "healthy",
        "audit": "healthy",
        "connectors": "unknown",     # skipped
    }

    def _mk(name: str):
        async def _stub() -> dict:
            return {"status": statuses[name]}
        return _stub

    with patch.multiple(
        "monctl_central.system.router",
        _check_central=_mk("central"),
        _check_postgresql_standalone=_mk("postgresql"),
        _check_patroni=_mk("patroni"),
        _check_etcd=_mk("etcd"),
        _check_clickhouse=_mk("clickhouse"),
        _check_redis=_mk("redis"),
        _check_collectors_standalone=_mk("collectors"),
        _check_scheduler=_mk("scheduler"),
        _check_alerts_standalone=_mk("alerts"),
        _check_audit=_mk("audit"),
        _check_connectors_drift=_mk("connectors"),
    ):
        rows = await _subsystem_health_checks()

    # connectors → unknown → skipped; everyone else gets a row.
    names = sorted(r["entity_key"] for r in rows)
    assert "subsystem|connectors" not in names
    assert "subsystem|patroni" in names
    assert "subsystem|clickhouse" in names
    assert len([r for r in rows if r["breached"]]) == 2
    # Healthy subsystems still emit rows so the prev_state machine
    # can clear stale firing entries.
    assert len([r for r in rows if not r["breached"]]) == 8


@pytest.mark.asyncio
async def test_one_subsystem_raising_doesnt_blank_the_batch() -> None:
    """If a single `_check_*` blows up, gather surfaces the exception —
    the helper must skip just that one and keep the rest intact, not
    throw away the whole batch."""
    async def _ok() -> dict:
        return {"status": "healthy"}

    async def _boom() -> dict:
        raise RuntimeError("CH unreachable")

    with patch.multiple(
        "monctl_central.system.router",
        _check_central=_ok,
        _check_postgresql_standalone=_ok,
        _check_patroni=_ok,
        _check_etcd=_ok,
        _check_clickhouse=_boom,  # exception — skipped
        _check_redis=_ok,
        _check_collectors_standalone=_ok,
        _check_scheduler=_ok,
        _check_alerts_standalone=_ok,
        _check_audit=_ok,
        _check_connectors_drift=_ok,
    ):
        rows = await _subsystem_health_checks()

    names = {r["entity_key"] for r in rows}
    assert "subsystem|clickhouse" not in names  # skipped due to exception
    assert "subsystem|patroni" in names
    assert "subsystem|central" in names
    # 11 subsystems - 1 skipped = 10 rows
    assert len(rows) == 10
