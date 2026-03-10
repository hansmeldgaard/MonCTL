"""Synchronous HTTP client for central API — used by TUI workers."""

from __future__ import annotations

from typing import Any

import httpx


class CentralClient:
    """Thin wrapper around httpx for calling central API endpoints."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def health(self) -> dict[str, Any]:
        """GET /v1/health — test connectivity."""
        r = httpx.get(
            f"{self.base_url}/v1/health",
            headers=self._headers(),
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def register(
        self,
        hostname: str,
        registration_code: str,
        fingerprint: str,
        ip_addresses: list[str] | None = None,
        peer_address: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/collectors/register"""
        payload: dict[str, Any] = {
            "hostname": hostname,
            "registration_code": registration_code,
            "fingerprint": fingerprint,
        }
        if ip_addresses:
            payload["ip_addresses"] = ip_addresses
        if peer_address:
            payload["peer_address"] = peer_address

        r = httpx.post(
            f"{self.base_url}/v1/collectors/register",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def registration_status(self, collector_id: str) -> dict[str, Any]:
        """GET /v1/collectors/{id}/registration-status"""
        r = httpx.get(
            f"{self.base_url}/v1/collectors/{collector_id}/registration-status",
            headers=self._headers(),
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()
