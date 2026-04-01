# MonCTL — System Description for Planning Sessions

> Brug dette dokument som kontekst i en separat Claude-session til at lave implementeringsplaner.
> Planen skal være detaljeret nok til at en anden Claude-session kan implementere den direkte.

---

## Hvad er MonCTL

Distribueret monitoring-platform med central management server og distribuerede collector-noder. Collectors henter job-assignments fra central, eksekverer monitoring checks (ping, port, SNMP, HTTP, custom apps) og sender resultater tilbage til central for lagring i ClickHouse.

## Arkitektur

```
Browser → HAProxy (VIP 10.145.210.40:443) → central1-4 (:8443)
                                              ├── PostgreSQL (Patroni HA)
                                              ├── ClickHouse (replicated cluster)
                                              └── Redis (Sentinel HA: primary central1, replica central2, 3 sentinels)

Collectors (worker1-4) → poll jobs fra central → eksekver checks → forward resultater
                       → WebSocket command channel (wss://central/ws/collector)
                       → Log shipper (batch POST /api/v1/logs/ingest every 10s)
```

## Tech Stack

| Layer | Teknologi |
|-------|-----------|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic 2 |
| Frontend | React 19, TypeScript 5.9, Vite 7, Tailwind CSS v4, React Query (TanStack) 5 |
| Time-series | ClickHouse (ReplicatedMergeTree, replicated cluster) |
| Relational DB | PostgreSQL 16 (Patroni HA) |
| Cache | Redis (single node) |
| Proxy | HAProxy (TLS termination) + Keepalived (VIP failover) |
| Collector | Python 3.12, gRPC, SQLite (lokal buffer) |
| Icons | Lucide React |
| Charts | Recharts |
| Code editor | CodeMirror 6 (Python syntax) |

## Serverinventar

| Rolle | Hosts | IPs |
|-------|-------|-----|
| Central | central1-4 | 10.145.210.41-.44 |
| Workers | worker1-4 | 10.145.210.31-.34 |
| VIP | (keepalived) | 10.145.210.40 |

SSH bruger: `monctl` på alle servere. Compose files: `/opt/monctl/{central,collector}/docker-compose.yml`.

**Central1-3**: Bruger `central-ha` compose projekt i `/opt/monctl/central-ha/` (inkl. Patroni + Redis). Central1 kører også Metabase (port 3000, tilgængelig via HAProxy `/metabase`). **Central4**: Bruger `/opt/monctl/central/` (app + Grafana). Grafana tilgængelig via HAProxy `/grafana` sub-path.

---

## Package-struktur

