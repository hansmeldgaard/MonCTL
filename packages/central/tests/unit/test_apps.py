"""App CRUD and version management tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import AppFactory


class TestAppList:
    async def test_list_empty(self, auth_client: AsyncClient):
        resp = await auth_client.get("/v1/apps")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    async def test_list_with_apps(self, auth_client: AsyncClient):
        await auth_client.post("/v1/apps", json=AppFactory())
        await auth_client.post("/v1/apps", json=AppFactory())

        resp = await auth_client.get("/v1/apps")
        assert len(resp.json()["data"]) >= 2


class TestAppCreate:
    async def test_create_app(self, auth_client: AsyncClient):
        body = AppFactory()
        resp = await auth_client.post("/v1/apps", json=body)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["name"] == body["name"]

    @pytest.mark.pg_only
    async def test_create_duplicate_name(self, auth_client: AsyncClient):
        """Duplicate app name should be rejected. Requires PG for proper constraint handling."""
        body = AppFactory(name="duplicate_app")
        resp1 = await auth_client.post("/v1/apps", json=body)
        assert resp1.status_code == 201
        body2 = AppFactory(name="duplicate_app")
        resp2 = await auth_client.post("/v1/apps", json=body2)
        assert resp2.status_code in (409, 500)

    async def test_create_config_app(self, auth_client: AsyncClient):
        body = AppFactory(target_table="config")
        resp = await auth_client.post("/v1/apps", json=body)
        assert resp.status_code == 201

    async def test_create_unauthenticated(self, client: AsyncClient):
        resp = await client.post("/v1/apps", json=AppFactory())
        assert resp.status_code == 401


class TestAppVersions:
    async def _create_app(self, auth_client: AsyncClient) -> str:
        resp = await auth_client.post("/v1/apps", json=AppFactory())
        return resp.json()["data"]["id"]

    async def test_create_version(self, auth_client: AsyncClient):
        app_id = await self._create_app(auth_client)

        resp = await auth_client.post(f"/v1/apps/{app_id}/versions", json={
            "version": "1.0.0",
            "source_code": "class MyCheck:\n    pass\n",
            "entry_class": "MyCheck",
        })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["version"] == "1.0.0"
        assert data["is_latest"] is True  # first version auto-latest

    async def test_second_version_not_auto_latest(self, auth_client: AsyncClient):
        app_id = await self._create_app(auth_client)

        await auth_client.post(f"/v1/apps/{app_id}/versions", json={
            "version": "1.0.0",
            "source_code": "class V1:\n    pass\n",
            "entry_class": "V1",
        })
        resp = await auth_client.post(f"/v1/apps/{app_id}/versions", json={
            "version": "1.1.0",
            "source_code": "class V2:\n    pass\n",
            "entry_class": "V2",
        })
        assert resp.status_code == 201
        assert resp.json()["data"]["is_latest"] is False

    async def test_clone_version(self, auth_client: AsyncClient):
        app_id = await self._create_app(auth_client)

        v1 = await auth_client.post(f"/v1/apps/{app_id}/versions", json={
            "version": "1.0.0",
            "source_code": "class Original:\n    pass\n",
            "entry_class": "Original",
        })
        v1_id = v1.json()["data"]["id"]

        resp = await auth_client.post(f"/v1/apps/{app_id}/versions/{v1_id}/clone")
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["version"] == "1.0.1"
        assert data["is_latest"] is False
        assert data["cloned_from"]["version"] == "1.0.0"

    async def test_clone_version_increments_on_collision(self, auth_client: AsyncClient):
        app_id = await self._create_app(auth_client)

        v1 = await auth_client.post(f"/v1/apps/{app_id}/versions", json={
            "version": "1.0.0",
            "source_code": "pass\n",
            "entry_class": "A",
        })
        v1_id = v1.json()["data"]["id"]

        # Create 1.0.1 manually
        await auth_client.post(f"/v1/apps/{app_id}/versions", json={
            "version": "1.0.1",
            "source_code": "pass\n",
            "entry_class": "B",
        })

        # Clone should skip 1.0.1 and create 1.0.2
        resp = await auth_client.post(f"/v1/apps/{app_id}/versions/{v1_id}/clone")
        assert resp.status_code == 201
        assert resp.json()["data"]["version"] == "1.0.2"
