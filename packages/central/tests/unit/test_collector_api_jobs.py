"""Tests for `GET /api/v1/jobs` — the delta-sync invariant.

The collector polls this endpoint once per minute with `?since=<last_seen>`
and only re-applies assignments whose `updated_at` is strictly greater than
the previous timestamp. CLAUDE.md "Collector delta-sync" calls out the
matching gotcha on the write side: any raw-SQL update to `app_assignments`
MUST `SET updated_at=now()` or collectors keep using the cached definition.

This file pins the read side: that the endpoint correctly excludes rows
older than `since`, and the surrounding auth / 4xx contract.

Auth: uses the shared-secret path (`MONCTL_COLLECTOR_API_KEY` env var)
because it doesn't trigger the `_require_active_collector` lookup that
the per-collector-key path does — keeps the tests focused on `since`
filtering instead of auth plumbing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from monctl_central.storage.models import (
    App,
    AppAssignment,
    AppVersion,
    Collector,
    CollectorGroup,
    Device,
)


_SHARED_SECRET = "test-collector-secret"


@pytest.fixture(autouse=True)
def _set_shared_secret(monkeypatch):
    """Activate the shared-secret auth path for every test in this module."""
    monkeypatch.setenv("MONCTL_COLLECTOR_API_KEY", _SHARED_SECRET)


def _bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {_SHARED_SECRET}"}


# ── Helpers ────────────────────────────────────────────────────────────


async def _seed_app_and_version(db: AsyncSession) -> tuple[App, AppVersion]:
    """Create a minimal App + AppVersion pair the assignment can FK to."""
    app = App(name=f"test-app-{uuid.uuid4().hex[:8]}", app_type="availability")
    db.add(app)
    await db.flush()
    version = AppVersion(
        app_id=app.id,
        version="1.0.0",
        checksum_sha256="0" * 64,
    )
    db.add(version)
    await db.flush()
    return app, version


async def _seed_assignment(
    db: AsyncSession,
    app: App,
    version: AppVersion,
    *,
    enabled: bool = True,
    device_id: uuid.UUID | None = None,
    collector_id: uuid.UUID | None = None,
    config: dict | None = None,
) -> AppAssignment:
    a = AppAssignment(
        app_id=app.id,
        app_version_id=version.id,
        device_id=device_id,
        collector_id=collector_id,
        config=config or {"host": "203.0.113.1"},
        schedule_type="interval",
        schedule_value="60",
        enabled=enabled,
    )
    db.add(a)
    await db.flush()
    return a


async def _force_updated_at(
    db: AsyncSession, assignment_id: uuid.UUID, when: datetime
) -> None:
    """Pin `updated_at` to a precise instant.

    SQLAlchemy's `onupdate` would otherwise rewrite the value to `now()` on
    flush, which makes `since=` filtering testing impossible.
    """
    await db.execute(
        update(AppAssignment)
        .where(AppAssignment.id == assignment_id)
        .values(updated_at=when)
    )
    await db.commit()


# ── Auth contract ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_auth_header_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/jobs")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_secret_returns_401(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer not-the-real-secret"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_since_returns_400(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/jobs",
        params={"since": "not-an-iso-timestamp"},
        headers=_bearer(),
    )
    assert resp.status_code == 400
    assert "since" in resp.json()["detail"].lower()


# ── Delta-sync (the documented invariant) ──────────────────────────────


@pytest.mark.asyncio
async def test_no_since_returns_all_enabled_assignments(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    app, version = await _seed_app_and_version(db_session)
    await _seed_assignment(db_session, app, version, config={"host": "10.0.0.1"})
    await _seed_assignment(db_session, app, version, config={"host": "10.0.0.2"})
    await db_session.commit()

    resp = await client.get("/api/v1/jobs", headers=_bearer())
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["jobs"]) == 2


@pytest.mark.asyncio
async def test_since_excludes_assignments_with_older_updated_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The core delta-sync invariant: `updated_at <= since` → not returned."""
    app, version = await _seed_app_and_version(db_session)
    a = await _seed_assignment(db_session, app, version)
    # Pin updated_at to an hour ago.
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    await _force_updated_at(db_session, a.id, one_hour_ago)

    # Poll with since=now → no rows.
    now_iso = datetime.now(timezone.utc).isoformat()
    resp = await client.get(
        "/api/v1/jobs", params={"since": now_iso}, headers=_bearer()
    )
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []


@pytest.mark.asyncio
async def test_since_includes_assignments_with_newer_updated_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    app, version = await _seed_app_and_version(db_session)
    a = await _seed_assignment(db_session, app, version)
    # Pin updated_at to "now" (just-edited).
    now = datetime.now(timezone.utc)
    await _force_updated_at(db_session, a.id, now)

    # Poll with since=an-hour-ago → row IS returned.
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    resp = await client.get(
        "/api/v1/jobs", params={"since": one_hour_ago}, headers=_bearer()
    )
    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) == 1


