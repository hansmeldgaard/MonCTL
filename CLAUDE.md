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
- **Collector**: Python 3.12, gRPC (internal cache-node ↔ worker), SQLite (local result buffer)
- **Icons**: Lucide React
- **Charts**: Recharts

## Package Structure

```
apps/                           # Reference BasePoller source (SNMP apps only)
├── snmp_check.py               # SNMP scalar OID query (BasePoller)
├── snmp_interface_poller.py    # Full ifTable/ifXTable monitoring (BasePoller)
├── snmp_discovery.py           # Device auto-discovery (one-shot)
└── snmp_uptime.py              # Device uptime via snmpEngineTime/sysUpTime

packs/                          # 8 vendor-grouped packs (auto-imported at startup)
                                # snmp-core, basic-checks, cisco-monitoring,
                                # juniper-monitoring, linux-server,
                                # entity-mib-inventory, docker-container-stats,
                                # cisco-juniper-device-types
                                # Filenames have no version suffix; the pack
                                # JSON carries `version` internally.

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
│       ├── jobs/               # Job models, scheduling
│       └── peer/               # gRPC client/server for cache-node ↔ worker communication
├── common/                     # Shared: monctl_common.utils (utc_now, hash_api_key)
└── sdk/                        # SDK package (base classes, testing utilities)
```

---

## Key Gotchas & Non-Obvious Behavior

### App & Pack System

> Authoring a new app? Read [`docs/app-development-guide.md`](docs/app-development-guide.md) — it covers BasePoller, error categories, app-data cache, and the cross-app + delta patterns shipped in PR #151.

- **All apps are BasePoller subclasses** with `class Poller(BasePoller)` and `async def poll() -> PollResult`. No legacy script (stdin/stdout) execution.
- **Built-in packs** (`packs/`) are auto-imported at startup if not already present. Uses "skip" resolution (creates missing apps, never overwrites existing).
- **`snmp_discovery` is special**: One-shot (`interval=0`), injected into job lists when Redis discovery flag is set. Looked up by name, not ID.
- **Auto-rename on discovery**: `discovery/service.py` renames a device to `sysName` if `device.name == device.address` at discovery time. This is how bulk-imported devices (created via `POST /devices/bulk-import` with IP as temporary name) get their hostnames automatically. Manually named devices are never affected.
- **`apps/` directory** contains reference source for SNMP apps only. Not used at runtime — packs are the single source of truth.
- **Error categories**: All apps MUST set `error_category` on error PollResults: `"device"` (unreachable/timeout), `"config"` (missing connector/credential), `"app"` (bug/crash). Empty string = no error.

### Credential Resolution Chain (precedence order)

1. `AssignmentCredentialOverride` — per-assignment, per-connector-type
2. `AppAssignment.credential_id` — assignment-level
3. `Device.credentials` JSONB — per-type mapping (`{connector_type: credential_id}`)

### Connector System

- **`required_connectors`** on each `Poller` is a list of connector types (e.g. `["snmp"]`, `["snmp", "ssh"]`). Central parses it at version upload, pre-creates one slot per type on the App, and the operator picks a concrete connector per slot. At most one binding per connector_type per app. `context.connectors[type]` is how the poller looks them up at runtime.
- **SNMP Connector** accepts both `snmp_version` and `version` credential keys (backward compat). Credential API returns `version` from template key names.
- **Connector lifecycle**: Polling engine manages connect→use→close. **Apps must NOT call `connector.connect()`** — the engine does it. Idempotent guard prevents leaks if called anyway.
- **Venv site-packages** are permanently added to `sys.path` so lazy imports work at runtime.
- **Memory management**: `gc.collect()` + `malloc_trim(0)` after each job. Workers use `MALLOC_ARENA_MAX=2`, `PYTHONMALLOC=malloc`, `mem_limit: 1g`.

### Job Partitioning

