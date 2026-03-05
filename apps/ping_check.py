#!/usr/bin/env python3
"""Ping monitoring app — checks reachability of a host via ICMP ping.

Protocol:
  stdin:  JSON config {"host": "192.168.1.1", "count": 3, "timeout": 2}
  stdout: JSON result with check_result (including performance_data) and metrics
  exit:   0=OK, 2=CRITICAL

Config keys (device address is injected as "host" when a device is linked):
  host        str   Target IP or hostname (default: "localhost")
  count       int   Number of ping packets to send (default: 3)
  timeout     int   Per-ping timeout in seconds (default: 2)

Performance data (always present in check_result.performance_data):
  rtt_ms      Average round-trip time in milliseconds (0 if unreachable)
  reachable   1.0 if ping succeeded, 0.0 if it failed
"""
from __future__ import annotations

import json
import platform
import re
import subprocess
import sys


def ping(host: str, count: int, timeout: int) -> tuple[bool, float | None, str]:
    """Run system ping and return (success, avg_rtt_ms, output_line).

    Returns:
        (True, rtt_ms, description) on success
        (False, None, error_msg) on failure
    """
    system = platform.system()

    if system == "Windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
    elif system == "Darwin":
        # macOS: -c count, -W timeout in milliseconds, -q quiet
        cmd = ["ping", "-c", str(count), "-W", str(timeout * 1000), "-q", host]
    else:
        # Linux: -c count, -W timeout in seconds, -q quiet
        cmd = ["ping", "-c", str(count), "-W", str(timeout), "-q", host]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout * count + 2,
        )
    except subprocess.TimeoutExpired:
        return False, None, f"ping timed out after {timeout * count + 2}s"
    except FileNotFoundError:
        return False, None, "ping command not found"

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip() or "ping failed (no response)"
        return False, None, err

    # Parse average RTT from ping summary line
    # macOS/Linux: "round-trip min/avg/max/stddev = 0.041/0.041/0.041/0.000 ms"
    # or:          "rtt min/avg/max/mdev = 0.041/0.041/0.041/0.000 ms"
    output = result.stdout
    rtt_ms = None

    match = re.search(r"(?:round-trip|rtt)[^=]*=\s*[\d.]+/([\d.]+)/", output)
    if match:
        rtt_ms = float(match.group(1))
    else:
        # Fallback: look for any float sequence after "/"
        match = re.search(r"=\s*[\d.]+/([\d.]+)", output)
        if match:
            rtt_ms = float(match.group(1))

    return True, rtt_ms, output.strip().split("\n")[-1]


def main() -> None:
    raw = sys.stdin.read().strip()
    config: dict = json.loads(raw) if raw else {}

    host: str = config.get("host", "localhost")
    count: int = int(config.get("count", 3))
    timeout: int = int(config.get("timeout", 2))

    success, rtt_ms, detail = ping(host, count, timeout)

    if success:
        state = 0  # OK
        rtt_display = f"{rtt_ms:.3f}ms" if rtt_ms is not None else "unknown RTT"
        output = f"PING OK — {host} reachable, avg RTT {rtt_display}"
        performance_data = {
            "rtt_ms": rtt_ms if rtt_ms is not None else 0.0,
            "reachable": 1.0,
        }
        metrics = [
            {"name": "ping_reachable", "value": 1.0, "labels": {"host": host}},
        ]
        if rtt_ms is not None:
            metrics.append({
                "name": "ping_rtt_ms",
                "value": rtt_ms,
                "labels": {"host": host},
                "unit": "ms",
            })
    else:
        state = 2  # CRITICAL
        output = f"PING CRITICAL — {host} unreachable: {detail}"
        performance_data = {
            "rtt_ms": 0.0,
            "reachable": 0.0,
        }
        metrics = [
            {"name": "ping_reachable", "value": 0.0, "labels": {"host": host}},
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
