# MonCTL — Distributed Monitoring Platform

## Project Overview

MonCTL is a distributed monitoring platform with a central management server and distributed collector nodes. Collectors pull job assignments from central, execute monitoring checks (ping, port, SNMP, HTTP, custom apps), and forward results back to central for storage in ClickHouse.

## Architecture

```
Browser → HAProxy (VIP 10.145.210.40:443) → central1-4 (:8443)
                                              ├── PostgreSQL (Patroni HA)
                                              ├── ClickHouse (replicated cluster)
                                              └── Redis

Collectors (worker1-4) → poll jobs from central → execute checks → forward results
```

## Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy async, Alembic migrations
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS v4, React Query (TanStack)
- **Time-series storage**: ClickHouse (replicated cluster)
- **Relational DB**: PostgreSQL 16 (Patroni HA)
- **Cache**: Redis
- **Proxy**: HAProxy (TLS termination, round-robin to 4 central nodes)
- **Collector**: Python 3.12, gRPC (peer communication), SQLite (local result buffer)
- **Icons**: Lucide React
- **Charts**: Recharts

## Package Structure

```
apps/                           # Built-in monitoring apps (source stored in DB)
├── ping_check.py               # ICMP ping (BasePoller)
├── port_check.py               # TCP port check (BasePoller)
├── http_check.py               # HTTP/HTTPS check (BasePoller)
├── snmp_check.py               # SNMP scalar OID query (BasePoller)
└── snmp_interface_poller.py    # Full ifTable/ifXTable monitoring (BasePoller)

packages/
├── central/                    # Central management server
│   ├── src/monctl_central/
│   │   ├── main.py             # FastAPI app, lifespan, seed logic
│   │   ├── config.py           # Settings via env vars (MONCTL_ prefix)
│   │   ├── dependencies.py     # DI: get_db, get_clickhouse, require_auth, require_admin
│   │   ├── cache.py            # Redis client + caching (enrichment, interface ID, refresh flags, docker push)
│   │   ├── storage/
│   │   │   ├── models.py       # SQLAlchemy models (41 models, all PostgreSQL tables)
│   │   │   └── clickhouse.py   # ClickHouse client, DDL, insert/query methods
│   │   ├── api/router.py       # Main router (mounts 30 sub-routers at /v1/)
│   │   ├── auth/               # JWT cookie auth (login, refresh, me)
│   │   ├── devices/router.py   # Device CRUD, bulk-patch, monitoring config, interface metadata, credentials
│   │   ├── collectors/router.py # Collector registration, approval, heartbeat, WS status
│   │   ├── collector_api/router.py # /api/v1/ endpoints collectors call (jobs, results, credentials, logs/ingest)
│   │   ├── ws/                 # WebSocket command channel (collector ↔ central)
│   │   │   ├── router.py      # /ws/collector endpoint (persistent bidirectional)
│   │   │   ├── auth.py        # WS auth (shared secret + collector_id, or individual key)
│   │   │   ├── connection_manager.py # Connection tracking, keepalive, request-response
│   │   │   └── command_router.py # REST API to send commands via WS
│   │   ├── logs/               # Centralized log collection (ClickHouse)
│   │   │   └── router.py      # POST /logs/ingest, GET /logs (query), GET /logs/filters
│   │   ├── apps/router.py      # App CRUD + assignment CRUD + version management
│   │   ├── results/router.py   # ClickHouse query API (history, latest, interfaces)
│   │   ├── config_history/     # Config change history (changelog, snapshot, diff)
│   │   ├── credentials/        # Credential CRUD, types, crypto
│   │   ├── credential_keys/    # Reusable credential field definitions
│   │   ├── connectors/         # Connector CRUD + versions
│   │   ├── alerting/           # Alert definitions, entities, DSL engine, threshold variables, evaluation engine
│   │   │   ├── dsl.py          # DSL parser + ClickHouse SQL compiler (arithmetic, rate, safety limits)
│   │   │   ├── engine.py       # Alert evaluation engine (30s cycle, writes fire/clear to alert_log)
│   │   │   ├── router.py       # Alert definitions CRUD, entities, overrides, validation, alert log
│   │   │   ├── threshold_sync.py # Auto-sync threshold variables from DSL expressions
│   │   │   ├── instance_sync.py  # Sync alert entities for new assignments
│   │   │   ├── cleanup.py      # Reset old resolved entities
│   │   │   └── notifier.py     # Webhook notifications
│   │   ├── events/             # Event policies, engine, active/cleared events
│   │   │   ├── engine.py       # Event promotion engine (runs after alert engine)
│   │   │   └── router.py       # Events CRUD, policies, acknowledge/clear
│   │   ├── automations/         # Run Book Automation (actions + automations)
│   │   │   ├── engine.py       # AutomationEngine: trigger evaluation, orchestration
│   │   │   ├── executor.py     # Subprocess execution on central
│   │   │   └── router.py       # CRUD for actions/automations + trigger + run history
│   │   ├── dashboard/           # Aggregated dashboard summary endpoint
│   │   ├── packs/              # Monitoring pack import/export
│   │   ├── python_modules/     # Package registry + PyPI import + wheel distribution
│   │   ├── docker_infra/       # Docker host monitoring (stats, logs, events, images)
│   │   ├── roles/              # Custom RBAC roles + permissions
│   │   ├── templates/          # Monitoring templates + hierarchical bindings
│   │   │   ├── router.py      # Template CRUD, bindings CRUD, resolve, auto-apply
│   │   │   └── resolver.py    # Hierarchical merge engine (category → type override)
│   │   ├── tenants/router.py   # Multi-tenant support
│   │   ├── users/router.py     # User CRUD + timezone + API keys
│   │   ├── settings/router.py  # System settings (retention, intervals, etc.)
│   │   └── scheduler/          # Leader election + background tasks
│   ├── frontend/               # React SPA
│   │   └── src/
│   │       ├── api/
│   │       │   ├── client.ts   # fetch() wrapper (apiGet, apiPost, apiPut, apiPatch, apiDelete)
│   │       │   └── hooks.ts    # 185 React Query hooks for ALL API endpoints
│   │       ├── types/api.ts    # 100 TypeScript interfaces for API responses
│   │       ├── pages/          # 28 page components
│   │       ├── components/     # 33 reusable UI components (incl. ClearableInput, FilterableSortHead, PaginationBar)
│   │       ├── hooks/          # useAuth, useTimezone
│   │       └── layouts/        # Sidebar + Header (pageTitles map) + AppLayout
│   └── alembic/                # 39 database migrations
├── collector/                  # Collector node
│   └── src/monctl_collector/
│       ├── config.py           # YAML + env config
│       ├── central/
│       │   ├── api_client.py   # HTTP client for /api/v1/
│       │   ├── credentials.py  # Credential fetch + local encrypted cache
│       │   ├── ws_client.py    # WebSocket client (persistent, auto-reconnect with backoff)
│       │   ├── ws_handlers.py  # Command handlers (poll_device, config_reload, health_check, docker_*)
│       │   └── log_shipper.py  # Background log collection from sidecar → POST to central
│       ├── polling/
│       │   ├── engine.py       # Min-heap deadline scheduler + connector instantiation
│       │   └── base.py         # BasePoller abstract class
│       ├── apps/manager.py     # App/connector download, venv management, class loading
│       ├── forward/forwarder.py # Result batching + posting to central
│       ├── cache/
│       │   ├── local_cache.py  # SQLite backend (jobs, results, credentials, app_cache)
│       │   ├── app_cache_sync.py  # Syncs app cache with central
│       │   └── app_cache_accessor.py # Runtime accessor for apps
│       ├── jobs/               # Job models, scheduling, work stealing
│       └── peer/               # gRPC client/server for inter-collector communication
├── common/                     # Shared: monctl_common.utils (utc_now, hash_api_key)
└── sdk/                        # SDK package (base classes, testing utilities)
```