```
apps/                               # Built-in monitoring apps (source stored in DB)
├── ping_check.py                   # ICMP ping (BasePoller)
├── port_check.py                   # TCP port check (BasePoller)
├── http_check.py                   # HTTP/HTTPS check (BasePoller)
├── snmp_check.py                   # SNMP scalar OID query (BasePoller)
└── snmp_interface_poller.py        # Full ifTable/ifXTable monitoring (BasePoller)

packages/
├── central/                        # Central management server
│   ├── src/monctl_central/
│   │   ├── main.py                 # FastAPI app, lifespan, seeding (admin, device types, built-in apps)
│   │   ├── config.py               # Settings via MONCTL_ env vars + parse_node_list() helper
│   │   ├── dependencies.py         # DI: get_db, get_engine, get_session_factory, get_clickhouse,
│   │   │                           #     require_auth, require_admin, require_collector_auth,
│   │   │                           #     apply_tenant_filter, check_tenant_access
│   │   ├── cache.py                # Redis client + caching (api keys, credentials, enrichment, interface ID, refresh flags)
│   │   ├── storage/
│   │   │   ├── models.py           # 41 SQLAlchemy models (alle PostgreSQL-tabeller)
│   │   │   └── clickhouse.py       # ClickHouseClient wrapper, 5 domænetabeller + MV'er + rollup + config history
│   │   ├── api/router.py           # Hovedrouter — monterer 30 sub-routers på /v1/
│   │   ├── auth/                   # JWT cookie auth (login, refresh, me)
│   │   ├── devices/router.py       # Device CRUD, bulk-patch, monitoring config, interface metadata, credentials
│   │   ├── collectors/router.py    # Collector register, approve, reject, heartbeat, config, WS status
│   │   ├── collector_api/router.py # /api/v1/ endpoints collectors kalder (jobs, apps, credentials, results, logs)
│   │   ├── collector_groups/router.py
│   │   ├── ws/                     # WebSocket command channel (collector ↔ central)
│   │   │   ├── router.py          # /ws/collector endpoint
│   │   │   ├── auth.py            # WS auth (shared secret + collector_id, or individual key)
│   │   │   ├── connection_manager.py # Connection tracking, keepalive, request-response
│   │   │   └── command_router.py  # REST API for sending commands via WS
│   │   ├── logs/                   # Centralized log collection (ClickHouse)
│   │   │   └── router.py         # POST /logs/ingest, GET /logs, GET /logs/filters
│   │   ├── apps/router.py          # App CRUD + AppVersion CRUD + Assignment CRUD
│   │   ├── results/router.py       # ClickHouse query API (history, latest, interfaces)
│   │   ├── config_history/         # Config change history (changelog, snapshot, diff, timestamps)
│   │   ├── credentials/            # Credential CRUD, types, templates, crypto
│   │   ├── credential_keys/        # Reusable credential field definitions
│   │   ├── connectors/             # Connector CRUD + versions
│   │   ├── alerting/               # Alert definitions, entities, DSL engine, threshold variables
│   │   │   ├── dsl.py             # DSL parser + ClickHouse SQL compiler (arithmetic, rate)
│   │   │   ├── engine.py          # Alert evaluation (30s cycle, writes fire/clear to alert_log)
│   │   │   ├── router.py          # Definitions, entities, overrides, validation, alert log
│   │   │   └── threshold_sync.py  # Auto-sync threshold variables from expressions
│   │   ├── events/                 # Event policies + engine + acknowledge/clear
│   │   ├── dashboard/              # Aggregated dashboard summary endpoint (GET /dashboard/summary)
│   │   ├── packs/                  # Monitoring pack import/export (+ grafana_dashboards sektion)
│   │   ├── python_modules/         # Package registry + PyPI import + wheel distribution
│   │   ├── docker_infra/           # Docker host monitoring (stats, logs, events, images)
│   │   ├── roles/                  # Custom RBAC roles + permissions
│   │   ├── templates/router.py     # Monitoring templates (bulk app assignment)
│   │   ├── tenants/router.py       # Multi-tenant support
│   │   ├── users/router.py         # User CRUD + timezone + API keys
│   │   ├── settings/router.py      # System settings (retention, intervals, etc.)
│   │   ├── system/router.py        # GET /system/health — concurrent subsystem checks
│   │   └── scheduler/              # Leader election + background tasks (health monitor + alert eval)
│   ├── frontend/                   # React SPA
│   │   └── src/
│   │       ├── main.tsx            # Entry point + React Query client (30s stale, retry=1)
│   │       ├── App.tsx             # React Router — alle routes
│   │       ├── api/
│   │       │   ├── client.ts       # fetch() wrapper: apiGet, apiPost, apiPut, apiPatch, apiDelete
│   │       │   └── hooks.ts        # 185 React Query hooks for alle API endpoints
│   │       ├── types/api.ts        # 100 TypeScript interfaces for alle API responses
│   │       ├── lib/utils.ts        # cn(), formatDate(dateStr, tz), timeAgo(), capitalize(), truncate()
│   │       ├── hooks/
│   │       │   ├── useAuth.tsx     # Auth context (user, login, logout, refresh)
│   │       │   └── useTimezone.ts  # Returnerer user.timezone, default "UTC"
│   │       ├── pages/              # 28 page components
│   │       ├── components/         # 23 feature-komponenter + 10 UI-primitiver
│   │       │   └── ui/             # badge, button, card, clearable-input, dialog, input, label, select, table, tabs
│   │       └── layouts/            # AppLayout, Sidebar (15 nav items), Header (pageTitles map)
│   └── alembic/                    # 39 migrationer, kører auto ved container startup
├── collector/                      # Collector node
│   └── src/monctl_collector/
│       ├── config.py               # YAML + env config
│       ├── central/
│       │   ├── api_client.py       # HTTP client for /api/v1/
│       │   ├── credentials.py      # Credential fetch + local encrypted cache
│       │   ├── ws_client.py        # WebSocket client (persistent, auto-reconnect)
│       │   ├── ws_handlers.py      # Command handlers (poll_device, config_reload, etc.)
│       │   └── log_shipper.py      # Background log collection → POST to central
│       ├── polling/
│       │   ├── engine.py           # Min-heap deadline scheduler + connector instantiation
│       │   └── base.py             # BasePoller ABC: setup(), poll(context), teardown()
│       ├── apps/manager.py         # App/connector download, venv management, class loading
│       ├── forward/forwarder.py    # Result batching + posting to central
│       ├── cache/
│       │   ├── local_cache.py      # SQLite backend (jobs, results, credentials, app_cache)
│       │   ├── app_cache_sync.py   # Syncs app cache with central
│       │   └── app_cache_accessor.py # Runtime accessor for apps
│       ├── jobs/                   # Job models, scheduling, work stealing
│       └── peer/                   # gRPC client/server for inter-collector communication
├── common/                         # Shared: monctl_common.utils (utc_now, hash_api_key)
└── sdk/                            # SDK package (base classes, testing utilities)
```

---

## PostgreSQL-modeller (storage/models.py) — 42 modeller

