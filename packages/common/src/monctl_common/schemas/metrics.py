"""Schemas for metrics, check results, and events.

These are the core data types exchanged between collectors and central.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from monctl_common.constants import CheckState


class Metric(BaseModel):
    """A single metric data point."""

    name: str = Field(description="Metric name (e.g., 'http_response_time_seconds')")
    value: float = Field(description="Metric value")
    labels: dict[str, str] = Field(default_factory=dict, description="Key-value label pairs")
    unit: str = Field(default="", description="Unit of measurement")
    timestamp: datetime | None = Field(
        default=None, description="Timestamp; None means collector sets it at collection time"
    )


class CheckResult(BaseModel):
    """Result of a monitoring check execution."""

    state: CheckState = Field(description="Check state (0=OK, 1=WARN, 2=CRIT, 3=UNKNOWN)")
    output: str = Field(description="Human-readable check output")
    metrics: list[Metric] = Field(default_factory=list, description="Metrics produced by the check")
    performance_data: dict[str, float] = Field(
        default_factory=dict, description="Performance data key-value pairs"
    )
    execution_time: float | None = Field(
        default=None, description="Execution time in seconds"
    )
    error_category: str = Field(
        default="", description="Error category: 'device', 'config', 'app', or '' (no error)"
    )


class Event(BaseModel):
    """A monitoring event (log entry, state change, etc.)."""

    source: str = Field(description="Event source identifier")
    severity: str = Field(description="Severity level: 'info', 'warning', 'critical'")
    message: str = Field(description="Event message")
    data: dict[str, object] = Field(default_factory=dict, description="Additional event data")
    timestamp: datetime | None = Field(
        default=None, description="Event timestamp; None means collector sets it"
    )


class AppResult(BaseModel):
    """Complete result from a single app execution."""

    assignment_id: str = Field(description="Assignment UUID that produced this result")
    app_id: str = Field(description="App UUID")
    check_result: CheckResult
    executed_at: datetime = Field(description="When the check was executed")


class IngestPayload(BaseModel):
    """Payload sent by a collector to the central /v1/ingest endpoint."""

    collector_id: str = Field(description="Collector UUID")
    timestamp: datetime = Field(description="Payload creation timestamp")
    sequence: int = Field(description="Monotonically increasing sequence number for dedup")
    app_results: list[AppResult] = Field(
        default_factory=list, description="Check results from app executions"
    )
    events: list[Event] = Field(default_factory=list, description="Events to report")
