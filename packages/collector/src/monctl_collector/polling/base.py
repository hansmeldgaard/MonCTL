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

Error categories — all apps MUST set ``error_category`` on error results:
    "device"  — target unreachable, timeout, connection refused
    "config"  — missing connector, credential, or parameter
    "app"     — bug or crash in app code (parse error, unhandled exception)
    ""        — no error (status OK)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

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

    Connector requirements:
        Subclasses SHOULD declare which connectors they need via the
        ``required_connectors`` class attribute — a mapping of alias →
        connector type. Aliases are what ``poll()`` uses when looking up
        connectors via ``context.connectors[alias]``; the central server
        reads this declaration at app-version upload time and pre-creates
        the matching binding slots so the operator only has to pick a
        concrete connector per slot (no free-form alias typing).

        Examples::

            required_connectors = {"snmp": "snmp"}                       # single SNMP
            required_connectors = {"snmp": "snmp", "ssh": "ssh"}         # dual protocol
            required_connectors = {"primary": "snmp", "backup": "snmp"}  # two of same type
            required_connectors = {}                                     # no connector (e.g. ping)

        The declaration MUST be a literal dict of str→str so the central
        server can extract it via AST parsing without executing the app
        source code. Empty dict is a valid state and means "this poller
        does not use any connector".
    """

    required_connectors: ClassVar[dict[str, str]] = {}

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
