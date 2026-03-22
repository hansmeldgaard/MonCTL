"""System settings tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class TestSettings:
    async def test_get_settings(self, auth_client: AsyncClient):
        resp = await auth_client.get("/v1/settings")
        assert resp.status_code == 200
        data = resp.json()["data"]
        # Should include all defaults
        assert "check_results_retention_days" in data
        assert "session_idle_timeout_minutes" in data

    async def test_get_settings_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/v1/settings")
        assert resp.status_code == 401

    async def test_update_settings(self, auth_client: AsyncClient):
        resp = await auth_client.put("/v1/settings", json={
            "settings": {
                "session_idle_timeout_minutes": "120",
            },
        })
        assert resp.status_code == 200

        # Verify it persisted
        get_resp = await auth_client.get("/v1/settings")
        assert get_resp.json()["data"]["session_idle_timeout_minutes"] == "120"


class TestIdleTimeout:
    async def test_update_idle_timeout_valid(self, auth_client: AsyncClient):
        resp = await auth_client.put("/v1/users/me/idle-timeout", json={
            "idle_timeout_minutes": 120,
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["idle_timeout_minutes"] == 120

    async def test_update_idle_timeout_never(self, auth_client: AsyncClient):
        resp = await auth_client.put("/v1/users/me/idle-timeout", json={
            "idle_timeout_minutes": 0,
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["idle_timeout_minutes"] == 0

    async def test_update_idle_timeout_system_default(self, auth_client: AsyncClient):
        # Set to custom first
        await auth_client.put("/v1/users/me/idle-timeout", json={
            "idle_timeout_minutes": 30,
        })
        # Then reset to system default
        resp = await auth_client.put("/v1/users/me/idle-timeout", json={
            "idle_timeout_minutes": None,
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["idle_timeout_minutes"] is None

    async def test_update_idle_timeout_invalid_value(self, auth_client: AsyncClient):
        resp = await auth_client.put("/v1/users/me/idle-timeout", json={
            "idle_timeout_minutes": 45,  # not in VALID_IDLE_TIMEOUTS
        })
        assert resp.status_code == 422
