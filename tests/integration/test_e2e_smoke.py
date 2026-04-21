"""End-to-end smoke test (F-X-007 phase 1).

Exercises the golden path through a fresh central stack:

  1. Unauthenticated /v1/health returns 200.
  2. Admin can log in, sets cookies, can read /v1/auth/me.
  3. Admin can create a device, read it back, and delete it.
  4. /v1/devices list reflects the created + deleted lifecycle.

Runs against a stack started by `scripts/run_e2e.sh` (docker compose).
"""
from __future__ import annotations

import httpx


def test_health_endpoint_is_unauthenticated(base_url: str) -> None:
    resp = httpx.get(f"{base_url}/v1/health", timeout=10.0, verify=False)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "version" in body


def test_login_sets_cookies_and_me_returns_admin(admin_client: httpx.Client) -> None:
    resp = admin_client.get("/v1/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    data = body.get("data", body)
    assert data.get("username") == "admin"


def test_device_crud_roundtrip(admin_client: httpx.Client) -> None:
    create_resp = admin_client.post(
        "/v1/devices",
        json={
            "name": "e2e-smoke-device",
            "address": "198.51.100.1",
            "device_category": "host",
            "labels": {"env": "e2e"},
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()["data"]
    device_id = created["id"]
    assert created["name"] == "e2e-smoke-device"

    try:
        get_resp = admin_client.get(f"/v1/devices/{device_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["address"] == "198.51.100.1"

        list_resp = admin_client.get("/v1/devices", params={"limit": 100})
        assert list_resp.status_code == 200
        names = {d["name"] for d in list_resp.json()["data"]}
        assert "e2e-smoke-device" in names
    finally:
        del_resp = admin_client.delete(f"/v1/devices/{device_id}")
        assert del_resp.status_code in (200, 204), del_resp.text

    # FastAPI yield-dependency commits session AFTER the response returns,
    # so poll briefly for the delete to land instead of failing on the race.
    import time
    for _ in range(20):
        post_get = admin_client.get(f"/v1/devices/{device_id}")
        if post_get.status_code == 404:
            break
        time.sleep(0.1)
    else:
        raise AssertionError(f"device {device_id} still present 2s after DELETE returned 204")