- Unpinned assignments use consistent hashing via `CollectorGroup.weight_snapshot` JSONB.
- `weight_snapshot = NULL` → equal weights fallback. Set to NULL on collector DOWN/approve/group-change.
- Rebalancer runs every 5 min. Threshold: 1.5x imbalance ratio, 15% weight change hysteresis.
- **Weight updates use EMA blending** (alpha=0.3) to prevent oscillation. Pure inverse-proportional weights (`1/cost`) flip the entire distribution instead of equalising it. The EMA gradually converges over 5-7 cycles.
- **Minimum weight floor is 0.3** (both in rebalancer and `/jobs` endpoint). Lower values (e.g. 0.05) create extreme vnode ratios (20:1) that cause flip-flopping.

### Interface Monitoring

- **Rate calculation is central-side** (not collector). Previous counters cached in Redis.
- **Targeted polling**: `monitored_interfaces` list injected into job params. Uses SNMP GET (not walk).
- **Multi-tier retention**: Raw (7d), hourly (90d), daily (730d). Auto-tier selection by time range.

### Alerting & Thresholds

- **DSL**: `avg(metric) > 80`, `rate(octets) * 8 / 1e6 > 500`, `field CHANGED`, `state IN (...)`. Compiled to ClickHouse SQL.
- **4-level threshold hierarchy**: expression default → app_value → device override → entity override.
- **Engine**: 30s evaluation cycle. Writes fire/clear to `alert_log` ClickHouse table.
- **Positive-clear via healthy tier**: If the healthy tier carries an expression (e.g. `rtt_ms < rtt_ms_warn`) it acts as an explicit clear signal — an active alert only clears when that expression matches. Non-matching cycles where no fire tier matched leave the entity untouched (no spurious reset). Blank healthy expression → legacy auto-clear on any non-matching cycle.
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

### Audit Log

