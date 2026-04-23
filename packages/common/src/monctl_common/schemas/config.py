"""Configuration schemas shared between central and collector."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScheduleConfig(BaseModel):
    """Schedule configuration for an app assignment."""

    type: str = Field(description="Schedule type: 'interval' or 'cron'")
    value: str = Field(
        description="Schedule value: seconds for interval (e.g., '60'), cron expression for cron"
    )


class ResourceLimits(BaseModel):
    """Resource limits for app execution."""

    timeout_seconds: int = Field(default=30, description="Max execution time in seconds")
    memory_mb: int = Field(default=256, description="Max memory in MB")


class AppAssignmentConfig(BaseModel):
    """A single app assignment as seen by a collector."""

    assignment_id: str = Field(description="Assignment UUID")
    app_id: str = Field(description="App UUID")
    app_name: str = Field(description="App name for display")
    app_version: str = Field(description="Required app version (semver)")
    schedule: ScheduleConfig
    config: dict[str, object] = Field(
        default_factory=dict, description="App-specific configuration"
    )
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)


class CollectorSettings(BaseModel):
    """Global settings for the collector daemon."""

    heartbeat_interval: int = Field(default=30, description="Heartbeat interval in seconds")
    push_interval: int = Field(default=10, description="Result push interval in seconds")
    log_level: str = Field(default="INFO")


class CollectorConfig(BaseModel):
    """Full configuration snapshot returned by central to a collector."""

    config_version: int = Field(description="Incrementing config version number")
    settings: CollectorSettings = Field(default_factory=CollectorSettings)
    assignments: list[AppAssignmentConfig] = Field(default_factory=list)
