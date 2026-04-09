"""Control API — HTTP API for runtime management of the simulator."""
from __future__ import annotations

import json
import logging

from aiohttp import web

from simulator.config import FailureMode
from simulator.snmp_simulator import SnmpDeviceHandler

logger = logging.getLogger(__name__)


def build_control_app(handlers: list[SnmpDeviceHandler]) -> web.Application:
    """Build the control API aiohttp application."""
    app = web.Application()
    handler_map = {h.device.name: h for h in handlers}

    async def list_devices(request: web.Request) -> web.Response:
        devices = []
        for h in handlers:
            d = h.device
            devices.append({
                "name": d.name,
                "type": d.device_type,
                "snmp_port": d.snmp_port,
                "http_port": d.http_port,
                "tcp_ports": d.tcp_ports,
                "interfaces": len(d.interfaces),
                "failure_mode": d.failure.mode,
                "community": d.community,
                "requests": h.stats["requests"],
                "errors_injected": h.stats["errors_injected"],
            })
        return web.json_response({"devices": devices, "total": len(devices)})

    async def get_device(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        h = handler_map.get(name)
        if not h:
            return web.json_response({"error": f"Device '{name}' not found"}, status=404)
        d = h.device
        return web.json_response({
            "name": d.name,
            "type": d.device_type,
            "snmp_port": d.snmp_port,
            "sys_object_id": d.sys_object_id,
            "sys_descr": d.sys_descr,
            "failure_mode": d.failure.mode,
            "requests": h.stats["requests"],
            "interfaces": [
                {
                    "if_index": i.if_index,
                    "if_name": i.if_name,
                    "if_oper_status": i.if_oper_status,
                    "traffic_profile": i.traffic_profile,
                    "in_octets": i.in_octets_64,
                    "out_octets": i.out_octets_64,
                    "in_errors": i.in_errors,
                }
                for i in d.interfaces
            ],
        })

    async def set_failure(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        h = handler_map.get(name)
        if not h:
            return web.json_response({"error": f"Device '{name}' not found"}, status=404)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        mode = body.get("mode", "normal")
        h.device.failure = FailureMode(
            mode=mode,
            delay_ms=body.get("delay_ms", 3000),
            drop_rate=body.get("drop_rate", 0.3),
            flap_period_s=body.get("flap_period_s", 300),
        )
        logger.info("Failure mode changed: %s → %s", name, mode)
        return web.json_response({"status": "ok", "device": name, "failure_mode": mode})

    async def get_stats(request: web.Request) -> web.Response:
        total_requests = sum(h.stats["requests"] for h in handlers)
        total_errors = sum(h.stats["errors_injected"] for h in handlers)
        return web.json_response({
            "total_devices": len(handlers),
            "total_requests": total_requests,
            "total_errors_injected": total_errors,
            "devices_by_failure_mode": _count_by_mode(handlers),
        })

    app.router.add_get("/api/devices", list_devices)
    app.router.add_get("/api/device/{name}", get_device)
    app.router.add_post("/api/device/{name}/failure", set_failure)
    app.router.add_get("/api/stats", get_stats)
    return app


def _count_by_mode(handlers: list[SnmpDeviceHandler]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for h in handlers:
        mode = h.device.failure.mode
        counts[mode] = counts.get(mode, 0) + 1
    return counts


async def start_control_api(
    handlers: list[SnmpDeviceHandler], port: int = 9999,
) -> web.AppRunner:
    """Start the control API HTTP server."""
    app = build_control_app(handlers)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Control API started on http://0.0.0.0:%d", port)
    return runner
