"""HTTP simulator — multi-port web server for simulated devices."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time

from aiohttp import web

from simulator.config import DeviceProfile, SimulatorConfig

logger = logging.getLogger(__name__)


def _build_app(device: DeviceProfile) -> web.Application:
    """Build an aiohttp Application for a single simulated HTTP device."""
    app = web.Application()

    async def handle_root(request: web.Request) -> web.Response:
        fm = device.failure
        if fm.mode == "timeout":
            await asyncio.sleep(300)  # effectively hang
            return web.Response(status=504)
        if fm.mode == "slow":
            await asyncio.sleep(fm.delay_ms / 1000.0)
        if fm.mode == "partial" and random.random() < fm.drop_rate:
            return web.Response(status=500, text="Internal Server Error")
        if fm.mode == "flapping":
            cycle = time.time() % fm.flap_period_s
            if cycle > fm.flap_period_s / 2:
                return web.Response(status=503, text="Service Unavailable")

        body = json.dumps({
            "status": "ok",
            "device": device.name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "uptime_seconds": int(time.time() - device._start_time),
        })
        return web.Response(
            status=200, text=body, content_type="application/json",
        )

    async def handle_health(request: web.Request) -> web.Response:
        return web.Response(status=200, text="OK")

    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    return app


async def start_http_simulator(config: SimulatorConfig) -> list[web.AppRunner]:
    """Start HTTP servers for all devices that have http_port configured."""
    runners: list[web.AppRunner] = []

    for device in config.devices:
        if device.http_port is None:
            continue

        app = _build_app(device)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", device.http_port)
        await site.start()
        runners.append(runner)

        logger.info("HTTP server started: %s on TCP :%d", device.name, device.http_port)

    if runners:
        logger.info("HTTP simulator ready: %d endpoints", len(runners))
    else:
        logger.info("HTTP simulator: no devices with http_port configured")

    return runners