| Model | Tabel | Nøglefelter |
|-------|-------|-------------|
| CollectorCluster | collector_clusters | id, name, replication_factor, peer_port, settings (JSONB) |
| Collector | collectors | id, name, hostname, ip_addresses, status (PENDING/ACTIVE/DOWN/REJECTED), load_score, effective_load, total_jobs, deadline_miss_rate, group_id, cluster_id, fingerprint |
| CollectorGroup | collector_groups | id, name, description, label_selector (JSONB) |
| App | apps | id, name, description, app_type (script/sdk), config_schema (JSONB), target_table |
| AppVersion | app_versions | id, app_id, version, source_code, requirements (JSONB), entry_class, is_latest, checksum, display_template, volatile_keys (JSONB) |
| AppAssignment | app_assignments | id, app_id, app_version_id, collector_id, device_id, config (JSONB), schedule_type, schedule_value, resource_limits, role, use_latest, enabled, credential_id |
| AppConnectorBinding | app_connector_bindings | id, app_id, connector_id, alias, use_latest, settings (JSONB) |
| AssignmentConnectorBinding | assignment_connector_bindings | id, assignment_id, connector_id, connector_version_id, alias, credential_id, use_latest, settings (JSONB) |
| AssignmentCredentialOverride | assignment_credential_overrides | id, assignment_id, alias, credential_id |
| Device | devices | id, name, address, device_type, is_enabled, tenant_id, collector_group_id, default_credential_id, credentials (JSONB), labels (JSONB), metadata (JSONB) |
| DeviceType | device_types | id, name, description, category |
| Credential | credentials | id, name, credential_type, secret_data (AES-256-GCM encrypted), template_id |
| CredentialKey | credential_keys | id, name, description, key_type (plain/secret/enum), is_secret, enum_values |
| CredentialValue | credential_values | id, credential_id, key_id, value |
| CredentialTemplate | credential_templates | id, name, description |
| CredentialType | credential_types | id, name, description |
| User | users | id, username, password_hash, role (admin/viewer), role_id, timezone, all_tenants, is_active |
| Tenant | tenants | id, name, metadata (JSONB) |
| UserTenant | user_tenants | (user_id, tenant_id) composite PK |
| Role | roles | id, name, description, is_system |
| RolePermission | role_permissions | id, role_id, resource, action |
| AlertDefinition | alert_definitions | id, app_id, name, expression, window, severity, enabled, message_template |
| AlertEntity | alert_entities | id, definition_id, assignment_id, device_id, state (ok/firing/resolved), enabled, entity_key, entity_labels, fire_count, fire_history |
| ThresholdVariable | threshold_variables | id, app_id, name, display_name, description, default_value, app_value, unit (free-text, max 50 chars) |
| ThresholdOverride | threshold_overrides | id, variable_id, device_id, entity_key, value |
| EventPolicy | event_policies | id, name, definition_id, mode, fire_count_threshold, window_size, event_severity, auto_clear_on_resolve |
| ActiveEvent | active_events | id, policy_id, entity_key, clickhouse_event_id |
| ApiKey | api_keys | id, key_hash, key_type (collector/management), collector_id, user_id, scopes |
| RegistrationToken | registration_tokens | id, token_hash, short_code, one_time, used, cluster_id |
| TlsCertificate | tls_certificates | id, name, cert_pem, key_pem_encrypted, is_active |
| Template | templates | id, name, description, config (JSONB) |
| SnmpOid | snmp_oids | id, name, oid, description |
| SystemSetting | system_settings | key (PK), value |
| InterfaceMetadata | interface_metadata | id, device_id, if_name, current_if_index, if_descr, if_alias, if_speed_mbps, polling_enabled, alerting_enabled, poll_metrics |
| LabelKey | label_keys | id, key, description, color, show_description, predefined_values |
| PythonModule | python_modules | id, name, description, homepage_url, is_approved |
| PythonModuleVersion | python_module_versions | id, module_id, version, dependencies, python_requires |
| WheelFile | wheel_files | id, version_id, filename, file_data, sha256_hash, file_size, python_tag, abi_tag, platform_tag |
| Connector | connectors | id, name, description, connector_type, is_builtin |
| ConnectorVersion | connector_versions | id, connector_id, version, source_code, requirements, entry_class, is_latest, checksum |
| Pack | packs | id, pack_uid, name, description, author, current_version |
| PackVersion | pack_versions | id, pack_id, version, manifest (JSONB), changelog |
| AppCache | app_cache | id, app_name, cache_key, cache_value, ttl_seconds, device_id |

### Konventioner

- Altid `UUID(as_uuid=True)` med `default=uuid.uuid4` for ID'er
- Altid `created_at` og `updated_at` med `server_default="now()"`
- ForeignKey pattern: `ForeignKey("table.id", ondelete="SET NULL")`
- JSONB med `server_default="{}"` for dict-felter
- `metadata_` mapped til `"metadata"` kolonne for at undgå keyword-konflikter

---

## ClickHouse-tabeller (storage/clickhouse.py)

5 domænetabeller + materialized views (ReplacingMergeTree for `_latest`):

| Tabel | Indhold | ORDER BY | Nøglekolonner |
|-------|---------|----------|---------------|
| availability_latency | Ping, HTTP, port checks | (assignment_id, executed_at) | state, rtt_ms, response_time_ms, reachable, status_code |
| performance | CPU, memory, custom metrics | (device_id, component_type, component, executed_at) | component, component_type, metric_names[], metric_values[] |
| interface | Network interface stats | (device_id, interface_id, executed_at) | interface_id, if_name, if_speed_mbps, in/out rates, errors, discards, utilization |
| config | Config/discovery data (change-only writes) | (device_id, component_type, component, config_key, executed_at) | config_key, config_value, config_hash |
| alert_log | Alert fire/clear history | (tenant_id, definition_id, entity_key, occurred_at) | action, current_value, threshold_value, fire_count |
| events | Event lifecycle (active/ack/cleared) | (tenant_id, severity, occurred_at, id) | event_type, definition_id, policy_id, state |
| logs | Centralized Docker/app logs | (collector_name, container_name, timestamp) | level, stream, message, host_label, image_name |

Alle tabeller har: assignment_id, collector_id, app_id, device_id, executed_at, received_at + denormaliserede felter: collector_name, device_name, app_name, tenant_id.

Hver tabel har en `_latest` materialized view (ReplacingMergeTree) der holder seneste resultat per nøgle. Interface har også `interface_hourly` og `interface_daily` rollup-tabeller.

**Multi-tier retention**: Raw (7 dage), hourly rollup (90 dage), daily rollup (730 dage). Auto-tier selection baseret på query time range.

**History query default**: `GET /v1/results` queries `availability_latency`, `performance`, `config` (IKKE `interface` — interface har egne endpoints).

---

## Key Subsystems

### Credential System

**Storage**: `Credential` model med AES-256-GCM encrypted `secret_data` kolonne.

**Types**: Managed via `CredentialType` tabel. Bruges som dropdown i credential creation UI.

**Templates**: `CredentialTemplate` + felter definerer hvilke keys en credential-type kræver.