---

## Key Subsystems

### Credential System

**Storage**: `Credential` model with AES-256-GCM encrypted `secret_data` column.

**Types**: Managed via `CredentialType` table (CRUD at `/v1/credentials/types`). Used as dropdown in credential creation UI — prevents typos.

**Resolution chain** (for connector bindings, in order of precedence):
1. `AssignmentCredentialOverride` — per-assignment, per-connector-alias override
2. `AppAssignment.credential_id` — assignment-level credential
3. `Device.default_credential_id` — device-level fallback

**Device credentials**: `Device.credentials` JSONB column maps `{credential_type: credential_id}` for per-protocol credential assignment (e.g., separate SNMP and SSH credentials).

### Connector System

**App-level bindings**: `AppConnectorBinding` declares which connectors an app requires (e.g., snmp_interface_poller requires a "snmp" connector). Managed in the App Detail UI.

**Loading**: `apps/manager.py` downloads connector code from central, installs venvs, and loads classes. Venv site-packages are **permanently added to sys.path** so lazy imports (e.g., `import pysnmp`) work at runtime.

**SNMP Connector** (v1.3.1): Accepts both `snmp_version` and `version` credential keys for backward compatibility — the credential API returns `version` (from template key names), not `snmp_version`. Builds pysnmp v7 auth objects for v1/v2c/v3. `connect()` is **idempotent** — returns immediately if already connected to same host, closes previous engine if called with different host. This prevents memory leaks from apps that call `connect()` redundantly.

