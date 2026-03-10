"""Base class for all monitoring poll apps.

Every monitoring app (ping-check, snmp-poller, http-check, ...) must subclass
BasePoller and implement at minimum `poll()`.

Example app (minimal):
    class Poller(BasePoller):
        async def poll(self, context: PollContext) -> PollResult:
            import asyncio
            await asyncio.sleep(0.1)
            return PollResult(
                job_id=context.job.job_id,
                device_id=context.job.device_id,
                collector_node=context.node_id,
                timestamp=time.time(),
                metrics=[{"name": "latency_ms", "value": 1.0}],
                config_data=None,
                status="ok",
                reachable=True,
                error_message=None,
                execution_time_ms=100,
            )
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from monctl_collector.jobs.models import PollContext, PollResult


class BasePoller(ABC):
    """Abstract base class for monitoring poll apps.

    Lifecycle:
        setup()   — called once before the first poll (optional)
        poll()    — called every `job.interval` seconds (required)
        teardown() — called on shutdown or version upgrade (optional)

    The engine maintains exactly one instance per (app_id, version) so that
    `setup()` can cache expensive one-time initialisation (e.g. SNMP walk
    result, TLS session, device MIB tree).
    """

    async def setup(self) -> None:
        """One-time initialisation called before the first poll.

        Override to cache expensive resources. Default is a no-op.
        """

    @abstractmethod
    async def poll(self, context: PollContext) -> PollResult:
        """Execute a monitoring check and return the result.

        Args:
            context: Contains the job definition, resolved credentials,
                     node_id, device_host, and resolved parameters.

        Returns:
            PollResult with all metric data filled in.

        Raises:
            Exception: Any unhandled exception is caught by the engine and
                       converted to a PollResult with status="error".
        """
        ...

    async def teardown(self) -> None:
        """Clean up resources on shutdown or when the app version is replaced.

        Override to close connections, sockets, etc. Default is a no-op.
        """
