"""cache-node entrypoint — the collector brain.

Responsibilities:
  - Syncs job definitions from central (delta-sync every 60s)
  - Assigns jobs to registered poll-workers (app-affinity)
  - Serves gRPC API for local poll-workers
  - Serves HTTP status/health server (port 50052)

Configuration (in priority order):
  1. config.yaml (path via MONCTL_CONFIG or /etc/monctl/config.yaml)
  2. Environment variables (MONCTL_*)

Required env vars (if no config.yaml):
  MONCTL_NODE_ID         — unique name for this cache-node
  MONCTL_CENTRAL_URL     — e.g. https://central.example.com
  MONCTL_CENTRAL_API_KEY — API key for /api/v1/* endpoints
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import signal
import socket
import time
from datetime import datetime, timezone

import aiohttp
from aiohttp import web
import structlog

from monctl_collector.cache.local_cache import LocalCache
from monctl_collector.central.api_client import CentralAPIClient
from monctl_collector.central.credentials import CredentialManager
from monctl_collector.config import CollectorConfig, load_config
from monctl_collector.jobs.scheduler import JobScheduler
from monctl_collector.cache.app_cache_sync import AppCacheSyncLoop
from monctl_collector.peer.server import CollectorPeerServicer, start_server
from monctl_collector.upgrade_agent import UpgradeAgent
from monctl_collector.central.ws_client import WebSocketClient
from monctl_collector.central.ws_handlers import (
    init_handlers,
    handle_poll_device,
    handle_config_reload,
    handle_health_check,
    handle_module_update,
    handle_docker_health,
    handle_docker_logs,
)
from monctl_collector.central.log_shipper import LogShipper

logger = structlog.get_logger()


async def run(cfg: CollectorConfig) -> None:
    node_id = cfg.node_id or socket.gethostname()
    listen_addr = f"{cfg.listen_address}:{cfg.listen_port}"
    start_time = time.time()

    logger.info("cache_node_starting", node_id=node_id, listen=listen_addr)

    # ── Infrastructure ────────────────────────────────────────────────────────
    local_cache = LocalCache(cfg.cache.db_path)
    await local_cache.open()

    central_client = CentralAPIClient(
        cfg.central.url,
        api_key=cfg.central.api_key,
        timeout=cfg.central.timeout,
        verify_ssl=cfg.central.verify_ssl,
    )
    await central_client.open()

    encryption_key = CredentialManager.make_key()
    credential_manager = CredentialManager(
        central_client=central_client,
        local_cache=local_cache,
        encryption_key=encryption_key,
        refresh_interval=cfg.central.credential_refresh,
    )

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler = JobScheduler(
        node_id=node_id,
        local_cache=local_cache,
        central_client=central_client,
        config=cfg.scheduling,
        sync_interval=float(cfg.central.sync_interval),
        collector_id=cfg.collector_id,
    )

    # ── gRPC server ───────────────────────────────────────────────────────────
    servicer = CollectorPeerServicer(
        local_cache=local_cache,
        job_scheduler=scheduler,
        credential_manager=credential_manager,
        node_id=node_id,
    )
    grpc_server = await start_server(servicer, listen_addr)
    logger.info("grpc_server_started", address=listen_addr)

    # ── Wait for central ──────────────────────────────────────────────────────
    await central_client.wait_for_central(max_wait=120, check_interval=5)

    # ── Status HTTP server (port 50052) ───────────────────────────────────────
    status_server = await _start_status_server(
        node_id=node_id,
        scheduler=scheduler,
        central_url=cfg.central.url,
        collector_id=cfg.collector_id,
        verify_ssl=cfg.central.verify_ssl,
        start_time=start_time,
        port=int(os.environ.get("MONCTL_STATUS_PORT", "50052")),
    )

    # ── Start background tasks ────────────────────────────────────────────────
    await scheduler.start()
    asyncio.create_task(_cache_cleanup_loop(local_cache, cfg.cache.cleanup_interval))
    asyncio.create_task(_heartbeat_loop(central_client, node_id, scheduler))

    # App cache sync loop (push dirty entries to central, pull updates)
    app_cache_sync = AppCacheSyncLoop(
        local_cache=local_cache,
        central_client=central_client,
        node_id=node_id,
    )
    await app_cache_sync.start()

    # Upgrade agent (polls central for available upgrades)
    upgrade_agent = UpgradeAgent(
        central_url=cfg.central.url,
        api_key=cfg.central.api_key,
        collector_id=cfg.collector_id or "",
        verify_ssl=cfg.central.verify_ssl,
        check_interval=60,
    )
    await upgrade_agent.start()

    # ── WebSocket command channel ─────────────────────────────────────────────
    sidecar_url = os.environ.get("MONCTL_DOCKER_STATS_URL", "http://localhost:9100")
    ws_client = WebSocketClient(
        central_url=cfg.central.url,
        api_key=cfg.central.api_key,
        node_id=node_id,
        verify_ssl=cfg.central.verify_ssl,
        collector_id=cfg.collector_id or "",
    )

    init_handlers(
        scheduler=scheduler,
        central_client=central_client,
        sidecar_url=sidecar_url,
    )

    ws_client.register_handler("poll_device", handle_poll_device)
    ws_client.register_handler("config_reload", handle_config_reload)
    ws_client.register_handler("health_check", handle_health_check)
    ws_client.register_handler("module_update", handle_module_update)
    ws_client.register_handler("docker_health", handle_docker_health)
    ws_client.register_handler("docker_logs", handle_docker_logs)

    ws_task = asyncio.create_task(ws_client.run())

    # ── Log shipper ───────────────────────────────────────────────────────────
    host_label = os.environ.get("MONCTL_HOST_LABEL", node_id)
    log_level_filter = os.environ.get("MONCTL_LOG_LEVEL_FILTER", "INFO")
    log_shipper = LogShipper(
        central_client=central_client,
        collector_id=cfg.collector_id or "",
        collector_name=node_id,
        host_label=host_label,
        sidecar_url=sidecar_url,
        log_level_filter=log_level_filter,
    )
    log_shipper_task = asyncio.create_task(log_shipper.run())

    logger.info("cache_node_ready", node_id=node_id)

    # ── Shutdown handler ──────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("shutdown_signal_received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("cache_node_shutting_down")
    await log_shipper.stop()
    await ws_client.stop()
    await upgrade_agent.stop()
    await app_cache_sync.stop()
    await scheduler.stop()
    if status_server:
        await status_server.cleanup()
    grpc_server.stop(grace=5)
    await central_client.close()
    await local_cache.close()
    logger.info("cache_node_stopped")


# ── System resource helpers ──────────────────────────────────────────────────

def _read_system_resources() -> dict:
    """Read CPU/memory/disk from /proc (works inside container)."""
    result: dict = {}

    # CPU load
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()[:3]
            result["cpu_load"] = [float(x) for x in parts]
            result["cpu_count"] = os.cpu_count() or 1
    except Exception:
        result["cpu_load"] = []
        result["cpu_count"] = 0

    # Memory
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split()
                key = parts[0].rstrip(":")
                if key in ("MemTotal", "MemAvailable", "MemFree"):
                    mem[key] = int(parts[1])
        total_mb = mem.get("MemTotal", 0) / 1024
        avail_mb = mem.get("MemAvailable", mem.get("MemFree", 0)) / 1024
        result["memory_total_mb"] = round(total_mb)
        result["memory_used_mb"] = round(total_mb - avail_mb)
    except Exception:
        result["memory_total_mb"] = 0
        result["memory_used_mb"] = 0

    # Disk
    try:
        st = os.statvfs("/data")
        total = st.f_blocks * st.f_frsize / (1024**3)
        free = st.f_bfree * st.f_frsize / (1024**3)
        result["disk_total_gb"] = round(total, 1)
        result["disk_used_gb"] = round(total - free, 1)
    except Exception:
        result["disk_total_gb"] = 0
        result["disk_used_gb"] = 0

    return result


# ── Status server ────────────────────────────────────────────────────────────

async def _start_status_server(
    node_id: str,
    scheduler: JobScheduler,
    central_url: str,
    collector_id: str | None,
    verify_ssl: bool,
    start_time: float,
    port: int = 50052,
) -> web.AppRunner | None:
    """Start HTTP status/health server on port 50052."""
    try:
        app = web.Application()

        # ── GET /status ───────────────────────────────────────────────────────

        async def _handle_status(request: web.Request) -> web.Response:
            load_info = scheduler.get_current_load_info()
            body = {
                "node_id": node_id,
                "load": {
                    "total_jobs": load_info.total_jobs,
                    "load_score": load_info.load_score,
                },
            }
            return web.json_response(body)

        # ── GET /health ───────────────────────────────────────────────────────

        async def _handle_health(request: web.Request) -> web.Response:
            workers = []
            for wid, wreg in scheduler.get_registered_workers().items():
                workers.append({
                    "worker_id": wid,
                    "last_seen": datetime.fromtimestamp(
                        wreg.last_seen, tz=timezone.utc
                    ).isoformat(),
                    "job_count": wreg.job_count,
                })

            load_info = scheduler.get_current_load_info()

            central_ok = False
            try:
                connector = aiohttp.TCPConnector(ssl=verify_ssl)
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(
                    connector=connector, timeout=timeout
                ) as session:
                    async with session.get(
                        f"{central_url.rstrip('/')}/v1/health"
                    ) as resp:
                        central_ok = resp.status == 200
            except Exception:
                pass

            system = _read_system_resources()

            body = {
                "node_id": node_id,
                "central_url": central_url,
                "central_connected": central_ok,
                "collector_id": collector_id or None,
                "registration_status": "ACTIVE" if collector_id else "NOT_REGISTERED",
                "uptime_seconds": int(time.time() - start_time),
                "workers": workers,
                "load": {
                    "total_jobs": load_info.total_jobs,
                    "load_score": round(load_info.load_score, 2),
                    "worker_count": load_info.worker_count,
                    "deadline_miss_rate": round(load_info.deadline_miss_rate, 3),
                },
                "system": system,
            }
            return web.json_response(body)

        # ── Register routes ───────────────────────────────────────────────────

        app.router.add_get("/status", _handle_status)
        app.router.add_get("/health", _handle_health)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info("status_server_started", port=port)
        return runner
    except Exception as exc:
        logger.warning("status_server_failed", error=str(exc))
        return None


async def _get_container_states() -> dict[str, str] | None:
    """Query Docker socket for sibling container states.

    Returns a dict like {"cache-node": "running", "poll-worker-1": "running"}
    or None if the Docker socket is not available.
    """
    docker_socket = "/var/run/docker.sock"
    if not os.path.exists(docker_socket):
        return None
    try:
        connector = aiohttp.UnixConnector(path=docker_socket)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                "http://localhost/containers/json?all=true",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                if resp.status != 200:
                    return None
                containers = await resp.json()
                states: dict[str, str] = {}
                for c in containers:
                    name = c.get("Names", [""])[0].lstrip("/")
                    state = c.get("State", "unknown")
                    if any(svc in name for svc in ["cache-node", "poll-worker", "forwarder"]):
                        states[name] = state
                return states if states else None
    except Exception:
        return None


def _get_queue_stats(scheduler: JobScheduler) -> dict | None:
    """Gather queue and execution stats from the scheduler."""
    try:
        now = time.time()
        one_hour_ago = now - 3600
        overdue = 0
        errored_last_hour = 0
        exec_times: list[float] = []

        for profile in scheduler._profiles.values():
            if profile.next_deadline > 0 and profile.next_deadline < now:
                overdue += 1
            if profile.error_count > 0 and profile.last_run > one_hour_ago:
                errored_last_hour += profile.error_count
            if profile.last_execution_time > 0:
                exec_times.append(profile.last_execution_time * 1000)

        avg_exec_ms = round(sum(exec_times) / len(exec_times), 1) if exec_times else 0
        max_exec_ms = round(max(exec_times), 1) if exec_times else 0

        return {
            "pending_results": 0,
            "jobs_overdue": overdue,
            "jobs_errored_last_hour": errored_last_hour,
            "avg_execution_ms": avg_exec_ms,
            "max_execution_ms": max_exec_ms,
        }
    except Exception:
        return None


async def _heartbeat_loop(
    central_client: CentralAPIClient,
    node_id: str,
    scheduler: JobScheduler,
    interval: int = 30,
) -> None:
    """Send periodic heartbeats to central so the collector stays ACTIVE."""
    while True:
        try:
            load_info = dataclasses.asdict(scheduler.get_current_load_info())
            container_states = await _get_container_states()
            queue_stats = _get_queue_stats(scheduler)

            ok = await central_client.post_heartbeat(
                node_id,
                load_info,
                container_states=container_states,
                queue_stats=queue_stats,
            )
            if ok:
                logger.debug("heartbeat_sent", node_id=node_id,
                             containers=bool(container_states),
                             queue=bool(queue_stats))
            else:
                logger.warning("heartbeat_rejected", node_id=node_id)
        except Exception as exc:
            logger.warning("heartbeat_error", error=str(exc))
        await asyncio.sleep(interval)


async def _cache_cleanup_loop(cache: LocalCache, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            deleted = await cache.cleanup_expired()
            if deleted:
                logger.debug("cache_cleanup", deleted=deleted)
        except Exception as exc:
            logger.warning("cache_cleanup_error", error=str(exc))


def main() -> None:
    import logging
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
