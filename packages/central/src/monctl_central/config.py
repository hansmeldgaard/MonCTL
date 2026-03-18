"""Central server configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central server settings, loaded from environment variables."""

    model_config = {"env_prefix": "MONCTL_"}

    # Server
    host: str = "0.0.0.0"
    port: int = 8443
    debug: bool = False
    log_level: str = "INFO"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://monctl:monctl@localhost:5432/monctl"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # ClickHouse (replaces VictoriaMetrics for time-series + text data)
    clickhouse_hosts: str = "localhost"  # comma-separated: "192.168.1.41,192.168.1.42,192.168.1.43"
    clickhouse_port: int = 8123
    clickhouse_database: str = "monctl"
    clickhouse_cluster: str = "monctl_cluster"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_async_insert: bool = True

    # Docker stats sidecars (central tier only): "label:ip:port,label:ip:port,..."
    docker_stats_hosts: str = ""

    # Instance role: "api" (serve requests only), "scheduler" (run background tasks only), "all" (both)
    role: str = "all"

    # Ingestion
    ingest_batch_size: int = 1000
    ingest_flush_interval: float = 5.0
    ingest_max_queue_size: int = 50000

    # Leader election
    leader_lock_ttl: int = 30
    instance_id: str = ""

    # Heartbeat monitoring
    stale_threshold_seconds: int = 90
    dead_threshold_seconds: int = 300

    # Rate limiting
    rate_limit_per_key: int = 100

    # Wheel storage
    wheel_storage_dir: str = "/data/wheels"

    # Credential encryption (AES-256-GCM)
    # Must be a 64-character hex string (32 bytes).
    # Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
    # Leave empty to disable credential encryption (credentials won't work without it).
    encryption_key: str = ""

    # JWT Authentication
    jwt_secret_key: str = ""  # 64-char hex; generate: python3 -c "import secrets; print(secrets.token_hex(32))"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Initial admin user (created on first startup if no users exist)
    admin_username: str = "admin"
    admin_password: str = ""  # Set via MONCTL_ADMIN_PASSWORD to seed admin on first boot


settings = Settings()
