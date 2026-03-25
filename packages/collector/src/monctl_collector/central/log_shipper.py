"""Collects Docker container logs and ships to central in batches.

Runs as a background task in the cache-node. Every BATCH_INTERVAL seconds,
collects new log lines from Docker containers (via sidecar API) and
POSTs them to central.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()

BATCH_INTERVAL_SECONDS = 10
MAX_LINES_PER_BATCH = 5000


class LogShipper:
    """Collects and ships logs to central."""

    def __init__(
        self,
        central_client,
        collector_id: str,
        collector_name: str,
        host_label: str = "",
        sidecar_url: str = "http://localhost:9100",
        log_level_filter: str = "INFO",
    ):
        self._client = central_client
        self._collector_id = collector_id
        self._collector_name = collector_name
        self._host_label = host_label
        self._sidecar_url = sidecar_url
        self._log_level_filter = log_level_filter
        self._running = False
        self._last_timestamps: dict[str, str] = {}

    @property
    def log_level_filter(self) -> str:
        return self._log_level_filter

    @log_level_filter.setter
    def log_level_filter(self, value: str):
        self._log_level_filter = value

    async def run(self):
        self._running = True
        logger.info("log_shipper_started", interval=BATCH_INTERVAL_SECONDS)

        while self._running:
            try:
                await self._collect_and_ship()
            except Exception as exc:
                logger.warning("log_shipper_cycle_error", error=str(exc))
            await asyncio.sleep(BATCH_INTERVAL_SECONDS)

    async def stop(self):
        self._running = False

    async def _collect_and_ship(self):
        entries = []

        try:
            docker_entries = await asyncio.to_thread(self._fetch_docker_logs)
            entries.extend(docker_entries)
        except Exception as exc:
            logger.debug("log_shipper_docker_error", error=str(exc))

        if not entries:
            return

        level_order = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
        min_level = level_order.get(self._log_level_filter, 1)
        filtered = [
            e for e in entries
            if level_order.get(e.get("level", "INFO"), 1) >= min_level
        ]

        if not filtered:
            return

        batch = filtered[:MAX_LINES_PER_BATCH]

        payload = {
            "collector_id": self._collector_id,
            "collector_name": self._collector_name,
            "host_label": self._host_label,
            "entries": batch,
        }

        try:
            await self._client.post_json("/logs/ingest", payload)
            logger.debug("log_ship_ok", count=len(batch))
        except Exception as exc:
            logger.warning("log_ship_failed", error=str(exc))

    def _fetch_docker_logs(self) -> list[dict]:
        entries = []

        try:
            req = urllib.request.Request(f"{self._sidecar_url}/stats", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                stats_data = json.loads(resp.read().decode())
        except Exception:
            return entries

        containers = stats_data.get("containers", [])

        for container in containers:
            name = container.get("name", "")
            if not name:
                continue

            try:
                url = f"{self._sidecar_url}/logs?container={name}&tail=200"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    log_data = json.loads(resp.read().decode())

                lines = log_data.get("lines", [])
                last_ts = self._last_timestamps.get(name, "")

                new_lines = []
                for line in lines:
                    if isinstance(line, str):
                        new_lines.append(line)
                    else:
                        line_ts = line.get("timestamp", "")
                        if line_ts > last_ts:
                            new_lines.append(line)

                for line in new_lines:
                    if isinstance(line, str):
                        entries.append({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "source_type": "docker",
                            "container_name": name,
                            "image_name": container.get("image", ""),
                            "level": self._detect_level(line),
                            "stream": "stdout",
                            "message": line,
                        })
                    else:
                        entries.append({
                            "timestamp": line.get(
                                "timestamp", datetime.now(timezone.utc).isoformat()
                            ),
                            "source_type": "docker",
                            "container_name": name,
                            "image_name": container.get("image", ""),
                            "level": self._detect_level(line.get("message", "")),
                            "stream": line.get("stream", "stdout"),
                            "message": line.get("message", str(line)),
                        })

                if new_lines:
                    last = new_lines[-1]
                    if isinstance(last, dict) and "timestamp" in last:
                        self._last_timestamps[name] = last["timestamp"]

            except Exception:
                continue

        return entries

    @staticmethod
    def _detect_level(message: str) -> str:
        msg_upper = message.upper()[:100]
        if "CRITICAL" in msg_upper or "FATAL" in msg_upper:
            return "CRITICAL"
        if "ERROR" in msg_upper or "ERR " in msg_upper:
            return "ERROR"
        if "WARNING" in msg_upper or "WARN " in msg_upper:
            return "WARNING"
        if "DEBUG" in msg_upper:
            return "DEBUG"
        return "INFO"
