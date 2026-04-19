"""Ad-hoc debug runner: executes one poll inline with full output capture.

Used by the WebSocket `debug_run` command to give operators a diagnostic
bundle (PollResult + stdlib/structlog logs + stdout + stderr + traceback)
for a single assignment — without submitting the result to ClickHouse or
touching the scheduler heap.

Lives on the cache-node process (not the poll-worker) because the
cache-node:
  - already has `AppManager` + `CredentialManager` wired up for probe_oids,
  - doesn't run concurrent polls (poll-workers do, in separate processes),
    so process-global stdout redirect is safe,
  - is the process with the WebSocket command channel to central.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import dataclasses
import io
import logging
import time
import traceback
from typing import TYPE_CHECKING, Any

import structlog

from monctl_collector.cache.app_cache_accessor import AppCacheAccessor  # noqa: F401 (type-only)
from monctl_collector.jobs.models import JobDefinition, PollContext
from monctl_collector.polling.engine import _error_result

if TYPE_CHECKING:
    from monctl_collector.apps.manager import AppManager
    from monctl_collector.central.credentials import CredentialManager

logger = structlog.get_logger()

# Task-local log buffer. When set inside a debug coroutine, the installed
# handler appends records to this list; when unset (default None), the
# handler is a no-op. asyncio.Task auto-copies contextvars on creation, so
# inner tasks spawned by the poller inherit the buffer.
_log_buffer_var: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "debug_log_buffer", default=None,
)

_LOG_RECORD_CAP = 5000
_handler_installed = False


class _DebugCaptureHandler(logging.Handler):
    """Stdlib log handler that appends records to the task-local buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        buf = _log_buffer_var.get()
        if buf is None:
            return
        if len(buf) >= _LOG_RECORD_CAP:
            if len(buf) == _LOG_RECORD_CAP:
                buf.append({
                    "level": "WARNING",
                    "logger": "debug_runner",
                    "message": f"(log capture truncated after {_LOG_RECORD_CAP} entries)",
                    "timestamp": time.time(),
                })
            return
        try:
            msg = record.getMessage()
        except Exception:
            msg = record.msg
        entry: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": msg,
            "timestamp": record.created,
            "module": record.module,
            "lineno": record.lineno,
        }
        if record.exc_info:
            entry["exc_info"] = self.format(record) if record.exc_text else \
                "".join(traceback.format_exception(*record.exc_info))
        buf.append(entry)


def _install_handler_once() -> None:
    global _handler_installed
    if _handler_installed:
        return
    handler = _DebugCaptureHandler()
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    # Ensure root level lets DEBUG records through to handlers; individual
    # handlers can still filter higher. Don't lower below what's already set.
    if root.level == logging.NOTSET or root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)
    _handler_installed = True


async def run_debug(
    job: JobDefinition,
    *,
    app_manager: "AppManager",
    credential_manager: "CredentialManager",
    node_id: str,
) -> dict:
    """Run one poll for `job` with full diagnostic capture and return a bundle.

    Does NOT submit the result, does NOT update scheduler profiles, does NOT
    reschedule. Pure side-effect-free diagnostic execution.
    """
    _install_handler_once()

    started = time.time()
    log_buf: list[dict] = []
    token = _log_buffer_var.set(log_buf)

    fail_phase = "setup"
    result = None
    tb_str: str | None = None
    stdout_io = io.StringIO()
    stderr_io = io.StringIO()
    connectors: dict = {}

    try:
        with contextlib.redirect_stdout(stdout_io), contextlib.redirect_stderr(stderr_io):
            try:
                # 1. Load app class (downloads + venv if needed)
                cls = await app_manager.ensure_app(
                    job.app_id, job.app_version, job.app_checksum,
                )

                # 2. Resolve credentials referenced by the job
                cred_data: dict = {}
                if job.credential_names:
                    for cred_name in job.credential_names:
                        data = await credential_manager.get_credential(cred_name)
                        if data:
                            cred_data.update(data)

                # 3. Load + connect connectors
                for binding in job.connector_bindings:
                    conn_cls = await app_manager.ensure_connector(
                        binding.connector_id, binding.connector_version_id,
                        expected_checksum=binding.connector_checksum,
                    )
                    conn_cred: dict = {}
                    if binding.credential_name:
                        conn_cred = await credential_manager.get_credential(
                            binding.credential_name,
                        ) or {}
                    connector = conn_cls(
                        settings=binding.settings,
                        credential=conn_cred,
                    )
                    fail_phase = "connect"
                    await connector.connect(job.device_host or "")
                    connectors[binding.connector_type] = connector
                fail_phase = "poll"

                # 4. Build context — cache=None on purpose, debug runs must
                #    not mutate cache state that real polls read.
                ctx = PollContext(
                    job=job,
                    credential=cred_data,
                    node_id=node_id,
                    device_host=job.device_host or "",
                    parameters=job.parameters,
                    connectors=connectors,
                    cache=None,
                )

                poller = cls()
                await poller.setup()

                poll_task = asyncio.create_task(poller.poll(ctx))
                timeout_secs = float(job.max_execution_time)
                try:
                    result = await asyncio.wait_for(
                        asyncio.shield(poll_task),
                        timeout=timeout_secs,
                    )
                except asyncio.TimeoutError:
                    poll_task.cancel()
                    try:
                        await asyncio.wait_for(poll_task, timeout=5.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass
                    raise

                # Match engine.py: auto-fill error_category for apps that
                # return an error result without classifying it.
                if result is not None and result.status != "ok" and not result.error_category:
                    result.error_category = "device"

            except asyncio.TimeoutError:
                execution_ms = int((time.time() - started) * 1000)
                result = _error_result(
                    job, node_id, "timeout", execution_ms,
                    error_category="device",
                )
                tb_str = "TimeoutError: poll exceeded max_execution_time"
            except Exception as exc:  # noqa: BLE001
                execution_ms = int((time.time() - started) * 1000)
                category = {"setup": "config", "connect": "device", "poll": "app"}[fail_phase]
                result = _error_result(
                    job, node_id,
                    f"{type(exc).__name__}: {exc}",
                    execution_ms,
                    error_category=category,
                )
                tb_str = traceback.format_exc()
    finally:
        for conn in connectors.values():
            try:
                await conn.close()
            except Exception:
                pass
        _log_buffer_var.reset(token)

    duration_ms = int((time.time() - started) * 1000)
    success = result is not None and result.status == "ok"

    bundle: dict[str, Any] = {
        "success": success,
        "result": dataclasses.asdict(result) if result is not None else None,
        "logs": log_buf,
        "stdout": stdout_io.getvalue(),
        "stderr": stderr_io.getvalue(),
        "traceback": tb_str,
        "fail_phase": fail_phase if tb_str else None,
        "duration_ms": duration_ms,
    }
    logger.info(
        "debug_run_complete",
        job_id=job.job_id,
        success=success,
        fail_phase=bundle["fail_phase"],
        duration_ms=duration_ms,
        log_records=len(log_buf),
    )
    return bundle
