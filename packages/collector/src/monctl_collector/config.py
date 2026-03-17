"""Collector configuration — loaded from YAML file with env var overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CacheConfig:
    db_path: str = "/data/cache.db"
    default_ttl: int = 300               # TTL for cached monitoring data (seconds)
    cleanup_interval: int = 30           # how often to purge expired cache rows (seconds)


@dataclass
class CentralConfig:
    url: str = ""                         # e.g. https://central.example.com
    api_key: str | None = None
    sync_interval: int = 60              # how often to pull jobs from central (seconds)
    credential_refresh: int = 1800       # how often to refresh credentials (seconds)
    heartbeat_interval: int = 60         # how often to send heartbeat (seconds)
    timeout: int = 30                    # HTTP request timeout (seconds)
    verify_ssl: bool = True              # set False for self-signed certificates


@dataclass
class SchedulingConfig:
    max_concurrent_polls: int = 50
    heavy_threshold: float = 30.0        # avg_time >= this → use heavy slot
    heavy_slots: int = 5
    light_slots: int = 45
    default_avg_time: float = 5.0        # assumed avg execution time for new jobs
    ema_alpha: float = 0.3               # EMA smoothing factor
    deadline_miss_threshold: float = 0.05


@dataclass
class AppsConfig:
    apps_dir: str = "/data/apps"
    venvs_dir: str = "/data/venvs"      # shared venvs keyed by requirements hash
    pip_cache_dir: str = "/data/pip-cache"
    keep_old_versions: int = 3
    pip_index_url: str | None = None    # optional: custom pip index for air-gapped deploys


@dataclass
class CollectorConfig:
    node_id: str = ""                   # unique identifier for this cache-node
    collector_id: str = ""              # UUID from central registration (for config/peer discovery)
    collector_api_key: str = ""         # individual collector API key (from setup.yaml)
    listen_address: str = "0.0.0.0"
    listen_port: int = 50051            # gRPC port for worker communication
    cache: CacheConfig = field(default_factory=CacheConfig)
    central: CentralConfig = field(default_factory=CentralConfig)
    scheduling: SchedulingConfig = field(default_factory=SchedulingConfig)
    apps: AppsConfig = field(default_factory=AppsConfig)


def load_config(yaml_path: str = "/etc/collector/config.yaml") -> CollectorConfig:
    """Load config from YAML file, then override with environment variables.

    Environment variables (all optional):
        NODE_ID             — unique node identifier (default: hostname)
        LISTEN_PORT         — gRPC listen port (default: 50051)
        CENTRAL_URL         — central server URL
        CENTRAL_API_KEY     — API key for central server authentication
        CACHE_DB_PATH       — path to SQLite database (default: /data/cache.db)
        APPS_DIR            — path to apps directory (default: /data/apps)
        VENVS_DIR           — path to venvs directory (default: /data/venvs)
    """
    raw: dict[str, Any] = {}
    p = Path(yaml_path)
    if p.exists():
        with p.open() as f:
            raw = yaml.safe_load(f) or {}

    def _get(section: str, key: str, default: Any) -> Any:
        return raw.get(section, {}).get(key, default)

    # Build sub-configs from YAML
    cache = CacheConfig(
        db_path=_get("cache", "db_path", "/data/cache.db"),
        default_ttl=_get("cache", "default_ttl", 300),
        cleanup_interval=_get("cache", "cleanup_interval", 30),
    )
    central = CentralConfig(
        url=_get("central", "url", ""),
        api_key=_get("central", "api_key", None),
        sync_interval=_get("central", "sync_interval", 60),
        credential_refresh=_get("central", "credential_refresh", 1800),
        heartbeat_interval=_get("central", "heartbeat_interval", 60),
        timeout=_get("central", "timeout", 30),
    )
    scheduling = SchedulingConfig(
        max_concurrent_polls=_get("scheduling", "max_concurrent_polls", 50),
        heavy_threshold=_get("scheduling", "heavy_threshold", 30.0),
        heavy_slots=_get("scheduling", "heavy_slots", 5),
        light_slots=_get("scheduling", "light_slots", 45),
        default_avg_time=_get("scheduling", "default_avg_time", 5.0),
        ema_alpha=_get("scheduling", "ema_alpha", 0.3),
        deadline_miss_threshold=_get("scheduling", "deadline_miss_threshold", 0.05),
    )
    apps = AppsConfig(
        apps_dir=_get("apps", "apps_dir", "/data/apps"),
        venvs_dir=_get("apps", "venvs_dir", "/data/venvs"),
        pip_cache_dir=_get("apps", "pip_cache_dir", "/data/pip-cache"),
        keep_old_versions=_get("apps", "keep_old_versions", 3),
        pip_index_url=_get("apps", "pip_index_url", None),
    )

    import socket
    default_node_id = raw.get("node_id", socket.gethostname())

    cfg = CollectorConfig(
        node_id=raw.get("node_id", default_node_id),
        listen_address=raw.get("listen_address", "0.0.0.0"),
        listen_port=int(raw.get("listen_port", 50051)),
        cache=cache,
        central=central,
        scheduling=scheduling,
        apps=apps,
    )

    # Environment variable overrides (MONCTL_ prefix takes priority, fallback to bare name)
    def _env(*names: str) -> str | None:
        for n in names:
            v = os.environ.get(n)
            if v is not None:
                return v
        return None

    if v := _env("MONCTL_NODE_ID", "NODE_ID"):
        cfg.node_id = v
    if v := _env("MONCTL_LISTEN_PORT", "LISTEN_PORT"):
        cfg.listen_port = int(v)
    if v := _env("MONCTL_CENTRAL_URL", "CENTRAL_URL"):
        cfg.central.url = v
    if v := _env("MONCTL_CENTRAL_API_KEY", "CENTRAL_API_KEY"):
        cfg.central.api_key = v
    if v := _env("MONCTL_VERIFY_SSL", "VERIFY_SSL"):
        cfg.central.verify_ssl = v.lower() not in ("0", "false", "no")
    if v := _env("MONCTL_DB_PATH", "CACHE_DB_PATH"):
        cfg.cache.db_path = v
    if v := _env("MONCTL_APPS_DIR", "APPS_DIR"):
        cfg.apps.apps_dir = v
    if v := _env("MONCTL_VENVS_DIR", "VENVS_DIR"):
        cfg.apps.venvs_dir = v
    if v := _env("MONCTL_GRPC_ADDRESS"):
        # e.g. "0.0.0.0:50051" → parse port
        parts = v.rsplit(":", 1)
        if len(parts) == 2:
            cfg.listen_address = parts[0]
            cfg.listen_port = int(parts[1])

    # Read collector_id and individual API key from setup.yaml (written by monctl CLI)
    setup_path = Path(_env("MONCTL_SETUP_YAML") or "/etc/monctl/setup.yaml")
    if setup_path.exists():
        try:
            with setup_path.open() as f:
                setup = yaml.safe_load(f) or {}
            if not cfg.collector_id and setup.get("collector_id"):
                cfg.collector_id = setup["collector_id"]
            if not cfg.collector_api_key and setup.get("api_key"):
                cfg.collector_api_key = setup["api_key"]
        except Exception:
            pass

    # Explicit env overrides for collector identity
    if v := _env("MONCTL_COLLECTOR_ID"):
        cfg.collector_id = v
    if v := _env("MONCTL_COLLECTOR_API_KEY"):
        cfg.collector_api_key = v

    # Auto-detect pip_index_url from central URL if not explicitly set.
    # This points pip at central's PEP 503 endpoint for air-gapped deploys.
    if not cfg.apps.pip_index_url and cfg.central.url:
        central_base = cfg.central.url.rstrip("/")
        cfg.apps.pip_index_url = f"{central_base}/api/v1/pypi/simple/"

    return cfg
