"""Tests for monctl_central.alerting.engine.AlertEngine.

Closes T-CEN-001 from review #2: 814-line engine implementing PR #38's
tiered-severity model had zero tests. The engine is critical-path code
that runs every 30 s and writes to ``alert_log`` ClickHouse — every
regression here ships first to customers.

This test file mocks the two CH-touching methods (`_execute_compiled_query`
and `_fresh_assignments`) plus the notifier, then exercises real DB
state transitions on the SQLite in-memory session. State assertions on
``AlertEntity`` rows + structural assertions on returned ``alert_log``
records cover the behaviour CLAUDE.md and the review documented:

  * fire → escalate → downgrade → clear with explicit healthy tier
  * blank-healthy auto-clear (legacy path)
  * healthy tier defined + non-matching = ambiguous middle (no state
    change, no log)
  * healthy-tier evaluation that raises is caught — eval cycle proceeds
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from monctl_central.alerting.engine import AlertEngine
from monctl_central.storage.models import (
    AlertDefinition,
    AlertEntity,
    App,
    AppAssignment,
    AppVersion,
    Device,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory(sqlite_engine):
    """Return a callable that yields a fresh AsyncSession.

    Mirrors the production session-factory shape AlertEngine consumes
    (`async with self._session_factory() as session: ...`).
    """
    return async_sessionmaker(
        sqlite_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
async def alert_setup(db_session: AsyncSession):
    """Seed an App + AlertDefinition + Device + AppAssignment + AlertEntity.

    The definition has THREE non-healthy tiers (warning / critical /
    emergency) plus an explicit healthy tier expression. Tests build on
    this baseline: each test starts with the entity in `state='ok'`,
    `severity=None` and drives state transitions by patching the
    per-tier mock returns.
    """
    app = App(
        id=uuid.uuid4(),
        name="ping_check",
        app_type="availability",
        target_table="availability_latency",
        config_schema={},
    )
    db_session.add(app)
    await db_session.flush()

    app_ver = AppVersion(
        id=uuid.uuid4(),
        app_id=app.id,
        version="1.0.0",
        checksum_sha256="x" * 64,
        is_latest=True,
    )
    db_session.add(app_ver)
    await db_session.flush()

    defn = AlertDefinition(
        id=uuid.uuid4(),
        app_id=app.id,
        name="Latency tiered",
        severity_tiers=[
            {"severity": "warning", "expression": "rtt_ms > 50",
             "message_template": "warn"},
            {"severity": "critical", "expression": "rtt_ms > 200",
             "message_template": "crit"},
            {"severity": "emergency", "expression": "rtt_ms > 1000",
             "message_template": "emerg"},
            {"severity": "healthy", "expression": "rtt_ms < 50",
             "message_template": "recovered"},
        ],
        window="5m",
        enabled=True,
    )
    db_session.add(defn)

    device = Device(
        id=uuid.uuid4(),
        name="dev1",
        address="10.0.0.1",
    )
    db_session.add(device)

    asg = AppAssignment(
        id=uuid.uuid4(),
        app_id=app.id,
        app_version_id=app_ver.id,
        device_id=device.id,
        schedule_type="interval",
        schedule_value=60,
        enabled=True,
    )
    db_session.add(asg)

    entity = AlertEntity(
        id=uuid.uuid4(),
        definition_id=defn.id,
        assignment_id=asg.id,
        device_id=device.id,
        enabled=True,
        state="ok",
        severity=None,
        fire_count=0,
        fire_history=[],
        entity_key="",
        entity_labels={},
        metric_values={},
        threshold_values={},
    )
    db_session.add(entity)
    await db_session.commit()
    return {
        "app": app,
        "defn": defn,
        "device": device,
        "assignment": asg,
        "entity": entity,
    }


@pytest.fixture
def patch_dsl_compile():
    """Skip the real DSL compiler — return a stub object per tier.

    The engine only inspects ``compiled.is_config_changed`` /
    ``config_changed_key`` on the result, so a no-op object suffices.
    The return value is keyed back to the tier severity via the closure
    in ``patch_engine`` so the firing-keys mock can pick up the right
    tier.
    """
    class _StubCompiled:
        is_config_changed = False
        config_changed_key = ""

    with patch("monctl_central.alerting.engine.parse_expression", lambda expr: expr):
        with patch(
            "monctl_central.alerting.engine.compile_to_sql",
            lambda ast, target_table, window: _StubCompiled(),
        ):
            yield


@pytest.fixture
def silenced_notifier():
    """No-op the notifier — production hits structlog + Redis."""
    with patch(
        "monctl_central.alerting.engine.send_notifications",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.fixture
async def engine(session_factory, mock_clickhouse, alert_setup):
    """Construct an AlertEngine wired to the SQLite session factory."""
    return AlertEngine(session_factory, mock_clickhouse)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _firing_keys(*entities, value: float = 100.0) -> dict:
    """Return a `_execute_compiled_query`-shaped dict for the given entities."""
    return {
        (str(e.assignment_id), e.entity_key): {
            "value": value,
            "labels": {},
            "metric_values": {"rtt_ms": value},
            "threshold_values": {"rtt_ms_warn": 50},
        }
        for e in entities
    }


async def _reload_state(db_session: AsyncSession, entity_id: uuid.UUID) -> dict:
    """Re-fetch the entity's mutable state fields as a plain dict.

    The engine's per-definition isolated sessions commit independently;
    the outer test ``db_session`` has identity-mapped Python objects
    that won't see those commits without an explicit reload. Returning
    a plain dict (not the ORM row) sidesteps lazy-load greenlet issues
    after a rollback round-trip.
    """
    await db_session.commit()
    db_session.expire_all()
    from sqlalchemy import select
    row = (
        await db_session.execute(
            select(
                AlertEntity.state,
                AlertEntity.severity,
                AlertEntity.fire_count,
                AlertEntity.fire_history,
                AlertEntity.current_value,
                AlertEntity.last_triggered_at,
                AlertEntity.last_cleared_at,
            ).where(AlertEntity.id == entity_id)
        )
    ).one()
    return {
        "state": row.state,
        "severity": row.severity,
        "fire_count": row.fire_count,
        "fire_history": row.fire_history,
        "current_value": row.current_value,
        "last_triggered_at": row.last_triggered_at,
        "last_cleared_at": row.last_cleared_at,
    }


async def _reload(db_session: AsyncSession, entity_id: uuid.UUID):
    """Backward-compat wrapper returning a SimpleNamespace of state fields."""
    from types import SimpleNamespace
    return SimpleNamespace(**await _reload_state(db_session, entity_id))


# ---------------------------------------------------------------------------
# Tier-evaluation transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_from_ok_at_warning_tier(
    db_session, engine, alert_setup, patch_dsl_compile, silenced_notifier
):
    """ok → warning: state=firing, severity=warning, action=fire in log."""
    entity = alert_setup["entity"]

    # Mock per-tier matches: only the warning tier matches.
    async def _exec_q(compiled, instances, *_, **__):
        if compiled.__class__.__name__ != "_StubCompiled":
            return {}
        # Use the call-order trick: warning is first, others empty.
        # Re-use the _firing_keys helper.
        return _firing_keys(*instances)
    # First invocation = warning, second = critical, third = emergency,
    # fourth = healthy. Sequence is deterministic per the engine's loop.
    call_order: list[dict] = [
        _firing_keys(entity),
        {},  # critical
        {},  # emergency
        {},  # healthy — empty so no positive clear path
    ]
    iter_calls = iter(call_order)
    engine._execute_compiled_query = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda *a, **k: next(iter_calls)
    )
    engine._fresh_assignments = AsyncMock(  # type: ignore[method-assign]
        return_value={str(entity.assignment_id)}
    )

    await engine.evaluate_all()

    refreshed = await _reload(db_session, entity.id)
    assert refreshed.state == "firing"
    assert refreshed.severity == "warning"
    assert refreshed.fire_count == 1
    assert refreshed.fire_history == [True]
    assert refreshed.last_triggered_at is not None
    assert refreshed.current_value == 100.0


@pytest.mark.asyncio
async def test_escalate_warning_to_critical(
    db_session, engine, alert_setup, patch_dsl_compile, silenced_notifier
):
    """warning → critical: action=escalate, fire_count resets to 1."""
    entity = alert_setup["entity"]
    # Pre-seed entity as already firing at warning.
    entity.state = "firing"
    entity.severity = "warning"
    entity.fire_count = 5
    entity.fire_history = [True, True, True, True, True]
    entity.started_firing_at = datetime.now(timezone.utc)
    await db_session.commit()

    # warning + critical match (critical wins as higher severity).
    call_order = [
        _firing_keys(entity),  # warning
        _firing_keys(entity, value=300.0),  # critical
        {},
        {},
    ]
    iter_calls = iter(call_order)
    engine._execute_compiled_query = AsyncMock(side_effect=lambda *a, **k: next(iter_calls))
    engine._fresh_assignments = AsyncMock(return_value={str(entity.assignment_id)})

    await engine.evaluate_all()

    refreshed = await _reload(db_session, entity.id)
    assert refreshed.state == "firing"
    assert refreshed.severity == "critical"
    # fire_count resets on tier change (CLAUDE.md / engine.py:421)
    assert refreshed.fire_count == 1
    assert refreshed.fire_history[-1] is True


@pytest.mark.asyncio
async def test_downgrade_critical_to_warning(
    db_session, engine, alert_setup, patch_dsl_compile, silenced_notifier
):
    """critical → warning: action=downgrade."""
    entity = alert_setup["entity"]
    entity.state = "firing"
    entity.severity = "critical"
    entity.fire_count = 3
    await db_session.commit()

    call_order = [
        _firing_keys(entity),  # warning matches
        {},                    # critical no longer matches
        {},                    # emergency
        {},                    # healthy
    ]
    iter_calls = iter(call_order)
    engine._execute_compiled_query = AsyncMock(side_effect=lambda *a, **k: next(iter_calls))
    engine._fresh_assignments = AsyncMock(return_value={str(entity.assignment_id)})

    await engine.evaluate_all()

    refreshed = await _reload(db_session, entity.id)
    assert refreshed.state == "firing"
    assert refreshed.severity == "warning"
    # fire_count resets on tier change downward too
    assert refreshed.fire_count == 1


@pytest.mark.asyncio
async def test_same_severity_increments_fire_count(
    db_session, engine, alert_setup, patch_dsl_compile, silenced_notifier
):
    """Same severity across cycles: fire_count keeps counting."""
    entity = alert_setup["entity"]
    entity.state = "firing"
    entity.severity = "warning"
    entity.fire_count = 4
    await db_session.commit()

    call_order = [
        _firing_keys(entity),  # warning
        {},                    # critical
        {},                    # emergency
        {},                    # healthy
    ]
    iter_calls = iter(call_order)
    engine._execute_compiled_query = AsyncMock(side_effect=lambda *a, **k: next(iter_calls))
    engine._fresh_assignments = AsyncMock(return_value={str(entity.assignment_id)})

    await engine.evaluate_all()

    refreshed = await _reload(db_session, entity.id)
    assert refreshed.severity == "warning"
    assert refreshed.fire_count == 5


# ---------------------------------------------------------------------------
# Clear semantics — healthy tier present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_positive_clear_via_healthy_tier(
    db_session, engine, alert_setup, patch_dsl_compile, silenced_notifier
):
    """Healthy expression matches → action=clear, state=resolved.

    Distinguishes the healthy-tier-defined path from the legacy auto-clear:
    only an explicit healthy-tier match drives a clear. CLAUDE.md
    "Alerting & Thresholds" → "Positive-clear via healthy tier".
    """
    entity = alert_setup["entity"]
    entity.state = "firing"
    entity.severity = "critical"
    entity.fire_count = 8
    await db_session.commit()

    call_order = [
        {},                    # warning no match
        {},                    # critical no match
        {},                    # emergency no match
        _firing_keys(entity, value=20.0),  # healthy matches
    ]
    iter_calls = iter(call_order)
    engine._execute_compiled_query = AsyncMock(side_effect=lambda *a, **k: next(iter_calls))
    engine._fresh_assignments = AsyncMock(return_value={str(entity.assignment_id)})

    await engine.evaluate_all()

    refreshed = await _reload(db_session, entity.id)
    assert refreshed.state == "resolved"
    assert refreshed.severity is None
    assert refreshed.fire_count == 0
    assert refreshed.last_cleared_at is not None
    # Positive clear refreshes the snapshot from the healthy-tier value.
    assert refreshed.current_value == 20.0


@pytest.mark.asyncio
async def test_ambiguous_middle_no_state_change(
    db_session, engine, alert_setup, patch_dsl_compile, silenced_notifier
):
    """Healthy defined but doesn't match: stay firing, no clear, no log.

    `engine.py:373` — "ambiguous middle — skip entirely (no history append)".
    Prevents flapping when a metric briefly slips below the fire threshold
    but hasn't yet crossed the recovery threshold.
    """
    entity = alert_setup["entity"]
    entity.state = "firing"
    entity.severity = "critical"
    entity.fire_count = 5
    entity.fire_history = [True, True, True, True, True]
    await db_session.commit()

    # No tier matches at all.
    call_order = [{}, {}, {}, {}]
    iter_calls = iter(call_order)
    engine._execute_compiled_query = AsyncMock(side_effect=lambda *a, **k: next(iter_calls))
    engine._fresh_assignments = AsyncMock(return_value={str(entity.assignment_id)})

    await engine.evaluate_all()

    refreshed = await _reload(db_session, entity.id)
    # No transition: still firing at critical.
    assert refreshed.state == "firing"
    assert refreshed.severity == "critical"
    # fire_count untouched, fire_history NOT extended (engine.py:373).
    assert refreshed.fire_count == 5
    assert refreshed.fire_history == [True, True, True, True, True]


# ---------------------------------------------------------------------------
# Clear semantics — legacy (no healthy tier expression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_clear_when_no_healthy_expression(
    db_session, engine, alert_setup, patch_dsl_compile, silenced_notifier
):
    """No healthy tier defined → ANY non-matching cycle clears the firing entity.

    Back-compat path for definitions that haven't adopted the
    positive-clear pattern. engine.py:375-389.
    """
    entity = alert_setup["entity"]
    defn = alert_setup["defn"]
    # Drop the healthy tier so the engine takes the legacy path.
    defn.severity_tiers = [
        t for t in defn.severity_tiers if t["severity"] != "healthy"
    ]
    entity.state = "firing"
    entity.severity = "warning"
    entity.fire_count = 3
    await db_session.commit()

    # No tier matches.
    call_order = [{}, {}, {}]
    iter_calls = iter(call_order)
    engine._execute_compiled_query = AsyncMock(side_effect=lambda *a, **k: next(iter_calls))
    engine._fresh_assignments = AsyncMock(return_value={str(entity.assignment_id)})

    await engine.evaluate_all()

    refreshed = await _reload(db_session, entity.id)
    assert refreshed.state == "resolved"
    assert refreshed.severity is None
    assert refreshed.fire_count == 0
    # fire_history extended with False (legacy behaviour).
    assert refreshed.fire_history[-1] is False


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthy_tier_eval_error_does_not_block_cycle(
    db_session, engine, alert_setup, patch_dsl_compile, silenced_notifier
):
    """A raise inside healthy-tier eval is caught; entity stays firing.

    Engine catches and falls back to ``healthy_fk = {}``. The entity then
    hits the ambiguous-middle branch (healthy defined + no match) and
    skips the cycle without state change. Confirms fail-closed semantics
    documented in `project_alerting_semantics`.
    """
    entity = alert_setup["entity"]
    entity.state = "firing"
    entity.severity = "warning"
    entity.fire_count = 2
    await db_session.commit()

    # warning/critical/emergency = no match; healthy raises.
    async def _maybe_raise(compiled, instances, *_, **__):
        # Use a counter to know which call this is (4 tiers in order).
        _maybe_raise.calls += 1  # type: ignore[attr-defined]
        if _maybe_raise.calls == 4:  # type: ignore[attr-defined]
            raise RuntimeError("clickhouse went away")
        return {}
    _maybe_raise.calls = 0  # type: ignore[attr-defined]
    engine._execute_compiled_query = AsyncMock(side_effect=_maybe_raise)
    engine._fresh_assignments = AsyncMock(return_value={str(entity.assignment_id)})

    # Should not raise — the engine catches the healthy-tier error.
    await engine.evaluate_all()

    refreshed = await _reload(db_session, entity.id)
    # No state change: ambiguous-middle path (healthy defined + no match
    # because healthy_fk fell back to {}).
    assert refreshed.state == "firing"
    assert refreshed.severity == "warning"
    assert refreshed.fire_count == 2  # untouched


@pytest.mark.asyncio
async def test_failing_definition_isolation_rolls_back_only_itself(
    db_session, engine, alert_setup, patch_dsl_compile, silenced_notifier,
):
    """P-CEN-001 — per-definition session isolation.

    With chunked ``asyncio.gather`` each evaluation owns its own session
    via ``_evaluate_definition_isolated``. A definition whose evaluation
    raises rolls back ONLY its own session; a sibling that succeeds
    commits independently.

    Tested serially against ``_evaluate_definition_isolated`` rather than
    via ``evaluate_all``'s gather: SQLite + StaticPool serialises
    concurrent writes, which doesn't reflect production Postgres
    behaviour and produces test flakes that aren't meaningful. The
    per-call isolation logic (commit on success, rollback on raise)
    is the actual contract worth pinning.
    """
    app = alert_setup["app"]
    asg = alert_setup["assignment"]
    device = alert_setup["device"]
    good_entity = alert_setup["entity"]
    good_defn = alert_setup["defn"]

    bad_defn = AlertDefinition(
        id=uuid.uuid4(),
        app_id=app.id,
        name="Latency-bad",
        severity_tiers=[
            {"severity": "critical", "expression": "rtt_ms > 200",
             "message_template": "x"},
        ],
        window="5m",
        enabled=True,
    )
    db_session.add(bad_defn)
    bad_entity = AlertEntity(
        id=uuid.uuid4(),
        definition_id=bad_defn.id,
        assignment_id=asg.id,
        device_id=device.id,
        enabled=True,
        state="ok",
        fire_count=0,
        fire_history=[],
        entity_key="",
        entity_labels={},
        metric_values={},
        threshold_values={},
    )
    db_session.add(bad_entity)
    await db_session.commit()

    # Capture IDs as plain UUIDs up front — the ORM objects can't survive
    # ``db_session.expire_all()`` round-trips inside ``_reload`` without
    # triggering greenlet errors (lazy-attribute reload requires an
    # awaited session, but we mid-test on a fresh greenlet).
    good_defn_id = good_defn.id
    good_entity_id = good_entity.id
    bad_defn_id = bad_defn.id
    bad_entity_id = bad_entity.id
    asg_id = asg.id

    # Bad-def call raises; good-def call returns warning-firing on first
    # call (warning tier), empty on subsequent tiers.
    per_def_calls: dict[uuid.UUID, int] = {}

    async def _per_def_query(compiled, instances, *_, **__):
        if not instances:
            return {}
        def_id = instances[0].definition_id
        if def_id == bad_defn_id:
            raise RuntimeError("ch outage on bad def")
        per_def_calls[def_id] = per_def_calls.get(def_id, 0) + 1
        if per_def_calls[def_id] == 1:
            return _firing_keys(*instances)
        return {}

    engine._execute_compiled_query = AsyncMock(side_effect=_per_def_query)
    engine._fresh_assignments = AsyncMock(return_value={str(asg_id)})

    # Bad def: must raise, leaving its entity untouched.
    with pytest.raises(RuntimeError, match="ch outage"):
        await engine._evaluate_definition_isolated(bad_defn_id)
    refreshed_bad = await _reload(db_session, bad_entity_id)
    assert refreshed_bad.state == "ok"
    assert refreshed_bad.severity is None

    # Good def: must succeed, persisting state change.
    records = await engine._evaluate_definition_isolated(good_defn_id)
    assert records, "expected at least one alert_log record from good def"
    refreshed_good = await _reload(db_session, good_entity_id)
    assert refreshed_good.state == "firing"
    assert refreshed_good.severity == "warning"
