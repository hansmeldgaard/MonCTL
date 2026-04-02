"""Async HTTP client for communication with the central server.

All calls are outbound (collectors pull; central never contacts collectors).
Uses aiohttp with connection pooling and configurable timeout.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import aiohttp
import structlog

from monctl_collector.jobs.models import ConnectorBinding, JobDefinition

logger = structlog.get_logger()


class CentralAPIClient:
    """Client for the MonCTL central server collector API (/api/v1/)."""

    def __init__(
        self, base_url: str, api_key: str | None = None, timeout: int = 30, verify_ssl: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._verify_ssl = verify_ssl
        self._session: aiohttp.ClientSession | None = None

    async def open(self) -> None:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
        self._session = aiohttp.ClientSession(
            headers=headers,
            timeout=self._timeout,
            connector=connector,
        )

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "CentralAPIClient":
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    def _url(self, path: str) -> str:
        return f"{self._base_url}/api/v1{path}"

    async def post_json(self, path: str, payload: dict) -> dict | None:
        """Generic POST helper for JSON payloads."""
        url = self._url(path)
        async with self._session.post(url, json=payload) as resp:
            if resp.status in (200, 201, 202):
                return await resp.json()
            body = await resp.text()
            raise RuntimeError(f"POST {path} failed: {resp.status} {body[:200]}")

    # ── Jobs ─────────────────────────────────────────────────────────────────

    async def get_jobs(
        self, since: datetime | None = None, collector_id: str | None = None,
    ) -> tuple[list[JobDefinition], list[str]]:
        """Fetch active jobs from central. Returns (changed_jobs, deleted_ids).

        Pass `since` for delta-sync — only jobs updated after that timestamp
        are returned. Pass None to fetch all jobs (on startup).
        Pass `collector_id` to filter jobs to the collector's group.
        """
        params: dict[str, str] = {}
        if since is not None:
            params["since"] = since.isoformat()
        if collector_id:
            params["collector_id"] = collector_id

        async with self._session.get(self._url("/jobs"), params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        jobs: list[JobDefinition] = []
        for j in data.get("jobs", []):
            bindings = [
                ConnectorBinding(
                    alias=b["alias"],
                    connector_id=b["connector_id"],
                    connector_version_id=b["connector_version_id"],
                    credential_name=b.get("credential_name"),
                    use_latest=b.get("use_latest", False),
                    settings=b.get("settings", {}),
                )
                for b in j.get("connector_bindings", [])
            ]
            jobs.append(JobDefinition(
                job_id=j["job_id"],
                device_id=j.get("device_id"),
                device_host=j.get("device_host"),
                app_id=j["app_id"],
                app_version=j["app_version"],
                credential_names=j.get("credential_names", []),
                interval=j.get("interval", 60),
                parameters=j.get("parameters", {}),
                role=j.get("role"),
                max_execution_time=j.get("max_execution_time", 120),
                enabled=j.get("enabled", True),
                updated_at=j.get("updated_at", ""),
                connector_bindings=bindings,
            ))

        deleted_ids: list[str] = data.get("deleted_ids", [])
        return jobs, deleted_ids

    # ── Apps ─────────────────────────────────────────────────────────────────

    async def get_app_metadata(self, app_id: str, version: str | None = None) -> dict:
        """Return app metadata: requirements, entry_class, checksum."""
        params: dict[str, str] = {}
        if version:
            params["version"] = version
        async with self._session.get(
            self._url(f"/apps/{app_id}/metadata"), params=params
        ) as resp:
            resp.raise_for_status()
            return (await resp.json())

    async def get_app_code(self, app_id: str, version: str | None = None) -> dict:
        """Return app source code, checksum, requirements, and entry_class."""
        params: dict[str, str] = {}
        if version:
            params["version"] = version
        async with self._session.get(
            self._url(f"/apps/{app_id}/code"), params=params
        ) as resp:
            resp.raise_for_status()
            return (await resp.json())

    # ── Connectors ─────────────────────────────────────────────────────────────

    async def get_connector_metadata(self, connector_id: str, version_id: str | None = None) -> dict:
        """Return connector metadata: name, version, requirements, entry_class, checksum."""
        params: dict[str, str] = {}
        if version_id:
            params["version_id"] = version_id
        async with self._session.get(
            self._url(f"/connectors/{connector_id}/metadata"), params=params
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_connector_code(self, connector_id: str, version_id: str | None = None) -> dict:
        """Return connector source code."""
        params: dict[str, str] = {}
        if version_id:
            params["version_id"] = version_id
        async with self._session.get(
            self._url(f"/connectors/{connector_id}/code"), params=params
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ── Credentials ───────────────────────────────────────────────────────────

    async def get_credential(self, credential_name: str) -> dict:
        """Return decrypted credential data for a named credential.

        Returns: {"name": ..., "type": ..., "data": {...}}
        """
        async with self._session.get(
            self._url(f"/credentials/{quote(credential_name, safe='')}")
        ) as resp:
            resp.raise_for_status()
            return (await resp.json())

    # ── Results ───────────────────────────────────────────────────────────────

    async def post_results(self, collector_node: str, results: list[dict]) -> bool:
        """Submit a batch of poll results to central.

        Returns True on success, False if central is unavailable (for retry logic).
        """
        payload = {
            "collector_node": collector_node,
            "results": results,
        }
        try:
            async with self._session.post(self._url("/results"), json=payload) as resp:
                if resp.status in (200, 201, 202):
                    return True
                body = await resp.text()
                logger.warning("results_post_error", status=resp.status, body=body[:200])
                return False
        except aiohttp.ClientError as exc:
            logger.warning("results_post_failed", error=str(exc))
            return False

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def post_heartbeat(
        self,
        node_id: str,
        load_info: dict,
        container_states: dict[str, str] | None = None,
        queue_stats: dict | None = None,
        job_costs: dict[str, float] | None = None,
        system_resources: dict | None = None,
    ) -> bool:
        """Send a heartbeat with current load information.

        Returns True on success.
        """
        import platform

        payload = {
            "node_id": node_id,
            "load_score": load_info.get("load_score", 0.0),
            "worker_count": load_info.get("worker_count", 0),
            "effective_load": load_info.get("effective_load", 0.0),
            "deadline_miss_rate": load_info.get("deadline_miss_rate", 0.0),
            "total_jobs": load_info.get("total_jobs", 0),
            "container_states": container_states,
            "queue_stats": queue_stats,
            "job_costs": job_costs,
            "system_resources": system_resources,
            "system_stats": {
                "monctl_version": "0.1.0",
                "os_info": {
                    "os_version": f"{platform.system()} {platform.release()}",
                    "kernel_version": platform.release(),
                    "python_version": platform.python_version(),
                },
            },
        }
        try:
            async with self._session.post(self._url("/heartbeat"), json=payload) as resp:
                return resp.status in (200, 201, 202)
        except aiohttp.ClientError as exc:
            logger.warning("heartbeat_failed", error=str(exc))
            return False

    # ── Config / Peer Discovery ────────────────────────────────────────────

    async def get_config(
        self, collector_id: str, collector_api_key: str
    ) -> dict:
        """Fetch full config from central, including cluster peer info.

        Uses the collector's individual API key (not the shared secret),
        because the /v1/collectors/{id}/config endpoint requires it.
        """
        url = f"{self._base_url}/v1/collectors/{collector_id}/config"
        headers = {"Authorization": f"Bearer {collector_api_key}"}
        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(
                    "get_config_error", status=resp.status, collector_id=collector_id
                )
                return {}
        except aiohttp.ClientError as exc:
            logger.warning("get_config_failed", error=str(exc))
            return {}

    # ── App Cache ─────────────────────────────────────────────────────────────

    async def push_app_cache(
        self, entries: list[dict], node_id: str | None = None,
    ) -> dict | None:
        """Push dirty app cache entries to central."""
        try:
            params: dict[str, str] = {}
            if node_id:
                params["node_id"] = node_id
            async with self._session.post(
                self._url("/app-cache/push"), json={"entries": entries}, params=params,
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    return data.get("data", data)
                body = await resp.text()
                logger.warning("app_cache_push_error", status=resp.status, body=body[:200])
                return None
        except aiohttp.ClientError as exc:
            logger.warning("app_cache_push_failed", error=str(exc))
            return None

    async def pull_app_cache(
        self, since: str | None = None, limit: int = 1000, node_id: str | None = None,
    ) -> dict | None:
        """Pull updated app cache entries from central."""
        params: dict[str, str | int] = {"limit": limit}
        if since:
            params["since"] = since
        if node_id:
            params["node_id"] = node_id
        try:
            async with self._session.get(
                self._url("/app-cache/pull"), params=params
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", data)
                body = await resp.text()
                logger.warning("app_cache_pull_error", status=resp.status, body=body[:200])
                return None
        except aiohttp.ClientError as exc:
            logger.warning("app_cache_pull_failed", error=str(exc))
            return None

    # ── Health ────────────────────────────────────────────────────────────────

    async def wait_for_central(self, max_wait: int = 120, check_interval: int = 5) -> bool:
        """Poll /v1/health until central responds or max_wait is exceeded.

        Returns True if central became available, False on timeout.
        """
        deadline = time.time() + max_wait
        health_url = f"{self._base_url}/v1/health"
        while time.time() < deadline:
            try:
                async with self._session.get(health_url) as resp:
                    if resp.status == 200:
                        logger.info("central_available", url=self._base_url)
                        return True
            except aiohttp.ClientError:
                pass
            logger.info("waiting_for_central", url=self._base_url, retry_in=check_interval)
            import asyncio
            await asyncio.sleep(check_interval)
        return False