**Connector credential keys**: Credential field names are defined by `CredentialTemplate` key definitions, and the collector API (`/api/v1/credentials/{name}`) returns values using those template key names. Connectors must match these exact key names — e.g., the SNMP credential template uses `version`, `username`, `auth_password`, `priv_password`, `auth_protocol`, `priv_protocol`, `security_level`, `port`.

**Connector versioning**: Connectors are stored in DB with checksums. When a new version is uploaded (`POST /v1/connectors/{id}/versions` with `set_latest: true`), the next job-fetch returns the new checksum, triggering collectors to re-download automatically. Restart poll-workers to force immediate pickup.

**Connector lifecycle**: The polling engine manages the full connect→use→close lifecycle for connectors. **Apps must NOT call `connector.connect()` themselves** — the engine calls it before passing the connector to the app. If an app calls `connect()` anyway, the idempotent guard prevents leaks, but new apps should rely on the engine-managed lifecycle.

**Memory management**: Polling engine calls `gc.collect()` + `malloc_trim(0)` after each job to return freed memory to OS. Workers use `MALLOC_ARENA_MAX=2` and `PYTHONMALLOC=malloc` env vars to reduce glibc arena fragmentation. All poll-workers have `mem_limit: 1g` as safety net.

### Template Hierarchy (App Auto-Assignment)

**Two-level binding system**: Templates can be linked to `DeviceCategory` (broad, e.g. "cisco-router") and `DeviceType` (specific, e.g. "Cisco ASR 1002-X") via many-to-many binding tables with priority.

**Models**: `DeviceCategoryTemplateBinding` and `DeviceTypeTemplateBinding` — each has `priority` (int, higher overrides lower within same level) and `pack_id` (for pack import/export).

**Merge logic** (`templates/resolver.py`): Category-level templates merge first (low→high priority), then type-level templates overlay. Per-role monitoring overrides, per-app_name app overrides, dict-merge for labels, last-writer-wins for scalars.

**API endpoints** (under `/v1/templates/`):
- `POST/DELETE /bindings/category`, `GET /bindings/category/{id}` — category binding CRUD
- `POST/DELETE /bindings/device-type`, `GET /bindings/device-type/{id}` — type binding CRUD
- `POST /resolve` — preview merged config per device (no side effects)
- `POST /auto-apply` — resolve + create assignments

**Discovery integration**: `auto_apply_templates_on_discovery` system setting (default: false). When enabled, templates are auto-applied after SNMP device type matching in `discovery/service.py`.

**Pack support**: Bindings export as `template_bindings_category` and `template_bindings_device_type` sections, referenced by name (not UUID). Imported after all entities are created.

### Interface Monitoring

**Metadata**: `InterfaceMetadata` table caches stable interface identity `(device_id, if_name)` with `polling_enabled`, `alerting_enabled`, `poll_metrics` settings.

**Targeted polling**: GetJobs injects `monitored_interfaces` list (only polling_enabled=True interfaces) into job parameters. Poller uses targeted SNMP GET instead of full walk.

**Name resolution**: In targeted GET mode, poller uses authoritative `if_name` from metadata rather than SNMP response, preventing incorrect names when SNMP fails.

**Metadata refresh**: `POST /v1/devices/{id}/interface-metadata/refresh` sets a Redis flag. Next job-fetch omits `monitored_interfaces`, forcing a full SNMP walk to rediscover interfaces.

**Rate calculation**: Central-side (not collector). Previous counters cached in Redis per interface. Delta/rate computed on result ingestion.

**Multi-tier retention**: Raw (7 days), hourly rollup (90 days), daily rollup (730 days). Auto-tier selection based on query time range.

### ClickHouse Tables

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `availability_latency` | Ping/port/HTTP check results | state, rtt_ms, response_time_ms, reachable |
| `performance` | Custom metric results | component, component_type, metric_names[], metric_values[] |
| `interface` | Per-interface SNMP data | interface_id, in/out octets, rates, errors, discards, utilization |
| `config` | Configuration tracking (change-only writes) | config_key, config_value, config_hash |
| `alert_log` | Alert fire/clear history | definition_id, entity_key, action, current_value, threshold_value |
| `events` | Event lifecycle (active/ack/cleared) | definition_id, policy_id, severity, state |
| `logs` | Centralized Docker/app logs | collector_name, container_name, level, message |
| `rba_runs` | Automation run results | automation_id, device_id, status, step_results, duration_ms |

Each table has a `*_latest` materialized view (ReplacingMergeTree) for instant latest-per-key lookups. Interface also has `interface_hourly` and `interface_daily` rollup tables.

**History query default**: `GET /v1/results` queries `availability_latency`, `performance`, `config` by default (NOT `interface` — interface data has its own dedicated endpoints to avoid flooding the History tab with one row per interface per poll).

