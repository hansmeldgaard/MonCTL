"""TCP simulator — multi-port TCP listener for port check testing."""
from __future__ import annotations

import asyncio
import logging

from simulator.config import DeviceProfile, SimulatorConfig

logger = logging.getLogger(__name__)


class TcpHandler:
    """Handles TCP connections for a simulated device port."""

    def __init__(self, device: DeviceProfile, port: int):
        self.device = device
        self.port = port
        self.connections = 0

    async def handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        self.connections += 1
        fm = self.device.failure
        try:
            if fm.mode == "slow":
                await asyncio.sleep(fm.delay_ms / 1000.0)
            elif fm.mode == "timeout":
                await asyncio.sleep(300)
                return
        finally:
            writer.close()
            await writer.wait_closed()


async def start_tcp_simulator(config: SimulatorConfig) -> list[asyncio.Server]:
    """Start TCP listeners for all devices that have tcp_ports configured."""
    servers: list[asyncio.Server] = []

    for device in config.devices:
        for port in device.tcp_ports:
            handler = TcpHandler(device, port)
            server = await asyncio.start_server(
                handler.handle_connection, "0.0.0.0", port,
            )
            servers.append(server)
            logger.info("TCP listener started: %s on TCP :%d", device.name, port)

    if servers:
        logger.info("TCP simulator ready: %d listeners", len(servers))
    else:
        logger.info("TCP simulator: no devices with tcp_ports configured")

    return servers