**Resolution chain** (for connector bindings, i prioritetsrækkefølge):
1. `AssignmentCredentialOverride` — per-assignment, per-connector-alias override
2. `AppAssignment.credential_id` — assignment-level credential
3. `Device.default_credential_id` — device-level fallback

**Device credentials**: `Device.credentials` JSONB kolonne mapper `{credential_type: credential_id}` for per-protocol credential assignment.

### Connector System

**App-level bindings**: `AppConnectorBinding` erklærer hvilke connectors en app kræver (fx snmp_interface_poller kræver "snmp" connector). Managed i App Detail UI.

**Loading**: `apps/manager.py` downloader connector-kode fra central, installerer venvs, og loader klasser. Venv site-packages tilføjes **permanent til sys.path** så lazy imports virker.

**SNMP Connector** (v1.3.1): Accepterer både `snmp_version` og `version` credential keys for bagudkompatibilitet — credential API'et returnerer `version` (fra template key names), ikke `snmp_version`. Bygger pysnmp v7 auth objects for v1/v2c/v3. `connect()` er **idempotent** — returnerer med det samme hvis allerede forbundet til samme host.

**Connector credential keys**: Credential-feltnavne defineres af `CredentialTemplate` key definitions, og collector API'et (`/api/v1/credentials/{name}`) returnerer værdier med disse template key names. SNMP credential template bruger: `version`, `username`, `auth_password`, `priv_password`, `auth_protocol`, `priv_protocol`, `security_level`, `port`.

**Connector versionering**: Connectors gemmes i DB med checksums. Ny version (`POST /v1/connectors/{id}/versions` med `set_latest: true`) → næste job-fetch returnerer ny checksum → collectors re-downloader automatisk. Genstart poll-workers for at forcere øjeblikkelig opdatering.

**Connector lifecycle**: Polling engine styrer connect→use→close lifecycle. **Apps må IKKE kalde `connector.connect()` selv** — engine kalder det før appen får connector'en. Hvis en app kalder `connect()` alligevel, forhindrer den idempotente guard memory leaks.

**Memory management**: Engine kalder `gc.collect()` + `malloc_trim(0)` efter hvert job. Workers bruger `MALLOC_ARENA_MAX=2`, `PYTHONMALLOC=malloc`, og `mem_limit: 1g` i docker-compose.

### Interface Monitoring

**Metadata**: `InterfaceMetadata` tabel cacher stabil interface-identitet `(device_id, if_name)` med `polling_enabled`, `alerting_enabled`, `poll_metrics` settings.

**Targeted polling**: GetJobs injicerer `monitored_interfaces` liste i job-parametre. Poller bruger targeted SNMP GET i stedet for full walk.

**Metadata refresh**: `POST /v1/devices/{id}/interface-metadata/refresh` sætter Redis flag. Næste job-fetch omitter `monitored_interfaces`, tvinger full SNMP walk.

**Rate calculation**: Central-side (ikke collector). Previous counters cached i Redis per interface. Delta/rate computed ved result ingestion.

### Config Data Optimization

**Write suppression**: `collector_api/router.py` sammenligner MD5 hash per config key mod `config_latest FINAL` før skrivning. Kun ændrede keys og volatile keys skrives. In-memory LRU cache (60s TTL).

**Volatile keys**: `AppVersion.volatile_keys` JSONB felt — keys der ændres hvert poll (fx uptime). Bypasser suppression.

**Change history API** (`config_history/router.py`): 4 endpoints under `/v1/devices/{id}/config/`:
- `GET /changelog` — paginated ændringshistorik
- `GET /snapshot` — nuværende config (fra `config_latest FINAL`)
- `GET /diff?config_key=...` — værdihistorik for specifik key
- `GET /change-timestamps` — tidslinje (minut-buckets)

**Retention**: `config_retention_days` system setting (default 90 dage). Scheduler cleanup task sletter gammel config data.

### Device Enable/Disable

**Model**: `Device.is_enabled` boolean (default `true`). Disabled devices udelukkes fra collector job scheduling via `or_(device_id IS NULL, Device.is_enabled == True)` filter i `GET /api/v1/jobs`.

**Bulk operations**: `POST /v1/devices/bulk-patch` accepterer `{device_ids, is_enabled?, collector_group_id?, tenant_id?}`. Tenant-scoped visibility filtering. Ved flytning til collector group migreres assignments og collector config versions bumpes.

**Frontend**: DevicesPage bulk action bar inkluderer Enable, Disable, Move to Group, Move to Tenant knapper. Disabled devices renderes med `opacity-50` og grå status dot.

### Alerting System (Redesigned)

**Two-tier architecture**: Alerts (per-entity, high-volume) → Events (policy-promoted, lower-volume).

**Alert Definitions** (`AlertDefinition`): App-level (NOT version-level). DSL expression language with arithmetic (+, -, *, /), `rate()`, safety limits (2000 chars, 200 tokens, 10 nesting). Auto-extracts threshold parameters.

**DSL Examples**: `avg(in_utilization_pct) > 80`, `rate(in_octets) * 8 / 1000000 > 500`, `firmware_version CHANGED`, `state IN ('down')`.

**Alert Entities** (`AlertEntity`): Per-assignment per-entity state (ok/firing/resolved). fire_count, fire_history (20-entry ring buffer), current_value.

**Threshold Variables** (`ThresholdVariable`): App-level named parameters auto-synced from DSL. Fields: `name`, `display_name`, `description`, `default_value`, `app_value`, `unit` (free-text string, max 50 chars). 4-level hierarchy: expression default → app_value → device override → entity override. `ThresholdOverride` references `variable_id` + scalar `value`.

