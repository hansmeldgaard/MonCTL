"""Push client - sends buffered results to central server."""

from __future__ import annotations

import asyncio
import math

import httpx
import structlog

from monctl_collector.buffer.service import ResultBuffer

logger = structlog.get_logger()


class PushClient:
    """Drains the local buffer and pushes results to central."""

    def __init__(
        self,
        central_url: str,
        api_key: str,
        collector_id: str,
        buffer: ResultBuffer,
        push_interval: float = 10.0,
        max_backoff: float = 60.0,
    ):
        self.central_url = central_url
        self.api_key = api_key
        self.collector_id = collector_id
        self.buffer = buffer
        self.push_interval = push_interval
        self.max_backoff = max_backoff
        self._consecutive_failures = 0

    async def run(self):
        """Main push loop - drain buffer and send to central."""
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        ) as client:
            while True:
                batch = await self.buffer.dequeue_batch(100)
                if batch:
                    success = await self._send_batch(client, batch)
                    if success:
                        self._consecutive_failures = 0
                        ids = [item["id"] for item in batch]
                        await self.buffer.mark_sent(ids)
                        # Clean up periodically
                        await self.buffer.cleanup()
                    else:
                        self._consecutive_failures += 1
                        ids = [item["id"] for item in batch]
                        await self.buffer.mark_failed(ids)
                        backoff = min(
                            self.max_backoff,
                            math.pow(2, self._consecutive_failures),
                        )
                        logger.warning(
                            "push_backoff",
                            failures=self._consecutive_failures,
                            backoff_seconds=backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue
                else:
                    await asyncio.sleep(self.push_interval)

    async def _send_batch(self, client: httpx.AsyncClient, batch: list[dict]) -> bool:
        """Send a batch of results to central. Returns True on success."""
        try:
            # Merge payloads into a single ingest payload
            all_results = []
            all_events = []
            for item in batch:
                payload = item["payload"]
                all_results.extend(payload.get("app_results", []))
                all_events.extend(payload.get("events", []))

            ingest_payload = {
                "collector_id": self.collector_id,
                "timestamp": payload.get("timestamp", ""),
                "sequence": payload.get("sequence", 0),
                "app_results": all_results,
                "events": all_events,
            }

            response = await client.post(
                f"{self.central_url}/v1/ingest",
                json=ingest_payload,
            )

            if response.status_code == 202:
                logger.debug("push_success", results=len(all_results), events=len(all_events))
                return True
            elif response.status_code == 503:
                logger.warning("central_overloaded")
                return False
            else:
                logger.warning("push_failed", status=response.status_code)
                return False
        except Exception as e:
            logger.warning("push_error", error=str(e))
            return False
