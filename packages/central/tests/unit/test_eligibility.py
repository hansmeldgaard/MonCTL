"""Tests for /v1/apps/{id}/test-eligibility and /auto-assign-eligible endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import AppFactory


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _create_collector_group(session: AsyncSession) -> uuid.UUID:
    from monctl_central.storage.models import CollectorGroup

    grp = CollectorGroup(name=f"grp-{uuid.uuid4().hex[:8]}")
    session.add(grp)
    await session.flush()
    return grp.id


async def _create_device(
    session: AsyncSession,
    *,
    address: str,
    sys_object_id: str | None,
    collector_group_id: uuid.UUID,
    is_enabled: bool = True,
) -> uuid.UUID:
    from monctl_central.storage.models import Device

    device = Device(
        name=address,
        address=address,
        is_enabled=is_enabled,
        collector_group_id=collector_group_id,
        metadata_={"sys_object_id": sys_object_id} if sys_object_id else {},
    )
    session.add(device)
    await session.flush()
    return device.id


async def _create_app_with_version(
    session: AsyncSession,
    *,
    vendor_oid_prefix: str | None = None,
    eligibility_oids: list[dict] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an App + AppVersion (latest) with the given eligibility config."""
    import hashlib
    from monctl_central.storage.models import App, AppVersion

    app = App(
        name=f"app-{uuid.uuid4().hex[:8]}",
        app_type="script",
        target_table="availability_latency",
        vendor_oid_prefix=vendor_oid_prefix,
    )
    session.add(app)
    await session.flush()

    src = "class Poller: pass\n"
    version = AppVersion(
        app_id=app.id,
        version="1.0.0",
        source_code=src,
        checksum_sha256=hashlib.sha256(src.encode()).hexdigest(),
        entry_class="Poller",
        is_latest=True,
        eligibility_oids=eligibility_oids,
    )
    session.add(version)
    await session.flush()
    return app.id, version.id


# ── Instant mode ─────────────────────────────────────────────────────────────


