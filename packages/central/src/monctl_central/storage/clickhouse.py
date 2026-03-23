"""ClickHouse client wrapper for time-series data storage.

Handles 4 domain-specific tables:
  - availability_latency: ping, HTTP, port checks
  - performance: CPU, memory, disk, custom metrics
  - interface: network interface statistics
  - config: configuration/discovery data
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table definitions — clustered (ReplicatedMergeTree)
# ---------------------------------------------------------------------------

_AVAILABILITY_LATENCY_DDL = """
CREATE TABLE IF NOT EXISTS availability_latency ON CLUSTER '{cluster}'
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

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),
    execution_time     Float32       DEFAULT 0,
    started_at         DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    role               String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT '',

)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/availability_latency', '{{replica}}'
)
PARTITION BY toYYYYMM(executed_at)
ORDER BY (assignment_id, executed_at)
SETTINGS index_granularity = 8192
"""

_AVAILABILITY_LATENCY_LATEST_DDL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS availability_latency_latest ON CLUSTER '{cluster}'
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{{shard}}/availability_latency_latest', '{{replica}}',
    executed_at
)
ORDER BY (assignment_id)
AS SELECT * FROM availability_latency
"""

_PERFORMANCE_DDL = """
CREATE TABLE IF NOT EXISTS performance ON CLUSTER '{cluster}'
(
    assignment_id      UUID,
    collector_id       UUID,
    app_id             UUID,
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    component          String        DEFAULT '',
    component_type     String        DEFAULT '',

    state              UInt8,
    output             String        DEFAULT '',
    error_message      String        DEFAULT '',

    metric_names       Array(String)   DEFAULT [],
    metric_values      Array(Float64)  DEFAULT [],
    metric_types       Array(String)   DEFAULT [],

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),
    execution_time     Float32       DEFAULT 0,
    started_at         DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT '',

)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/performance', '{{replica}}'
)
PARTITION BY toYYYYMM(executed_at)
ORDER BY (device_id, component_type, component, executed_at)
SETTINGS index_granularity = 8192
"""

_PERFORMANCE_LATEST_DDL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS performance_latest ON CLUSTER '{cluster}'
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{{shard}}/performance_latest', '{{replica}}',
    executed_at
)
ORDER BY (device_id, component_type, component)
AS SELECT * FROM performance
"""

_INTERFACE_DDL = """
CREATE TABLE IF NOT EXISTS interface ON CLUSTER '{cluster}'
(
    assignment_id      UUID,
    collector_id       UUID,
    app_id             UUID,
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    interface_id       UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    if_index           UInt32        DEFAULT 0,
    if_name            String        DEFAULT '',
    if_alias           String        DEFAULT '',
    if_speed_mbps      UInt32        DEFAULT 0,
    if_admin_status    String        DEFAULT '',
    if_oper_status     String        DEFAULT '',

    in_octets          UInt64        DEFAULT 0,
    out_octets         UInt64        DEFAULT 0,
    in_errors          UInt64        DEFAULT 0,
    out_errors         UInt64        DEFAULT 0,
    in_discards        UInt64        DEFAULT 0,
    out_discards       UInt64        DEFAULT 0,
    in_unicast_pkts    UInt64        DEFAULT 0,
    out_unicast_pkts   UInt64        DEFAULT 0,

    in_rate_bps        Float64       DEFAULT 0,
    out_rate_bps       Float64       DEFAULT 0,
    in_utilization_pct Float32       DEFAULT 0,
    out_utilization_pct Float32      DEFAULT 0,
    poll_interval_sec  UInt16        DEFAULT 0,

    state              UInt8         DEFAULT 0,

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT '',

)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/interface', '{{replica}}'
)
PARTITION BY toYYYYMM(executed_at)
ORDER BY (device_id, interface_id, executed_at)
SETTINGS index_granularity = 8192
"""

_INTERFACE_LATEST_DDL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS interface_latest ON CLUSTER '{cluster}'
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{{shard}}/interface_latest', '{{replica}}',
    executed_at
)
ORDER BY (device_id, interface_id)
AS SELECT * FROM interface
"""

_CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS config ON CLUSTER '{cluster}'
(
    assignment_id      UUID,
    collector_id       UUID,
    app_id             UUID,
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    component          String        DEFAULT '',
    component_type     String        DEFAULT '',

    config_key         String        DEFAULT '',
    config_value       String        DEFAULT '',
    config_hash        String        DEFAULT '',

    state              UInt8         DEFAULT 0,

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT '',

)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/config', '{{replica}}'
)
PARTITION BY toYYYYMM(executed_at)
ORDER BY (device_id, component_type, component, config_key, executed_at)
SETTINGS index_granularity = 8192
"""

_CONFIG_LATEST_DDL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS config_latest ON CLUSTER '{cluster}'
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{{shard}}/config_latest', '{{replica}}',
    executed_at
)
ORDER BY (device_id, component_type, component, config_key)
AS SELECT * FROM config
"""

# ---------------------------------------------------------------------------
# Non-clustered fallback DDL (single-node / dev)
# ---------------------------------------------------------------------------

_AVAILABILITY_LATENCY_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS availability_latency
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

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),
    execution_time     Float32       DEFAULT 0,
    started_at         DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    role               String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT '',

)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(executed_at)
ORDER BY (assignment_id, executed_at)
SETTINGS index_granularity = 8192
"""

_AVAILABILITY_LATENCY_LATEST_DDL_LOCAL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS availability_latency_latest
ENGINE = ReplacingMergeTree(executed_at)
ORDER BY (assignment_id)
AS SELECT * FROM availability_latency
"""

_PERFORMANCE_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS performance
(
    assignment_id      UUID,
    collector_id       UUID,
    app_id             UUID,
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    component          String        DEFAULT '',
    component_type     String        DEFAULT '',

    state              UInt8,
    output             String        DEFAULT '',
    error_message      String        DEFAULT '',

    metric_names       Array(String)   DEFAULT [],
    metric_values      Array(Float64)  DEFAULT [],
    metric_types       Array(String)   DEFAULT [],

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),
    execution_time     Float32       DEFAULT 0,
    started_at         DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT '',

)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(executed_at)
ORDER BY (device_id, component_type, component, executed_at)
SETTINGS index_granularity = 8192
"""

_PERFORMANCE_LATEST_DDL_LOCAL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS performance_latest
ENGINE = ReplacingMergeTree(executed_at)
ORDER BY (device_id, component_type, component)
AS SELECT * FROM performance
"""

