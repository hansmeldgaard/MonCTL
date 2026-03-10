"""forwarder entrypoint — ships buffered results to central.

The forwarder reads from the SQLite database (shared volume with cache-node)
and POSTs unsent results to central's /api/v1/results endpoint.

Configuration (env vars):
  MONCTL_CENTRAL_URL     — e.g. https://central.example.com
  MONCTL_CENTRAL_API_KEY — API key
  MONCTL_DB_PATH         — path to SQLite database (default: /data/cache.db)
  MONCTL_NODE_ID         — identifies this collector node in result payloads
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket

import structlog

from monctl_collector.cache.local_cache import LocalCache
from monctl_collector.config import CollectorConfig, load_config
from monctl_collector.forward.forwarder import Forwarder

logger = structlog.get_logger()


async def run(cfg: CollectorConfig) -> None:
    node_id = cfg.node_id or socket.gethostname()

    logger.info("forwarder_starting", node_id=node_id, central=cfg.central.url)

    local_cache = LocalCache(cfg.cache.db_path)
    await local_cache.open()

    forwarder = Forwarder(
        node_id=node_id,
        local_cache=local_cache,
        config=cfg.central,
    )

    fwd_task = await forwarder.start()

    # ── Shutdown handler ──────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("forwarder_shutdown_signal")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    await shutdown_event.wait()

    await forwarder.stop()
    await local_cache.close()
    logger.info("forwarder_stopped")


def main() -> None:
    import logging
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
