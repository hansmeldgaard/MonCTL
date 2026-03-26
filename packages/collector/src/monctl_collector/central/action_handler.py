"""Handler for run_action WebSocket commands from central."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

import structlog

logger = structlog.get_logger()

_WRAPPER_TEMPLATE = '''
import json
import sys
import os

_ctx_json = os.environ.get("MONCTL_ACTION_CONTEXT", "{}")
_ctx = json.loads(_ctx_json)

class ActionContext:
    def __init__(self, data):
        self.device_id = data.get("device_id", "")
        self.device_name = data.get("device_name", "")
        self.device_ip = data.get("device_ip", "")
        self.collector_id = data.get("collector_id", "")
        self.collector_name = data.get("collector_name", "")
        self.credential = data.get("credential", {})
        self.trigger_type = data.get("trigger_type", "")
        self.event_id = data.get("event_id", "")
        self.event_severity = data.get("event_severity", "")
        self.event_message = data.get("event_message", "")
        self.shared_data = data.get("shared_data", {})
        self.step_number = data.get("step_number", 0)
        self.action_name = data.get("action_name", "")
        self._output_data = {}

    def set_output(self, key, value):
        self._output_data[key] = value

    def get_output_json(self):
        return json.dumps(self._output_data)

context = ActionContext(_ctx)

{user_script}

_output_path = os.environ.get("MONCTL_ACTION_OUTPUT", "/tmp/action_output.json")
with open(_output_path, "w") as _f:
    _f.write(context.get_output_json())
'''


async def handle_run_action(payload: dict) -> dict:
    """Execute an action script on this collector.

    Payload from central:
        {
            "source_code": "...",
            "context": { ActionContext fields },
            "timeout": 60,
        }

    Returns:
        {
            "status": "success" | "failed" | "timeout",
            "exit_code": int,
            "stdout": str,
            "stderr": str,
            "output_data": dict,
            "duration_ms": int,
        }
    """
    source_code = payload.get("source_code", "")
    context_data = payload.get("context", {})
    timeout = min(payload.get("timeout", 60), 300)

    start = time.time()

    with tempfile.TemporaryDirectory(prefix="monctl_action_") as tmpdir:
        script_path = Path(tmpdir) / "action_script.py"
        output_path = Path(tmpdir) / "action_output.json"

        wrapped = _WRAPPER_TEMPLATE.format(user_script=source_code)
        script_path.write_text(wrapped)

        env = os.environ.copy()
        env["MONCTL_ACTION_CONTEXT"] = json.dumps(context_data)
        env["MONCTL_ACTION_OUTPUT"] = str(output_path)

        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=tmpdir,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "status": "timeout",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Timed out after {timeout}s",
                    "output_data": {},
                    "duration_ms": int((time.time() - start) * 1000),
                }

            stdout = stdout_bytes.decode("utf-8", errors="replace")[:50000]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:50000]

            output_data = {}
            if output_path.exists():
                try:
                    output_data = json.loads(output_path.read_text())
                except (json.JSONDecodeError, OSError):
                    pass

            return {
                "status": "success" if proc.returncode == 0 else "failed",
                "exit_code": proc.returncode or 0,
                "stdout": stdout,
                "stderr": stderr,
                "output_data": output_data,
                "duration_ms": int((time.time() - start) * 1000),
            }
        except Exception as exc:
            logger.error("action_handler_error", error=str(exc))
            return {
                "status": "failed",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
                "output_data": {},
                "duration_ms": int((time.time() - start) * 1000),
            }