_INTERFACE_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS interface
(
    assignment_id      UUID,
    collector_id       UUID,
    app_id             UUID,
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    interface_id       UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    if_index           UInt32        DEFAULT 0,
    if_name            String        DEFAULT '',
    if_alias           String        DEFAULT '',
    if_speed_mbps      UInt32        DEFAULT 0,
    if_admin_status    String        DEFAULT '',
    if_oper_status     String        DEFAULT '',

    in_octets          UInt64        DEFAULT 0,
    out_octets         UInt64        DEFAULT 0,
    in_errors          UInt64        DEFAULT 0,
    out_errors         UInt64        DEFAULT 0,
    in_discards        UInt64        DEFAULT 0,
    out_discards       UInt64        DEFAULT 0,
    in_unicast_pkts    UInt64        DEFAULT 0,
    out_unicast_pkts   UInt64        DEFAULT 0,

    in_rate_bps        Float64       DEFAULT 0,
    out_rate_bps       Float64       DEFAULT 0,
    in_utilization_pct Float32       DEFAULT 0,
    out_utilization_pct Float32      DEFAULT 0,
    poll_interval_sec  UInt16        DEFAULT 0,

    state              UInt8         DEFAULT 0,

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT '',

)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(executed_at)
ORDER BY (device_id, interface_id, executed_at)
SETTINGS index_granularity = 8192
"""

_INTERFACE_LATEST_DDL_LOCAL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS interface_latest
ENGINE = ReplacingMergeTree(executed_at)
ORDER BY (device_id, interface_id)
AS SELECT * FROM interface
"""

_CONFIG_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS config
(
    assignment_id      UUID,
    collector_id       UUID,
    app_id             UUID,
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    component          String        DEFAULT '',
    component_type     String        DEFAULT '',

    config_key         String        DEFAULT '',
    config_value       String        DEFAULT '',
    config_hash        String        DEFAULT '',

    state              UInt8         DEFAULT 0,

    executed_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT '',

)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(executed_at)
ORDER BY (device_id, component_type, component, config_key, executed_at)
SETTINGS index_granularity = 8192
"""

_CONFIG_LATEST_DDL_LOCAL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS config_latest
ENGINE = ReplacingMergeTree(executed_at)
ORDER BY (device_id, component_type, component, config_key)
AS SELECT * FROM config
"""

# ---------------------------------------------------------------------------
# Events table
# ---------------------------------------------------------------------------

_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events ON CLUSTER '{cluster}'
(
    id                 UUID          DEFAULT generateUUIDv4(),
    event_type         String        DEFAULT 'alert',

    definition_id      UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    definition_name    String        DEFAULT '',
    policy_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    policy_name        String        DEFAULT '',

    collector_id       UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    app_id             UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    assignment_id      UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    source             String        DEFAULT '',
    severity           String        DEFAULT 'info',
    message            String        DEFAULT '',
    data               String        DEFAULT '{{}}',

    state              String        DEFAULT 'active',
    acknowledged_at    DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),
    acknowledged_by    String        DEFAULT '',
    cleared_at         DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),
    cleared_by         String        DEFAULT '',

    occurred_at        DateTime64(3, 'UTC'),
    resolved_at        DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT ''
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/events', '{{replica}}'
)
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, severity, occurred_at, id)
SETTINGS index_granularity = 8192
"""

_EVENTS_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS events
(
    id                 UUID          DEFAULT generateUUIDv4(),
    event_type         String        DEFAULT 'alert',

    definition_id      UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    definition_name    String        DEFAULT '',
    policy_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    policy_name        String        DEFAULT '',

    collector_id       UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    app_id             UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    assignment_id      UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),

    source             String        DEFAULT '',
    severity           String        DEFAULT 'info',
    message            String        DEFAULT '',
    data               String        DEFAULT '{}',

    state              String        DEFAULT 'active',
    acknowledged_at    DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),
    acknowledged_by    String        DEFAULT '',
    cleared_at         DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),
    cleared_by         String        DEFAULT '',

    occurred_at        DateTime64(3, 'UTC'),
    resolved_at        DateTime64(3, 'UTC') DEFAULT toDateTime64(0, 3),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3),

    collector_name     String        DEFAULT '',
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT ''
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, severity, occurred_at, id)
SETTINGS index_granularity = 8192
"""

_EVENTS_INSERT_COLUMNS = [
    "event_type", "definition_id", "definition_name",
    "policy_id", "policy_name",
    "collector_id", "device_id", "app_id", "assignment_id", "tenant_id",
    "source", "severity", "message", "data",
    "state", "occurred_at",
    "collector_name", "device_name", "app_name",
]

# ---------------------------------------------------------------------------
# Alert log table
# ---------------------------------------------------------------------------

_ALERT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS alert_log ON CLUSTER '{cluster}'
(
    id                 UUID          DEFAULT generateUUIDv4(),
    definition_id      UUID,
    definition_name    String        DEFAULT '',
    entity_key         String,
    action             String,
    severity           String        DEFAULT 'warning',
    current_value      Float64       DEFAULT 0,
    threshold_value    Float64       DEFAULT 0,
    expression         String        DEFAULT '',
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    device_name        String        DEFAULT '',
    assignment_id      UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    app_id             UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    entity_labels      String        DEFAULT '{{}}',
    fire_count         UInt32        DEFAULT 0,
    message            String        DEFAULT '',
    occurred_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/alert_log', '{{replica}}'
)
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, definition_id, entity_key, occurred_at)
SETTINGS index_granularity = 8192
"""

_ALERT_LOG_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS alert_log
(
    id                 UUID          DEFAULT generateUUIDv4(),
    definition_id      UUID,
    definition_name    String        DEFAULT '',
    entity_key         String,
    action             String,
    severity           String        DEFAULT 'warning',
    current_value      Float64       DEFAULT 0,
    threshold_value    Float64       DEFAULT 0,
    expression         String        DEFAULT '',
    device_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    device_name        String        DEFAULT '',
    assignment_id      UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    app_id             UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    entity_labels      String        DEFAULT '{}',
    fire_count         UInt32        DEFAULT 0,
    message            String        DEFAULT '',
    occurred_at        DateTime64(3, 'UTC'),
    received_at        DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, definition_id, entity_key, occurred_at)
SETTINGS index_granularity = 8192
"""

_ALERT_LOG_INSERT_COLUMNS = [
    "definition_id", "definition_name", "entity_key",
    "action", "severity",
    "current_value", "threshold_value", "expression",
    "device_id", "device_name",
    "assignment_id", "app_id", "app_name", "tenant_id",
    "entity_labels", "fire_count", "message",
    "occurred_at",
]

# ---------------------------------------------------------------------------
# Insert column definitions per table
# ---------------------------------------------------------------------------

_AVAIL_INSERT_COLUMNS = [
    "assignment_id", "collector_id", "app_id", "device_id",
    "state", "output", "error_message",
    "rtt_ms", "response_time_ms", "reachable", "status_code",
    "executed_at", "execution_time", "started_at",
    "collector_name", "device_name", "app_name", "role", "tenant_id", "tenant_name",
]

_PERF_INSERT_COLUMNS = [
    "assignment_id", "collector_id", "app_id", "device_id",
    "component", "component_type",
    "state", "output", "error_message",
    "metric_names", "metric_values", "metric_types",
    "executed_at", "execution_time", "started_at",
    "collector_name", "device_name", "app_name", "tenant_id", "tenant_name",
]

