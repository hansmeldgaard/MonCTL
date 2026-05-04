"""Execute action scripts in isolated subprocesses on central."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

import structlog

logger = structlog.get_logger()


# S-CEN-010 — env var allowlist for the action subprocess.
#
# Previously: ``env=os.environ.copy()`` inherited every MonCTL secret
# (encryption key, JWT secret, DB DSN with password, OAuth client secret,
# collector API key, peer token, ...). An action with `automation:create`
# could exfil the cluster's keying material in a single ``print
# os.environ`` line. We now build a clean env from a small allowlist of
# system vars the user script may legitimately depend on, plus the two
# wrapper-internal vars (``MONCTL_ACTION_CONTEXT``,
# ``MONCTL_ACTION_OUTPUT``). Anything else — secrets in particular —
# stays in the parent process and never reaches the subprocess.
_SAFE_ENV_VARS = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "USER", "TZ", "TERM",
    "TMPDIR", "PYTHONIOENCODING",
)

_WRAPPER_TEMPLATE = '''
import json
import sys
import os

_ctx_json = os.environ.get("MONCTL_ACTION_CONTEXT", "{}")
_ctx = json.loads(_ctx_json)

class ActionContext:
    """Runtime context for the action script."""
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

    def set_output(self, key: str, value):
        """Store output data that will be available to subsequent actions."""
        self._output_data[key] = value

    def get_output_json(self) -> str:
        return json.dumps(self._output_data)

context = ActionContext(_ctx)

# ---- User script starts here ----
{user_script}
# ---- User script ends here ----

_output_path = os.environ.get("MONCTL_ACTION_OUTPUT", "/tmp/action_output.json")
with open(_output_path, "w") as _f:
    _f.write(context.get_output_json())
'''


async def execute_action_locally(
    source_code: str,
    context_data: dict,
    timeout: int = 60,
) -> dict:
    """Execute an action script in a subprocess on central.

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
    start = time.time()

    with tempfile.TemporaryDirectory(prefix="monctl_action_") as tmpdir:
        script_path = Path(tmpdir) / "action_script.py"
        output_path = Path(tmpdir) / "action_output.json"

        # `.replace` instead of `.format` — the wrapper template
        # contains literal `{}` (e.g. `data.get("credential", {})`,
        # `self._output_data = {}`) which `.format()` interprets as
        # positional placeholders and raises `IndexError`. Replace is
        # also robust against `{` chars in user-supplied source_code.
        wrapped = _WRAPPER_TEMPLATE.replace("{user_script}", source_code)
        script_path.write_text(wrapped)

        # S-CEN-010 — allowlist clean env. Never propagate parent
        # MonCTL secrets to the user-authored action script.
        env = {
            name: os.environ[name]
            for name in _SAFE_ENV_VARS
            if name in os.environ
        }
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
                duration_ms = int((time.time() - start) * 1000)
                return {
                    "status": "timeout",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Action timed out after {timeout}s",
                    "output_data": {},
                    "duration_ms": duration_ms,
                }

            duration_ms = int((time.time() - start) * 1000)
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
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            logger.error("action_execution_error", error=str(exc))
            return {
                "status": "failed",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
                "output_data": {},
                "duration_ms": duration_ms,
            }
