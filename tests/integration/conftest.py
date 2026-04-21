"""Fixtures for the e2e integration harness (F-X-007).

Assumes `docker/docker-compose.e2e.yml` has been started externally
(via `scripts/run_e2e.sh` or manually). The fixtures just point at
`http://localhost:18443` and log in once per session.
"""
from __future__ import annotations

import os

import httpx
import pytest


BASE_URL = os.environ.get("MONCTL_E2E_BASE_URL", "http://localhost:18443")
ADMIN_USERNAME = os.environ.get("MONCTL_E2E_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("MONCTL_E2E_ADMIN_PASSWORD", "e2e-test-password")


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def admin_client(base_url: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=15.0, verify=False)
    resp = client.post(
        "/v1/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    resp.raise_for_status()
    yield client
    client.close()