_IFACE_INSERT_COLUMNS = [
    "assignment_id", "collector_id", "app_id", "device_id", "interface_id",
    "if_index", "if_name", "if_alias", "if_speed_mbps",
    "if_admin_status", "if_oper_status",
    "in_octets", "out_octets", "in_errors", "out_errors",
    "in_discards", "out_discards", "in_unicast_pkts", "out_unicast_pkts",
    "in_rate_bps", "out_rate_bps", "in_utilization_pct", "out_utilization_pct",
    "poll_interval_sec", "state",
    "executed_at",
    "collector_name", "device_name", "app_name", "tenant_id", "tenant_name",
]

_CONFIG_INSERT_COLUMNS = [
    "assignment_id", "collector_id", "app_id", "device_id",
    "component", "component_type",
    "config_key", "config_value", "config_hash",
    "state", "executed_at",
    "collector_name", "device_name", "app_name", "tenant_id", "tenant_name",
]

# Old tables to drop
_OLD_TABLES = [
    "check_results_latest",  # MV must be dropped before base table
    "check_results",
]

# Interface tables to recreate (ORDER BY changed to use interface_id)
_INTERFACE_RECREATE = [
    "interface_latest",  # MV must be dropped before base table
    "interface",
]

# ---------------------------------------------------------------------------
# Rollup table definitions
# ---------------------------------------------------------------------------

_ROLLUP_COLUMNS = """
    device_id          UUID,
    interface_id       UUID,
    {time_col}         DateTime('UTC'),
    in_rate_min        Float64       DEFAULT 0,
    in_rate_max        Float64       DEFAULT 0,
    in_rate_avg        Float64       DEFAULT 0,
    in_rate_p95        Float64       DEFAULT 0,
    out_rate_min       Float64       DEFAULT 0,
    out_rate_max       Float64       DEFAULT 0,
    out_rate_avg       Float64       DEFAULT 0,
    out_rate_p95       Float64       DEFAULT 0,
    in_utilization_max Float32       DEFAULT 0,
    in_utilization_avg Float32       DEFAULT 0,
    out_utilization_max Float32      DEFAULT 0,
    out_utilization_avg Float32      DEFAULT 0,
    in_octets_total    UInt64        DEFAULT 0,
    out_octets_total   UInt64        DEFAULT 0,
    in_errors_total    UInt64        DEFAULT 0,
    out_errors_total   UInt64        DEFAULT 0,
    in_discards_total  UInt64        DEFAULT 0,
    out_discards_total UInt64        DEFAULT 0,
    availability_pct   Float32       DEFAULT 0,
    sample_count       UInt16        DEFAULT 0,
    if_speed_mbps      UInt32        DEFAULT 0,
    device_name        String        DEFAULT '',
    if_name            String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT ''
"""

_INTERFACE_HOURLY_DDL = """
CREATE TABLE IF NOT EXISTS interface_hourly ON CLUSTER '{cluster}'
(
""" + _ROLLUP_COLUMNS.format(time_col="hour") + """
)
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{{shard}}/interface_hourly', '{{replica}}',
    hour
)
PARTITION BY toYYYYMM(hour)
ORDER BY (device_id, interface_id, hour)
SETTINGS index_granularity = 8192
"""

_INTERFACE_DAILY_DDL = """
CREATE TABLE IF NOT EXISTS interface_daily ON CLUSTER '{cluster}'
(
""" + _ROLLUP_COLUMNS.format(time_col="day") + """
)
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{{shard}}/interface_daily', '{{replica}}',
    day
)
PARTITION BY toYear(day)
ORDER BY (device_id, interface_id, day)
SETTINGS index_granularity = 8192
"""

_PERF_ROLLUP_COLUMNS = """
    device_id          UUID,
    app_id             UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    component_type     String        DEFAULT '',
    component          String        DEFAULT '',
    metric_name        String        DEFAULT '',
    metric_type        String        DEFAULT 'gauge',
    {time_col}         DateTime('UTC'),

    val_min            Float64       DEFAULT 0,
    val_max            Float64       DEFAULT 0,
    val_avg            Float64       DEFAULT 0,
    val_p95            Float64       DEFAULT 0,
    sample_count       UInt16        DEFAULT 0,

    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT ''
"""

_PERFORMANCE_HOURLY_DDL = """
CREATE TABLE IF NOT EXISTS performance_hourly ON CLUSTER '{cluster}'
(
""" + _PERF_ROLLUP_COLUMNS.format(time_col="hour") + """
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/performance_hourly', '{{replica}}'
)
PARTITION BY toYYYYMM(hour)
ORDER BY (device_id, component_type, component, metric_name, hour)
SETTINGS index_granularity = 8192
"""

_PERFORMANCE_DAILY_DDL = """
CREATE TABLE IF NOT EXISTS performance_daily ON CLUSTER '{cluster}'
(
""" + _PERF_ROLLUP_COLUMNS.format(time_col="day") + """
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{{shard}}/performance_daily', '{{replica}}'
)
PARTITION BY toYear(day)
ORDER BY (device_id, component_type, component, metric_name, day)
SETTINGS index_granularity = 8192
"""

_INTERFACE_HOURLY_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS interface_hourly
(
""" + _ROLLUP_COLUMNS.format(time_col="hour") + """
)
ENGINE = ReplacingMergeTree(hour)
PARTITION BY toYYYYMM(hour)
ORDER BY (device_id, interface_id, hour)
SETTINGS index_granularity = 8192
"""

_INTERFACE_DAILY_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS interface_daily
(
""" + _ROLLUP_COLUMNS.format(time_col="day") + """
)
ENGINE = ReplacingMergeTree(day)
PARTITION BY toYear(day)
ORDER BY (device_id, interface_id, day)
SETTINGS index_granularity = 8192
"""