@pytest.mark.asyncio
async def test_since_boundary_strict_greater_than(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`since` is a strict `>` filter, not `>=`. An assignment whose
    `updated_at` exactly equals `since` should NOT be returned — otherwise
    the collector would re-apply the same definition every poll cycle."""
    app, version = await _seed_app_and_version(db_session)
    a = await _seed_assignment(db_session, app, version)
    pinned = datetime.now(timezone.utc) - timedelta(minutes=5)
    await _force_updated_at(db_session, a.id, pinned)

    # since == updated_at → strict-greater excludes it.
    resp = await client.get(
        "/api/v1/jobs", params={"since": pinned.isoformat()}, headers=_bearer()
    )
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []


# ── Enabled / device-enabled gates ─────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_assignment_excluded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    app, version = await _seed_app_and_version(db_session)
    await _seed_assignment(db_session, app, version, enabled=False)
    await db_session.commit()

    resp = await client.get("/api/v1/jobs", headers=_bearer())
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []


@pytest.mark.asyncio
async def test_disabled_device_excludes_assignment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Even if the assignment is enabled, an `is_enabled=False` device
    must be skipped — the collector should stop polling deactivated hosts."""
    app, version = await _seed_app_and_version(db_session)
    device = Device(
        name="disabled-host",
        address="203.0.113.99",
        is_enabled=False,
    )
    db_session.add(device)
    await db_session.flush()

    await _seed_assignment(db_session, app, version, device_id=device.id)
    await db_session.commit()

    resp = await client.get("/api/v1/jobs", headers=_bearer())
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []


@pytest.mark.asyncio
async def test_enabled_device_assignment_included(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Counterpart to `test_disabled_device_excludes`: ensure the gate
    is on `is_enabled=False` specifically, not on having a device at all."""
    app, version = await _seed_app_and_version(db_session)
    device = Device(name="active-host", address="203.0.113.50", is_enabled=True)
    db_session.add(device)
    await db_session.flush()

    await _seed_assignment(db_session, app, version, device_id=device.id)
    await db_session.commit()

    resp = await client.get("/api/v1/jobs", headers=_bearer())
    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) == 1


# ── Pinned vs group-level interplay ────────────────────────────────────


@pytest.mark.asyncio
async def test_pinned_assignment_returned_for_owning_collector(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Pinned assignments are always returned for the owning collector,
    bypassing partitioning. (`pinned_rows` are unconditionally combined
    with the unpinned-and-partitioned set in the response.)"""
    app, version = await _seed_app_and_version(db_session)
    coll = Collector(name="pinned-owner", hostname="worker-pinned", status="ACTIVE")
    db_session.add(coll)
    await db_session.flush()
    await _seed_assignment(
        db_session, app, version, collector_id=coll.id
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/jobs",
        params={"collector_id": str(coll.id)},
        headers=_bearer(),
    )
    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) == 1


@pytest.mark.asyncio
async def test_group_filter_excludes_other_groups_devices(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Unpinned assignments are partitioned by `Device.collector_group_id`.
    A collector in group A must not see assignments for devices in group B."""
    app, version = await _seed_app_and_version(db_session)

    group_a = CollectorGroup(name="group-a")
    group_b = CollectorGroup(name="group-b")
    db_session.add_all([group_a, group_b])
    await db_session.flush()

    # Caller is in group A.
    coll_a = Collector(
        name="collector-a", hostname="worker-a", status="ACTIVE", group_id=group_a.id,
    )
    db_session.add(coll_a)

    # Device pinned to group B → should not appear.
    dev_b = Device(
        name="dev-in-b",
        address="203.0.113.10",
        is_enabled=True,
        collector_group_id=group_b.id,
    )
    db_session.add(dev_b)
    await db_session.flush()

    await _seed_assignment(db_session, app, version, device_id=dev_b.id)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/jobs",
        params={"collector_id": str(coll_a.id)},
        headers=_bearer(),
    )
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []


@pytest.mark.asyncio
async def test_host_unbound_assignment_returned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An assignment with `device_id=NULL` (e.g. central self-checks) must
    be served — the `or_(device_id IS NULL, device.is_enabled=True)` predicate
    in the WHERE clause keeps these rows."""
    app, version = await _seed_app_and_version(db_session)
    await _seed_assignment(db_session, app, version, device_id=None)
    await db_session.commit()

    resp = await client.get("/api/v1/jobs", headers=_bearer())
    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) == 1
