#!/usr/bin/env python3
"""TCP port check monitoring app — checks whether a TCP port is open and measures connect time.

Protocol:
  stdin:  JSON config {"host": "192.168.1.1", "port": 22, "timeout": 5}
  stdout: JSON result with check_result (including performance_data) and metrics
  exit:   0=OK, 2=CRITICAL

Config keys (device address is injected as "host" when a device is linked):
  host     str   Target IP or hostname (default: "localhost")
  port     int   TCP port number to connect to (required)
  timeout  float Connection timeout in seconds (default: 5)

Performance data (always present in check_result.performance_data):
  rtt_ms     TCP connect time in milliseconds (0 if unreachable)
  reachable  1.0 if port is open, 0.0 if not
"""
from __future__ import annotations

import json
import socket
import sys
import time


def check_port(host: str, port: int, timeout: float) -> tuple[bool, float | None, str]:
    """Attempt a TCP connection and return (success, rtt_ms, detail).

    Returns:
        (True, rtt_ms, description) on success
        (False, None, error_msg) on failure
    """
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            rtt_ms = (time.monotonic() - start) * 1000
            return True, rtt_ms, f"TCP connection to {host}:{port} succeeded"
    except OSError as exc:
        return False, None, str(exc)
    except Exception as exc:
        return False, None, str(exc)


def main() -> None:
    raw = sys.stdin.read().strip()
    config: dict = json.loads(raw) if raw else {}

    host: str = config.get("host", "localhost")
    port: int = int(config.get("port", 80))
    timeout: float = float(config.get("timeout", 5))

    success, rtt_ms, detail = check_port(host, port, timeout)

    if success:
        state = 0  # OK
        rtt_display = f"{rtt_ms:.3f}ms" if rtt_ms is not None else "unknown RTT"
        output = f"PORT OK — {host}:{port} open, RTT {rtt_display}"
        performance_data = {
            "rtt_ms": rtt_ms if rtt_ms is not None else 0.0,
            "reachable": 1.0,
        }
        metrics = [
            {"name": "port_reachable", "value": 1.0, "labels": {"host": host, "port": str(port)}},
            {"name": "port_rtt_ms", "value": rtt_ms, "labels": {"host": host, "port": str(port)}, "unit": "ms"},
        ]
    else:
        state = 2  # CRITICAL
        output = f"PORT CRITICAL — {host}:{port} unreachable: {detail}"
        performance_data = {
            "rtt_ms": 0.0,
            "reachable": 0.0,
        }
        metrics = [
            {"name": "port_reachable", "value": 0.0, "labels": {"host": host, "port": str(port)}},
        ]

    result = {
        "check_result": {
            "state": state,
            "output": output,
            "performance_data": performance_data,
        },
        "metrics": metrics,
    }

    print(json.dumps(result))
    sys.exit(state)


if __name__ == "__main__":
    main()
