"""MonCTL Device Simulator — entry point.

Starts all simulators (SNMP, HTTP, TCP) and the control API in a single
asyncio event loop.

Usage:
    python -m simulator                           # uses simulator/config.yaml
    python -m simulator --config /path/to/config.yaml
    SIM_CONFIG=/path/to/config.yaml python -m simulator
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("simulator")


async def run(config_path: str) -> None:
    from simulator.config import load_config
    from simulator.snmp_simulator import start_snmp_simulator
    from simulator.http_simulator import start_http_simulator
    from simulator.tcp_simulator import start_tcp_simulator
    from simulator.control_api import start_control_api

    logger.info("Loading config from %s", config_path)
    config = load_config(config_path)

    logger.info("Starting simulator: %d devices, host=%s",
                len(config.devices), config.host_ip)
    logger.info("  SNMP ports: %d-%d",
                config.snmp_port_start,
                config.snmp_port_start + len(config.devices) - 1)

    # Start all simulators
    snmp_handlers = await start_snmp_simulator(config)
    await start_http_simulator(config)
    await start_tcp_simulator(config)
    await start_control_api(snmp_handlers, config.control_port)

    logger.info("=" * 60)
    logger.info("Simulator fully started — %d devices ready", len(config.devices))
    logger.info("Control API: http://0.0.0.0:%d/api/devices", config.control_port)
    logger.info("=" * 60)

    # Wait forever (or until signal)
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    logger.info("Shutting down...")


def main() -> None:
    parser = argparse.ArgumentParser(description="MonCTL Device Simulator")
    default_config = os.environ.get(
        "SIM_CONFIG",
        os.path.join(os.path.dirname(__file__), "config.yaml"),
    )
    parser.add_argument("--config", default=default_config, help="Path to config.yaml")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        logger.error("Config file not found: %s", args.config)
        sys.exit(1)

    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
