"""cache-node entrypoint — the collector brain.

Responsibilities:
  - Syncs job definitions from central (delta-sync every 60s)
  - Assigns jobs to registered poll-workers (app-affinity)
  - Serves gRPC API for local poll-workers
  - Serves HTTP management API (port 50052) for CLI tool

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
import hashlib
import json
import os
import signal
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from aiohttp import web
import structlog
import yaml

from monctl_collector.cache.local_cache import LocalCache
from monctl_collector.central.api_client import CentralAPIClient
from monctl_collector.central.credentials import CredentialManager
from monctl_collector.config import CollectorConfig, load_config
from monctl_collector.jobs.scheduler import JobScheduler
from monctl_collector.peer.server import CollectorPeerServicer, start_server

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
        central_client=central_client,
        cfg=cfg,
        start_time=start_time,
        port=int(os.environ.get("MONCTL_STATUS_PORT", "50052")),
    )

    # ── Start background tasks ────────────────────────────────────────────────
    await scheduler.start()
    asyncio.create_task(_cache_cleanup_loop(local_cache, cfg.cache.cleanup_interval))
    asyncio.create_task(_heartbeat_loop(central_client, node_id, scheduler))

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


# ── Fingerprint helpers ──────────────────────────────────────────────────────

def _generate_fingerprint() -> str:
    """Generate a deterministic machine fingerprint.

    SHA256(/etc/machine-id + ":" + primary-MAC)[:32] formatted as
    XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX.
    """
    try:
        with open("/etc/machine-id") as f:
            machine_id = f.read().strip()
    except OSError:
        machine_id = socket.gethostname()

    mac = uuid.getnode()
    mac_str = ":".join(f"{(mac >> (8 * i)) & 0xff:02x}" for i in reversed(range(6)))
    raw = hashlib.sha256(f"{machine_id}:{mac_str}".encode()).hexdigest()[:32]
    return "-".join(raw[i:i + 4] for i in range(0, 32, 4))


def _get_local_ips() -> list[str]:
    """Get non-loopback IPs."""
    ips: list[str] = []
    try:
        import subprocess
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5
        )
        ips = result.stdout.strip().split()
    except Exception:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips = [s.getsockname()[0]]
            s.close()
        except Exception:
            pass
    return ips


def _get_setup_path() -> Path:
    return Path(os.environ.get("MONCTL_SETUP_YAML", "/etc/monctl/setup.yaml"))


def _read_setup_yaml() -> dict:
    setup_path = _get_setup_path()
    if setup_path.exists():
        return yaml.safe_load(setup_path.read_text()) or {}
    return {}


def _write_setup_yaml(
    collector_id: str, api_key: str, central_url: str, fingerprint: str
) -> None:
    """Write setup.yaml — mounted into container from host."""
    setup_path = _get_setup_path()
    data = {
        "collector_id": collector_id,
        "api_key": api_key,
        "central_url": central_url,
        "fingerprint": fingerprint,
    }
    setup_path.parent.mkdir(parents=True, exist_ok=True)
    setup_path.write_text(yaml.safe_dump(data))
    logger.info("setup_yaml_written", path=str(setup_path))


# ── Status server ────────────────────────────────────────────────────────────

async def _start_status_server(
    node_id: str,
    scheduler: JobScheduler,
    central_client: CentralAPIClient,
    cfg: CollectorConfig,
    start_time: float,
    port: int = 50052,
) -> web.AppRunner | None:
    """Start HTTP management server on port 50052 for CLI queries."""
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
                async with central_client._session.get(
                    f"{central_client._base_url}/v1/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    central_ok = resp.status == 200
            except Exception:
                pass

            system = _read_system_resources()

            body = {
                "node_id": node_id,
                "central_url": cfg.central.url,
                "central_connected": central_ok,
                "collector_id": cfg.collector_id or None,
                "registration_status": "ACTIVE" if cfg.collector_id else "NOT_REGISTERED",
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

        # ── POST /setup/register ──────────────────────────────────────────────

        async def _handle_register(request: web.Request) -> web.Response:
            try:
                body = await request.json()
            except Exception:
                return web.json_response(
                    {"status": "error", "message": "Invalid JSON"}, status=400
                )

            url = body.get("central_url", "").strip()
            code = body.get("registration_code", "").strip()
            if not url or not code:
                return web.json_response(
                    {"status": "error", "message": "central_url and registration_code required"},
                    status=400,
                )

            fingerprint = _generate_fingerprint()
            hostname = socket.gethostname()
            ip_addresses = _get_local_ips()

            try:
                verify_ssl = cfg.central.verify_ssl
                connector = aiohttp.TCPConnector(ssl=verify_ssl)
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    reg_url = f"{url.rstrip('/')}/v1/collectors/register"
                    payload = {
                        "hostname": hostname,
                        "registration_code": code.upper(),
                        "fingerprint": fingerprint,
                        "ip_addresses": ip_addresses,
                    }
                    async with session.post(reg_url, json=payload) as resp:
                        if resp.status in (200, 201):
                            data = await resp.json()
                            result_data = data.get("data", data)
                            collector_id = result_data.get("collector_id", "")
                            api_key = result_data.get("api_key", "")

                            _write_setup_yaml(collector_id, api_key, url, fingerprint)

                            return web.json_response({
                                "status": "registered",
                                "collector_id": collector_id,
                                "registration_status": result_data.get("status", "PENDING"),
                                "message": "Registered — waiting for admin approval",
                            })
                        else:
                            error_body = await resp.text()
                            return web.json_response(
                                {"status": "error", "message": f"Central returned {resp.status}: {error_body[:200]}"},
                                status=502,
                            )
            except Exception as exc:
                return web.json_response(
                    {"status": "error", "message": f"Registration failed: {exc}"},
                    status=502,
                )

        # ── POST /setup/configure ─────────────────────────────────────────────

        async def _handle_configure(request: web.Request) -> web.Response:
            try:
                body = await request.json()
            except Exception:
                return web.json_response(
                    {"status": "error", "message": "Invalid JSON"}, status=400
                )

            central_url = body.get("central_url")
            api_key = body.get("api_key")

            if not central_url and not api_key:
                return web.json_response(
                    {"status": "error", "message": "Provide central_url and/or api_key"},
                    status=400,
                )

            existing = _read_setup_yaml()
            if central_url:
                existing["central_url"] = central_url
            if api_key:
                existing["api_key"] = api_key

            setup_path = _get_setup_path()
            setup_path.write_text(yaml.safe_dump(existing))

            return web.json_response({
                "status": "ok",
                "message": "Configuration updated — container restart required",
                "restart_hint": "docker compose -f /opt/monctl/collector/docker-compose.yml restart",
            })

        # ── GET /setup/check ──────────────────────────────────────────────────

        async def _handle_setup_check(request: web.Request) -> web.Response:
            setup = _read_setup_yaml()
            collector_id = setup.get("collector_id") or cfg.collector_id
            central_url = setup.get("central_url") or cfg.central.url

            central_ok = False
            reg_status = "NOT_REGISTERED"
            if central_url:
                try:
                    verify = cfg.central.verify_ssl
                    connector = aiohttp.TCPConnector(ssl=verify)
                    timeout = aiohttp.ClientTimeout(total=5)
                    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                        async with session.get(f"{central_url.rstrip('/')}/v1/health") as resp:
                            central_ok = resp.status == 200
                except Exception:
                    pass

            if collector_id:
                reg_status = "ACTIVE" if central_ok else "REGISTERED_NOT_CONNECTED"

            return web.json_response({
                "collector_id": collector_id or None,
                "registration_status": reg_status,
                "central_url": central_url or None,
                "central_reachable": central_ok,
            })

        # ── Register routes ───────────────────────────────────────────────────

        app.router.add_get("/status", _handle_status)
        app.router.add_get("/health", _handle_health)
        app.router.add_post("/setup/register", _handle_register)
        app.router.add_post("/setup/configure", _handle_configure)
        app.router.add_get("/setup/check", _handle_setup_check)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info("status_server_started", port=port)
        return runner
    except Exception as exc:
        logger.warning("status_server_failed", error=str(exc))
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
            ok = await central_client.post_heartbeat(node_id, load_info)
            if ok:
                logger.debug("heartbeat_sent", node_id=node_id)
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
