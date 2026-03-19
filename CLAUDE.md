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
│   │   ├── cache.py            # Redis client + caching (enrichment, interface ID, refresh flags)
│   │   ├── storage/
│   │   │   ├── models.py       # SQLAlchemy models (33 models, all PostgreSQL tables)
│   │   │   └── clickhouse.py   # ClickHouse client, DDL, insert/query methods
│   │   ├── api/router.py       # Main router (mounts 25+ sub-routers at /v1/)
│   │   ├── auth/               # JWT cookie auth (login, refresh, me)
│   │   ├── devices/router.py   # Device CRUD, bulk-patch, monitoring config, interface metadata, credentials
│   │   ├── collectors/router.py # Collector registration, approval, heartbeat
│   │   ├── collector_api/router.py # /api/v1/ endpoints collectors call (jobs, results, credentials)
│   │   ├── apps/router.py      # App CRUD + assignment CRUD + version management
│   │   ├── results/router.py   # ClickHouse query API (history, latest, interfaces)
│   │   ├── credentials/        # Credential CRUD, types, crypto
│   │   ├── credential_keys/    # Reusable credential field definitions
│   │   ├── connectors/         # Connector CRUD + versions
│   │   ├── alerting/           # Alert definitions, instances, evaluation engine, event policies
│   │   ├── events/             # Active/cleared events, acknowledgement
│   │   ├── packs/              # Monitoring pack import/export
│   │   ├── python_modules/     # Package registry + PyPI import + wheel distribution
│   │   ├── docker_infra/       # Docker host monitoring (stats, logs, events, images)
│   │   ├── roles/              # Custom RBAC roles + permissions
│   │   ├── templates/router.py # Monitoring templates (bulk app assignment)
│   │   ├── tenants/router.py   # Multi-tenant support
│   │   ├── users/router.py     # User CRUD + timezone + API keys
│   │   ├── settings/router.py  # System settings (retention, intervals, etc.)
│   │   └── scheduler/          # Leader election + background tasks
│   ├── frontend/               # React SPA
│   │   └── src/
│   │       ├── api/
│   │       │   ├── client.ts   # fetch() wrapper (apiGet, apiPost, apiPut, apiPatch, apiDelete)
│   │       │   └── hooks.ts    # 116 React Query hooks for ALL API endpoints
│   │       ├── types/api.ts    # 93+ TypeScript interfaces for API responses
│   │       ├── pages/          # 26 page components
│   │       ├── components/     # 19 reusable UI components (incl. ClearableInput)
│   │       ├── hooks/          # useAuth, useTimezone
│   │       └── layouts/        # Sidebar + Header + AppLayout
│   └── alembic/                # 42 database migrations
├── collector/                  # Collector node
│   └── src/monctl_collector/
│       ├── config.py           # YAML + env config
│       ├── central/
│       │   ├── api_client.py   # HTTP client for /api/v1/
│       │   └── credentials.py  # Credential fetch + local encrypted cache
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

**SNMP Connector**: Accepts both `snmp_version` and `version` credential keys for backward compatibility. Builds pysnmp v7 auth objects for v1/v2c/v3.

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
| `config` | Configuration tracking | config_key, config_value, config_hash |
| `events` | Collector events | TTL 30 days |

Each table has a `*_latest` materialized view (ReplacingMergeTree) for instant latest-per-key lookups. Interface also has `interface_hourly` and `interface_daily` rollup tables.

**History query default**: `GET /v1/results` queries `availability_latency`, `performance`, `config` by default (NOT `interface` — interface data has its own dedicated endpoints to avoid flooding the History tab with one row per interface per poll).

### Device Enable/Disable

**Model**: `Device.is_enabled` boolean column (default `true`). Disabled devices are excluded from collector job scheduling via an `or_(device_id IS NULL, Device.is_enabled == True)` filter in `GET /api/v1/jobs`.

**Bulk operations**: `POST /v1/devices/bulk-patch` accepts `{device_ids, is_enabled?, collector_group_id?, tenant_id?}`. Applies tenant-scoped visibility filtering. When moving to a collector group, also migrates assignments (nulls out explicit collector_id) and bumps collector config versions.

**Frontend**: DevicesPage bulk action bar includes Enable, Disable, Move to Group, Move to Tenant buttons. Disabled devices render with `opacity-50` and a grey status dot.

### Alerting System

- `AppAlertDefinition`: Alert rules defined per app (DSL expression language)
- `AlertInstance`: Active/resolved alert instances
- `ThresholdOverride`: Per-device per-entity overrides
- `EventPolicy`: Rules for promoting alerts to events
- Background evaluation engine with leader election

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

### Server Inventory

| Role     | Hosts          | IPs                    |
|----------|----------------|------------------------|
| Central  | central1-4     | 10.145.210.41 - .44    |
| Workers  | worker1-4      | 10.145.210.31 - .34    |
| VIP      | (keepalived)   | 10.145.210.40          |

SSH user: `monctl` for all servers. Compose files at `/opt/monctl/{central,collector}/docker-compose.yml`.

### Code Style

- Python: ruff with line-length 100, target Python 3.11
- TypeScript: standard React conventions, path aliases `@/`
- Communicate in Danish when the user writes in Danish

### Frontend UI Patterns

**ClearableInput** (`components/ui/clearable-input.tsx`): Wraps `<Input>` with an inline `×` clear button. The button and `pr-7` padding are **always in the DOM** (hidden via `opacity-0 pointer-events-none`) to avoid focus loss caused by DOM structure changes during typing.

**Filter empty states**: When filters are active but match no results, always keep the table visible (headers + filter inputs) with an empty body row message like `"No devices match your filters"`. Only show the big centered empty state (icon + action button) when there are truly zero items AND no filters are active. This lets users refine their query without losing context.

**Conditional rendering and focus**: Never use `{condition && <Element/>}` to insert/remove elements in a parent container that has sibling form inputs — React's index-based reconciliation can cause focus loss. Instead, always render the element and toggle visibility with CSS (`opacity-0 pointer-events-none`).
