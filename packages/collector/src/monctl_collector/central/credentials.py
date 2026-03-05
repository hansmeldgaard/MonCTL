"""Credential manager — fetches from central, stores encrypted in local SQLite.

Design principles:
  - Credentials are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) at rest.
  - Never written to disk unencrypted.
  - Refresh periodically (default 30 min) but NEVER deleted when central is down.
  - The last known value is always used as fallback — monitoring must not stop
    because central is temporarily unreachable.
"""

from __future__ import annotations

import json
import os
import time

import structlog
from cryptography.fernet import Fernet

from monctl_collector.cache.local_cache import LocalCache
from monctl_collector.central.api_client import CentralAPIClient

logger = structlog.get_logger()

_REFRESH_MARGIN = 60  # refresh this many seconds before refresh_after deadline


class CredentialManager:
    """Manages poll-app credentials with encrypted local cache."""

    def __init__(
        self,
        central_client: CentralAPIClient,
        local_cache: LocalCache,
        encryption_key: bytes,
        refresh_interval: int = 1800,
    ) -> None:
        self._client = central_client
        self._cache = local_cache
        self._fernet = Fernet(encryption_key)
        self._refresh_interval = refresh_interval

    @classmethod
    def make_key(cls, hex_key: str | None = None) -> bytes:
        """Generate or derive a Fernet key.

        Pass a 32-byte hex string from ENCRYPTION_KEY env var, or None to
        auto-generate (useful for single-node setups without key management).
        """
        if hex_key:
            raw = bytes.fromhex(hex_key)
            if len(raw) != 32:
                raise ValueError("ENCRYPTION_KEY must be 64 hex chars (32 bytes)")
            import base64
            return base64.urlsafe_b64encode(raw)
        return Fernet.generate_key()

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_credential(self, credential_name: str) -> dict:
        """Return the decrypted credential data dict for `credential_name`.

        Fetch order:
          1. Local SQLite (if not past refresh_after deadline)
          2. Central server (fetch fresh, update local cache)
          3. Local SQLite fallback (if central unavailable — use stale copy)

        Returns {} if credential is unknown.
        """
        now = time.time()
        row = await self._cache.get_credential(credential_name)

        if row is not None and row["refresh_after"] > now + _REFRESH_MARGIN:
            # Fresh enough — decrypt and return
            return self._decrypt(row["encrypted_data"])

        # Need to refresh
        try:
            fresh = await self._client.get_credential(credential_name)
            data = fresh.get("data", {})
            cred_type = fresh.get("type", "unknown")
            await self._store(credential_name, cred_type, data)
            return data
        except Exception as exc:
            logger.warning(
                "credential_refresh_failed",
                name=credential_name,
                error=str(exc),
            )
            # Fall back to cached copy (even if stale)
            if row is not None:
                logger.info("credential_using_stale_cache", name=credential_name)
                return self._decrypt(row["encrypted_data"])
            return {}

    async def refresh_all(self, credential_names: set[str]) -> None:
        """Refresh all known credentials that are approaching their deadline.

        Called periodically (every refresh_interval seconds).
        """
        now = time.time()
        for name in credential_names:
            row = await self._cache.get_credential(name)
            if row is None or row["refresh_after"] < now + _REFRESH_MARGIN:
                try:
                    fresh = await self._client.get_credential(name)
                    await self._store(name, fresh.get("type", "unknown"), fresh.get("data", {}))
                    logger.debug("credential_refreshed", name=name)
                except Exception as exc:
                    logger.warning("credential_refresh_failed", name=name, error=str(exc))

    # ── Private ───────────────────────────────────────────────────────────────

    def _encrypt(self, data: dict) -> bytes:
        return self._fernet.encrypt(json.dumps(data).encode())

    def _decrypt(self, encrypted: bytes) -> dict:
        return json.loads(self._fernet.decrypt(encrypted).decode())

    async def _store(self, name: str, cred_type: str, data: dict) -> None:
        encrypted = self._encrypt(data)
        refresh_after = time.time() + self._refresh_interval
        await self._cache.upsert_credential(name, cred_type, encrypted, refresh_after)