- **Two stores**: `audit_login_events` (PostgreSQL — auth events, ACID, queryable by user) and `audit_mutations` (ClickHouse — high-volume mutation history, 365d TTL).
- **Capture mechanism**: `AuditContextMiddleware` populates a request-scoped `contextvars.ContextVar` with user/IP/request_id. A SQLAlchemy `before_flush` event listener walks `session.new/dirty/deleted`, extracts old values from `attrs.history`, and stashes rows on the context. The middleware forwards them to an async batch buffer on response completion. No per-endpoint decorators.
- **Whitelist, not blacklist**: Only tablenames listed in `audit/resource_map.py::TABLE_TO_RESOURCE` are audited. Adding a new audited table requires updating that map.
- **Redaction**: `audit/diff.py` redacts fields whose names contain `password`, `api_key`, `token`, `secret`, `jwt_secret`, `credential_value`, `private_key`. Applied before JSON serialization.
- **Login event gotcha**: Failed logins raise HTTPException which triggers `get_db()` rollback — so `record_login_event()` uses its **own** session that commits immediately, not the request session. Otherwise login failures would never be logged.
- **Non-blocking**: If ClickHouse is down, audit rows are dropped with a warning. PG login events are critical and block the login response (rare enough that it's fine).
- **Permission**: `audit:view` (admins bypass). UI lives under Settings → Audit Log.
- **Request ID**: Every response has `X-Request-Id` header — matches the `request_id` column in audit rows for end-to-end correlation.
- **ClickHouse cluster DDL gotcha**: Any DDL in the `ON CLUSTER` path uses `.format(cluster=...)`, so literal `{}` in DEFAULT clauses (e.g. `'{}'` for empty JSON) must be escaped to `'{{}}'`. Otherwise Python raises `IndexError: Replacement index 0` before the SQL reaches ClickHouse.

### System Health

- **Overall status excludes alerts** — only infrastructure subsystems (postgresql, clickhouse, redis, scheduler, collectors, etc.) count. Alerts reflect monitored devices, not platform health.
- **Scheduler leader election**: Redis SETNX with 30s TTL, renewed every 10s. Only `role=all` or `role=scheduler` instances participate. **Gotcha**: Do not reuse `role` as a variable name in `main.py` lifespan — it shadows `settings.role` and breaks the scheduler check.
- **Lightweight status endpoint**: `GET /system/health/status` returns cached `overall_status` from last full check. Used by the top-bar health indicator dot (admin-only).
- **Patroni switchover**: `POST /system/patroni/switchover` proxies to Patroni REST API. Admin-only.
- **Infrastructure node config**: Patroni/etcd/sentinel node lists are configured via env vars — **no hardcoded IPs in application code**. Set `MONCTL_PATRONI_NODES`, `MONCTL_ETCD_NODES`, `MONCTL_REDIS_SENTINEL_HOSTS` in compose env files. Format: `"name:ip,name:ip,..."` (e.g. `"central1:10.145.210.41,central2:10.145.210.42"`). Health checks report "unconfigured" if not set.
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
- **Collector API**: `Authorization: Bearer <MONCTL_COLLECTOR_API_KEY>` (shared secret); per-collector keys (PR #120/#122) take precedence when issued
- **OAuth2 / OIDC provider**: `/v1/oauth/{authorize,token,userinfo}` for Superset SSO and any future external OAuth2 client. HS256-signed JWTs. Configured via `MONCTL_OAUTH_CLIENT_ID/SECRET/REDIRECT_URIS/ISSUER`. See `docs/superset.md` for the SSO flow and 9 non-obvious quirks.
- **Dependencies**: `require_permission("resource", "action")` (RBAC-enforced), `require_admin` (admin role only)
- **RBAC**: All endpoints use `require_permission`. Admins and API keys bypass automatically. Resources: `device`, `app`, `assignment`, `credential`, `alert`, `collector`, `tenant`, `user`, `template`, `settings`, `result`. Actions: `view`, `create`, `edit`, `delete`, `manage`.
- **Frontend**: `usePermissions()` hook controls sidebar visibility, settings tabs, and action buttons

### Routes

- Web API under `/v1/` (e.g., `/v1/devices`, `/v1/apps`)
- Collector API under `/api/v1/` (e.g., `/api/v1/jobs`, `/api/v1/results`)

### OpenAPI tag taxonomy

Tags are assigned **at `include_router` time**, never on individual `@router.*` decorators. One tag per resource group. The canonical mount points are `packages/central/src/monctl_central/api/router.py` (every `/v1/*` resource) and `packages/central/src/monctl_central/main.py` (the two `/api/v1/*` parents + websocket). When you add a new resource:

1. Mount it in `api/router.py` with `tags=["<resource-name>"]` matching the URL prefix in kebab-case (e.g. `prefix="/incident-rules"` → `tags=["incident-rules"]`).
2. Don't pass `tags=...` to `APIRouter()` itself unless the router is mounted at app-root with no parent tag — `dashboard/router.py` and `logs/router.py` are the only two cases that need this and they exist for historical reasons; new routers should follow the include-time pattern.
3. New collector-facing endpoints go under `/api/v1/*`. The parent router carries `tags=["collector-api"]`; nested sub-routers (`upgrade`, `os-packages`, `logs`) keep their own narrower tag.

The current taxonomy is the union of every `tags=` argument in those two files — Swagger UI groups endpoints by tag, so a missing tag means the endpoint lands in the unnamed "default" bucket and is hard to find. Audit the diff in `api/router.py` whenever you mount a new sub-router.

### Multi-Tenant Filtering

```python
from monctl_central.dependencies import apply_tenant_filter
stmt = apply_tenant_filter(stmt, auth, Device.tenant_id)
```

---

## Building & Deploying

> `./deploy.sh` is the **maintainer dev-cluster workflow** against `10.145.210.41-44` / `.31-.34`. Customers and external operators should use `monctl_ctl deploy` — see `INSTALL.md`.

### Deploy Script (preferred — dev cluster)

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

| Role    | Hosts        | IPs                 |
| ------- | ------------ | ------------------- |
| Central | central1-4   | 10.145.210.41 - .44 |
| Workers | worker1-4    | 10.145.210.31 - .34 |
| VIP     | (keepalived) | 10.145.210.40       |

SSH user: `monctl` for all servers.

### Central Compose Projects

| Project           | Path                             | Central1                                 | Central2                                 | Central3             | Central4             |
| ----------------- | -------------------------------- | ---------------------------------------- | ---------------------------------------- | -------------------- | -------------------- |
| central-ha        | `/opt/monctl/central-ha/`        | app + Patroni + Redis primary + sentinel | app + Patroni + Redis replica + sentinel | app + Redis sentinel | —                    |
| central           | `/opt/monctl/central/`           | —                                        | —                                        | —                    | app                  |
| clickhouse        | `/opt/monctl/clickhouse/`        | —                                        | —                                        | ClickHouse node      | ClickHouse node      |
| clickhouse-keeper | `/opt/monctl/clickhouse-keeper/` | Keeper-only (quorum voter)               | —                                        | —                    | —                    |
| haproxy           | `/opt/monctl/haproxy/`           | HAProxy + keepalived                     | HAProxy + keepalived                     | HAProxy + keepalived | HAProxy + keepalived |
| etcd              | `/opt/monctl/etcd/`              | etcd                                     | etcd                                     | etcd                 | —                    |
| docker-stats      | `/opt/monctl/docker-stats/`      | stats agent                              | stats agent                              | stats agent          | stats agent          |

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

## Known pitfalls

These have each bitten the project at least once. Read them before touching the named subsystem.

**Nullable DB fields in API responses** — Use `meta.get("key") or default`, NOT `meta.get("key", default)`. If the column is nullable and the row has `NULL`, the key _exists_ with value `None` and the second form returns `None`. This broke `snmp_check` v2.0.0 fleet-wide when `entry_class` was null.

**Collector delta-sync** — `/api/v1/jobs` filters `AppAssignment.updated_at > since`. Raw-SQL updates to `app_assignments` (or any delta-sync-served table) MUST `SET updated_at=now()` in the same statement, or collectors keep serving the cached definition. SQLAlchemy ORM does this automatically via `onupdate`; raw SQL does not.

**ClickHouse materialized view schema changes** — MVs created with `AS SELECT * FROM base` freeze their column list. `ALTER TABLE base ADD COLUMN` won't propagate to the MV; `ALTER MATERIALIZED VIEW … MODIFY ORDER BY` doesn't exist. Changes to a `*_latest` MV's columns or sort key require a guarded DROP+CREATE in the startup migration (compare live `system.tables.sorting_key` to expected, drop+recreate only if drifted).

**Poller apps — timing and error categorisation** — `start = time.time()` must be the **first** statement of `poll()`. Every `PollResult` return must compute `execution_time_ms = int((time.time() - start) * 1000)` immediately before the return. Every error `PollResult` must set `error_category` to `"device"` (unreachable/timeout), `"config"` (missing connector/credential), or `"app"` (bug/crash); empty string = no error.

**Poller debug logging** — Use stdlib `logging.getLogger(__name__)` and printf-style formatting only: `logger.debug("event key=%s", val)`. The central packs/service.py already had this bug twice: structlog-style kwargs (`logger.warning("x", key=v)`) raise `TypeError` at runtime and silently fail pack imports. In pollers, dense `logger.debug(...)` calls (~20–40 per poll) are free in prod (no-op) and essential for the Assignment Debug Run feature; add them by default.

**Connector rewrites — preserve every credential-key name** — Built-in connectors (esp. SNMP/SSH) read credentials via `credential.get(...)`. Prod credential templates may supply different key names than the "canonical" one in code. Before bumping a connector, enumerate every template's `fields[].name` and keep `get(canonical) or get(legacy, default)` fallbacks for all of them. Dropping one broke SNMPv3 fleet-wide in minutes (2026-04-20).

**Batch freshness queries must filter per-entity** — Never `WHERE timestamp > min(per_entity_cutoff)` across heterogeneous entities. The global-min answers "newer than the _oldest_ cutoff", not "newer than each entity's own cutoff". Use `GROUP BY entity_id` + per-entity comparison in code. This fired alerts every 30s instead of once per datapoint through 3 debug iterations before it was identified.

**Frontend `node_modules` shadows container install** — `Dockerfile.central` COPYs `packages/central/frontend/` into the image. Any host `node_modules` (from a local type-check, playwright install, etc.) overlays the container's fresh `npm install`, causing `tsc: not found` at `npm run build`. Before `./deploy.sh central`, delete it: `find packages/central/frontend/node_modules -depth -delete`.

**Regenerated gRPC stub needs relative import** — `protoc` emits `import collector_pb2 as collector__pb2` (absolute) in `collector_pb2_grpc.py`. That fails inside the installed wheel (`ModuleNotFoundError`). After any regeneration, change it to `from . import collector_pb2 as collector__pb2`.

**Frontend zod schemas are telemetry, not gates** — `apiGetSafe(..., Schema)` runs `safeParse` and logs drift via `console.warn("[schema-drift] …")`; it never throws. TypeScript stays the source of truth for types. Schemas only list fields the UI reads. Don't try to make `z.infer<typeof Schema>` match the TS type — the generic is loosened on purpose so schemas can lag types without breaking tsc.

**Alembic migrations and rebases** — When rebasing a long-lived branch onto main, check for duplicate revision IDs and carry any unmerged migrations forward. Deploying from a branch missing migrations the DB already ran will fail at startup with "Can't locate revision". Always `git log --oneline main..HEAD -- '*/alembic/versions/'` before `./deploy.sh`.

**PAT scope for workflow files** — As of 2026-04-21 the project PAT has the `workflow` scope, so pushes that touch `.github/workflows/*.yml` work directly. Don't preemptively split workflow edits into a separate commit — try the push first. Only fall back to splitting (or having the user commit via web UI) if the push is actually rejected with `refusing to allow a Personal Access Token…`.

**History endpoints need server-side `toStartOfInterval` bucketing** — Any `*_history` endpoint that returns N rows per timestamp (e.g. one row per ingestion table per sample, one row per host per sample) silently truncates at `LIMIT 10000` somewhere around 7 days of history. Mirror the `db_size_history` pattern: accept `step_seconds`, wrap the query with `toStartOfInterval(timestamp, INTERVAL {step:UInt32} SECOND)` + `GROUP BY` + aggregate. Use `_bucket_step_for_range` from the system router to pick the step.

**`AlertDefinition.expression` is gone (PR #38)** — The single-expression model was replaced by `severity_tiers` (JSONB list of `{severity, expression, message_template}`). Anything still reading `def.expression` is dead code that should be deleted. The healthy tier is optional and acts as a positive-clear signal when present.

**Pack first-import race is benign on HA** — On a 4-central HA cluster, the first-time deploy of a NEW `pack_uid` lets all 4 nodes attempt the insert simultaneously. N-1 lose the unique-violation race and log `builtin_pack_import_failed` with `error="UniqueViolationError ..."`. Real pack-corruption failures emit the same WARN line shape, so context matters: if you see 3 of these in 4 central logs at startup with the same pack_uid, ignore them. The pack-import path catches `IntegrityError` separately as of post-review-#2 follow-up; pre-fix logs need to be filtered by hand.

**Squash-merge can silently drop dev-branch compose / config edits** — When merging a long-lived branch via squash, any compose-file or `.env.j2` edits that landed on the branch but never made it into a separate commit can be silently absorbed away. After every squash-merge that touched `docker/`, `packages/installer/.../templates/`, or central env files, diff the merge result against the branch tip: `git diff <branch-tip> main -- docker/ packages/installer/`.

**`monctl_ctl` not `monctlctl`** — No glued suffixes on CLI binary names. The customer installer ships as `monctl_ctl` (underscore separator). When introducing a new CLI, prefer `monctl_<word>` or a distinct word entirely. Compound forms like `monctlctl` / `monctlbi` are unparseable at a glance.

**Grep for existing helpers before adding enforcement logic** — This codebase often has half-wired private helpers (`_caller_*`, `_require_*`, `_resolve_*`) that are imported but unused, or wired only in some endpoints. Before writing a new auth check / validation gate, grep the surface module for matching names. Adding a parallel implementation creates two enforcement paths and the next refactor only catches one.

**Empty UI state may be a 500, not missing data** — Most frontend hooks use `apiGet` without an error surface, so a 500 and a truly-empty `[]` render identically as "no X". When the user reports an empty tab/list, first action is browser console (Playwright MCP) + `docker logs central-ha-central-1 --since 2m` for the endpoint path. Only after seeing a clean 200 with empty payload should you investigate seed/data paths. PR #138's threshold-tab regression hid behind exactly this for an extra debug round.

**Compose orphan cleanup after service removal** — `docker compose up -d` silently leaves containers running for services no longer in the compose file. `./deploy.sh` can't touch services not in the compose, so the orphan keeps running its old image. Symptom: a `docker ps` line with an image hash instead of a tag, and a `CreatedAt` much older than the latest deploy. After removing any compose service, run `docker compose up -d --remove-orphans` on every affected host. A stale `poll-worker-2` orphan once wedged collector-01 at 85% CPU on 13 zombie `snmp_discovery` jobs.

**httpx 0.28+ — `client.cookies = resp.cookies` is a silent no-op** — In tests (`packages/central/tests/unit/conftest.py` historically), assigning the cookie jar via attribute is accepted-and-ignored on httpx 0.28; the JWT cookie never lands in the jar and every subsequent `/v1/*` returns 401. Iterate and `.set()` per cookie instead. If you see "Authentication required" on `/v1/*` immediately after a 200 from `/v1/auth/login`, this is the first thing to check.

**Deploying from a stale branch silently rolls back unmerged sibling fixes** — `./deploy.sh` builds the image from whatever's on disk, so deploying off a branch cut from `main` _before_ an unrelated PR landed will erase that PR's fixes from production. Before any `./deploy.sh`, run `gh pr list --author @me --state open` and eyeball each entry's base/head — anything that touches the target package is a landmine. Either merge the pending PRs first, cherry-pick their commits, or wait. PR #64's `_LockedClient` ClickHouse fix was rolled back this way once.

**Bumping a shared library / connector — diff against prod `is_latest` first** — Built-in connectors and other shared code applied as `is_latest=true` have fleet-wide blast radius. Never rewrite from an older snapshot or paraphrase the source — fetch the current uploaded version (DB or `/v1/connectors/{name}/source`), diff against the draft, and read every `memory/project_*.md` entry mentioning the filename. The 2026-04-16 SNMP v1.4.0 push silently dropped a `snmp_version`/`version` credential-key fallback from v1.3.2 and took availability from ~77% to 0% before rollback. For a connector fix targeted at one app, prefer explicit `connector_version_id` pinning over `is_latest`.

**Re-reported symptom — re-investigate from raw data, don't trust prior fix** — When the user complains again about a bug you previously "fixed and verified", treat it as a new bug. Pull fresh production data (alert_log, ClickHouse tables, logs from the leader) for the affected entity and trace second-by-second. A two-minute verification window is not enough to conclude correctness when the bug needs a full poll cycle (5+ minutes) to manifest. Be willing to reopen and rewrite recently-merged code; freshness is not correctness.

---

## Playwright MCP (Browser Automation)

**Target URL**: `https://10.145.210.40` (HAProxy VIP)

**Auth flow**:

1. Navigate with `--storage-state .playwright/auth-state.json`
2. If redirected to `/login`, read credentials from `.env.local-dev` (`MONCTL_TEST_USER`, `MONCTL_TEST_PASSWORD`)
3. Save state after login

**Notes**: Self-signed cert (Chromium ignores by default). Always headless. Screenshots to `.playwright/screenshots/`.

**Testing policy**: After implementing or deploying a new feature/fix, proactively verify it works in the real UI using the Playwright MCP browser — navigate to the relevant page, interact, and take a screenshot. Don't just check the API.