class TestEligibilityInstant:
    async def test_vendor_match_returns_only_matching_devices(
        self,
        auth_client: AsyncClient,
        seeded_session: AsyncSession,
        mock_clickhouse: MagicMock,
    ):
        grp_id = await _create_collector_group(seeded_session)
        # Cisco device — matches prefix
        await _create_device(
            seeded_session,
            address="10.0.0.1",
            sys_object_id="1.3.6.1.4.1.9.1.2571",
            collector_group_id=grp_id,
        )
        # Juniper device — does not match
        await _create_device(
            seeded_session,
            address="10.0.0.2",
            sys_object_id="1.3.6.1.4.1.2636.1.1.1.2.143",
            collector_group_id=grp_id,
        )
        app_id, _ = await _create_app_with_version(
            seeded_session, vendor_oid_prefix="1.3.6.1.4.1.9"
        )
        await seeded_session.flush()

        resp = await auth_client.post(
            f"/v1/apps/{app_id}/test-eligibility",
            json={"mode": "instant"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["mode"] == "instant"
        assert data["total_devices"] == 1
        assert data["eligible"] == 1
        # Insert into eligibility_runs + results was attempted
        assert mock_clickhouse.insert_eligibility_run.called
        assert mock_clickhouse.insert_eligibility_results.called

    async def test_vendor_match_excludes_disabled_devices(
        self,
        auth_client: AsyncClient,
        seeded_session: AsyncSession,
    ):
        grp_id = await _create_collector_group(seeded_session)
        await _create_device(
            seeded_session,
            address="10.0.0.1",
            sys_object_id="1.3.6.1.4.1.9.1.2571",
            collector_group_id=grp_id,
            is_enabled=False,
        )
        app_id, _ = await _create_app_with_version(
            seeded_session, vendor_oid_prefix="1.3.6.1.4.1.9"
        )
        await seeded_session.flush()

        resp = await auth_client.post(
            f"/v1/apps/{app_id}/test-eligibility",
            json={"mode": "instant"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["total_devices"] == 0

    async def test_vendor_match_excludes_orphan_devices(
        self,
        auth_client: AsyncClient,
        seeded_session: AsyncSession,
    ):
        from monctl_central.storage.models import Device

        # Device without collector_group_id should be filtered out
        device = Device(
            name="orphan",
            address="10.0.0.99",
            is_enabled=True,
            collector_group_id=None,
            metadata_={"sys_object_id": "1.3.6.1.4.1.9.1.2571"},
        )
        seeded_session.add(device)
        app_id, _ = await _create_app_with_version(
            seeded_session, vendor_oid_prefix="1.3.6.1.4.1.9"
        )
        await seeded_session.flush()

        resp = await auth_client.post(
            f"/v1/apps/{app_id}/test-eligibility",
            json={"mode": "instant"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["total_devices"] == 0

    async def test_no_vendor_prefix_matches_all_enabled_devices(
        self,
        auth_client: AsyncClient,
        seeded_session: AsyncSession,
    ):
        grp_id = await _create_collector_group(seeded_session)
        for i, oid in enumerate(
            ["1.3.6.1.4.1.9.1.1", "1.3.6.1.4.1.2636.1", None],
        ):
            await _create_device(
                seeded_session,
                address=f"10.0.1.{i + 1}",
                sys_object_id=oid,
                collector_group_id=grp_id,
            )
        app_id, _ = await _create_app_with_version(seeded_session)
        await seeded_session.flush()

        resp = await auth_client.post(
            f"/v1/apps/{app_id}/test-eligibility",
            json={"mode": "instant"},
        )
        assert resp.status_code == 200
        # No vendor filter → all 3 devices match
        assert resp.json()["data"]["total_devices"] == 3


# ── Probe mode ───────────────────────────────────────────────────────────────


class TestEligibilityProbe:
    async def test_probe_400_when_no_oids_defined(
        self,
        auth_client: AsyncClient,
        seeded_session: AsyncSession,
    ):
        grp_id = await _create_collector_group(seeded_session)
        await _create_device(
            seeded_session,
            address="10.0.0.1",
            sys_object_id="1.3.6.1.4.1.9.1.2571",
            collector_group_id=grp_id,
        )
        # App has no eligibility_oids → probe must reject
        app_id, _ = await _create_app_with_version(
            seeded_session, vendor_oid_prefix="1.3.6.1.4.1.9"
        )
        await seeded_session.flush()

        resp = await auth_client.post(
            f"/v1/apps/{app_id}/test-eligibility",
            json={"mode": "probe"},
        )
        assert resp.status_code == 400
        assert "No eligibility OIDs" in resp.json()["detail"]

    async def test_probe_sets_redis_flags_per_device(
        self,
        auth_client: AsyncClient,
        seeded_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        grp_id = await _create_collector_group(seeded_session)
        device_id = await _create_device(
            seeded_session,
            address="10.0.0.1",
            sys_object_id="1.3.6.1.4.1.9.1.2571",
            collector_group_id=grp_id,
        )
        app_id, _ = await _create_app_with_version(
            seeded_session,
            vendor_oid_prefix="1.3.6.1.4.1.9",
            eligibility_oids=[
                {"oid": "1.3.6.1.4.1.9.9.13.1.1.0", "check": "exists"},
            ],
        )
        await seeded_session.flush()

        # Track Redis-helper calls
        flag_calls: list[str] = []
        oid_calls: list[tuple[str, list[str]]] = []
        run_calls: list[tuple[str, str, str]] = []

        async def fake_set_flag(dev_id: str, ttl: int = 600) -> None:
            flag_calls.append(dev_id)

        async def fake_set_oids(dev_id: str, oids: list[str]) -> None:
            oid_calls.append((dev_id, oids))

        async def fake_set_run(dev_id: str, run_id: str, app_id: str) -> None:
            run_calls.append((dev_id, run_id, app_id))

        monkeypatch.setattr(
            "monctl_central.cache.set_discovery_flag", fake_set_flag
        )
        monkeypatch.setattr(
            "monctl_central.cache.set_eligibility_oids_for_device",
            fake_set_oids,
        )
        monkeypatch.setattr(
            "monctl_central.cache.set_eligibility_run_for_device",
            fake_set_run,
        )

        resp = await auth_client.post(
            f"/v1/apps/{app_id}/test-eligibility",
            json={"mode": "probe"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["mode"] == "probe"
        assert data["flagged"] == 1

        assert flag_calls == [str(device_id)]
        assert len(oid_calls) == 1
        assert oid_calls[0][1] == ["1.3.6.1.4.1.9.9.13.1.1.0"]
        assert len(run_calls) == 1
        assert run_calls[0][0] == str(device_id)


# ── Auto-assign ──────────────────────────────────────────────────────────────


class TestAutoAssignEligible:
    async def test_auto_assign_creates_assignments(
        self,
        auth_client: AsyncClient,
        seeded_session: AsyncSession,
        mock_clickhouse: MagicMock,
    ):
        grp_id = await _create_collector_group(seeded_session)
        device_id = await _create_device(
            seeded_session,
            address="10.0.0.1",
            sys_object_id="1.3.6.1.4.1.9.1.2571",
            collector_group_id=grp_id,
        )
        app_id, version_id = await _create_app_with_version(
            seeded_session, vendor_oid_prefix="1.3.6.1.4.1.9"
        )
        await seeded_session.flush()

        run_id = str(uuid.uuid4())
        mock_clickhouse.query_eligibility_results = MagicMock(
            return_value=([{"device_id": str(device_id)}], 1)
        )

        resp = await auth_client.post(
            f"/v1/apps/{app_id}/auto-assign-eligible?run_id={run_id}",
            json={"device_ids": [str(device_id)]},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["created"] == 1
        assert data["skipped"] == 0

        # Verify the AppAssignment row was created and points at the latest version
        from monctl_central.storage.models import AppAssignment
        from sqlalchemy import select

        rows = (
            await seeded_session.execute(
                select(AppAssignment).where(AppAssignment.app_id == app_id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].device_id == device_id
        assert rows[0].app_version_id == version_id
        assert rows[0].enabled is True

    async def test_auto_assign_skips_already_assigned(
        self,
        auth_client: AsyncClient,
        seeded_session: AsyncSession,
        mock_clickhouse: MagicMock,
    ):
        from monctl_central.storage.models import AppAssignment

        grp_id = await _create_collector_group(seeded_session)
        device_id = await _create_device(
            seeded_session,
            address="10.0.0.1",
            sys_object_id="1.3.6.1.4.1.9.1.2571",
            collector_group_id=grp_id,
        )
        app_id, version_id = await _create_app_with_version(
            seeded_session, vendor_oid_prefix="1.3.6.1.4.1.9"
        )
        # Pre-existing assignment
        seeded_session.add(
            AppAssignment(
                app_id=app_id,
                app_version_id=version_id,
                device_id=device_id,
                config={},
                schedule_type="interval",
                schedule_value="60",
                use_latest=True,
                enabled=True,
            )
        )
        await seeded_session.flush()

        run_id = str(uuid.uuid4())
        mock_clickhouse.query_eligibility_results = MagicMock(
            return_value=([{"device_id": str(device_id)}], 1)
        )

        resp = await auth_client.post(
            f"/v1/apps/{app_id}/auto-assign-eligible?run_id={run_id}",
            json={"device_ids": [str(device_id)]},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["created"] == 0
        assert data["skipped"] == 1

    async def test_auto_assign_filters_by_device_ids(
        self,
        auth_client: AsyncClient,
        seeded_session: AsyncSession,
        mock_clickhouse: MagicMock,
    ):
        grp_id = await _create_collector_group(seeded_session)
        keep_id = await _create_device(
            seeded_session,
            address="10.0.0.1",
            sys_object_id="1.3.6.1.4.1.9.1.1",
            collector_group_id=grp_id,
        )
        skip_id = await _create_device(
            seeded_session,
            address="10.0.0.2",
            sys_object_id="1.3.6.1.4.1.9.1.2",
            collector_group_id=grp_id,
        )
        app_id, _ = await _create_app_with_version(
            seeded_session, vendor_oid_prefix="1.3.6.1.4.1.9"
        )
        await seeded_session.flush()

        run_id = str(uuid.uuid4())
        # Run-results contain BOTH devices, but body filters to one
        mock_clickhouse.query_eligibility_results = MagicMock(
            return_value=(
                [
                    {"device_id": str(keep_id)},
                    {"device_id": str(skip_id)},
                ],
                2,
            )
        )

        resp = await auth_client.post(
            f"/v1/apps/{app_id}/auto-assign-eligible?run_id={run_id}",
            json={"device_ids": [str(keep_id)]},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["created"] == 1

        from monctl_central.storage.models import AppAssignment
        from sqlalchemy import select

        rows = (
            await seeded_session.execute(
                select(AppAssignment.device_id).where(
                    AppAssignment.app_id == app_id
                )
            )
        ).scalars().all()
        assert rows == [keep_id]
