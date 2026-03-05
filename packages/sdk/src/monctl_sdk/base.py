"""Base classes for MonCTL monitoring apps.

App developers extend these classes to create monitoring apps that run on collectors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from monctl_common.constants import CheckState
from monctl_common.schemas.metrics import CheckResult, Event, Metric


class MonitoringApp(ABC):
    """Base class for all monitoring apps.

    Subclass this to create a check-based monitoring app that produces
    a CheckResult with state (OK/WARNING/CRITICAL/UNKNOWN) and optional metrics.

    Example::

        class HttpCheck(MonitoringApp):
            name = "http_check"
            version = "1.0.0"

            async def execute(self, config: dict) -> CheckResult:
                # ... perform HTTP check ...
                return CheckResult(
                    state=CheckState.OK,
                    output="HTTP 200 OK",
                    metrics=[Metric(name="response_time", value=0.234)],
                )
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique app identifier."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string (e.g., '1.2.0')."""

    def validate_config(self, config: dict) -> None:
        """Validate the app configuration.

        Override to add custom validation. Raise ValueError if invalid.
        Called before execute() with the assignment's config dict.
        """

    @abstractmethod
    async def execute(self, config: dict) -> CheckResult:
        """Run the monitoring check.

        Args:
            config: App-specific configuration dict from the assignment.

        Returns:
            CheckResult with state, output message, and optional metrics.

        Raises:
            Any exception is caught by the runner and converted to UNKNOWN state.
        """


class MetricCollector(MonitoringApp):
    """Base class for apps that only collect metrics (no check state).

    The execute() method is pre-implemented to wrap collect() results
    into a CheckResult with OK state.

    Example::

        class SystemMetrics(MetricCollector):
            name = "system_metrics"
            version = "1.0.0"

            async def collect(self, config: dict) -> list[Metric]:
                import psutil
                return [
                    Metric(name="cpu_percent", value=psutil.cpu_percent()),
                    Metric(name="memory_percent", value=psutil.virtual_memory().percent),
                ]
    """

    @abstractmethod
    async def collect(self, config: dict) -> list[Metric]:
        """Collect and return metrics.

        Args:
            config: App-specific configuration dict.

        Returns:
            List of Metric objects.
        """

    async def execute(self, config: dict) -> CheckResult:
        """Execute by collecting metrics and wrapping in a CheckResult."""
        metrics = await self.collect(config)
        return CheckResult(
            state=CheckState.OK,
            output=f"Collected {len(metrics)} metrics",
            metrics=metrics,
        )


class EventSource(MonitoringApp):
    """Base class for apps that produce events (log watchers, etc.).

    Example::

        class LogWatcher(EventSource):
            name = "log_watcher"
            version = "1.0.0"

            async def poll_events(self, config: dict) -> list[Event]:
                # ... read new log entries since last poll ...
                return [Event(source="syslog", severity="warning", message="Disk full")]
    """

    @abstractmethod
    async def poll_events(self, config: dict) -> list[Event]:
        """Poll for new events since last invocation.

        Args:
            config: App-specific configuration dict.

        Returns:
            List of Event objects.
        """

    async def execute(self, config: dict) -> CheckResult:
        """Execute by polling events and wrapping in a CheckResult."""
        events = await self.poll_events(config)
        # Store events for the runner to extract and send separately
        self._last_events = events
        return CheckResult(
            state=CheckState.OK,
            output=f"Polled {len(events)} events",
            metrics=[],
        )
