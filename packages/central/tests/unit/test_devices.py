"""Device CRUD tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import DeviceFactory


class TestDeviceList:
    async def test_list_empty(self, auth_client: AsyncClient):
        resp = await auth_client.get("/v1/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert isinstance(data["data"], list)

    async def test_list_with_devices(self, auth_client: AsyncClient):
        types_resp = await auth_client.get("/v1/device-types")
        type_id = types_resp.json()["data"][0]["id"]

        for i in range(2):
            body = DeviceFactory(address=f"10.0.0.{i + 1}", device_type_id=type_id)
            await auth_client.post("/v1/devices", json=body)

        resp = await auth_client.get("/v1/devices")
        assert len(resp.json()["data"]) == 2


class TestDeviceCreate:
    async def test_create_device(self, auth_client: AsyncClient):
        types_resp = await auth_client.get("/v1/device-types")
        type_id = types_resp.json()["data"][0]["id"]

        body = DeviceFactory(device_type_id=type_id)
        resp = await auth_client.post("/v1/devices", json=body)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["name"] == body["name"]
        assert data["address"] == body["address"]

    @pytest.mark.pg_only
    async def test_create_duplicate_address(self, auth_client: AsyncClient):
        """Devices with same address should be rejected. Requires PG for constraint handling."""
        types_resp = await auth_client.get("/v1/device-types")
        type_id = types_resp.json()["data"][0]["id"]

        body = DeviceFactory(device_type_id=type_id, address="10.99.99.1")
        await auth_client.post("/v1/devices", json=body)
        body2 = DeviceFactory(device_type_id=type_id, address="10.99.99.1")
        resp = await auth_client.post("/v1/devices", json=body2)
        assert resp.status_code in (409, 500)

    async def test_create_unauthenticated(self, client: AsyncClient):
        resp = await client.post("/v1/devices", json=DeviceFactory())
        assert resp.status_code == 401


class TestDeviceUpdate:
    async def test_update_name(self, auth_client: AsyncClient):
        types_resp = await auth_client.get("/v1/device-types")
        type_id = types_resp.json()["data"][0]["id"]

        create_resp = await auth_client.post(
            "/v1/devices", json=DeviceFactory(device_type_id=type_id)
        )
        device_id = create_resp.json()["data"]["id"]

        resp = await auth_client.put(
            f"/v1/devices/{device_id}",
            json={"name": "renamed-device"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "renamed-device"


class TestDeviceDelete:
    async def test_delete_device(self, auth_client: AsyncClient):
        types_resp = await auth_client.get("/v1/device-types")
        type_id = types_resp.json()["data"][0]["id"]

        create_resp = await auth_client.post(
            "/v1/devices", json=DeviceFactory(device_type_id=type_id)
        )
        device_id = create_resp.json()["data"]["id"]

        resp = await auth_client.delete(f"/v1/devices/{device_id}")
        assert resp.status_code in (200, 204)

        get_resp = await auth_client.get(f"/v1/devices/{device_id}")
        assert get_resp.status_code == 404

    async def test_delete_nonexistent(self, auth_client: AsyncClient):
        resp = await auth_client.delete(
            "/v1/devices/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code == 404


class TestDeviceFiltering:
    async def test_filter_by_name(self, auth_client: AsyncClient):
        types_resp = await auth_client.get("/v1/device-types")
        type_id = types_resp.json()["data"][0]["id"]

        await auth_client.post("/v1/devices", json=DeviceFactory(
            name="router-alpha", device_type_id=type_id, address="10.0.1.1",
        ))
        await auth_client.post("/v1/devices", json=DeviceFactory(
            name="switch-beta", device_type_id=type_id, address="10.0.1.2",
        ))

        resp = await auth_client.get("/v1/devices?name=router")
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "router-alpha"

    async def test_pagination(self, auth_client: AsyncClient):
        types_resp = await auth_client.get("/v1/device-types")
        type_id = types_resp.json()["data"][0]["id"]

        for i in range(5):
            await auth_client.post("/v1/devices", json=DeviceFactory(
                device_type_id=type_id, address=f"10.0.2.{i + 1}",
            ))

        resp = await auth_client.get("/v1/devices?limit=2&offset=0")
        assert len(resp.json()["data"]) == 2
        assert resp.json()["meta"]["total"] == 5