### Dashboard & Analytics

**Operational Dashboard** (`dashboard/router.py`): Single `GET /v1/dashboard/summary` endpoint aggregating alert_summary (total firing + top 10 recent), device_health (up/down/degraded counts + worst 10), collector_status (online/offline/pending + stale list), performance_top_n (CPU/memory/bandwidth from ClickHouse). Frontend uses `useDashboardSummary()` hook with 15s auto-refresh.

**Metabase** (`docker/metabase/`): Metabase v0.54 runs on central1 as Docker Compose service. Native ClickHouse driver (core-level, no plugin). Uses existing PostgreSQL for its application database (`metabase` database). Accessible via HAProxy at `/metabase` sub-path (path-strip rewrite in HAProxy). Setup via `docker/metabase/setup.py` (creates admin user, adds ClickHouse datasource, seeds dashboards). 4 pre-built dashboards in "MonCTL" collection: Device Performance, Interface Traffic, Availability Overview, Alert History. Admin credentials: `admin@monctl.local`.

**Grafana** (`docker/grafana/`): Grafana OSS 11.4 runs on central4 as Docker Compose service. Accessible via HAProxy at `/grafana` sub-path. Anonymous viewer access enabled.

**Analytics Page** (`pages/AnalyticsPage.tsx`): Links to Metabase dashboards + SQL query builder. Reads `metabase_url` from system settings. Shows "Metabase not configured" empty state when URL not set.

**Custom Dashboards** (`analytics/dashboards.py`): User-created dashboards with SQL-based widgets. `AnalyticsDashboard` model (PostgreSQL) with `variables` JSONB column for cross-widget context variables. `AnalyticsWidget` model stores per-widget SQL, chart config, and layout.

**Dashboard Editor** (`pages/DashboardEditorPage.tsx`): Uses `react-grid-layout` v2.2.3 (hook-based API: `useContainerWidth`, `ResponsiveGridLayout`) for drag-and-drop + resize. 24-column grid, `rowHeight: 40`, `.drag-handle` on GripVertical icon. `onLayoutChange` updates widget positions and marks dirty.

**Time Picker** (`components/DashboardTimePicker.tsx`): Dashboard-level time range with presets (15m, 1h, 6h, 24h, 7d, 30d) + custom datetime range. Widgets use `{time_from}` and `{time_to}` placeholders in SQL — client-side substitution via `resolveSQL()` in `DashboardWidget.tsx`.

**Time format**: ClickHouse 24.3 cannot parse ISO 8601 (`2026-03-26T15:00:00.000Z`). `resolveTimestamp()` outputs `YYYY-MM-DD HH:MM:SS` format. All substituted values are wrapped in single quotes for valid SQL.

**Cross-Widget Variables**: Dashboard-level named variables (`DashboardVariable`). Widgets reference `{var:name}` in SQL (client-side substitution, single-quote wrapped, SQL-escaped). Table widgets can "publish" a column value to a variable on row click (`config.publishes: {column, variable}`). `DashboardVariableBar` component shows active values as pills.

**Widget Append**: `POST /v1/analytics/dashboards/{id}/widgets` appends a single widget without replacing existing ones. Used by SQL Explorer's "Save to Dashboard" feature (`useAppendDashboardWidget` hook).

**Add Widget Dialog** (`components/AddWidgetDialog.tsx`): SQL editor + Test button (resolves placeholders with default "last 1h" range) + visualization picker + width selector (Half=12, Full=24) + X/Y/Group By config (visible after Test) + "Publishes to variable" config for table widgets.

### Config Data Optimization

**Write suppression**: `collector_api/router.py` compares each config key's MD5 hash against `config_latest FINAL` before writing. Only changed keys and volatile keys are written to ClickHouse. In-memory LRU cache (60s TTL) avoids repeated ClickHouse lookups.

**Volatile keys**: `AppVersion.volatile_keys` JSONB field lists keys that change every poll cycle (e.g., uptime). These bypass suppression and are always written.

**Change history API** (`config_history/router.py`): 4 endpoints under `/v1/devices/{id}/config/`:
- `GET /changelog` — paginated change history
- `GET /snapshot` — current config values from `config_latest FINAL`
- `GET /diff?config_key=...` — value history for a specific key
- `GET /change-timestamps` — timeline of changes (minute-level buckets)

**Retention**: `config_retention_days` system setting (default 90 days). Scheduler cleanup task deletes old config rows.

**Frontend**: ConfigurationTab has "Current" / "Changes" toggle. Changes view shows paginated changelog. Diff dialog shows value history per key with change highlighting.

### Device Enable/Disable

**Model**: `Device.is_enabled` boolean column (default `true`). Disabled devices are excluded from collector job scheduling via an `or_(device_id IS NULL, Device.is_enabled == True)` filter in `GET /api/v1/jobs`.

