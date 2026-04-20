"""Collector logging bootstrap.

Routes structlog through stdlib so every log line — regardless of whether
the call site uses `structlog.get_logger()` or `logging.getLogger(__name__)`
— lands on the same root stdlib logger. That matters for Debug Run, which
installs a task-local stdlib handler (`debug_runner._DebugCaptureHandler`)
to gather a connector/poll trace into the bundle's structured `logs`
field. Without this bootstrap, structlog uses its default PrintLoggerFactory
and writes to stdout instead, so connector debug lines only show up in the
bundle's `stdout` blob — readable, but out of band.
"""

from __future__ import annotations

import logging
import os

import structlog


def setup_logging(level: str | None = None, *, json: bool | None = None) -> None:
    """Configure stdlib + structlog once, at process start.

    Args:
        level: Logging level name (DEBUG/INFO/WARNING/...). Falls back to
            MONCTL_LOG_LEVEL env var, then INFO.
        json: Force JSON rendering on/off. Defaults to True in container/
            non-TTY environments, False on an interactive terminal.
    """
    lvl_name = (level or os.environ.get("MONCTL_LOG_LEVEL") or "INFO").upper()
    lvl = getattr(logging, lvl_name, logging.INFO)

    if json is None:
        # Structured logs in containers (stdout captured by Docker -> log
        # shipper), pretty console output locally. `sys.stderr.isatty()` is
        # a decent proxy for "running under a TTY".
        import sys

        json = not sys.stderr.isatty()

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            # Prepare the event dict for ProcessorFormatter: structlog wraps
            # the event and hands it to stdlib, where the ProcessorFormatter
            # below runs the final renderer. This is the canonical pattern
            # from structlog's "make structlog and stdlib logging play nice"
            # recipe.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(lvl),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root = logging.getLogger()
    # Idempotent: strip any stream handlers we installed in a prior call so
    # re-initialising (e.g. poll-worker restart under the same process)
    # doesn't double-emit every line.
    for h in list(root.handlers):
        if getattr(h, "_monctl_stream_handler", False):
            root.removeHandler(h)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream._monctl_stream_handler = True  # type: ignore[attr-defined]
    root.addHandler(stream)
    root.setLevel(lvl)
