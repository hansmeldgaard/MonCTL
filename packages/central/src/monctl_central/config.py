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
    # Redis Sentinel (HA mode — takes precedence over redis_url when set)
    redis_sentinel_hosts: str = ""  # comma-separated: "host1:26379,host2:26379,host3:26379"
    redis_sentinel_master: str = "monctl-redis"

    # Infrastructure node topology (used by system health checks)
    # Format: "name:ip,name:ip,..." e.g. "central1:10.145.210.41,central2:10.145.210.42"
    patroni_nodes: str = ""
    etcd_nodes: str = ""

    # ClickHouse (replaces VictoriaMetrics for time-series + text data)
    clickhouse_hosts: str = "localhost"  # comma-separated: "192.168.1.41,192.168.1.42,192.168.1.43"
    clickhouse_port: int = 8123
    clickhouse_database: str = "monctl"
    clickhouse_cluster: str = "monctl_cluster"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_async_insert: bool = True
    clickhouse_pool_size: int = 8  # concurrent client connections per central node

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
    node_name: str = ""  # MONCTL_NODE_NAME — human-readable hostname for this node

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

    # Emit `Secure` flag on auth cookies. Default True — override with MONCTL_COOKIE_SECURE=false
    # only for dev setups that serve the UI over plain HTTP (no HAProxy TLS termination).
    cookie_secure: bool = True

    # Upgrade management
    upgrade_storage_dir: str = "/data/upgrades"

    # TLS certificate SANs (for self-signed generation)
    # Comma-separated IP addresses to include as Subject Alternative Names
    tls_san_ips: str = ""  # e.g. "10.145.210.40,10.145.210.41,10.145.210.42"
    # Path where HAProxy reads its cert (shared volume mount point)
    tls_cert_path: str = "/etc/haproxy/certs/monctl.pem"

    # Initial admin user (created on first startup if no users exist)
    admin_username: str = "admin"
    admin_password: str = ""  # Set via MONCTL_ADMIN_PASSWORD to seed admin on first boot

    # IncidentEngine (phase 1 of the event policy rework — see
    # docs/event-policy-rework.md). "off" = no-op, "shadow" = runs alongside
    # the existing EventEngine and writes to PG incidents table only.
    incident_engine: str = "shadow"

    # OAuth2 / OIDC provider (used by Superset SSO today; any OAuth2 client
    # in the future). Single-client config via env for now — promote to a DB
    # table when a second client arrives.
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    # Comma-separated list of exact allowed redirect_uri values for the client.
    # Any deviation rejects the authorize request — do not wildcard.
    oauth_redirect_uris: str = ""
    # OIDC issuer claim; should match the public base URL seen by browsers.
    oauth_issuer: str = "https://10.145.210.40"

    # S-CEN-002 — strict per-collector authentication.
    # When True, /api/v1/* endpoints reject the legacy shared-secret path
    # whenever the caller can't be matched to a specific Collector record
    # (no per-collector key, no X-Collector-Id header, no hostname match).
    # Default False during the rollout — the installer doesn't provision
    # per-collector keys yet (M-INST-011), so flipping this on
    # cluster-wide would lock out collector hosts. Operators who have
    # rolled per-collector keys (#117/#118/#122 in prod) can opt in via
    # MONCTL_REQUIRE_PER_COLLECTOR_AUTH=true. When False, every
    # shared-secret call without a resolvable collector identity emits a
    # `collector_shared_secret_used` warning so operators can monitor the
    # sunset.
    require_per_collector_auth: bool = False


settings = Settings()


def parse_node_list(raw: str) -> list[tuple[str, str]]:
    """Parse 'name:ip,name:ip,...' into [(name, ip), ...]."""
    if not raw.strip():
        return []
    nodes = []
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            name, ip = entry.split(":", 1)
            nodes.append((name.strip(), ip.strip()))
    return nodes