**Bulk operations**: `POST /v1/devices/bulk-patch` accepts `{device_ids, is_enabled?, collector_group_id?, tenant_id?}`. Applies tenant-scoped visibility filtering. When moving to a collector group, also migrates assignments (nulls out explicit collector_id) and bumps collector config versions.

**Frontend**: DevicesPage bulk action bar includes Enable, Disable, Move to Group, Move to Tenant buttons. Disabled devices render with `opacity-50` and a grey status dot.

### Alerting System

**Two-tier architecture**: Alerts (high-volume, per-entity) → Events (advanced logic, lower-volume).

**Alert Definitions** (`AlertDefinition`): Live on the **app** (not version). DSL expression language with arithmetic (+, -, *, /), `rate()` function, and safety limits. Definitions persist across version upgrades.

**DSL Grammar**: `avg(in_utilization_pct) > 80 AND max(in_errors) > 100`, `rate(in_octets) * 8 / 1000000 > 500`, `firmware_version CHANGED`, `state IN ('down', 'degraded')`. Compiled to parameterized ClickHouse SQL.

**Alert Entities** (`AlertEntity`): Per-assignment per-entity state tracking (ok/firing/resolved). Created dynamically on first encounter. Tracks fire_count, fire_history (ring buffer of 20), current_value.

**Threshold Variables** (`ThresholdVariable`): Named parameters auto-extracted from DSL expressions. Fields: `name`, `display_name`, `description`, `default_value`, `app_value`, `unit`. 4-level override hierarchy: expression default → app variable (`app_value`) → device override → entity override. Auto-synced when definitions are created/updated.

**Threshold Units**: Free-text `String(50)` column. Built-in units: `percent`, `ms`, `seconds`, `bytes`, `count`, `ratio`, `dBm`, `pps`, `bps`. Custom units allowed via CRUD endpoints (any non-empty string). Pack import schema validates against built-in list only. Frontend `UnitSelector` component offers built-in dropdown + "Custom..." free-text option.

**Threshold Editing** (App Thresholds tab): `Default` column is inline-editable (click to edit). `App Value` column shows pencil icon + Reset button (sends `clear_app_value: true` to explicitly null app_value). `PUT /apps/{id}/thresholds/{var_id}` accepts `default_value`, `app_value`, `clear_app_value`, `display_name`, `description`, `unit`.

**Device Thresholds** (`GET /devices/{id}/thresholds`): Returns flat `DeviceThresholdRow[]` list (one row per variable, not per definition). Each row includes `expression_default`, `app_value`, `device_value`, `effective_value` (never null — resolves device override → app_value → default_value), `entity_overrides[]`, `used_by_definitions[]`. Frontend highlights active level with brand color + source label.

**Threshold Overrides** (`ThresholdOverride`): References `variable_id` (not definition_id). Single `value: Float` per override row.

**Alert Log** (`alert_log` ClickHouse table): Append-only fire/clear history. Written by engine every 30s evaluation cycle.

**Event Policies** (`EventPolicy`): Promote alerts to events based on fire_count (consecutive) or fire_history (cumulative/sliding window). `ActiveEvent` PostgreSQL table for dedup tracking.

**Events** (`events` ClickHouse table): State machine: active → acknowledged → cleared. Auto-clear when underlying alerts resolve.

**Engine**: Runs every 30s via scheduler. Writes fire/clear records to `alert_log`. Resolves thresholds per-entity from 4-level hierarchy. Groups entities by effective threshold for batched ClickHouse queries.

**Validation**: `POST /v1/alerts/validate-expression` returns `errors[]`, `warnings[]`, `referenced_metrics[]`, `threshold_params[]`, `has_arithmetic`, `has_division`.

### Automations & Actions (Run Book Automation)

**Two-layer system**: Actions are reusable Python scripts (stored in PostgreSQL). Automations chain one or more actions in sequence, triggered by events, cron schedules, or manual request.

**Actions** (`actions` table): Python source code, target (`collector` or `central`), optional credential type, configurable timeout (5-300s). Execute in subprocess with `ActionContext` providing device info, credentials, event data, and shared data from previous steps. `context.set_output(key, value)` stores data for subsequent actions.

**Automations** (`automations` table): Trigger type (`event` or `cron`), event filters (severity, device labels), cron expression + device scope, cooldown per device (default 300s). Steps ordered via `automation_steps` join table.

**Execution**: `AutomationEngine` in `automations/engine.py`. Sequential fail-fast — if a step fails, the chain stops. Collector-targeted actions dispatched via WebSocket `run_action` command. Central-targeted actions run locally in subprocess. Results stored in ClickHouse `rba_runs` table.

