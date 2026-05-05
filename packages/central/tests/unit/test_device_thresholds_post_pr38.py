"""Regression: GET /v1/devices/{id}/thresholds must walk severity_tiers.

PR #38 replaced ``AlertDefinition.expression`` with ``severity_tiers``
(JSONB list of ``{severity, expression, message_template}``).
``get_device_thresholds`` and three sibling sites still referenced
``d.expression`` after that rework — every call returned HTTP 500 the
moment the per-variable loop was non-empty. The frontend rendered the
500 as the same "no thresholds" empty state as a legitimately empty
response, so the bug stayed invisible until PR #138 (2026-04-22).

This test is the failing-on-old-code regression: it builds a definition
with ``severity_tiers`` referencing a named threshold variable and
calls the endpoint. Before the fix the endpoint hit
``AttributeError: 'AlertDefinition' object has no attribute 'expression'``
and returned 500. After the fix it returns 200 with the variable
listed under ``used_by_definitions``.

See also docs/review/2026-04-30/testing.md (T-X-006) and the
"empty UI state may be a 500" pitfall in CLAUDE.md.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import (
    AlertDefinition,
    App,
    AppAssignment,
    AppVersion,
    Device,
    ThresholdVariable,
)


@pytest.fixture
async def thresholds_seed(seeded_session: AsyncSession) -> dict:
    app = App(
        id=uuid.uuid4(),
        name="port_check_test",
        app_type="availability",
        target_table="availability_latency",
        config_schema={},
    )
    seeded_session.add(app)
    await seeded_session.flush()

    app_ver = AppVersion(
        id=uuid.uuid4(),
        app_id=app.id,
        version="1.0.0",
        checksum_sha256="x" * 64,
        is_latest=True,
    )
    seeded_session.add(app_ver)
    await seeded_session.flush()

    var = ThresholdVariable(
        id=uuid.uuid4(),
        app_id=app.id,
        name="rtt_ms_warn",
        display_name="Slow connect threshold",
        default_value=200.0,
        unit="ms",
    )
    seeded_session.add(var)

    # Tier expressions reference the threshold variable by name. The
    # fixed `get_device_thresholds` builds `used_by_definitions` by
    # walking each tier's `expression` string for `op<var.name>` matches.
    defn = AlertDefinition(
        id=uuid.uuid4(),
        app_id=app.id,
        name="Port - Slow Connect",
        severity_tiers=[
            {
                "severity": "warning",
                "expression": "rtt_ms > rtt_ms_warn",
                "message_template": "slow",
            },
            {
                "severity": "healthy",
                "expression": "rtt_ms <= rtt_ms_warn",
                "message_template": "ok",
            },
        ],
        window="5m",
        enabled=True,
    )
    seeded_session.add(defn)

    device = Device(
        id=uuid.uuid4(),
        name="port-check-device",
        address="10.99.0.1",
    )
    seeded_session.add(device)
    await seeded_session.flush()

    asg = AppAssignment(
        id=uuid.uuid4(),
        app_id=app.id,
        app_version_id=app_ver.id,
        device_id=device.id,
        schedule_type="interval",
        schedule_value="60",
        enabled=True,
    )
    seeded_session.add(asg)
    await seeded_session.commit()
    return {
        "app": app,
        "defn": defn,
        "device": device,
        "variable": var,
    }


class TestDeviceThresholdsAfterPr38:
    async def test_returns_variable_with_used_by_definition(
        self, auth_client: AsyncClient, thresholds_seed: dict,
    ) -> None:
        device_id = str(thresholds_seed["device"].id)
        resp = await auth_client.get(f"/v1/devices/{device_id}/thresholds")

        # Pre-fix: AttributeError on `d.expression` → 500.
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "success"
        rows = body["data"]
        assert len(rows) == 1, rows

        row = rows[0]
        assert row["name"] == "rtt_ms_warn"
        assert row["expression_default"] == 200.0
        assert row["effective_value"] == 200.0

        # The fixed code walks `severity_tiers[*].expression` for the
        # variable name. Pre-fix `d.expression` short-circuited and
        # `used_by_definitions` was always empty even when the response
        # didn't 500.
        used_by = row["used_by_definitions"]
        assert len(used_by) == 1
        assert used_by[0]["definition_name"] == "Port - Slow Connect"

    async def test_handles_definition_with_only_healthy_tier(
        self, auth_client: AsyncClient, thresholds_seed: dict, db_session: AsyncSession,
    ) -> None:
        """Definitions whose only tier is `healthy` (no fire tier) must
        still be walked — the pre-fix code AttributeError'd on the
        first definition regardless of tier shape."""
        from sqlalchemy import select

        defn = thresholds_seed["defn"]
        result = await db_session.execute(
            select(AlertDefinition).where(AlertDefinition.id == defn.id)
        )
        live = result.scalar_one()
        live.severity_tiers = [
            {
                "severity": "healthy",
                "expression": "rtt_ms <= rtt_ms_warn",
                "message_template": "ok",
            },
        ]
        await db_session.commit()

        device_id = str(thresholds_seed["device"].id)
        resp = await auth_client.get(f"/v1/devices/{device_id}/thresholds")
        assert resp.status_code == 200, resp.text
        rows = resp.json()["data"]
        assert len(rows) == 1
        # Healthy-only tier still references the variable, so used_by
        # picks it up.
        assert len(rows[0]["used_by_definitions"]) == 1