**Threshold Units**: Built-in: `percent`, `ms`, `seconds`, `bytes`, `count`, `ratio`, `dBm`, `pps`, `bps`. Custom units allowed via CRUD (any non-empty string up to 50 chars). Pack import validates against built-in list only.

**Device Thresholds API** (`GET /devices/{id}/thresholds`): Returns flat `DeviceThresholdRow[]` — one row per variable across all apps assigned to the device. Each row: `variable_id`, `name`, `display_name`, `unit`, `app_name`, `expression_default`, `app_value`, `device_value`, `effective_value` (never null), `device_override_id`, `entity_overrides[]`, `used_by_definitions[]`.

**Threshold Editing** (`PUT /apps/{id}/thresholds/{var_id}`): Accepts `default_value`, `app_value`, `clear_app_value` (bool, explicitly nulls app_value), `display_name`, `description`, `unit`.

**Alert Log** (`alert_log` ClickHouse): Append-only fire/clear records. Written every 30s by engine.

**Event Policies** (`EventPolicy`): consecutive or cumulative mode. `ActiveEvent` table for dedup.

**Events** (`events` ClickHouse): active → acknowledged → cleared. Auto-clear on alert resolve.

**Engine**: 30s cycle, leader-elected. Resolves thresholds per-entity, batches ClickHouse queries by effective threshold combination.

### WebSocket Command Channel

Persistent bidirectional WebSocket (`/ws/collector`) for ad-hoc commands. Collector initiates outward (NAT/firewall compatible). Message envelope: `{message_id, type, in_reply_to, payload, timestamp}`. Types: ping/pong, poll_device, config_reload, health_check, module_update, docker_health, docker_logs. 60s timeout, 30s keepalive. Auto-reconnect: 1s/2s/3s/5s backoff.

Auth: shared secret (`MONCTL_COLLECTOR_API_KEY`) + `collector_id` query param (production mode), or individual collector API key.

### Centralized Log Collection

Docker-stats sidecars push logs to central via `/api/v1/docker-stats/push`. Push handler writes to Redis (ring-buffer) + ClickHouse (`logs` table). Collectors also run a backup log shipper that POSTs to `/api/v1/logs/ingest` every 10s. Sidecar URL for collectors: `http://monctl-docker-stats:9100` (Docker container DNS).

ClickHouse `logs` table: TTL `toDateTime(timestamp) + INTERVAL 7 DAY` (ClickHouse 24.3 requires `toDateTime()` wrapper for DateTime64 TTL). Configurable via `log_retention_days` system setting.

Query: `GET /v1/logs` (filter, paginate, sort), `GET /v1/logs/filters` (distinct values for dropdowns). Frontend: Logs tab on Docker Infrastructure page with live tail (2s poll).

### Redis Sentinel HA

3 sentinels (central1-3), primary (central1), replica (central2). **Critical**: `sentinel announce-ip <host-ip>` in sentinel.conf and `--replica-announce-ip <host-ip>` in Redis command — required for Docker bridge networking. Without this, sentinels advertise container-internal IPs (172.x.x.x) and cross-host communication breaks. Coordinated restart needed to reset corrupt sentinel state (stop all 3 simultaneously, then start all).

### Infrastructure Node Configuration

**Ingen hardcodede IP-adresser i applikationskoden.** Patroni, etcd og Redis Sentinel node-lister konfigureres via env vars:

| Env var | Format | Eksempel |
|---------|--------|----------|
| `MONCTL_PATRONI_NODES` | `name:ip,name:ip,...` | `central1:10.145.210.41,central2:10.145.210.42` |
| `MONCTL_ETCD_NODES` | `name:ip,name:ip,...` | `central1:10.145.210.41,central2:10.145.210.42,central3:10.145.210.43` |
| `MONCTL_REDIS_SENTINEL_HOSTS` | `host:port,host:port,...` | `10.145.210.41:26379,10.145.210.42:26379,10.145.210.43:26379` |

`parse_node_list()` i `config.py` parser `name:ip`-formatet. Health checks returnerer "unconfigured" status hvis ikke sat.

### Dashboard & Analytics

**Operational Dashboard** (`dashboard/router.py`): `GET /v1/dashboard/summary` aggregerer alert_summary, device_health, collector_status, performance_top_n i ét kald. Frontend bruger `useDashboardSummary()` med 15s auto-refresh. Stat cards, worst devices tabel, performance top-N med progress bars.

**Metabase** (`docker/metabase/`): Metabase v0.54 kører på central1 som Docker Compose service. Native ClickHouse driver. Bruger eksisterende PostgreSQL (`metabase` database). Tilgængelig via HAProxy på `https://VIP/metabase` (path-strip rewrite). Setup: `docker/metabase/setup.py`. 4 pre-built dashboards: Device Performance, Interface Traffic, Availability Overview, Alert History. Admin: `admin@monctl.local`.

**Grafana**: Grafana OSS 11.4 kører på central4. Tilgængelig via HAProxy på `https://VIP/grafana`.

**Analytics Page** (`pages/AnalyticsPage.tsx`): Links til Metabase dashboards + SQL query builder. Læser `metabase_url` fra system settings. Sidebar: "Analytics" mellem Events og Upgrades.

**Custom Dashboards** (`analytics/dashboards.py`): Bruger-oprettede dashboards med SQL-baserede widgets. `AnalyticsDashboard` model (PostgreSQL) med `variables` JSONB kolonne for cross-widget kontekst-variabler. `AnalyticsWidget` gemmer SQL, chart config og layout per widget.

