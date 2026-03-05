"""App execution engine - runs monitoring apps and collects results."""

from __future__ import annotations

import asyncio
import json
import sys
import time

import structlog

from monctl_common.constants import CheckState
from monctl_common.schemas.metrics import CheckResult, Metric
from monctl_sdk.base import MonitoringApp

logger = structlog.get_logger()


class AppExecutor:
    """Executes monitoring apps (both scripts and SDK-based)."""

    def __init__(self, max_concurrent: int = 50):
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def run_sdk_app(
        self,
        app: MonitoringApp,
        config: dict,
        timeout_seconds: int = 30,
    ) -> CheckResult:
        """Run an SDK-based app with timeout and resource limits."""
        async with self._semaphore:
            start = time.monotonic()
            try:
                app.validate_config(config)
                result = await asyncio.wait_for(
                    app.execute(config),
                    timeout=timeout_seconds,
                )
                result.execution_time = time.monotonic() - start
                return result
            except asyncio.TimeoutError:
                return CheckResult(
                    state=CheckState.UNKNOWN,
                    output=f"Execution timed out after {timeout_seconds}s",
                    execution_time=time.monotonic() - start,
                )
            except Exception as e:
                return CheckResult(
                    state=CheckState.UNKNOWN,
                    output=f"Execution error: {e}",
                    execution_time=time.monotonic() - start,
                )

    async def run_script_app(
        self,
        script_path: str,
        config: dict,
        timeout_seconds: int = 30,
        memory_mb: int = 256,
    ) -> CheckResult:
        """Run a script-based app in a subprocess."""
        async with self._semaphore:
            config_json = json.dumps(config)
            start = time.monotonic()

            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, script_path,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=config_json.encode()),
                    timeout=timeout_seconds,
                )

                elapsed = time.monotonic() - start
                return self._parse_script_output(stdout, stderr, proc.returncode, elapsed)

            except asyncio.TimeoutError:
                if proc:
                    proc.kill()
                return CheckResult(
                    state=CheckState.UNKNOWN,
                    output=f"Script timed out after {timeout_seconds}s",
                    execution_time=time.monotonic() - start,
                )
            except Exception as e:
                return CheckResult(
                    state=CheckState.UNKNOWN,
                    output=f"Script execution error: {e}",
                    execution_time=time.monotonic() - start,
                )

    def _parse_script_output(
        self,
        stdout: bytes,
        stderr: bytes,
        returncode: int | None,
        elapsed: float,
    ) -> CheckResult:
        """Parse script output into a CheckResult."""
        try:
            output = json.loads(stdout.decode())
            metrics = [
                Metric(**m) for m in output.get("metrics", [])
            ]
            check = output.get("check_result", {})
            state = CheckState(check.get("state", returncode or 3))
            return CheckResult(
                state=state,
                output=check.get("output", output.get("message", "")),
                metrics=metrics,
                performance_data=check.get("performance_data", {}),
                execution_time=elapsed,
            )
        except (json.JSONDecodeError, Exception):
            # Fallback: use exit code and raw stdout
            state_map = {0: CheckState.OK, 1: CheckState.WARNING, 2: CheckState.CRITICAL}
            state = state_map.get(returncode, CheckState.UNKNOWN)
            return CheckResult(
                state=state,
                output=stdout.decode().strip() or stderr.decode().strip() or "No output",
                execution_time=elapsed,
            )