**Triggers**: Event-triggered automations fire from `events/engine.py` after event insertion. Cron-triggered automations evaluated every 30s in scheduler. Manual trigger via `POST /v1/automations/automations/{id}/trigger` with device_ids.

**API**: `/v1/automations/actions` (CRUD), `/v1/automations/automations` (CRUD + trigger), `/v1/automations/runs` (history from ClickHouse).

**Frontend**: `AutomationsPage.tsx` with 3 tabs (Automations, Actions, Run History). Code editor for action scripts, step builder for automation chains, run detail viewer with expandable step output.

**Dependency**: `croniter>=2.0` for cron expression parsing.

### WebSocket Command Channel

**Architecture**: Collectors maintain a persistent bidirectional WebSocket to central (`/ws/collector`). Central can push ad-hoc commands; collectors respond with results. Separate from HTTP polling (jobs, heartbeat) — used for real-time commands.

**Auth**: Two modes: (1) individual collector API key (from `api_keys` table), (2) shared secret (`MONCTL_COLLECTOR_API_KEY` env var) + `collector_id` query parameter. Mode 2 is used in production since collectors use the shared secret.

**Connection manager** (`ws/connection_manager.py`): Tracks active connections, sends keepalive pings every 30s, supports request-response with 60s timeout and `message_id`/`in_reply_to` correlation.

**Message types**: `ping/pong`, `poll_device`, `config_reload`, `health_check`, `module_update`, `docker_health`, `docker_logs`. Each command type has a `_result` or `_ack` response type.

**Reconnect**: Collector uses soft backoff: 1s, 2s, 3s, 5s (cap). Resets on successful connect.

**REST API**: `GET /v1/collectors/{id}/ws-status`, `GET /v1/collectors/ws-connections`, `POST /v1/collectors/{id}/command/{type}`.

**Frontend**: Green/grey WS connection dot on Collectors page.

### Centralized Log Collection

**Flow**: Docker-stats sidecars on all hosts (central + workers) push logs to central via `/api/v1/docker-stats/push`. The push handler writes logs to both Redis (ring-buffer for UI) and ClickHouse (`logs` table) for persistent storage.

**Collector log shipper** (`central/log_shipper.py`): Also runs on collector cache-nodes as a backup path. Fetches Docker container logs from local sidecar (`http://monctl-docker-stats:9100`) every 10s and POSTs batches to `/api/v1/logs/ingest`. Level detection heuristic. Max 5000 lines per batch.

**ClickHouse `logs` table**: Partitioned by day, ORDER BY (collector_name, container_name, timestamp), TTL 7 days (configurable via `log_retention_days` setting). Uses `toDateTime(timestamp)` wrapper in TTL expression (required for ClickHouse 24.3 with DateTime64 columns).

**Query API**: `GET /v1/logs` with filters (collector, container, host, level, source_type, search), pagination, sorting. `GET /v1/logs/filters` returns distinct values for dropdowns.

**Frontend**: Logs tab on Docker Infrastructure page with search, container/level/collector filters, sortable columns, pagination, and live tail mode (polls every 2s). Log retention dropdown in Settings → Data Retention.

**Collector model**: `log_level_filter` column (default "INFO") controls minimum log level shipped by each collector.

### Redis Sentinel

**Setup**: 3 sentinel nodes (central1-3), Redis primary on central1, replica on central2. All central apps connect via Sentinel for automatic failover.

**Critical: `announce-ip`**: Sentinels and Redis instances run in Docker bridge mode. Without `sentinel announce-ip <host-ip>` in sentinel.conf and `--replica-announce-ip <host-ip>` in Redis command, sentinels advertise Docker-internal IPs (172.x.x.x) which are unreachable cross-host. This breaks quorum and causes stale master state after failovers.

**Sentinel config** (`/opt/monctl/central-ha/sentinel.conf`): Each node has unique `sentinel announce-ip` pointing to its host IP. Template is copied to `/tmp/sentinel.conf` on container start — sentinel modifies it at runtime, so container must be recreated (not just restarted) to reset state.

**Coordinated restart**: When sentinel state is corrupt, all 3 sentinels must be stopped simultaneously before restarting — otherwise running sentinels propagate stale state to newly started ones.

### System Settings

Key-value pairs in `SystemSetting` table. Managed via `GET/PUT /v1/settings`. Notable settings: retention days (config, interface, performance, availability, logs), `metabase_url`, `grafana_url`, `pypi_network_mode`, `session_idle_timeout_minutes`, `collector_central_url`.

---

## How to Add a New Feature (Full Stack)

### Step 1: Database Model

**File**: `packages/central/src/monctl_central/storage/models.py`

```python
class MyEntity(Base):
    __tablename__ = "my_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
```

