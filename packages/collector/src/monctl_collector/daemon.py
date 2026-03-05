"""Main collector daemon orchestrator."""

from __future__ import annotations

import asyncio
import signal

import structlog

from monctl_collector.config import collector_settings

logger = structlog.get_logger()


class CollectorDaemon:
    """Orchestrates all collector components."""

    def __init__(self):
        self.running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        """Start the collector daemon."""
        self.running = True
        logger.info(
            "collector_starting",
            collector_id=collector_settings.collector_id,
            central_url=collector_settings.central_url,
        )

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Initialize components
        from monctl_collector.buffer.service import ResultBuffer
        from monctl_collector.push_client.service import PushClient
        from monctl_collector.config_sync.service import ConfigSyncService
        from monctl_collector.runner.scheduler import AppScheduler

        self.buffer = ResultBuffer(collector_settings.buffer_path, collector_settings.buffer_max_size_mb)
        await self.buffer.initialize()

        self.push_client = PushClient(
            central_url=collector_settings.central_url,
            api_key=collector_settings.api_key,
            collector_id=collector_settings.collector_id,
            buffer=self.buffer,
        )

        self.config_sync = ConfigSyncService(
            central_url=collector_settings.central_url,
            api_key=collector_settings.api_key,
            collector_id=collector_settings.collector_id,
        )

        self.app_scheduler = AppScheduler(
            buffer=self.buffer,
            collector_id=collector_settings.collector_id,
            apps_dir=collector_settings.apps_dir,
            max_concurrent=collector_settings.max_concurrent_apps,
        )
        self.app_scheduler.start()

        # Fetch initial configuration and apply assignments immediately
        config = await self.config_sync.fetch_config()
        if config:
            await self.app_scheduler.apply_config(config)
        logger.info("initial_config_fetched", config_version=config.config_version if config else 0)

        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat"),
            asyncio.create_task(self.push_client.run(), name="push_client"),
            asyncio.create_task(self.config_sync.run(), name="config_sync"),
            asyncio.create_task(self._config_watch_loop(), name="config_watcher"),
        ]

        # If in a cluster, start gossip
        if collector_settings.cluster_id:
            from monctl_collector.cluster.manager import ClusterManager
            self.cluster_manager = ClusterManager()
            self._tasks.append(
                asyncio.create_task(self.cluster_manager.run(), name="cluster_gossip")
            )

        logger.info("collector_started", tasks=[t.get_name() for t in self._tasks])

        # Wait for all tasks
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("collector_tasks_cancelled")

    async def stop(self):
        """Stop the collector daemon gracefully."""
        if not self.running:
            return
        self.running = False
        logger.info("collector_stopping")

        self.app_scheduler.shutdown()

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("collector_stopped")

    async def _heartbeat_loop(self):
        """Send periodic heartbeats to central."""
        import httpx
        from monctl_common.utils import utc_now

        async with httpx.AsyncClient(verify=collector_settings.verify_ssl) as client:
            while self.running:
                try:
                    response = await client.post(
                        f"{collector_settings.central_url}/v1/collectors/{collector_settings.collector_id}/heartbeat",
                        json={
                            "collector_id": collector_settings.collector_id,
                            "timestamp": utc_now().isoformat(),
                            "config_version": self.config_sync.current_config_version,
                        },
                        headers={"Authorization": f"Bearer {collector_settings.api_key}"},
                        timeout=10,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("config_changed"):
                            logger.info("config_changed_detected", new_version=data.get("config_version"))
                            config = await self.config_sync.fetch_config()
                            if config:
                                await self.app_scheduler.apply_config(config)
                    else:
                        logger.warning("heartbeat_failed", status=response.status_code)
                except Exception as e:
                    logger.warning("heartbeat_error", error=str(e))

                await asyncio.sleep(collector_settings.heartbeat_interval)

    async def _config_watch_loop(self):
        """Periodically re-apply config to the scheduler (catches slow config drift)."""
        while self.running:
            await asyncio.sleep(60)
            if self.config_sync.current_config:
                await self.app_scheduler.apply_config(self.config_sync.current_config)
