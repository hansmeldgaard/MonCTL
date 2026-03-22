"""User management tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import UserFactory


class TestUserCRUD:
    async def test_list_users(self, auth_client: AsyncClient):
        resp = await auth_client.get("/v1/users")
        assert resp.status_code == 200
        users = resp.json()["data"]
        assert len(users) >= 1  # at least the seeded admin
        assert any(u["username"] == "admin" for u in users)

    async def test_create_user(self, auth_client: AsyncClient):
        body = UserFactory()
        resp = await auth_client.post("/v1/users", json=body)
        assert resp.status_code == 201
        assert resp.json()["data"]["username"] == body["username"]

    async def test_create_duplicate_username(self, auth_client: AsyncClient):
        body = UserFactory(username="dupuser")
        await auth_client.post("/v1/users", json=body)
        resp = await auth_client.post("/v1/users", json=body)
        assert resp.status_code == 409

    async def test_delete_user(self, auth_client: AsyncClient):
        body = UserFactory()
        create_resp = await auth_client.post("/v1/users", json=body)
        user_id = create_resp.json()["data"]["id"]

        resp = await auth_client.delete(f"/v1/users/{user_id}")
        assert resp.status_code == 204

    async def test_cannot_delete_self(self, auth_client: AsyncClient):
        me_resp = await auth_client.get("/v1/auth/me")
        my_id = me_resp.json()["data"]["user_id"]

        resp = await auth_client.delete(f"/v1/users/{my_id}")
        assert resp.status_code == 400


class TestTimezone:
    async def test_update_timezone(self, auth_client: AsyncClient):
        resp = await auth_client.put("/v1/users/me/timezone", json={
            "timezone": "Europe/Copenhagen",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["timezone"] == "Europe/Copenhagen"
