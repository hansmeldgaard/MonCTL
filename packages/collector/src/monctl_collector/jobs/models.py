"""Data models for the collector job system."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from monctl_collector.cache.app_cache_accessor import AppCacheAccessor


@dataclass
class ConnectorBinding:
    """A connector bound to a job via its assignment."""
    alias: str                         # named reference (e.g. "snmp")
    connector_id: str                  # connector UUID
    connector_version_id: str          # connector version UUID
    credential_name: str | None = None # credential name (resolved by CredentialManager)
    use_latest: bool = False
    settings: dict = field(default_factory=dict)


@dataclass
class JobDefinition:
    """A monitoring job fetched from the central DB.

    Stored permanently in SQLite (no TTL). Valid until central deletes it.
    Maps 1-to-1 to an AppAssignment in the central server.
    """
    job_id: str           # = assignment_id UUID string
    device_id: str | None
    device_host: str | None    # IP or hostname of the device to monitor
    app_id: str                # app name string (e.g. "ping_check")
    app_version: str           # version string (e.g. "1.0.0")
    credential_names: list[str]  # names of credentials referenced in parameters
    interval: int              # seconds between polls
    parameters: dict           # app-specific config (may contain $credential: refs)
    role: str | None = None    # "availability" | "latency" | None
    max_execution_time: int = 120
    enabled: bool = True
    updated_at: str = ""
    connector_bindings: list[ConnectorBinding] = field(default_factory=list)


@dataclass
class JobProfile:
    """Execution profile for a job — built from actual execution data.

    Stored permanently in SQLite. EMA adapts dynamically as jobs run.
    """
    job_id: str
    avg_execution_time: float = 5.0    # EMA. 5s conservative default for unknown jobs.
    last_execution_time: float = 0.0
    max_execution_time: float = 0.0
    execution_count: int = 0
    error_count: int = 0
    last_run: float = 0.0              # Unix timestamp
    next_deadline: float = 0.0        # Unix timestamp
    status: str = "idle"
    is_stable: bool = False            # True after 3+ executions
    is_heavy: bool = False             # avg_execution_time >= heavy_threshold
    def update_after_execution(
        self,
        actual_time: float,
        alpha: float = 0.3,
        heavy_threshold: float = 30.0,
    ) -> None:
        """Update EMA and profile stats after a job execution.

        With alpha=0.3, a job jumping from 2s → 10s converges in ~5 runs:
        4.4 → 6.1 → 7.3 → 8.1 → 8.7

        Args:
            actual_time: Wall-clock execution time in seconds.
            alpha: EMA smoothing factor (0 = ignore new data, 1 = ignore history).
            heavy_threshold: Jobs above this avg are classified as heavy.
        """
        self.last_execution_time = actual_time
        self.max_execution_time = max(self.max_execution_time, actual_time)
        self.execution_count += 1
        self.last_run = time.time()

        if self.execution_count <= 1:
            self.avg_execution_time = actual_time
        else:
            self.avg_execution_time = (
                alpha * actual_time + (1 - alpha) * self.avg_execution_time
            )

        self.is_stable = self.execution_count >= 3
        self.is_heavy = self.avg_execution_time >= heavy_threshold

    def load_contribution(self, interval: int) -> float:
        """Load contribution of this job: avg_time / interval.

        Example: a 45s SNMP walk every 300s contributes 0.15 load units.
        Sum across all jobs gives the node's load_score.
        """
        if interval <= 0:
            return 0.0
        return self.avg_execution_time / interval


@dataclass
class NodeLoadInfo:
    """Load information for one cache-node, reported via heartbeat."""
    node_id: str
    load_score: float        # sum(avg_time/interval) for all active jobs
    worker_count: int
    effective_load: float    # load_score / worker_count
    deadline_miss_rate: float
    total_jobs: int

    @classmethod
    def empty(cls, node_id: str) -> "NodeLoadInfo":
        return cls(
            node_id=node_id,
            load_score=0.0,
            worker_count=0,
            effective_load=0.0,
            deadline_miss_rate=0.0,
            total_jobs=0,
        )


@dataclass
class WorkerRegistration:
    """A poll-worker registered with the local cache-node.

    Tracks which apps the worker has loaded so the scheduler can assign
    jobs with app affinity (minimize new venv creation).
    """
    worker_id: str
    loaded_apps: set[tuple[str, str]] = field(default_factory=set)  # (app_id, version)
    job_count: int = 0
    last_seen: float = field(default_factory=time.time)


@dataclass(order=True)
class ScheduledJob:
    """An entry in the scheduler's min-heap priority queue.

    Sorted by next_deadline so the earliest due job always runs first.
    """
    next_deadline: float                           # sort key — Unix timestamp
    job_id: str = field(compare=False)
    job: JobDefinition = field(compare=False)
    profile: JobProfile = field(compare=False)


@dataclass
class PollResult:
    """Result of executing one job on a poll-worker."""
    job_id: str
    device_id: str | None
    collector_node: str
    timestamp: float          # Unix timestamp
    metrics: list[dict]
    config_data: dict | None  # discovered config data (e.g. interface names)
    status: str               # "ok" | "warning" | "critical" | "unknown" | "error"
    reachable: bool
    error_message: str | None
    execution_time_ms: int
    started_at: float | None = None
    rtt_ms: float | None = None
    response_time_ms: float | None = None
    interface_rows: list[dict] | None = None  # Per-interface data for interface-table apps


@dataclass
class PollContext:
    """Context passed to a BasePoller.poll() call."""
    job: JobDefinition
    credential: dict          # decrypted credential data dict (or {} if no credential)
    node_id: str              # collector node hostname
    device_host: str          # resolved device address
    parameters: dict          # resolved parameters (credentials substituted)
    connectors: dict = field(default_factory=dict)  # alias → connector instance
    cache: AppCacheAccessor | None = None  # shared cache accessor
