"""Configuration sync - polls central for config changes."""

from __future__ import annotations

import asyncio

import httpx
import structlog

from monctl_collector.config import collector_settings
from monctl_common.schemas.config import CollectorConfig

logger = structlog.get_logger()


class ConfigSyncService:
    """Polls central for configuration changes and applies them."""

    def __init__(self, central_url: str, api_key: str, collector_id: str):
        self.central_url = central_url
        self.api_key = api_key
        self.collector_id = collector_id
        self.current_config_version: int = 0
        self.current_config: CollectorConfig | None = None

    async def fetch_config(self) -> CollectorConfig | None:
        """Fetch the full config snapshot from central."""
        try:
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self.api_key}"},
                verify=collector_settings.verify_ssl,
                timeout=30,
            ) as client:
                response = await client.get(
                    f"{self.central_url}/v1/collectors/{self.collector_id}/config",
                )

                if response.status_code == 200:
                    data = response.json().get("data", {})
                    config = CollectorConfig(**data)
                    self.current_config = config
                    self.current_config_version = config.config_version
                    logger.info("config_fetched", version=config.config_version)
                    return config
                else:
                    logger.warning("config_fetch_failed", status=response.status_code)
                    return None
        except Exception as e:
            logger.warning("config_fetch_error", error=str(e))
            return None

    async def run(self):
        """Periodic config sync loop (backup to heartbeat-triggered sync)."""
        while True:
            await asyncio.sleep(collector_settings.config_poll_interval)
            await self.fetch_config()