Conventions:
- Always use `UUID(as_uuid=True)` for IDs with `default=uuid.uuid4`
- Always include `created_at` and `updated_at` with `server_default="now()"`
- Use `mapped_column("metadata", JSONB, ...)` (rename to `metadata_`) to avoid keyword conflicts
- ForeignKey pattern: `mapped_column(UUID(as_uuid=True), ForeignKey("table.id", ondelete="SET NULL"), nullable=True)`

### Step 2: Alembic Migration

**File**: `packages/central/alembic/versions/<revision_id>_<description>.py`

Find the current head revision in the existing migration files. Naming: `<alphanumeric id>_<snake_case_description>.py`.

Migrations run automatically on container startup with an advisory lock (safe for multi-instance).

### Step 3: Backend Router

Standard pattern (see existing routers):
- `_fmt()` function to serialize model → dict
- Pydantic `BaseModel` for request validation
- `get_db` + `require_auth` dependencies
- Response format: `{"status": "success", "data": ...}`
- Register in `api/router.py`

### Step 4: Frontend (Types → Hooks → Page → Route)

1. **Types**: Add interface in `types/api.ts`
2. **Hooks**: Add React Query hooks in `api/hooks.ts`
3. **Page**: Create page in `pages/`
4. **Route**: Add to `App.tsx` + `layouts/Sidebar.tsx`

---

## API Conventions

### Response Format (ALWAYS)

```json
{"status": "success", "data": { ... }}
{"status": "success", "data": [...], "meta": {"limit": 50, "offset": 0, "count": 10, "total": 123}}
```

### Authentication

- **Web UI**: JWT in HTTP-only cookies (`access_token` + `refresh_token`), set on `POST /v1/auth/login`
- **Management API**: `Authorization: Bearer monctl_m_<key>`
- **Collector API**: `Authorization: Bearer <MONCTL_COLLECTOR_API_KEY>` (shared secret)
- **Dependencies**: `require_auth` (any authenticated), `require_admin` (admin role only)

### Routes

- All web API under `/v1/` (e.g., `/v1/devices`, `/v1/apps`)
- Collector API under `/api/v1/` (e.g., `/api/v1/jobs`, `/api/v1/results`)
- Use plural nouns: `/devices`, `/collectors`, `/apps`

### Multi-Tenant Filtering

```python
from monctl_central.dependencies import apply_tenant_filter
stmt = apply_tenant_filter(stmt, auth, Device.tenant_id)
```

---

## Building & Deploying

### Central
```bash
docker build --platform linux/amd64 --no-cache -t monctl-central:latest -f docker/Dockerfile.central .
docker save monctl-central:latest | ssh monctl@10.145.210.41 'docker load'
ssh monctl@10.145.210.41 'cd /opt/monctl/central && docker compose down && docker compose up -d'
```

### Collector
```bash
docker build --platform linux/amd64 --no-cache -t monctl-collector:latest -f docker/Dockerfile.collector-v2 .
docker save monctl-collector:latest | ssh monctl@10.145.210.31 'docker load'
ssh monctl@10.145.210.31 'cd /opt/monctl/collector && docker compose down && docker compose up -d'
```

**Important**:
- Use `Dockerfile.collector-v2` (not `Dockerfile.collector`) — v2 uses CMD allowing docker-compose command override
- No npm/node on servers — Dockerfile handles frontend build
- No package-lock.json — uses `npm install` (not `npm ci`)
- Always use `--no-cache` when rebuilding after source changes
- Use `docker compose up -d` (not `restart`) to pick up new images
- Deploy to ALL 4 central nodes and ALL 4 worker nodes
- **Healthchecks in Alpine containers**: Alpine images (TimescaleDB/Patroni, Redis) do not include curl. Use `pg_isready -h 127.0.0.1 -p 5433` for Patroni (not wget — it causes `ConnectionResetError` spam in Patroni logs). Use `redis-cli ping` for Redis.

### Server Inventory

| Role     | Hosts          | IPs                    |
|----------|----------------|------------------------|
| Central  | central1-4     | 10.145.210.41 - .44    |
| Workers  | worker1-4      | 10.145.210.31 - .34    |
| VIP      | (keepalived)   | 10.145.210.40          |

SSH user: `monctl` for all servers.

**Central compose projects** (multiple per server — restart order matters):

