"""poll-worker entrypoint — executes monitoring apps.

The poll-worker:
  1. Connects to the local cache-node via gRPC.
  2. Starts the PollEngine which pulls jobs and executes them.
  3. Sends results back to the cache-node.

Configuration (env vars):
  MONCTL_CACHE_NODE     — host:port of the local cache-node (default: cache-node:50051)
  MONCTL_WORKER_ID      — unique worker ID (default: hostname-pid)
  MONCTL_APPS_DIR       — path for downloaded app code (default: /data/apps)
  MONCTL_VENVS_DIR      — path for shared virtualenvs (default: /data/venvs)
  MONCTL_CENTRAL_URL    — needed for app downloads
  MONCTL_CENTRAL_API_KEY
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket

import structlog

from monctl_collector.apps.manager import AppManager
from monctl_collector.cache.local_cache import LocalCache
from monctl_collector.central.api_client import CentralAPIClient
from monctl_collector.central.credentials import CredentialManager
from monctl_collector.config import CollectorConfig, load_config
from monctl_collector.peer.client import PeerChannelPool
from monctl_collector.polling.engine import PollEngine

logger = structlog.get_logger()


async def run(cfg: CollectorConfig) -> None:
    worker_id = os.environ.get(
        "MONCTL_WORKER_ID",
        f"{socket.gethostname()}-{os.getpid()}",
    )
    cache_node_addr = os.environ.get("MONCTL_CACHE_NODE", "cache-node:50051")

    logger.info("poll_worker_starting", worker_id=worker_id, cache_node=cache_node_addr)

    # ── Shared infrastructure ─────────────────────────────────────────────────
    channel_pool = PeerChannelPool()
    central_client = CentralAPIClient(
        cfg.central.url,
        api_key=cfg.effective_auth_token(),
        timeout=cfg.central.timeout,
        verify_ssl=cfg.central.verify_ssl,
        collector_id=cfg.collector_id or None,
    )
    await central_client.open()

    # Poll-workers don't have their own SQLite for jobs, but they do use a
    # small local cache for credential fallback (shared volume or in-memory).
    local_cache = LocalCache(cfg.cache.db_path)
    await local_cache.open()

    encryption_key = CredentialManager.make_key()
    credential_manager = CredentialManager(
        central_client=central_client,
        local_cache=local_cache,
        encryption_key=encryption_key,
        refresh_interval=cfg.central.credential_refresh,
    )

    # ── App manager ───────────────────────────────────────────────────────────
    app_manager = AppManager(
        config=cfg.apps,
        central_client=central_client,
    )

    # ── Poll engine ───────────────────────────────────────────────────────────
    engine = PollEngine(
        worker_id=worker_id,
        cache_node_address=cache_node_addr,
        app_manager=app_manager,
        credential_manager=credential_manager,
        config=cfg.scheduling,
        channel_pool=channel_pool,
    )

    engine_task = await engine.start()

    logger.info("poll_worker_ready", worker_id=worker_id)

    # ── Shutdown handler ──────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("worker_shutdown_signal")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    await shutdown_event.wait()

    await engine.stop()
    await central_client.close()
    await local_cache.close()
    await channel_pool.close_all()
    logger.info("poll_worker_stopped", worker_id=worker_id)


def main() -> None:
    from monctl_collector.logging_setup import setup_logging
    setup_logging()
    cfg = load_config()
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