**Dashboard Editor** (`pages/DashboardEditorPage.tsx`): Bruger `react-grid-layout` v2.2.3 (hook-baseret API: `useContainerWidth`, `ResponsiveGridLayout`) for drag-and-drop + resize. 24-kolonne grid, `rowHeight: 40`, `.drag-handle` på GripVertical ikon.

**Time Picker** (`components/DashboardTimePicker.tsx`): Dashboard-level tidsinterval med presets (15m, 1h, 6h, 24h, 7d, 30d) + custom datetime range. Widgets bruger `{time_from}` og `{time_to}` placeholders i SQL — client-side substitution via `resolveSQL()`. ClickHouse 24.3 kræver `YYYY-MM-DD HH:MM:SS` format (ikke ISO 8601). Værdier wrappes i single quotes.

**Cross-Widget Variables**: Dashboard-level navngivne variabler (`DashboardVariable`). Widgets refererer `{var:name}` i SQL (client-side substitution, SQL-escaped). Tabel-widgets kan "publicere" en kolonne-værdi til en variabel ved row-klik (`config.publishes`). `DashboardVariableBar` viser aktive værdier som pills.

**Widget Append**: `POST /v1/analytics/dashboards/{id}/widgets` tilføjer en widget uden at erstatte eksisterende. Bruges af SQL Explorer's "Save to Dashboard" (`useAppendDashboardWidget` hook).

**Add Widget Dialog** (`components/AddWidgetDialog.tsx`): SQL editor + Test-knap (resolver placeholders med default "last 1h") + visualisering + bredde-valg (Half/Full) + X/Y/Group By config (synlig efter Test) + "Publishes to variable" for tabel-widgets.

### Packs System

Import/export af monitoring packs (apps + connectors + alert definitions + credential templates + grafana dashboards). Preview + conflict detection. Version tracking. `grafana_dashboards` sektion eksporterer/importerer dashboards via Grafana API (tagging konvention: `pack:{uid}`).

---

## API-endpoints

### Web API (`/v1/`) — 30 routers

| Router | Prefix | Endpoints | Auth |
|--------|--------|-----------|------|
| auth | /v1/auth | POST login, logout, refresh; GET me | Public (login) |
| devices | /v1/devices | GET list (sort/filter/paginate), POST create, POST bulk-patch, POST bulk-delete, GET/:id, PUT/:id, DELETE/:id, monitoring CRUD, interface-metadata CRUD | require_auth |
| collectors | /v1/collectors | POST register, approve, reject, heartbeat; GET list, /:id, config; PUT/:id, DELETE/:id | Mixed |
| collector_groups | /v1/collector-groups | CRUD | require_auth |
| apps | /v1/apps | CRUD apps + versions + assignments + connector bindings | require_auth |
| results | /v1/results | GET list, /latest, /by-device/:id, /interfaces, /interface-history | require_auth |
| config_history | /v1/devices/:id/config | GET /changelog, /snapshot, /diff, /change-timestamps | require_auth |
| credentials | /v1/credentials | CRUD + types CRUD (secrets aldrig returneret) | require_auth |
| credential_keys | /v1/credential-keys | CRUD | require_auth |
| credential_templates | /v1/credential-templates | CRUD | require_auth |
| connectors | /v1/connectors | CRUD connectors + versions | require_auth |
| alerting | /v1/alerts | Definitions, instances, evaluation, metrics, thresholds | require_auth |
| events | /v1/events | GET list, POST acknowledge, POST clear | require_auth |
| tenants | /v1/tenants | CRUD | require_auth |
| users | /v1/users | CRUD + PUT /me/timezone + tenant assignments | require_admin (mest) |
| roles | /v1/roles | CRUD + permissions | require_admin |
| device_types | /v1/device-types | CRUD | require_auth |
| snmp_oids | /v1/snmp-oids | CRUD | require_auth |
| label_keys | /v1/label-keys | CRUD | require_auth |
| registration_tokens | /v1/registration-tokens | POST create, GET list | require_auth |
| templates | /v1/templates | CRUD + POST /:id/apply | require_auth |
| packs | /v1/packs | Import, export, preview, CRUD | require_auth |
| python_modules | /v1/python-modules | Registry + PyPI import + wheel upload/download | require_auth |
| user_api_keys | /v1/user-api-keys | CRUD | require_auth |
| settings | /v1/settings | GET, PUT | require_admin |
| tls | /v1/settings/tls | GET, POST generate/upload/deploy | require_admin |
| system | /v1/system | GET /health (concurrent subsystem checks) | require_admin |
| docker_infra | /v1/docker-infra | GET overview, stats, containers, logs, events, images | require_auth |
| dashboard | /v1/dashboard | GET /summary (aggregated dashboard data) | require_auth |
| logs | /v1/logs | GET (query+filter+paginate), GET /filters, POST /ingest | require_auth |
| ws_command | /v1/collectors | GET /{id}/ws-status, GET /ws-connections, POST /{id}/command/{type} | require_auth |
| ws | /ws/collector | WebSocket endpoint (persistent bidirectional) | token query param |
| ingestion | /v1 | POST /ingest (legacy) | require_collector_auth |

### Collector API (`/api/v1/`)

| Endpoint | Metode | Formål |
|----------|--------|--------|
| /api/v1/jobs | GET | Hent job assignments (server-side weighted partitioning, excludes disabled devices) |
| /api/v1/apps/:id/metadata | GET | App metadata |
| /api/v1/apps/:id/code | GET | App source code + requirements |
| /api/v1/connectors/:id/code | GET | Connector source code + requirements |
| /api/v1/credentials/:name | GET | Dekrypteret credential |
| /api/v1/results | POST | Push check resultater |
| /api/v1/logs/ingest | POST | Batch log ingestion (collector → ClickHouse) |
| /api/v1/app-cache | GET/PUT | App-level persistent cache |

