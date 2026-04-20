"""Collects Docker container logs and ships to central in batches.

Runs as a background task in the cache-node. Every BATCH_INTERVAL seconds,
collects new log lines from Docker containers (via sidecar API) and
POSTs them to central.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.request
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()

BATCH_INTERVAL_SECONDS = 10
MAX_LINES_PER_BATCH = 5000

# Drop any log line whose message matches one of these patterns — they almost
# always carry credentials in plaintext. The structlog-shipped logs on central
# already redact via `audit/diff.py`, but container stdout is raw and a single
# `logger.error(f"auth failed: {creds}")` in any third-party app would leak
# into ClickHouse. Cheap belt-and-braces at the shipper boundary.
_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(api[_-]?key|apikey)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(token|bearer|secret|jwt)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bAuthorization:\s*Bearer\s+\S+"),
    re.compile(r"(?i)\bsnmp_community\s*[:=]\s*\S+"),
]

# Hard cap on lines per cycle per container — a runaway container flooding
# stdout must not swamp central's ingest pipeline for its neighbours.
_PER_CONTAINER_RATE_LIMIT = 500


def _contains_secret(msg: str) -> bool:
    return any(p.search(msg) for p in _SECRET_PATTERNS)


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
        self._dropped_secret = 0
        self._dropped_rate = 0
        self._last_stats_log = 0.0

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

            now = time.time()
            if now - self._last_stats_log > 300 and (
                self._dropped_secret or self._dropped_rate
            ):
                logger.info(
                    "log_shipper_drops",
                    dropped_secret=self._dropped_secret,
                    dropped_rate=self._dropped_rate,
                )
                self._last_stats_log = now

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

                shipped_this_container = 0
                for line in new_lines:
                    if shipped_this_container >= _PER_CONTAINER_RATE_LIMIT:
                        self._dropped_rate += 1
                        continue

                    if isinstance(line, dict):
                        msg = line.get("message", str(line))
                        if _contains_secret(msg):
                            self._dropped_secret += 1
                            continue
                        entries.append({
                            "timestamp": line.get(
                                "timestamp", datetime.now(timezone.utc).isoformat()
                            ),
                            "source_type": "docker",
                            "container_name": name,
                            "image_name": container.get("image", ""),
                            "level": self._detect_level(msg),
                            "stream": line.get("stream", "stdout"),
                            "message": msg,
                        })
                    else:
                        # Raw string — parse Docker timestamp prefix if present
                        # Format: "2026-04-04T17:11:55.242448430Z message"
                        ts = datetime.now(timezone.utc).isoformat()
                        msg = line
                        z_pos = line.find('Z ', 19, 40) if len(line) > 20 else -1
                        if z_pos > 0 and line[4] == '-' and line[10] == 'T':
                            ts = line[:z_pos + 1]
                            msg = line[z_pos + 2:]
                        if _contains_secret(msg):
                            self._dropped_secret += 1
                            continue
                        entries.append({
                            "timestamp": ts,
                            "source_type": "docker",
                            "container_name": name,
                            "image_name": container.get("image", ""),
                            "level": self._detect_level(msg),
                            "stream": "stdout",
                            "message": msg,
                        })
                    shipped_this_container += 1

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
