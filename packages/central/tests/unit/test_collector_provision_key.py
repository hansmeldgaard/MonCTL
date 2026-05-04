"""Tests for the admin-only per-collector key-mint endpoint.

Wave 2 enabler (M-INST-011 / S-COL-002 / S-X-002). Closes the gap
where customer installs ship every collector with the same shared
secret because ``monctl_ctl deploy`` had no way to mint per-host
keys at install time. ``POST /v1/collectors/by-hostname/{hostname}/
api-keys`` lets an admin (or the installer using the admin creds in
secrets.env) provision a unique key per host.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import pytest

from monctl_central.storage.models import ApiKey, Collector


@pytest.mark.asyncio
async def test_admin_creates_collector_and_mints_key_for_new_hostname(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await auth_client.post(
        "/v1/collectors/by-hostname/worker-99/api-keys",
        json={},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Endpoint returns the key shape directly (no `data` envelope) per
    # the response_model — the customer installer reads `api_key` directly.
    assert body["name"] == "worker-99"
    assert body["status"] == "PENDING"
    assert body["created"] is True
    assert body["api_key"].startswith("monctl_c_")  # COLLECTOR_KEY_PREFIX
    assert body["collector_id"]

    # Collector row exists in PG + a single ApiKey row points to it.
    coll = (
        await db_session.execute(
            select(Collector).where(Collector.hostname == "worker-99")
        )
    ).scalar_one()
    assert coll.status == "PENDING"
    keys = (
        await db_session.execute(
            select(ApiKey).where(ApiKey.collector_id == coll.id)
        )
    ).scalars().all()
    assert len(keys) == 1
    assert keys[0].key_type == "collector"
    assert keys[0].scopes == ["collector:*"]


@pytest.mark.asyncio
async def test_admin_mints_additional_key_for_existing_collector(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Re-running the endpoint adds a new key without resetting collector
    state — key rotation supported, but the existing approval / group
    membership / status survive."""
    # First call creates the collector and key #1.
    first = await auth_client.post(
        "/v1/collectors/by-hostname/worker-99/api-keys",
        json={},
    )
    assert first.status_code == 201

    # Manually move it to ACTIVE so we can verify the second call doesn't
    # demote it back to PENDING.
    coll = (
        await db_session.execute(
            select(Collector).where(Collector.hostname == "worker-99")
        )
    ).scalar_one()
    coll.status = "ACTIVE"
    await db_session.commit()

    second = await auth_client.post(
        "/v1/collectors/by-hostname/worker-99/api-keys",
        json={},
    )
    assert second.status_code == 201
    body = second.json()
    assert body["created"] is False
    assert body["status"] == "ACTIVE"
    # Two distinct keys now exist for this collector
    keys = (
        await db_session.execute(
            select(ApiKey).where(ApiKey.collector_id == coll.id)
        )
    ).scalars().all()
    assert len(keys) == 2
    assert {k.key_hash for k in keys} != {keys[0].key_hash}  # distinct hashes


@pytest.mark.asyncio
async def test_revoke_existing_drops_prior_keys(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Operator rotates the key — pass `revoke_existing=true` so the
    leaked old key stops working immediately."""
    await auth_client.post(
        "/v1/collectors/by-hostname/worker-99/api-keys",
        json={},
    )
    rotated = await auth_client.post(
        "/v1/collectors/by-hostname/worker-99/api-keys",
        json={"revoke_existing": True},
    )
    assert rotated.status_code == 201

    coll = (
        await db_session.execute(
            select(Collector).where(Collector.hostname == "worker-99")
        )
    ).scalar_one()
    keys = (
        await db_session.execute(
            select(ApiKey).where(ApiKey.collector_id == coll.id)
        )
    ).scalars().all()
    # Exactly one key after rotation — the new one
    assert len(keys) == 1


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/v1/collectors/by-hostname/worker-99/api-keys",
        json={},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_blank_hostname_rejected(
    auth_client: AsyncClient,
) -> None:
    """FastAPI lets `   ` past the path-parameter type check; the handler
    has to defend itself."""
    resp = await auth_client.post(
        "/v1/collectors/by-hostname/   /api-keys",
        json={},
    )
    # Strict: blank hostname is a 400 (caller bug), not silently accepted.
    assert resp.status_code == 400
    assert "hostname" in resp.json()["detail"].lower()