### API Response-format

```json
{"status": "success", "data": { ... }}
{"status": "success", "data": [...], "meta": {"limit": 50, "offset": 0, "count": 10, "total": 123}}
```

### Authentication

- **Web UI**: JWT i HTTP-only cookies (access_token + refresh_token)
- **Management API**: `Authorization: Bearer monctl_m_<key>`
- **Collector API**: `Authorization: Bearer <MONCTL_COLLECTOR_API_KEY>` (shared secret)
- **Dependencies**: `require_auth` (any), `require_admin` (admin role), `require_collector_auth` (3-mode)

### Multi-Tenant Filtering

```python
stmt = apply_tenant_filter(stmt, auth, Device.tenant_id)
```

---

## Frontend — sider og komponenter

### Sider (28)

| Side | Route | Formål |
|------|-------|--------|
| LoginPage | /login | Username/password login |
| DashboardPage | / | 4 stat cards (alerts/up/down/collectors) + active alerts tabel + worst devices + performance top-N (CPU/memory/bandwidth) + collector issues |
| SystemHealthPage | /system-health | Subsystem-kort (PG, CH, Redis, Collectors, Scheduler) + collector-tabel med filter |
| DockerInfraPage | /docker-infrastructure | Docker host overview, containers, logs, events, images |
| DevicesPage | /devices | Server-side pagination/sort/filter, bulk actions (enable/disable/move/delete/template), status dots |
| DeviceDetailPage | /devices/:id | Tabs: Overview (staleness warning + availability chart), Checks, Assignments, Interfaces, Performance, Config (poll status badge), Alerts, Thresholds (flat variable list with effective value highlighting) |
| AppsPage | /apps | App liste med type/target_table/version count |
| AppDetailPage | /apps/:id | Tabs: Overview (edit), Versions (CodeEditor+VersionActions), Connector Bindings, Alerts, Thresholds (inline-editable Default+App Value, UnitSelector, Description) |
| ConnectorsPage | /connectors | Connector liste |
| ConnectorDetailPage | /connectors/:id | Connector versions + code editor |
| PythonModulesPage | /python-modules | Package registry, PyPI import, wheel upload |
| AssignmentsPage | /assignments | Assignment liste med per-column filter, bulk actions (schedule, credential, enabled) |
| TemplatesPage | /templates | Template CRUD |
| PacksPage | /packs | Monitoring pack liste |
| PackDetailPage | /packs/:id | Pack versions, entities, export |
| AlertsPage | /alerts | Tabs: Active Alerts, Alert Log (ClickHouse), Alert Definitions |
| EventsPage | /events | Active/cleared events med acknowledge/clear |
| AnalyticsPage | /analytics | Grafana dashboard links, reads grafana_url fra system settings |
| UpgradesPage | /upgrades | OS upgrades, package management, rolling upgrade orchestration |
| SettingsPage | /settings/:tab | Tabs: Profile, System, Device Types, Collectors, Credentials, SNMP OIDs, Labels, Roles, Users, Tenants |
| CollectorsPage | (settings tab) | Pending/Active collectors, Groups, Registration Tokens |
| CredentialsPage | (settings tab) | Credential Keys + Templates + Types + Credentials CRUD |
| UsersPage | (settings tab) | User CRUD + tenant assignments |
| TenantsPage | (settings tab) | Tenant CRUD med metadata editor |
| DeviceTypesPage | (settings tab) | Device type CRUD |
| LabelKeysPage | (settings tab) | Label key CRUD med farver og predefined values |
| RolesPage | (settings tab) | RBAC role CRUD + permissions |
| SnmpOidsPage | (settings tab) | SNMP OID catalog CRUD |

### Feature-komponenter (23)

| Komponent | Formål |
|-----------|--------|
| AddDeviceDialog | Form dialog: name, address, type, tenant, group, credential |
| ApplyTemplateDialog | Bulk apply monitoring template til valgte devices |
| AvailabilityChart | Recharts: availability strip + latency lines, adaptive buckets, gap detection |
| CodeEditor | CodeMirror 6: Python syntax, one-dark theme, resizable |
| ConfigDataRenderer | Renders config key-value data med diff highlighting |
| CredentialCell | Viser credential chain (override → assignment → device default) |
| CreatePackDialog | Dialog til at oprette monitoring packs |
| DisplayTemplateEditor | Editor for app display templates (HTML/CSS) |
| FilterableSortHead | Sort label + inline ClearableInput filter i TableHead |
| PaginationBar | Reusable pagination controls (X-Y of Z + prev/next) |
| InterfaceTrafficChart | Recharts: In/Out traffic chart for network interfaces |
| KeyValueEditor | Key-value pair editor for metadata/labels |
| LabelEditor | Label editor med auto-complete fra LabelKey definitions |
| ModulePicker | Python module version picker for app requirements |
| PerformanceChart | Recharts: Multi-metric performance chart |
| PyPIImportDialog | Dialog til at importere packages fra PyPI |
| StatusBadge | State → farve+label mapping (OK, WARNING, CRITICAL, DOWN, etc.) |
| TimePicker | Time picker component |
| TimeRangePicker | Dropdown: presets (15m-30d-all) + relative + absolute custom ranges |
| VersionActions | Reusable icon-only action buttons for version rows (fixed-width slots) |
| WheelUploadDialog | Dialog til at uploade Python wheel files |