| Project | Path | Central1 | Central2 | Central3 | Central4 |
|---------|------|----------|----------|----------|----------|
| central-ha | `/opt/monctl/central-ha/` | app + Patroni + Redis primary + sentinel + Metabase | app + Patroni + Redis replica + sentinel | app + Redis sentinel | — |
| central | `/opt/monctl/central/` | — | — | — | app + Grafana |
| clickhouse | `/opt/monctl/clickhouse/` | — | — | ClickHouse node | ClickHouse node |
| haproxy | `/opt/monctl/haproxy/` | HAProxy + keepalived | HAProxy + keepalived | HAProxy + keepalived | HAProxy + keepalived (+ `/grafana` → central4:3000) |
| etcd | `/opt/monctl/etcd/` | etcd | etcd | etcd | — |
| docker-stats | `/opt/monctl/docker-stats/` | stats agent (push to VIP) | stats agent (push to VIP) | stats agent (push to VIP) | stats agent (push to VIP) |

**Important**: Central1-3 use `central-ha` for the main app (binds :8443). Central4 uses `central` (also binds :8443). Do NOT start both `central-ha` and `central` on the same node — they conflict on port 8443.

**Workers**: All use single compose project at `/opt/monctl/collector/` (poll-worker, forwarder, cache-node, docker-stats).

### Code Style

- Python: ruff with line-length 100, target Python 3.11
- TypeScript: standard React conventions, path aliases `@/`
- Communicate in Danish when the user writes in Danish

### Frontend UI Patterns

**ClearableInput** (`components/ui/clearable-input.tsx`): Wraps `<Input>` with an inline `×` clear button. The button and `pr-7` padding are **always in the DOM** (hidden via `opacity-0 pointer-events-none`) to avoid focus loss caused by DOM structure changes during typing.

**Filter empty states**: When filters are active but match no results, always keep the table visible (headers + filter inputs) with an empty body row message like `"No devices match your filters"`. Only show the big centered empty state (icon + action button) when there are truly zero items AND no filters are active. This lets users refine their query without losing context.

**Conditional rendering and focus**: Never use `{condition && <Element/>}` to insert/remove elements in a parent container that has sibling form inputs — React's index-based reconciliation can cause focus loss. Instead, always render the element and toggle visibility with CSS (`opacity-0 pointer-events-none`).

**VersionActions** (`components/VersionActions.tsx`): Reusable icon-only action buttons for version table rows (Set Latest, View, Edit, Clone, Delete). Each action sits in a fixed-width `w-7` slot — guarantees vertical alignment across rows regardless of conditional visibility.

**Config poll status badge**: ConfigurationTab shows a color-coded badge next to app name — green (within 1.5x interval), yellow (1 poll missed), red (2+ polls missed). Uses assignment interval data.

**Staleness warning**: OverviewTab shows an amber banner when no check data received in 15+ minutes.

**List views (server-side search/sort/pagination)**: All list pages use the `useListState` hook for per-column debounced filters (300ms), sort state, and pagination. Column headers use `FilterableSortHead` (sort label + inline `ClearableInput`). Pagination uses `PaginationBar`. All list hooks accept `ListParams` and use `placeholderData: keepPreviousData` to prevent table unmount during refetch.

**Threshold value formatting**: `formatThresholdValue(value, unit)` handles all unit types with auto-scaling: `bps` → kbps/Mbps/Gbps, `bytes` → KB/MB/GB. Null values render as em-dash. Custom units render as `{value} {unit}`. Used in both AppDetailPage and DeviceDetailPage threshold tabs.

**UnitSelector** (`AppDetailPage.tsx`): Combined dropdown + free-text component for threshold variable units. Built-in options (9 units) + "Custom..." option that reveals a text input. Used in New Variable form and inline editing.

### Playwright MCP (Browser Automation)
 
**When to use**: After implementing UI changes, to verify they render correctly against the running MonCTL instance. Also for reading live system state (device lists, alert status, performance charts) and running E2E verification flows.
 
**Target URL**: `https://10.145.210.40` (HAProxy VIP — routes to central1-4)
 
**Authentication flow**:
1. First, try navigating with `--storage-state .playwright/auth-state.json`
2. If redirected to `/login`, perform login:
   - Username: (read from `.env.local-dev` → `MONCTL_TEST_USER`)
   - Password: (read from `.env.local-dev` → `MONCTL_TEST_PASSWORD`)
3. After login, save state: store cookies to `.playwright/auth-state.json`
4. Subsequent navigations reuse the saved state
 
**Environment file** (`.env.local-dev`, gitignored):
```
MONCTL_TEST_USER=admin
MONCTL_TEST_PASSWORD=<password>
MONCTL_BASE_URL=https://10.145.210.40
```
 
**TLS**: The lab HAProxy uses a self-signed certificate. Playwright's Chromium ignores certificate errors by default in MCP mode, so no special config is needed.
 
**Headless mode**: The lab server has no display. Playwright always runs headless. Do NOT pass `--headed` or attempt to use headed mode.
 
**Screenshots**: When verifying UI changes, always take a screenshot as evidence. Store in `.playwright/screenshots/` (gitignored). Describe what the screenshot shows in your response.