_PERFORMANCE_HOURLY_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS performance_hourly
(
""" + _PERF_ROLLUP_COLUMNS.format(time_col="hour") + """
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (device_id, component_type, component, metric_name, hour)
SETTINGS index_granularity = 8192
"""

_PERFORMANCE_DAILY_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS performance_daily
(
""" + _PERF_ROLLUP_COLUMNS.format(time_col="day") + """
)
ENGINE = MergeTree()
PARTITION BY toYear(day)
ORDER BY (device_id, component_type, component, metric_name, day)
SETTINGS index_granularity = 8192
"""

# ---------------------------------------------------------------------------
# Availability/Latency rollup tables
# ---------------------------------------------------------------------------

_AVAIL_ROLLUP_COLUMNS = """
    device_id          UUID,
    assignment_id      UUID,
    app_id             UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    {time_col}         DateTime('UTC'),
    rtt_min            Float64       DEFAULT 0,
    rtt_max            Float64       DEFAULT 0,
    rtt_avg            Float64       DEFAULT 0,
    rtt_p95            Float64       DEFAULT 0,
    response_time_min  Float64       DEFAULT 0,
    response_time_max  Float64       DEFAULT 0,
    response_time_avg  Float64       DEFAULT 0,
    response_time_p95  Float64       DEFAULT 0,
    availability_pct   Float32       DEFAULT 0,
    sample_count       UInt16        DEFAULT 0,
    device_name        String        DEFAULT '',
    app_name           String        DEFAULT '',
    tenant_id          UUID          DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    tenant_name        String        DEFAULT ''
"""

_AVAIL_HOURLY_DDL = """
CREATE TABLE IF NOT EXISTS availability_latency_hourly ON CLUSTER '{cluster}'
(
""" + _AVAIL_ROLLUP_COLUMNS.format(time_col="hour") + """
)
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{{shard}}/availability_latency_hourly', '{{replica}}',
    hour
)
PARTITION BY toYYYYMM(hour)
ORDER BY (device_id, assignment_id, hour)
SETTINGS index_granularity = 8192
"""

_AVAIL_DAILY_DDL = """
CREATE TABLE IF NOT EXISTS availability_latency_daily ON CLUSTER '{cluster}'
(
""" + _AVAIL_ROLLUP_COLUMNS.format(time_col="day") + """
)
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{{shard}}/availability_latency_daily', '{{replica}}',
    day
)
PARTITION BY toYear(day)
ORDER BY (device_id, assignment_id, day)
SETTINGS index_granularity = 8192
"""

_AVAIL_HOURLY_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS availability_latency_hourly
(
""" + _AVAIL_ROLLUP_COLUMNS.format(time_col="hour") + """
)
ENGINE = ReplacingMergeTree(hour)
PARTITION BY toYYYYMM(hour)
ORDER BY (device_id, assignment_id, hour)
SETTINGS index_granularity = 8192
"""

_AVAIL_DAILY_DDL_LOCAL = """
CREATE TABLE IF NOT EXISTS availability_latency_daily
(
""" + _AVAIL_ROLLUP_COLUMNS.format(time_col="day") + """
)
ENGINE = ReplacingMergeTree(day)
PARTITION BY toYear(day)
ORDER BY (device_id, assignment_id, day)
SETTINGS index_granularity = 8192
"""


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
                settings["wait_for_async_insert"] = 1
            self._client = clickhouse_connect.get_client(
                host=self._hosts[0],
                port=self._port,
                username=self._username,
                password=self._password,
                database=self._database,
                settings=settings,
            )
        return self._client

    def _reconnect(self) -> Client:
        """Drop cached client and create a fresh connection."""
        logger.warning("ClickHouse reconnecting to %s", self._hosts[0])
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        return self._get_client()

    def _is_connection_error(self, exc: Exception) -> bool:
        """Check if an exception is a connection/transport error worth retrying."""
        # Connection refused, broken pipe, timeout, etc.
        if isinstance(exc, (OSError, ConnectionError, TimeoutError)):
            return True
        # clickhouse-connect wraps some errors as DatabaseError
        msg = str(exc).lower()
        if any(s in msg for s in ("broken pipe", "connection refused", "timed out", "reset by peer")):
            return True
        return False

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _drop_old_tables(self, has_cluster: bool) -> None:
        """Drop legacy check_results / events tables (only test data)."""
        client = self._get_client()
        for table in _OLD_TABLES:
            try:
                if has_cluster:
                    client.command(f"DROP TABLE IF EXISTS {table} ON CLUSTER '{self._cluster_name}'")
                else:
                    client.command(f"DROP TABLE IF EXISTS {table}")
                logger.info("Dropped old table %s", table)
            except Exception:
                logger.debug("Could not drop old table %s (may not exist)", table)

    def _recreate_interface_tables(self, has_cluster: bool) -> None:
        """Drop and recreate interface tables to update ORDER BY to use interface_id.

        Safe to run — no existing interface data in production.
        Only drops if the table exists and uses the old ORDER BY (if_index).
        """
        client = self._get_client()
        try:
            # Check if interface table exists and uses old ORDER BY
            result = client.query(
                "SELECT create_table_query FROM system.tables "
                "WHERE database = {db:String} AND name = 'interface'",
                parameters={"db": self._database},
            )
            if not result.result_rows:
                return  # Table doesn't exist yet, will be created normally
            create_query = result.first_row[0]
            if "interface_id" in create_query:
                return  # Already has interface_id in ORDER BY
        except Exception:
            return  # Can't check, skip recreation

        logger.info("Recreating interface tables with interface_id ORDER BY")
        for table in _INTERFACE_RECREATE:
            try:
                if has_cluster:
                    client.command(f"DROP TABLE IF EXISTS {table} ON CLUSTER '{self._cluster_name}'")
                else:
                    client.command(f"DROP TABLE IF EXISTS {table}")
                logger.info("Dropped interface table %s for recreation", table)
            except Exception:
                logger.warning("Could not drop interface table %s", table)

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

        # Drop old tables first
        self._drop_old_tables(has_cluster)

        # Recreate interface tables with updated ORDER BY (interface_id instead of if_index)
        self._recreate_interface_tables(has_cluster)

        if has_cluster:
            for ddl in [
                _AVAILABILITY_LATENCY_DDL,
                _PERFORMANCE_DDL,
                _INTERFACE_DDL,
                _CONFIG_DDL,
                _EVENTS_DDL,
                _ALERT_LOG_DDL,
                _INTERFACE_HOURLY_DDL,
                _INTERFACE_DAILY_DDL,
                _PERFORMANCE_HOURLY_DDL,
                _PERFORMANCE_DAILY_DDL,
                _AVAIL_HOURLY_DDL,
                _AVAIL_DAILY_DDL,
            ]:
                client.command(ddl.format(cluster=self._cluster_name))
            for mv_ddl in [
                _AVAILABILITY_LATENCY_LATEST_DDL,
                _PERFORMANCE_LATEST_DDL,
                _INTERFACE_LATEST_DDL,
                _CONFIG_LATEST_DDL,
            ]:
                client.command(mv_ddl.format(cluster=self._cluster_name))
        else:
            logger.info("No ClickHouse cluster detected, using local MergeTree engines")
            for ddl in [
                _AVAILABILITY_LATENCY_DDL_LOCAL,
                _PERFORMANCE_DDL_LOCAL,
                _INTERFACE_DDL_LOCAL,
                _CONFIG_DDL_LOCAL,
                _EVENTS_DDL_LOCAL,
                _ALERT_LOG_DDL_LOCAL,
                _INTERFACE_HOURLY_DDL_LOCAL,
                _INTERFACE_DAILY_DDL_LOCAL,
                _PERFORMANCE_HOURLY_DDL_LOCAL,
                _PERFORMANCE_DAILY_DDL_LOCAL,
                _AVAIL_HOURLY_DDL_LOCAL,
                _AVAIL_DAILY_DDL_LOCAL,
            ]:
                client.command(ddl)
            for mv_ddl in [
                _AVAILABILITY_LATENCY_LATEST_DDL_LOCAL,
                _PERFORMANCE_LATEST_DDL_LOCAL,
                _INTERFACE_LATEST_DDL_LOCAL,
                _CONFIG_LATEST_DDL_LOCAL,
            ]:
                client.command(mv_ddl)

        # Add tenant_name column to existing tables (safe to run if column already exists)
        _TENANT_NAME_ALTERS = [
            "ALTER TABLE availability_latency ADD COLUMN IF NOT EXISTS tenant_name String DEFAULT ''",
            "ALTER TABLE performance ADD COLUMN IF NOT EXISTS tenant_name String DEFAULT ''",
            "ALTER TABLE interface ADD COLUMN IF NOT EXISTS tenant_name String DEFAULT ''",
            "ALTER TABLE config ADD COLUMN IF NOT EXISTS tenant_name String DEFAULT ''",
            "ALTER TABLE interface_hourly ADD COLUMN IF NOT EXISTS tenant_name String DEFAULT ''",
            "ALTER TABLE interface_daily ADD COLUMN IF NOT EXISTS tenant_name String DEFAULT ''",
            # Add metric_types to performance tables
            "ALTER TABLE performance ADD COLUMN IF NOT EXISTS metric_types Array(String) DEFAULT [] AFTER metric_values",
        ]
        for alter_sql in _TENANT_NAME_ALTERS:
            try:
                client.command(alter_sql)
            except Exception:
                pass

        # Add bloom filter indexes via ALTER TABLE (ClickHouse 24.x compat)
        _INDEXES = [
            # availability_latency
            "ALTER TABLE availability_latency ADD INDEX IF NOT EXISTS idx_device bloom_filter(device_id) GRANULARITY 4",
            "ALTER TABLE availability_latency ADD INDEX IF NOT EXISTS idx_collector bloom_filter(collector_id) GRANULARITY 4",
            "ALTER TABLE availability_latency ADD INDEX IF NOT EXISTS idx_tenant bloom_filter(tenant_id) GRANULARITY 4",
            "ALTER TABLE availability_latency ADD INDEX IF NOT EXISTS idx_state set(state) GRANULARITY 4",
            # performance
            "ALTER TABLE performance ADD INDEX IF NOT EXISTS idx_device bloom_filter(device_id) GRANULARITY 4",
            "ALTER TABLE performance ADD INDEX IF NOT EXISTS idx_collector bloom_filter(collector_id) GRANULARITY 4",
            "ALTER TABLE performance ADD INDEX IF NOT EXISTS idx_tenant bloom_filter(tenant_id) GRANULARITY 4",
            "ALTER TABLE performance ADD INDEX IF NOT EXISTS idx_state set(state) GRANULARITY 4",
            # interface
            "ALTER TABLE interface ADD INDEX IF NOT EXISTS idx_device bloom_filter(device_id) GRANULARITY 4",
            "ALTER TABLE interface ADD INDEX IF NOT EXISTS idx_iface bloom_filter(interface_id) GRANULARITY 4",
            "ALTER TABLE interface ADD INDEX IF NOT EXISTS idx_collector bloom_filter(collector_id) GRANULARITY 4",
            "ALTER TABLE interface ADD INDEX IF NOT EXISTS idx_tenant bloom_filter(tenant_id) GRANULARITY 4",
            # config
            "ALTER TABLE config ADD INDEX IF NOT EXISTS idx_device bloom_filter(device_id) GRANULARITY 4",
            "ALTER TABLE config ADD INDEX IF NOT EXISTS idx_collector bloom_filter(collector_id) GRANULARITY 4",
            "ALTER TABLE config ADD INDEX IF NOT EXISTS idx_tenant bloom_filter(tenant_id) GRANULARITY 4",
            # events
            "ALTER TABLE events ADD INDEX IF NOT EXISTS idx_device bloom_filter(device_id) GRANULARITY 4",
            "ALTER TABLE events ADD INDEX IF NOT EXISTS idx_tenant bloom_filter(tenant_id) GRANULARITY 4",
            "ALTER TABLE events ADD INDEX IF NOT EXISTS idx_policy bloom_filter(policy_id) GRANULARITY 4",
            "ALTER TABLE events ADD INDEX IF NOT EXISTS idx_state set(state) GRANULARITY 4",
            "ALTER TABLE events ADD INDEX IF NOT EXISTS idx_severity set(severity) GRANULARITY 4",
            # alert_log
            "ALTER TABLE alert_log ADD INDEX IF NOT EXISTS idx_definition bloom_filter(definition_id) GRANULARITY 4",
            "ALTER TABLE alert_log ADD INDEX IF NOT EXISTS idx_device bloom_filter(device_id) GRANULARITY 4",
            "ALTER TABLE alert_log ADD INDEX IF NOT EXISTS idx_tenant bloom_filter(tenant_id) GRANULARITY 4",
            "ALTER TABLE alert_log ADD INDEX IF NOT EXISTS idx_action set(action) GRANULARITY 4",
            "ALTER TABLE alert_log ADD INDEX IF NOT EXISTS idx_severity set(severity) GRANULARITY 4",
        ]
        for idx_sql in _INDEXES:
            try:
                client.command(idx_sql)
            except Exception:
                pass

        logger.info("ClickHouse tables ensured (4 domain tables + events + alert_log + materialized views)")

    # ------------------------------------------------------------------
    # Insert methods
    # ------------------------------------------------------------------

    def insert_availability_latency(self, results: list[dict]) -> None:
        """Batch insert availability/latency results."""
        if not results:
            return
        client = self._get_client()
        data = [[r.get(col) for col in _AVAIL_INSERT_COLUMNS] for r in results]
        client.insert("availability_latency", data, column_names=_AVAIL_INSERT_COLUMNS)

    def insert_performance(self, results: list[dict]) -> None:
        """Batch insert performance results."""
        if not results:
            return
        client = self._get_client()
        data = [[r.get(col) for col in _PERF_INSERT_COLUMNS] for r in results]
        client.insert("performance", data, column_names=_PERF_INSERT_COLUMNS)

    # Columns that must never be None (ClickHouse UInt/Float, no Nullable)
    _IFACE_NUMERIC_DEFAULTS: dict[str, int | float] = {
        "if_index": 0, "if_speed_mbps": 0,
        "in_octets": 0, "out_octets": 0,
        "in_errors": 0, "out_errors": 0,
        "in_discards": 0, "out_discards": 0,
        "in_unicast_pkts": 0, "out_unicast_pkts": 0,
        "in_rate_bps": 0.0, "out_rate_bps": 0.0,
        "in_utilization_pct": 0.0, "out_utilization_pct": 0.0,
        "poll_interval_sec": 0, "state": 0,
    }

    def insert_interface(self, results: list[dict]) -> None:
        """Batch insert interface results."""
        if not results:
            return
        client = self._get_client()
        nd = self._IFACE_NUMERIC_DEFAULTS
        data = [
            [r.get(col) if r.get(col) is not None else nd.get(col, r.get(col))
             for col in _IFACE_INSERT_COLUMNS]
            for r in results
        ]
        client.insert("interface", data, column_names=_IFACE_INSERT_COLUMNS)

    def insert_config(self, results: list[dict]) -> None:
        """Batch insert config results."""
        if not results:
            return
        client = self._get_client()
        data = [[r.get(col) for col in _CONFIG_INSERT_COLUMNS] for r in results]
        client.insert("config", data, column_names=_CONFIG_INSERT_COLUMNS)

    def get_config_hashes(self, device_id: str, app_id: str) -> dict[tuple[str, str, str], str]:
        """Return current config_hash values from config_latest for a device+app.

        Returns: dict mapping (component_type, component, config_key) -> config_hash
        """
        sql = (
            "SELECT component_type, component, config_key, config_hash "
            "FROM config_latest FINAL "
            "WHERE device_id = {device_id:UUID} AND app_id = {app_id:UUID}"
        )
        try:
            client = self._get_client()
            result = client.query(sql, parameters={
                "device_id": device_id,
                "app_id": app_id,
            })
            return {
                (row["component_type"], row["component"], row["config_key"]): row["config_hash"]
                for row in result.named_results()
            }
        except Exception as exc:
            if self._is_table_missing_error(exc) or self._is_connection_error(exc):
                return {}
            raise

    def insert_by_table(self, table: str, results: list[dict]) -> None:
        """Route inserts to the correct table by name."""
        inserters = {
            "availability_latency": self.insert_availability_latency,
            "performance": self.insert_performance,
            "interface": self.insert_interface,
            "config": self.insert_config,
        }
        fn = inserters.get(table)
        if fn is None:
            logger.warning("Unknown target_table %r, falling back to availability_latency", table)
            self.insert_availability_latency(results)
        else:
            fn(results)

    # ------------------------------------------------------------------
    # Query methods — availability_latency (primary, backward compat)
    # ------------------------------------------------------------------

    def query_latest(
        self,
        *,
        table: str = "availability_latency",
        tenant_id: str | None = None,
        device_id: str | None = None,
        collector_id: str | None = None,
    ) -> list[dict]:
        """Query latest result per key from the materialized view."""
        view = f"{table}_latest"
        sql = f"SELECT * FROM {view} FINAL"
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

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return list(result.named_results())
        except Exception as exc:
            if self._is_connection_error(exc):
                logger.warning("ClickHouse query_latest connection error, retrying: %s", exc)
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                return list(result.named_results())
            raise

    def _is_table_missing_error(self, exc: Exception) -> bool:
        """Check if an exception is due to a missing table/view."""
        msg = str(exc).lower()
        return "unknown table" in msg or "table" in msg and "doesn't exist" in msg

    def query_by_device(self, device_id: str, table: str | None = None) -> list[dict]:
        """Query latest results for a specific device across all tables."""
        if table:
            return self.query_latest(table=table, device_id=device_id)
        # Query all domain tables and merge results
        all_rows: list[dict] = []
        for t in ("availability_latency", "performance", "interface", "config"):
            try:
                rows = list(self.query_latest(table=t, device_id=device_id))
                if rows:
                    logger.debug("query_by_device(%s): %s_latest returned %d rows", device_id, t, len(rows))
                all_rows.extend(rows)
            except Exception as exc:
                if self._is_table_missing_error(exc):
                    logger.debug("Table %s_latest does not exist yet, skipping", t)
                else:
                    logger.error("ClickHouse query failed for table %s, device %s: %s", t, device_id, exc)
                    raise
        if not all_rows:
            logger.warning("query_by_device(%s): all tables returned 0 rows", device_id)
        return all_rows

    def query_history(
        self,
        *,
        table: str = "availability_latency",
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
        """Query historical results with filters."""
        sql = f"SELECT * FROM {table}"
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
            params["from_ts"] = from_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] if hasattr(from_ts, "strftime") else str(from_ts)
        if to_ts:
            wheres.append("executed_at <= {to_ts:DateTime64(3)}")
            params["to_ts"] = to_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] if hasattr(to_ts, "strftime") else str(to_ts)

        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY executed_at DESC"
        sql += f" LIMIT {limit} OFFSET {offset}"

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return list(result.named_results())
        except Exception as exc:
            if self._is_connection_error(exc):
                logger.warning("ClickHouse query_history connection error, retrying: %s", exc)
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                return list(result.named_results())
            raise

    def execute_rollup(self, sql: str, params: dict[str, Any] | None = None) -> None:
        """Execute a rollup INSERT INTO ... SELECT statement."""
        try:
            client = self._get_client()
            client.command(sql, parameters=params or {})
        except Exception as exc:
            if self._is_connection_error(exc):
                client = self._reconnect()
                client.command(sql, parameters=params or {})
            else:
                raise

    def execute_cleanup(self, sql: str) -> None:
        """Execute a data cleanup ALTER TABLE DELETE statement."""
        try:
            client = self._get_client()
            client.command(sql)
        except Exception as exc:
            if self._is_connection_error(exc):
                client = self._reconnect()
                client.command(sql)
            else:
                raise

    def query_for_alert(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Execute an arbitrary read query for alert evaluation."""
        try:
            client = self._get_client()
            result = client.query(sql, parameters=params or {})
            return list(result.named_results())
        except Exception as exc:
            if self._is_connection_error(exc):
                logger.warning("ClickHouse query_for_alert connection error, retrying: %s", exc)
                client = self._reconnect()
                result = client.query(sql, parameters=params or {})
                return list(result.named_results())
            raise

    # ------------------------------------------------------------------
    # Config history methods
    # ------------------------------------------------------------------

    def query_config_changelog(
        self,
        device_id: str,
        *,
        app_id: str | None = None,
        config_key: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """Return config changes for a device, ordered by time descending.

        Each row represents a config write — Phase 2 suppression means
        only actual changes (or volatile keys) are stored.
        """
        sql = (
            "SELECT device_id, device_name, app_id, app_name, "
            "component_type, component, config_key, config_value, "
            "config_hash, executed_at "
            "FROM config "
            "WHERE device_id = {device_id:UUID}"
        )
        params: dict[str, Any] = {"device_id": device_id}

        if app_id:
            sql += " AND app_id = {app_id:UUID}"
            params["app_id"] = app_id
        if config_key:
            sql += " AND config_key = {config_key:String}"
            params["config_key"] = config_key
        if from_ts:
            sql += " AND executed_at >= {from_ts:DateTime64(3)}"
            params["from_ts"] = from_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if to_ts:
            sql += " AND executed_at <= {to_ts:DateTime64(3)}"
            params["to_ts"] = to_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        sql += " ORDER BY executed_at DESC"
        sql += f" LIMIT {limit} OFFSET {offset}"

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return list(result.named_results())
        except Exception as exc:
            if self._is_table_missing_error(exc):
                return []
            if self._is_connection_error(exc):
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                return list(result.named_results())
            raise

    def count_config_changelog(
        self,
        device_id: str,
        *,
        app_id: str | None = None,
        config_key: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> int:
        """Count config change rows for pagination."""
        sql = "SELECT count() AS cnt FROM config WHERE device_id = {device_id:UUID}"
        params: dict[str, Any] = {"device_id": device_id}

        if app_id:
            sql += " AND app_id = {app_id:UUID}"
            params["app_id"] = app_id
        if config_key:
            sql += " AND config_key = {config_key:String}"
            params["config_key"] = config_key
        if from_ts:
            sql += " AND executed_at >= {from_ts:DateTime64(3)}"
            params["from_ts"] = from_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if to_ts:
            sql += " AND executed_at <= {to_ts:DateTime64(3)}"
            params["to_ts"] = to_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            rows = list(result.named_results())
            return rows[0]["cnt"] if rows else 0
        except Exception as exc:
            if self._is_table_missing_error(exc):
                return 0
            if self._is_connection_error(exc):
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                rows = list(result.named_results())
                return rows[0]["cnt"] if rows else 0
            raise

    def query_config_snapshot(
        self,
        device_id: str,
        *,
        app_id: str | None = None,
    ) -> list[dict]:
        """Return the current config snapshot from config_latest FINAL."""
        sql = (
            "SELECT device_id, device_name, app_id, app_name, "
            "component_type, component, config_key, config_value, "
            "config_hash, executed_at "
            "FROM config_latest FINAL "
            "WHERE device_id = {device_id:UUID}"
        )
        params: dict[str, Any] = {"device_id": device_id}

        if app_id:
            sql += " AND app_id = {app_id:UUID}"
            params["app_id"] = app_id

        sql += " ORDER BY component_type, component, config_key"

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return list(result.named_results())
        except Exception as exc:
            if self._is_table_missing_error(exc):
                return []
            if self._is_connection_error(exc):
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                return list(result.named_results())
            raise

    def query_config_change_timestamps(
        self,
        device_id: str,
        *,
        app_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> list[dict]:
        """Return distinct timestamps where config changes occurred.

        Useful for building a timeline of changes.
        """
        sql = (
            "SELECT toStartOfMinute(executed_at) AS change_time, "
            "count() AS change_count, "
            "groupUniqArray(config_key) AS changed_keys "
            "FROM config "
            "WHERE device_id = {device_id:UUID}"
        )
        params: dict[str, Any] = {"device_id": device_id}

        if app_id:
            sql += " AND app_id = {app_id:UUID}"
            params["app_id"] = app_id
        if from_ts:
            sql += " AND executed_at >= {from_ts:DateTime64(3)}"
            params["from_ts"] = from_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if to_ts:
            sql += " AND executed_at <= {to_ts:DateTime64(3)}"
            params["to_ts"] = to_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        sql += " GROUP BY change_time ORDER BY change_time DESC LIMIT 500"

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return list(result.named_results())
        except Exception as exc:
            if self._is_table_missing_error(exc):
                return []
            if self._is_connection_error(exc):
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                return list(result.named_results())
            raise

    def query_config_diff(
        self,
        device_id: str,
        config_key: str,
        *,
        app_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return history for a specific config key, for building diffs."""
        sql = (
            "SELECT device_id, app_id, app_name, "
            "component_type, component, config_key, config_value, "
            "config_hash, executed_at "
            "FROM config "
            "WHERE device_id = {device_id:UUID} "
            "AND config_key = {config_key:String}"
        )
        params: dict[str, Any] = {"device_id": device_id, "config_key": config_key}

        if app_id:
            sql += " AND app_id = {app_id:UUID}"
            params["app_id"] = app_id

        sql += f" ORDER BY executed_at DESC LIMIT {limit}"

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return list(result.named_results())
        except Exception as exc:
            if self._is_table_missing_error(exc):
                return []
            if self._is_connection_error(exc):
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                return list(result.named_results())
            raise

    def query_config_snapshot_at_time(
        self,
        device_id: str,
        at_time: str,
        *,
        app_id: str | None = None,
    ) -> list[dict]:
        """Return the config state at a specific point in time.

        Uses argMax to get the latest value for each key at or before `at_time`.
        """
        app_filter = ""
        params: dict[str, Any] = {"device_id": device_id, "at_time": at_time}
        if app_id:
            app_filter = " AND app_id = {app_id:UUID}"
            params["app_id"] = app_id

        sql = (
            "SELECT "
            "  component_type, component, config_key, "
            "  argMax(config_value, executed_at) AS config_value, "
            "  argMax(config_hash, executed_at) AS config_hash, "
            "  argMax(app_name, executed_at) AS resolved_app_name, "
            "  argMax(app_id, executed_at) AS resolved_app_id, "
            "  max(executed_at) AS latest_ts "
            "FROM config "
            "WHERE device_id = {device_id:UUID} "
            f"  AND executed_at <= {{at_time:DateTime64(3)}}{app_filter}"
            " GROUP BY component_type, component, config_key"
            " ORDER BY component_type, component, config_key"
        )

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return list(result.named_results())
        except Exception as exc:
            if self._is_table_missing_error(exc):
                return []
            if self._is_connection_error(exc):
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                return list(result.named_results())
            raise

    # ------------------------------------------------------------------
    # Events methods
    # ------------------------------------------------------------------

    def insert_events(self, events: list[dict]) -> None:
        """Batch insert events into the events table."""
        if not events:
            return
        client = self._get_client()
        data = [[e.get(col) for col in _EVENTS_INSERT_COLUMNS] for e in events]
        client.insert("events", data, column_names=_EVENTS_INSERT_COLUMNS)

    def _build_event_filters(
        self,
        *,
        state: str | None = None,
        severity: str | None = None,
        device_id: str | None = None,
        tenant_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        message: str | None = None,
        source: str | None = None,
    ) -> tuple[list[str], dict[str, Any]]:
        """Build WHERE clauses and params for event queries."""
        wheres: list[str] = []
        params: dict[str, Any] = {}

        if state:
            wheres.append("state = {state:String}")
            params["state"] = state
        if severity:
            wheres.append("severity = {severity:String}")
            params["severity"] = severity
        if device_id:
            wheres.append("device_id = {device_id:UUID}")
            params["device_id"] = device_id
        if tenant_id:
            wheres.append("tenant_id = {tenant_id:UUID}")
            params["tenant_id"] = tenant_id
        if from_ts:
            wheres.append("occurred_at >= {from_ts:DateTime64(3)}")
            params["from_ts"] = from_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if to_ts:
            wheres.append("occurred_at <= {to_ts:DateTime64(3)}")
            params["to_ts"] = to_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if message:
            wheres.append("message ILIKE {message_pattern:String}")
            params["message_pattern"] = f"%{message}%"
        if source:
            wheres.append("source ILIKE {source_pattern:String}")
            params["source_pattern"] = f"%{source}%"

        return wheres, params

    def count_events(
        self,
        *,
        state: str | None = None,
        severity: str | None = None,
        device_id: str | None = None,
        tenant_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        message: str | None = None,
        source: str | None = None,
    ) -> int:
        """Count events matching the given filters."""
        wheres, params = self._build_event_filters(
            state=state, severity=severity, device_id=device_id,
            tenant_id=tenant_id, from_ts=from_ts, to_ts=to_ts,
            message=message, source=source,
        )
        sql = "SELECT count() FROM events"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return result.result_rows[0][0] if result.result_rows else 0
        except Exception:
            return 0

    def query_events(
        self,
        *,
        state: str | None = None,
        severity: str | None = None,
        device_id: str | None = None,
        tenant_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        message: str | None = None,
        source: str | None = None,
        sort_by: str = "occurred_at",
        sort_dir: str = "desc",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """Query events with optional filters."""
        wheres, params = self._build_event_filters(
            state=state, severity=severity, device_id=device_id,
            tenant_id=tenant_id, from_ts=from_ts, to_ts=to_ts,
            message=message, source=source,
        )

        sql = "SELECT * FROM events"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)

        VALID_SORT = {"occurred_at", "severity", "source", "message"}
        sort_col = sort_by if sort_by in VALID_SORT else "occurred_at"
        sort_direction = "DESC" if sort_dir == "desc" else "ASC"
        sql += f" ORDER BY {sort_col} {sort_direction}"
        sql += f" LIMIT {limit} OFFSET {offset}"

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return list(result.named_results())
        except Exception as exc:
            if self._is_connection_error(exc):
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                return list(result.named_results())
            raise

    def update_event_state(
        self, event_ids: list[str], new_state: str, actor: str
    ) -> None:
        """Update state of events (acknowledge or clear) via ALTER UPDATE."""
        if not event_ids:
            return
        client = self._get_client()
        id_list = ", ".join(f"'{eid}'" for eid in event_ids)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        if new_state == "acknowledged":
            sql = (
                f"ALTER TABLE events UPDATE "
                f"state = 'acknowledged', "
                f"acknowledged_at = '{now_str}', "
                f"acknowledged_by = '{actor}' "
                f"WHERE id IN ({id_list}) AND state = 'active'"
            )
        elif new_state == "cleared":
            sql = (
                f"ALTER TABLE events UPDATE "
                f"state = 'cleared', "
                f"cleared_at = '{now_str}', "
                f"cleared_by = '{actor}' "
                f"WHERE id IN ({id_list}) AND state IN ('active', 'acknowledged')"
            )
        else:
            return

        client.command(sql)

    # ------------------------------------------------------------------
    # Alert log methods
    # ------------------------------------------------------------------

    def insert_alert_log(self, records: list[dict]) -> None:
        """Batch insert alert fire/clear records."""
        if not records:
            return
        client = self._get_client()
        data = [[r.get(col) for col in _ALERT_LOG_INSERT_COLUMNS] for r in records]
        client.insert("alert_log", data, column_names=_ALERT_LOG_INSERT_COLUMNS)

    def _build_alert_log_filters(
        self,
        *,
        definition_id: str | None = None,
        entity_key: str | None = None,
        device_id: str | None = None,
        action: str | None = None,
        definition_name: str | None = None,
        message: str | None = None,
        tenant_id: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> tuple[list[str], dict[str, Any]]:
        """Build WHERE clauses and params for alert_log queries."""
        wheres: list[str] = []
        params: dict[str, Any] = {}

        if definition_id:
            wheres.append("definition_id = {definition_id:UUID}")
            params["definition_id"] = definition_id
        if entity_key:
            wheres.append("entity_key = {entity_key:String}")
            params["entity_key"] = entity_key
        if device_id:
            wheres.append("device_id = {device_id:UUID}")
            params["device_id"] = device_id
        if action:
            wheres.append("action = {action:String}")
            params["action"] = action
        if definition_name:
            wheres.append("definition_name ILIKE {definition_name_pat:String}")
            params["definition_name_pat"] = f"%{definition_name}%"
        if message:
            wheres.append("message ILIKE {message_pat:String}")
            params["message_pat"] = f"%{message}%"
        if tenant_id:
            wheres.append("tenant_id = {tenant_id:UUID}")
            params["tenant_id"] = tenant_id
        if from_ts:
            wheres.append("occurred_at >= {from_ts:DateTime64(3)}")
            params["from_ts"] = from_ts
        if to_ts:
            wheres.append("occurred_at <= {to_ts:DateTime64(3)}")
            params["to_ts"] = to_ts

        return wheres, params

    def query_alert_log(
        self,
        *,
        definition_id: str | None = None,
        entity_key: str | None = None,
        device_id: str | None = None,
        action: str | None = None,
        definition_name: str | None = None,
        message: str | None = None,
        tenant_id: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        sort_by: str = "occurred_at",
        sort_dir: str = "DESC",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query alert log records with filters."""
        wheres, params = self._build_alert_log_filters(
            definition_id=definition_id, entity_key=entity_key,
            device_id=device_id, action=action,
            definition_name=definition_name, message=message,
            tenant_id=tenant_id, from_ts=from_ts, to_ts=to_ts,
        )

        sql = "SELECT * FROM alert_log"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)

        VALID_SORT = {"occurred_at", "severity", "action", "definition_name", "device_name"}
        sort_col = sort_by if sort_by in VALID_SORT else "occurred_at"
        sort_direction = "DESC" if sort_dir.upper() == "DESC" else "ASC"
        sql += f" ORDER BY {sort_col} {sort_direction}"
        sql += f" LIMIT {limit} OFFSET {offset}"

        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return list(result.named_results())
        except Exception as exc:
            if self._is_connection_error(exc):
                client = self._reconnect()
                result = client.query(sql, parameters=params)
                return list(result.named_results())
            raise

    def count_alert_log(
        self,
        *,
        definition_id: str | None = None,
        entity_key: str | None = None,
        device_id: str | None = None,
        action: str | None = None,
        definition_name: str | None = None,
        message: str | None = None,
        tenant_id: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> int:
        """Count alert log records matching the given filters."""
        wheres, params = self._build_alert_log_filters(
            definition_id=definition_id, entity_key=entity_key,
            device_id=device_id, action=action,
            definition_name=definition_name, message=message,
            tenant_id=tenant_id, from_ts=from_ts, to_ts=to_ts,
        )
        sql = "SELECT count() FROM alert_log"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        try:
            client = self._get_client()
            result = client.query(sql, parameters=params)
            return result.result_rows[0][0] if result.result_rows else 0
        except Exception:
            return 0
