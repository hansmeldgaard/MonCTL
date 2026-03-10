"""ClickHouse client wrapper for time-series data storage.

Handles check results and events — replaces PostgreSQL for high-volume
append-only data and VictoriaMetrics for metrics storage.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client

logger = logging.getLogger(__name__)

# ClickHouse table DDL — executed via ensure_tables() on startup
_CHECK_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS check_results ON CLUSTER '{cluster}'
(
    assignment_id      UUID,
    collector_id       UUID,
    app_id             UUID,
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    state              UInt8,
    output             String,
    error_message      String        DEFAULT '',

    rtt_ms             Float64       DEFAULT 0,
    response_time_ms   Float64       DEFAULT 0,
    reachable          UInt8         DEFAULT 1,
    status_code        UInt16        DEFAULT 0,

    metric_names       Array(String)   DEFAULT [],
    metric_values      Array(Float64)  DEFAULT [],

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),
    execution_time     Float32       DEFAULT 0,
    started_at         DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),
    collector_name     String               DEFAULT '',

    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    role               String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000')
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/check_results', '{{replica}}'
)
PARTITION BY toYYYYMM(executed_at)
ORDER BY (assignment_id, executed_at)
TTL executed_at + INTERVAL 90 DAY
SETTINGS index_granularity = 8192
"""

_CHECK_RESULTS_INDEXES = [
    "ALTER TABLE check_results ADD INDEX IF NOT EXISTS idx_device bloom_filter(device_id) GRANULARITY 4",
    "ALTER TABLE check_results ADD INDEX IF NOT EXISTS idx_collector bloom_filter(collector_id) GRANULARITY 4",
    "ALTER TABLE check_results ADD INDEX IF NOT EXISTS idx_state set(state) GRANULARITY 4",
    "ALTER TABLE check_results ADD INDEX IF NOT EXISTS idx_tenant bloom_filter(tenant_id) GRANULARITY 4",
]

_CHECK_RESULTS_LATEST_DDL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS check_results_latest ON CLUSTER '{cluster}'
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{{shard}}/check_results_latest_v2', '{{replica}}',
    executed_at
)
ORDER BY (assignment_id)
AS SELECT * FROM check_results
"""

_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events ON CLUSTER '{cluster}'
(
    collector_id   UUID,
    app_id         UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    source         String,
    severity       LowCardinality(String),
    message        String,
    data           String        DEFAULT '{{}}',
    occurred_at    DateTime64(3, 'UTC'),
    received_at    DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/events', '{{replica}}'
)
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (collector_id, occurred_at)
TTL occurred_at + INTERVAL 30 DAY
"""

# Non-clustered fallback DDL (single-node / dev)
_CHECK_RESULTS_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS check_results
(
    assignment_id      UUID,
    collector_id       UUID,
    app_id             UUID,
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    state              UInt8,
    output             String,
    error_message      String        DEFAULT '',

    rtt_ms             Float64       DEFAULT 0,
    response_time_ms   Float64       DEFAULT 0,
    reachable          UInt8         DEFAULT 1,
    status_code        UInt16        DEFAULT 0,

    metric_names       Array(String)   DEFAULT [],
    metric_values      Array(Float64)  DEFAULT [],

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),
    execution_time     Float32       DEFAULT 0,
    started_at         DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),
    collector_name     String               DEFAULT '',

    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    role               String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000')
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(executed_at)
ORDER BY (assignment_id, executed_at)
TTL executed_at + INTERVAL 90 DAY
SETTINGS index_granularity = 8192
"""

_CHECK_RESULTS_LATEST_DDL_LOCAL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS check_results_latest
ENGINE = ReplacingMergeTree(executed_at)
ORDER BY (assignment_id)
AS SELECT * FROM check_results
"""

