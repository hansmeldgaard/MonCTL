"""Collector daemon configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class CollectorSettings(BaseSettings):
    """Collector settings, loaded from environment variables."""

    model_config = {"env_prefix": "MONCTL_COLLECTOR_"}

    # Central server
    central_url: str = "https://localhost:8443"
    registration_token: str = ""

    # Identity (set after registration)
    collector_id: str = ""
    api_key: str = ""
    credentials_file: str = "/etc/monctl/collector.key"

    # Cluster
    cluster_id: str = ""
    peer_address: str = ""
    peer_port: int = 9901

    # Intervals
    heartbeat_interval: int = 30
    push_interval: int = 10
    config_poll_interval: int = 30

    # Buffer
    buffer_path: str = "/var/lib/monctl/buffer.db"
    buffer_max_size_mb: int = 500

    # App execution
    apps_dir: str = "/opt/monctl/apps"
    max_concurrent_apps: int = 50
    default_timeout: int = 30
    default_memory_mb: int = 256

    # Logging
    log_level: str = "INFO"

    # TLS
    verify_ssl: bool = True
    ca_cert: str = ""


collector_settings = CollectorSettings()