### UI-primitiver (10)

badge, button, card, clearable-input, dialog, input, label, select, table, tabs

### Sidebar navigation (15 items)

Dashboard → System Health → Docker Infra → Devices → Apps → Connectors → Modules → Assignments → Templates → Packs → Alerts → Events → Analytics → Upgrades → Settings

### Polling

- Lister: 30 sekunder
- Detail views: 15 sekunder
- System Health: 15 sekunder

### React Query patterns

- `useQuery` med `queryKey` og `refetchInterval`
- `useMutation` med `onSuccess: async () => { await qc.invalidateQueries(...) }`
- `apiGet<T>()` returnerer `ApiResponse<T>` = `{status, data}`
- Hooks: `useDevices(params)`, `useCreateDevice()`, `useBulkPatchDevices()`, etc.

### Frontend UI-patterns

**ClearableInput** (`components/ui/clearable-input.tsx`): Wrapper around `<Input>` med inline `×` clear-knap. Knappen og `pr-7` padding er **altid i DOM** (skjult via `opacity-0 pointer-events-none`) for at undgå fokus-tab.

**Filter empty states**: Når filtre er aktive men matcher intet, vis altid tabellen (headers + filter inputs) med en tom body-række. Vis kun den store centered empty state når der virkelig er nul items OG ingen filtre er aktive.

**Conditional rendering og fokus**: Brug aldrig `{condition && <Element/>}` til at indsætte/fjerne elementer i en parent container der har sibling form inputs. Brug i stedet CSS visibility (`opacity-0 pointer-events-none`).

**List views (server-side søgning/sortering/paginering)**: Alle list pages bruger `useListState` hook for per-column debounced filters (300ms), sort state og paginering. Column headers bruger `FilterableSortHead`. Paginering bruger `PaginationBar`. Alle list hooks accepterer `ListParams` og bruger `placeholderData: keepPreviousData` for at undgå tabel-unmount under refetch.

---

## Vigtige implementeringsdetaljer

### Nye features — step by step

1. **Model** i `storage/models.py` (UUID PK, created_at/updated_at)
2. **Alembic migration** i `alembic/versions/`
3. **Router** i ny mappe `my_feature/router.py`, registrér i `api/router.py`
4. **TypeScript types** i `types/api.ts`
5. **React Query hooks** i `api/hooks.ts`
6. **Page** i `pages/MyPage.tsx`
7. **Route** i `App.tsx`
8. **Nav item** i `layouts/Sidebar.tsx`

### ClickHouse er synkron

`clickhouse_connect` er synkron → wrap i `asyncio.to_thread()` i async-kontekst.

### Redis-adgang

`_redis` er en module-level global i `cache.py`. Importér med `from monctl_central.cache import _redis`.

### Scheduler leader

Redis key `monctl:scheduler:leader` med 30s TTL. Læs med `_redis.get()` og `_redis.ttl()`.

### Error handling

```python
raise HTTPException(status_code=400, detail="Invalid input")
raise HTTPException(status_code=404, detail="Not found")
raise HTTPException(status_code=409, detail="Already exists")
```

### Build & Deploy

```bash
# Central build
docker build --platform linux/amd64 --no-cache -t monctl-central:latest -f docker/Dockerfile.central .

# Push til alle central servere
for ip in 41 42 43 44; do
  docker save monctl-central:latest | ssh monctl@10.145.210.$ip 'docker load'
done

# Restart central (central1-3 bruger central-ha, central4 bruger central/)
for ip in 41 42 43; do
  ssh monctl@10.145.210.$ip 'cd /opt/monctl/central-ha && docker compose down && docker compose up -d'
done
ssh monctl@10.145.210.44 'cd /opt/monctl/central && docker compose down && docker compose up -d'
```

### Collector deploy

```bash
docker build --platform linux/amd64 --no-cache -t monctl-collector:latest -f docker/Dockerfile.collector-v2 .
# Push til worker1-4 (.31-.34), restart: cd /opt/monctl/collector && docker compose down && docker compose up -d
```

### Vigtige deploy-noter

- Brug `Dockerfile.collector-v2` (ikke `Dockerfile.collector`)
- Ingen npm/node på servere — Dockerfile håndterer frontend build
- Ingen package-lock.json — bruger `npm install` (ikke `npm ci`)
- Altid `--no-cache` ved rebuild efter source changes
- Brug `docker compose up -d` (ikke `restart`) for at bruge nye images
- Deploy til ALLE 4 central nodes og ALLE 4 worker nodes

### Kode-stil

- Python: ruff, line-length 100, target Python 3.11
- TypeScript: standard React conventions, path alias `@/`
- Kommunikér på dansk når bruger skriver dansk

---

## Hvad planen skal indeholde

Når du laver en plan til implementering, inkludér:

1. **Kontekst**: Hvad feature'en løser og hvorfor
2. **Scope**: Præcis hvilke filer der oprettes/ændres
3. **Backend**: Router-kode med endpoints, request/response modeller, DB queries
4. **Frontend**: Types, hooks, page-komponent, routing, navigation
5. **Migrationer**: Hvis der er nye tabeller/kolonner
6. **Vigtige detaljer**: Gotchas, async patterns, ClickHouse wrapping, auth requirements
7. **Implementeringsrækkefølge**: Nummereret liste
8. **Verifikation**: Hvordan man tester at det virker

Planen skal være specifik nok til at man kan implementere direkte uden at skulle læse yderligere kode, men undgå at gengive kode der allerede eksisterer (referer til filer/mønstre i stedet).