_EVENTS_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS events
(
    collector_id   UUID,
    app_id         UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    source         String,
    severity       LowCardinality(String),
    message        String,
    data           String        DEFAULT '{}',
    occurred_at    DateTime64(3, 'UTC'),
    received_at    DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (collector_id, occurred_at)
TTL occurred_at + INTERVAL 30 DAY
"""

# Columns used for check_results inserts
_INSERT_COLUMNS = [
    "assignment_id", "collector_id", "app_id", "device_id",
    "state", "output", "error_message",
    "rtt_ms", "response_time_ms", "reachable", "status_code",
    "metric_names", "metric_values",
    "executed_at", "execution_time",
    "started_at", "collector_name",
    "device_name", "app_name", "role", "tenant_id",
]

_EVENT_INSERT_COLUMNS = [
    "collector_id", "app_id", "source", "severity",
    "message", "data", "occurred_at",
]


class ClickHouseClient:
    """Thin wrapper around clickhouse-connect for MonCTL operations."""

    def __init__(
        self,
        hosts: list[str],
        port: int = 8123,
        database: str = "monctl",
        cluster_name: str = "monctl_cluster",
        async_insert: bool = True,
        username: str = "default",
        password: str = "",
    ):
        self._hosts = hosts
        self._port = port
        self._database = database
        self._cluster_name = cluster_name
        self._async_insert = async_insert
        self._username = username
        self._password = password
        self._client: Client | None = None

    def _get_client(self) -> Client:
        if self._client is None:
            settings: dict[str, Any] = {}
            if self._async_insert:
                settings["async_insert"] = 1
                settings["wait_for_async_insert"] = 0
            self._client = clickhouse_connect.get_client(
                host=self._hosts[0],
                port=self._port,
                username=self._username,
                password=self._password,
                database=self._database,
                settings=settings,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _ensure_mv_columns(self) -> None:
        """Drop and recreate the materialized view if it doesn't have new columns."""
        client = self._get_client()
        try:
            # Check if the MV has the new columns
            cols = client.query("DESCRIBE TABLE check_results_latest")
            col_names = {r[0] for r in cols.result_rows}
            if "started_at" not in col_names:
                client.command("DROP VIEW IF EXISTS check_results_latest")
                # It will be recreated by ensure_tables
        except Exception:
            pass

    def ensure_tables(self) -> None:
        """Create tables if they don't exist. Safe to call on every startup."""
        client = self._get_client()

        # Try to create database first
        client.command(f"CREATE DATABASE IF NOT EXISTS {self._database}")

        # Detect if cluster is available
        try:
            rows = client.query(
                "SELECT count() FROM system.clusters WHERE cluster = {cluster:String}",
                parameters={"cluster": self._cluster_name},
            )
            has_cluster = rows.first_row[0] > 0 if rows.result_rows else False
        except Exception:
            has_cluster = False

        if has_cluster:
            client.command(_CHECK_RESULTS_DDL.format(cluster=self._cluster_name))
            for idx_sql in _CHECK_RESULTS_INDEXES:
                try:
                    client.command(idx_sql)
                except Exception:
                    pass  # index may already exist
            # Add new columns to existing tables
            _NEW_COLUMNS = [
                ("started_at", "DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3)"),
                ("collector_name", "String DEFAULT ''"),
            ]
            for col_name, col_def in _NEW_COLUMNS:
                try:
                    client.command(f"ALTER TABLE check_results ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
                except Exception:
                    pass
            self._ensure_mv_columns()
            client.command(_CHECK_RESULTS_LATEST_DDL.format(cluster=self._cluster_name))
            client.command(_EVENTS_DDL.format(cluster=self._cluster_name))
        else:
            logger.info("No ClickHouse cluster detected, using local MergeTree engines")
            client.command(_CHECK_RESULTS_DDL_LOCAL)
            for idx_sql in _CHECK_RESULTS_INDEXES:
                try:
                    client.command(idx_sql)
                except Exception:
                    pass
            # Add new columns to existing tables
            _NEW_COLUMNS = [
                ("started_at", "DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3)"),
                ("collector_name", "String DEFAULT ''"),
            ]
            for col_name, col_def in _NEW_COLUMNS:
                try:
                    client.command(f"ALTER TABLE check_results ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
                except Exception:
                    pass
            self._ensure_mv_columns()
            client.command(_CHECK_RESULTS_LATEST_DDL_LOCAL)
            client.command(_EVENTS_DDL_LOCAL)

        logger.info("ClickHouse tables ensured")

    def insert_check_results(self, results: list[dict]) -> None:
        """Batch insert check results. Uses async insert for high throughput."""
        if not results:
            return
        client = self._get_client()
        data = []
        for r in results:
            row = [r.get(col) for col in _INSERT_COLUMNS]
            data.append(row)
        client.insert(
            "check_results",
            data,
            column_names=_INSERT_COLUMNS,
        )

    def insert_events(self, events: list[dict]) -> None:
        """Batch insert events."""
        if not events:
            return
        client = self._get_client()
        data = []
        for e in events:
            row = [e.get(col) for col in _EVENT_INSERT_COLUMNS]
            data.append(row)
        client.insert(
            "events",
            data,
            column_names=_EVENT_INSERT_COLUMNS,
        )

    def query_latest(
        self,
        *,
        tenant_id: str | None = None,
        device_id: str | None = None,
        collector_id: str | None = None,
    ) -> list[dict]:
        """Query latest result per assignment from the materialized view."""
        client = self._get_client()
        sql = "SELECT * FROM check_results_latest FINAL"
        wheres: list[str] = []
        params: dict[str, Any] = {}

        if tenant_id:
            wheres.append("tenant_id = {tenant_id:UUID}")
            params["tenant_id"] = tenant_id
        if device_id:
            wheres.append("device_id = {device_id:UUID}")
            params["device_id"] = device_id
        if collector_id:
            wheres.append("collector_id = {collector_id:UUID}")
            params["collector_id"] = collector_id

        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY executed_at DESC"

        result = client.query(sql, parameters=params)
        return result.named_results()

    def query_by_device(self, device_id: str) -> list[dict]:
        """Query latest results for a specific device."""
        return self.query_latest(device_id=device_id)

    def query_history(
        self,
        *,
        assignment_id: str | None = None,
        device_id: str | None = None,
        collector_id: str | None = None,
        app_id: str | None = None,
        state: int | None = None,
        tenant_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Query historical check results with filters."""
        client = self._get_client()
        sql = "SELECT * FROM check_results"
        wheres: list[str] = []
        params: dict[str, Any] = {}

        if assignment_id:
            wheres.append("assignment_id = {assignment_id:UUID}")
            params["assignment_id"] = assignment_id
        if device_id:
            wheres.append("device_id = {device_id:UUID}")
            params["device_id"] = device_id
        if collector_id:
            wheres.append("collector_id = {collector_id:UUID}")
            params["collector_id"] = collector_id
        if app_id:
            wheres.append("app_id = {app_id:UUID}")
            params["app_id"] = app_id
        if state is not None:
            wheres.append("state = {state:UInt8}")
            params["state"] = state
        if tenant_id:
            wheres.append("tenant_id = {tenant_id:UUID}")
            params["tenant_id"] = tenant_id
        if from_ts:
            wheres.append("executed_at >= {from_ts:DateTime64(3)}")
            params["from_ts"] = from_ts
        if to_ts:
            wheres.append("executed_at <= {to_ts:DateTime64(3)}")
            params["to_ts"] = to_ts

        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY executed_at DESC"
        sql += f" LIMIT {limit} OFFSET {offset}"

        result = client.query(sql, parameters=params)
        return result.named_results()

    def query_for_alert(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Execute an arbitrary read query for alert evaluation."""
        client = self._get_client()
        result = client.query(sql, parameters=params or {})
        return result.named_results()
