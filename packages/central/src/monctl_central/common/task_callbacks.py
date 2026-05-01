"""Shared done-callback helpers for fire-and-forget asyncio tasks.

`asyncio.create_task(...)` without a done-callback swallows any exception the
coroutine raises — Python emits a "Task exception was never retrieved" warning
on garbage collection, but operators rarely see that in production logs and
the failure is otherwise invisible. F-CEN-041 fixed this for scheduler-tick
tasks; R-CEN-003 / R-CEN-008 extended the pattern to automations + cert sync.

Use as::

    task = asyncio.create_task(coro())
    task.add_done_callback(log_task_exception)

The callback uses ``logger.exception`` so the full traceback lands in the
central log stream and audit pipeline.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def log_task_exception(task: asyncio.Task) -> None:
    """Done-callback that surfaces exceptions from fire-and-forget tasks.

    Cancellations are intentional and don't get logged. Any other exception
    is logged at ERROR with the task name + full traceback.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception(
            "background_task_failed",
            exc_info=exc,
            extra={"task": task.get_name()},
        )
