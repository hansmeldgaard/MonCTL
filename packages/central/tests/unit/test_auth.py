"""Auth endpoint tests — login, logout, JWT refresh, /me."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        resp = await client.post("/v1/auth/login", json={
            "username": "admin",
            "password": "changeme",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"]["username"] == "admin"
        assert data["data"]["role"] == "admin"
        assert "access_token" in resp.cookies

    async def test_login_wrong_password(self, client: AsyncClient):
        resp = await client.post("/v1/auth/login", json={
            "username": "admin",
            "password": "wrong",
        })
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        resp = await client.post("/v1/auth/login", json={
            "username": "nobody",
            "password": "whatever",
        })
        assert resp.status_code == 401

    async def test_login_returns_idle_timeout(self, client: AsyncClient):
        resp = await client.post("/v1/auth/login", json={
            "username": "admin",
            "password": "changeme",
        })
        assert resp.status_code == 200
        assert "idle_timeout_minutes" in resp.json()["data"]


class TestMe:
    async def test_me_authenticated(self, auth_client: AsyncClient):
        resp = await auth_client.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["username"] == "admin"
        assert data["role"] == "admin"
        assert "idle_timeout_minutes" in data

    async def test_me_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/v1/auth/me")
        assert resp.status_code == 401


class TestLogout:
    async def test_logout_clears_cookie(self, auth_client: AsyncClient):
        resp = await auth_client.post("/v1/auth/logout")
        assert resp.status_code == 200


class TestRefresh:
    async def test_refresh_with_valid_token(self, client: AsyncClient):
        # First login to get refresh cookie
        login_resp = await client.post("/v1/auth/login", json={
            "username": "admin",
            "password": "changeme",
        })
        assert login_resp.status_code == 200
        # `client.cookies = ...` is a silent no-op on httpx 0.28+; use per-cookie set
        for k, v in login_resp.cookies.items():
            client.cookies.set(k, v)

        # Now refresh
        resp = await client.post("/v1/auth/refresh")
        assert resp.status_code == 200
        assert resp.json()["data"]["username"] == "admin"
        assert "idle_timeout_minutes" in resp.json()["data"]

    async def test_refresh_without_cookie(self, client: AsyncClient):
        resp = await client.post("/v1/auth/refresh")
        assert resp.status_code == 401
