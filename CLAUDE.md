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
│   │   ├── cache.py            # Redis client + caching
│   │   ├── storage/
│   │   │   ├── models.py       # SQLAlchemy models (all PostgreSQL tables)
│   │   │   └── clickhouse.py   # ClickHouse client, DDL, insert/query methods
│   │   ├── api/router.py       # Main router (mounts sub-routers at /v1/)
│   │   ├── auth/               # JWT cookie auth (login, refresh, me)
│   │   ├── devices/router.py   # Device CRUD, bulk-patch, monitoring config, interface metadata
│   │   ├── collectors/router.py # Collector registration, approval, heartbeat, WS status
│   │   ├── collector_api/router.py # /api/v1/ endpoints collectors call (jobs, results, credentials)
│   │   ├── ws/                 # WebSocket command channel (collector ↔ central)
│   │   ├── logs/               # Centralized log collection (ClickHouse)
│   │   ├── apps/router.py      # App CRUD + assignment CRUD + version management
│   │   ├── results/router.py   # ClickHouse query API (history, latest, interfaces)
│   │   ├── config_history/     # Config change history (changelog, snapshot, diff)
│   │   ├── credentials/        # Credential CRUD, types, crypto
│   │   ├── credential_keys/    # Reusable credential field definitions
│   │   ├── connectors/         # Connector CRUD + versions
│   │   ├── alerting/           # Alert definitions, entities, DSL engine, thresholds
│   │   ├── events/             # Event policies, engine, active/cleared events
│   │   ├── automations/        # Run Book Automation (actions + automations)
│   │   ├── dashboard/          # Aggregated dashboard summary endpoint
│   │   ├── packs/              # Monitoring pack import/export
│   │   ├── python_modules/     # Package registry + PyPI import + wheel distribution
│   │   ├── docker_infra/       # Docker host monitoring (stats, logs, events, images)
│   │   ├── roles/              # Custom RBAC roles + permissions
│   │   ├── templates/          # Monitoring templates + hierarchical bindings
│   │   ├── tenants/router.py   # Multi-tenant support
│   │   ├── users/router.py     # User CRUD + timezone + API keys
│   │   ├── settings/router.py  # System settings (retention, intervals, etc.)
│   │   └── scheduler/          # Leader election + background tasks
│   ├── frontend/               # React SPA
│   │   └── src/
│   │       ├── api/
│   │       │   ├── client.ts   # fetch() wrapper (apiGet, apiPost, apiPut, apiPatch, apiDelete)
│   │       │   └── hooks.ts    # React Query hooks for ALL API endpoints
│   │       ├── types/api.ts    # TypeScript interfaces for API responses
│   │       ├── pages/          # Page components
│   │       ├── components/     # Reusable UI components
│   │       ├── hooks/          # useAuth, useTimezone, usePermissions
│   │       └── layouts/        # Sidebar + Header (pageTitles map) + AppLayout
│   └── alembic/                # Database migrations
├── collector/                  # Collector node
│   └── src/monctl_collector/
│       ├── config.py           # YAML + env config
│       ├── central/
│       │   ├── api_client.py   # HTTP client for /api/v1/
│       │   ├── credentials.py  # Credential fetch + local encrypted cache
│       │   ├── ws_client.py    # WebSocket client (persistent, auto-reconnect)
│       │   ├── ws_handlers.py  # Command handlers (poll_device, config_reload, docker_*)
│       │   └── log_shipper.py  # Background log collection → POST to central
│       ├── polling/
│       │   ├── engine.py       # Min-heap deadline scheduler + connector instantiation
│       │   └── base.py         # BasePoller abstract class
│       ├── apps/manager.py     # App/connector download, venv management, class loading
│       ├── forward/forwarder.py # Result batching + posting to central
│       ├── cache/              # SQLite backend + app cache sync
│       ├── jobs/               # Job models, scheduling, work stealing
│       └── peer/               # gRPC client/server for inter-collector communication
├── common/                     # Shared: monctl_common.utils (utc_now, hash_api_key)
└── sdk/                        # SDK package (base classes, testing utilities)
```

---

## Key Gotchas & Non-Obvious Behavior

### Credential Resolution Chain (precedence order)
1. `AssignmentCredentialOverride` — per-assignment, per-connector-alias
2. `AppAssignment.credential_id` — assignment-level
3. `Device.credentials` JSONB — per-type mapping (`{credential_type: credential_id}`)

### Connector System
- **SNMP Connector** accepts both `snmp_version` and `version` credential keys (backward compat). Credential API returns `version` from template key names.
- **Connector lifecycle**: Polling engine manages connect→use→close. **Apps must NOT call `connector.connect()`** — the engine does it. Idempotent guard prevents leaks if called anyway.
- **Venv site-packages** are permanently added to `sys.path` so lazy imports work at runtime.
- **Memory management**: `gc.collect()` + `malloc_trim(0)` after each job. Workers use `MALLOC_ARENA_MAX=2`, `PYTHONMALLOC=malloc`, `mem_limit: 1g`.

### Job Partitioning
- Unpinned assignments use consistent hashing via `CollectorGroup.weight_snapshot` JSONB.
- `weight_snapshot = NULL` → equal weights fallback. Set to NULL on collector DOWN/approve/group-change.
- Rebalancer runs every 5 min. Threshold: 1.5x imbalance ratio, 15% weight change hysteresis.

### Interface Monitoring
- **Rate calculation is central-side** (not collector). Previous counters cached in Redis.
- **Targeted polling**: `monitored_interfaces` list injected into job params. Uses SNMP GET (not walk).
- **Multi-tier retention**: Raw (7d), hourly (90d), daily (730d). Auto-tier selection by time range.

### Alerting & Thresholds
- **DSL**: `avg(metric) > 80`, `rate(octets) * 8 / 1e6 > 500`, `field CHANGED`, `state IN (...)`. Compiled to ClickHouse SQL.
- **4-level threshold hierarchy**: expression default → app_value → device override → entity override.
- **Engine**: 30s evaluation cycle. Writes fire/clear to `alert_log` ClickHouse table.
- **Events**: Promote alerts via `EventPolicy` (fire_count or fire_history window).

### Template Hierarchy
- Two-level: `DeviceCategory` (broad) → `DeviceType` (specific override). Priority field controls merge order.
- `templates/resolver.py`: Category merges first (low→high priority), then type overlays.

### Dashboard & Analytics
- **ClickHouse 24.3 cannot parse ISO 8601**. `resolveTimestamp()` outputs `YYYY-MM-DD HH:MM:SS`. Values wrapped in single quotes.
- **Dashboard Editor**: `react-grid-layout` v2.2.3 (hook-based API). 24-column grid, `rowHeight: 40`.
- **Cross-widget variables**: `{var:name}` in SQL, client-side substitution, single-quote wrapped.
- **History query default**: `GET /v1/results` queries `availability_latency`, `performance`, `config` — NOT `interface` (has own endpoints).

### Redis Sentinel
- **`announce-ip` is critical**: Without it in Docker bridge mode, sentinels advertise unreachable 172.x.x.x IPs.
- Sentinel config copied to `/tmp/` on start — container must be **recreated** (not restarted) to reset state.
- **Coordinated restart**: All 3 sentinels must stop simultaneously before restarting.

### Log Collection
- `logs` ClickHouse table uses `toDateTime(timestamp)` wrapper in TTL (required for ClickHouse 24.3 DateTime64).
- `log_level_filter` on Collector model controls minimum shipped level.

### System Health
- **Overall status excludes alerts** — only infrastructure subsystems (postgresql, clickhouse, redis, scheduler, collectors, etc.) count. Alerts reflect monitored devices, not platform health.
- **Scheduler leader election**: Redis SETNX with 30s TTL, renewed every 10s. Only `role=all` or `role=scheduler` instances participate. **Gotcha**: Do not reuse `role` as a variable name in `main.py` lifespan — it shadows `settings.role` and breaks the scheduler check.
- **Lightweight status endpoint**: `GET /system/health/status` returns cached `overall_status` from last full check. Used by the top-bar health indicator dot (admin-only).
- **Patroni switchover**: `POST /system/patroni/switchover` proxies to Patroni REST API. Admin-only.
- **Docker host count**: Central nodes report via both sidecar agents and Redis push. The health check deduplicates by filtering push labels that match sidecar labels.

---

## API Conventions

### Response Format (ALWAYS)

```json
{"status": "success", "data": { ... }}
{"status": "success", "data": [...], "meta": {"limit": 50, "offset": 0, "count": 10, "total": 123}}
```

### Authentication

- **Web UI**: JWT in HTTP-only cookies (`access_token` + `refresh_token`)
- **Management API**: `Authorization: Bearer monctl_m_<key>`
- **Collector API**: `Authorization: Bearer <MONCTL_COLLECTOR_API_KEY>` (shared secret)
- **Dependencies**: `require_permission("resource", "action")` (RBAC-enforced), `require_admin` (admin role only)
- **RBAC**: All endpoints use `require_permission`. Admins and API keys bypass automatically. Resources: `device`, `app`, `assignment`, `credential`, `alert`, `collector`, `tenant`, `user`, `template`, `settings`, `result`. Actions: `view`, `create`, `edit`, `delete`, `manage`.
- **Frontend**: `usePermissions()` hook controls sidebar visibility, settings tabs, and action buttons

### Routes

- Web API under `/v1/` (e.g., `/v1/devices`, `/v1/apps`)
- Collector API under `/api/v1/` (e.g., `/api/v1/jobs`, `/api/v1/results`)

### Multi-Tenant Filtering

```python
from monctl_central.dependencies import apply_tenant_filter
stmt = apply_tenant_filter(stmt, auth, Device.tenant_id)
```

---

## Building & Deploying

### Deploy Script (preferred)

Use `./deploy.sh` for all deployments — it builds, saves the image once, and deploys to all nodes in parallel:

```bash
./deploy.sh central              # Build + deploy to all 4 central nodes
./deploy.sh collector            # Build + deploy to all 4 worker nodes
./deploy.sh central --no-build   # Deploy only (skip build, reuse existing image)
./deploy.sh central 41 42        # Deploy to specific nodes (last IP octet)
```

The script handles: parallel transfer, correct compose paths (central-ha vs central), service restart, and image pruning.

### Manual Build (only if needed)

```bash
# Central
docker build --platform linux/amd64 -t monctl-central:latest -f docker/Dockerfile.central .
# Collector
docker build --platform linux/amd64 -t monctl-collector:latest -f docker/Dockerfile.collector-v2 .
```

**Important**:
- Use `Dockerfile.collector-v2` (not `Dockerfile.collector`)
- No npm/node on servers — Dockerfile handles frontend build
- No package-lock.json — uses `npm install` (not `npm ci`)
- Default build uses Docker layer caching (fast for source-only changes). Only add `--no-cache` when dependencies change (package.json, pyproject.toml)
- Use `docker compose up -d` (not `restart`) to pick up new images
- Deploy to ALL 4 central nodes and ALL 4 worker nodes
- **Alpine healthchecks**: Use `pg_isready` for Patroni (not wget/curl), `redis-cli ping` for Redis

### Server Inventory

| Role     | Hosts          | IPs                    |
|----------|----------------|------------------------|
| Central  | central1-4     | 10.145.210.41 - .44    |
| Workers  | worker1-4      | 10.145.210.31 - .34    |
| VIP      | (keepalived)   | 10.145.210.40          |

SSH user: `monctl` for all servers.

### Central Compose Projects

| Project | Path | Central1 | Central2 | Central3 | Central4 |
|---------|------|----------|----------|----------|----------|
| central-ha | `/opt/monctl/central-ha/` | app + Patroni + Redis primary + sentinel + Metabase | app + Patroni + Redis replica + sentinel | app + Redis sentinel | — |
| central | `/opt/monctl/central/` | — | — | — | app + Grafana |
| clickhouse | `/opt/monctl/clickhouse/` | — | — | ClickHouse node | ClickHouse node |
| haproxy | `/opt/monctl/haproxy/` | HAProxy + keepalived | HAProxy + keepalived | HAProxy + keepalived | HAProxy + keepalived |
| etcd | `/opt/monctl/etcd/` | etcd | etcd | etcd | — |
| docker-stats | `/opt/monctl/docker-stats/` | stats agent | stats agent | stats agent | stats agent |

**Important**: Central1-3 use `central-ha` (:8443). Central4 uses `central` (:8443). Never start both on same node.

**`MONCTL_NODE_NAME`**: Each central compose file must set `MONCTL_NODE_NAME: centralN` (e.g. `central1`). Used by system health to show human-readable node name instead of container ID.

**Workers**: Single compose project at `/opt/monctl/collector/`.

---

## Code Style

- Python: ruff, line-length 100, target Python 3.11
- TypeScript: standard React conventions, path aliases `@/`
- Communicate in Danish when the user writes in Danish

## Frontend UI Patterns

**ClearableInput**: Always-in-DOM clear button (hidden via `opacity-0 pointer-events-none`) to avoid focus loss from DOM changes.

**Conditional rendering and focus**: Never use `{condition && <Element/>}` near sibling form inputs — causes focus loss. Use CSS visibility toggle instead.

**Filter empty states**: Keep table visible with "No matches" message when filters are active. Only show big empty state with zero items AND no filters.

**List views**: `useListState` hook → `FilterableSortHead` + `ClearableInput` + `PaginationBar`. All hooks use `placeholderData: keepPreviousData`.

**Threshold formatting**: `formatThresholdValue(value, unit)` auto-scales bps→Mbps, bytes→GB etc.

---

## Playwright MCP (Browser Automation)

**Target URL**: `https://10.145.210.40` (HAProxy VIP)

**Auth flow**:
1. Navigate with `--storage-state .playwright/auth-state.json`
2. If redirected to `/login`, read credentials from `.env.local-dev` (`MONCTL_TEST_USER`, `MONCTL_TEST_PASSWORD`)
3. Save state after login

**Notes**: Self-signed cert (Chromium ignores by default). Always headless. Screenshots to `.playwright/screenshots/`.

**Testing policy**: After implementing or deploying a new feature/fix, proactively verify it works in the real UI using the Playwright MCP browser — navigate to the relevant page, interact, and take a screenshot. Don't just check the API.
