"""Test harness for MonCTL app developers.

Provides utilities to test monitoring apps locally without a running collector.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime

from monctl_common.constants import CheckState
from monctl_common.schemas.metrics import CheckResult

from monctl_sdk.base import EventSource, MonitoringApp


def run_app_sync(app: MonitoringApp, config: dict) -> CheckResult:
    """Run a monitoring app synchronously (for testing).

    Args:
        app: An instance of a MonitoringApp subclass.
        config: Configuration dict to pass to the app.

    Returns:
        CheckResult from the app execution.
    """
    app.validate_config(config)
    return asyncio.run(app.execute(config))


def run_app_cli(app: MonitoringApp) -> None:
    """Run a monitoring app from the command line (reads config from stdin).

    This is useful for testing apps as if they were script-based:
        echo '{"url": "https://example.com"}' | python -m my_app

    Args:
        app: An instance of a MonitoringApp subclass.
    """
    config_input = sys.stdin.read().strip()
    config = json.loads(config_input) if config_input else {}

    try:
        app.validate_config(config)
        result = asyncio.run(app.execute(config))
    except Exception as e:
        result = CheckResult(
            state=CheckState.UNKNOWN,
            output=f"App error: {e}",
        )

    output = {
        "status": result.state.name,
        "message": result.output,
        "metrics": [m.model_dump() for m in result.metrics],
        "check_result": {
            "state": result.state.value,
            "output": result.output,
        },
    }
    print(json.dumps(output, indent=2, default=str))
    sys.exit(result.state.value)


def format_result(result: CheckResult) -> str:
    """Format a CheckResult for human-readable display."""
    state_name = CheckState(result.state).name
    lines = [f"[{state_name}] {result.output}"]
    if result.metrics:
        lines.append(f"  Metrics ({len(result.metrics)}):")
        for m in result.metrics:
            labels = ", ".join(f"{k}={v}" for k, v in m.labels.items())
            label_str = f" {{{labels}}}" if labels else ""
            lines.append(f"    {m.name}{label_str} = {m.value}{' ' + m.unit if m.unit else ''}")
    if result.performance_data:
        lines.append(f"  Performance data: {result.performance_data}")
    if result.execution_time is not None:
        lines.append(f"  Execution time: {result.execution_time:.3f}s")
    return "\n".join(lines)
