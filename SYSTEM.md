# MonCTL — System Description for Planning Sessions

> Brug dette dokument som kontekst i en separat Claude-session til at lave implementeringsplaner.
> Planen skal være detaljeret nok til at en anden Claude-session kan implementere den direkte.

---

## Hvad er MonCTL

Distribueret monitoring-platform med central management server og distribuerede collector-noder. Collectors henter job-assignments fra central, eksekverer monitoring checks (ping, port, SNMP, custom apps) og sender resultater tilbage til central for lagring i ClickHouse.

## Arkitektur

```
Browser → HAProxy (VIP 10.145.210.40:443) → central1-4 (:8443)
                                              ├── PostgreSQL (Patroni HA, 2 noder)
                                              ├── ClickHouse (replicated cluster, 2 noder)
                                              └── Redis (single, central1)

Collectors (worker1-2) → poll jobs fra central → eksekver checks → forward resultater
  Hver collector kører 3 processer:
    cache-node  (gRPC + gossip + job scheduler)
    poll-worker (job execution + app venvs)
    forwarder   (batch result posting)
```

## Tech Stack

| Layer | Teknologi |
|-------|-----------|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic 2 |
| Frontend | React 19, TypeScript 5.9, Vite 7, Tailwind CSS v4, React Query (TanStack) 5 |
| Time-series | ClickHouse (ReplicatedMergeTree, 2 noder) |
| Relational DB | PostgreSQL 16 (Patroni HA) |
| Cache | Redis (single node) |
| Proxy | HAProxy (TLS termination) + Keepalived (VIP failover) |
| Collector | Python 3.12, gRPC, SQLite (lokal buffer), SWIM gossip protocol |
| Icons | Lucide React |
| Charts | Recharts |
| Code editor | CodeMirror 6 (Python syntax) |

## Serverinventar

| Rolle | Hosts | IPs |
|-------|-------|-----|
| Central | central1-4 | 10.145.210.41-.44 |
| Workers | worker1-2 | 10.145.210.31-.32 |
| VIP | (keepalived) | 10.145.210.40 |

SSH bruger: `monctl` på alle servere.

---

## Package-struktur

```
packages/
├── central/                        # Central management server
│   ├── src/monctl_central/
│   │   ├── main.py                 # FastAPI app, lifespan, seeding (admin, device types, built-in apps)
│   │   ├── config.py               # Settings via MONCTL_ env vars
│   │   ├── dependencies.py         # DI: get_db, get_engine, get_session_factory, get_clickhouse,
│   │   │                           #     require_auth, require_admin, require_collector_auth,
│   │   │                           #     apply_tenant_filter, check_tenant_access
│   │   ├── cache.py                # Redis client (_redis global) + caching (api keys, credentials, enrichment)
│   │   ├── storage/
│   │   │   ├── models.py           # Alle PostgreSQL-modeller (se nedenfor)
│   │   │   └── clickhouse.py       # ClickHouseClient wrapper, 4 domænetabeller + MV'er
│   │   ├── api/router.py           # Hovedrouter — monterer alle sub-routers på /v1/
│   │   ├── auth/
│   │   │   ├── router.py           # POST /login, /logout, /refresh, GET /me
│   │   │   └── service.py          # JWT creation/validation, bcrypt hashing
│   │   ├── devices/router.py       # Device CRUD + server-side sort/filter/pagination
│   │   ├── collectors/router.py    # Collector register, approve, reject, heartbeat, config
│   │   ├── collector_api/router.py # /api/v1/ endpoints collectors kalder (jobs, apps, credentials, results)
│   │   ├── collector_groups/router.py
│   │   ├── apps/router.py          # App CRUD + AppVersion CRUD + Assignment CRUD
│   │   ├── results/router.py       # Check results query API (læser fra ClickHouse)
│   │   ├── credentials/
│   │   │   ├── router.py           # Credential CRUD (secrets returneres aldrig)
│   │   │   └── crypto.py           # AES-256-GCM encrypt/decrypt
│   │   ├── credential_keys/router.py
│   │   ├── templates/router.py     # Device templates (bulk app assignment)
│   │   ├── alerting/router.py      # Alert rules + active alerts
│   │   ├── tls/router.py           # TLS certificate management
│   │   ├── settings/router.py      # System settings key-value store
│   │   ├── tenants/router.py       # Multi-tenant support
│   │   ├── users/router.py         # User CRUD + timezone + tenant assignments
│   │   ├── device_types/router.py
│   │   ├── registration_tokens/router.py
│   │   ├── snmp_oids/router.py
│   │   ├── ingestion/router.py     # Legacy POST /ingest endpoint
│   │   ├── system/router.py        # GET /system/health — concurrent subsystem checks
│   │   └── scheduler/
│   │       ├── leader.py           # Redis SETNX + TTL leader election (key: monctl:scheduler:leader)
│   │       └── tasks.py            # SchedulerRunner: health monitor (60s) + alert eval (30s)
│   ├── frontend/                   # React SPA
│   │   └── src/
│   │       ├── main.tsx            # Entry point + React Query client (30s stale, retry=1)
│   │       ├── App.tsx             # React Router — alle routes
│   │       ├── api/
│   │       │   ├── client.ts       # fetch() wrapper: apiGet, apiPost, apiPut, apiDelete
│   │       │   └── hooks.ts        # 70+ React Query hooks for alle API endpoints
│   │       ├── types/api.ts        # TypeScript interfaces for alle API responses
│   │       ├── lib/utils.ts        # cn(), formatDate(dateStr, tz), timeAgo(), capitalize(), truncate()
│   │       ├── hooks/
│   │       │   ├── useAuth.tsx     # Auth context (user, login, logout, refresh)
│   │       │   └── useTimezone.ts  # Returnerer user.timezone, default "UTC"
│   │       ├── pages/              # 17 sider (se nedenfor)
│   │       ├── components/         # Delte komponenter (se nedenfor)
│   │       │   └── ui/             # Shadcn-style UI primitiver
│   │       └── layouts/            # AppLayout, Sidebar, Header
│   └── alembic/                    # 16 migrationer, kører auto ved container startup
├── collector/                      # Collector node (v2, 3 processer)
│   └── src/monctl_collector/
│       ├── config.py               # YAML + env config
│       ├── central/
│       │   ├── api_client.py       # HTTP client for /api/v1/
│       │   └── credentials.py      # Encrypted credential manager (Fernet, SQLite cache)
│       ├── polling/
│       │   ├── engine.py           # Min-heap deadline scheduler, light/heavy semaphore lanes
│       │   └── base.py             # BasePoller ABC: setup(), poll(context), teardown()
│       ├── apps/manager.py         # App download + venv management (shared by hash)
│       ├── jobs/
│       │   ├── models.py           # JobDefinition, JobProfile (EMA), ScheduledJob, NodeLoadInfo
│       │   ├── scheduler.py        # Job sync fra central, app-affinity worker assignment
│       │   └── work_stealer.py     # Load-balancing via gRPC (disabled by default)
│       ├── cluster/
│       │   ├── gossip.py           # SWIM protocol — failure detection + load piggybacking
│       │   ├── membership.py       # ALIVE → SUSPECTED → DEAD state machine
│       │   └── hash_ring.py        # Consistent hashing (150 vnodes, SHA-256)
│       ├── peer/
│       │   ├── server.py           # gRPC servicer (cache, cluster, jobs, credentials, results, apps)
│       │   └── client.py           # gRPC client + channel pool
│       ├── cache/
│       │   ├── local_cache.py      # SQLite med 6 tabeller (cache, jobs, profiles, apps, credentials, results)
│       │   └── distributed_cache.py
│       ├── forward/forwarder.py    # Batch result posting med offline resilience
│       └── entrypoints/            # cache_node.py, poll_worker.py, forwarder_main.py
├── common/                         # Delt: utc_now(), generate_api_key(), hash_api_key(), CheckState enum
└── sdk/                            # MonitoringApp, MetricCollector, EventSource base classes
```

---

## PostgreSQL-modeller (storage/models.py)

| Model | Tabel | Nøglefelter | Relationer |
|-------|-------|-------------|------------|
| CollectorCluster | collector_clusters | id, name, replication_factor, peer_port, settings (JSONB) | → collectors[] |
| Collector | collectors | id, name, hostname, ip_addresses, status (PENDING/ACTIVE/DOWN/REJECTED), load_score, effective_load, total_jobs, deadline_miss_rate, group_id, cluster_id, fingerprint, approved_at | → cluster, group, assignments[], api_keys[] |
| CollectorGroup | collector_groups | id, name, description, label_selector (JSONB) | → collectors[], devices[] |
| App | apps | id, name, description, app_type (script/sdk), config_schema (JSONB), target_table | → versions[] |
| AppVersion | app_versions | id, app_id, version, source_code, requirements (JSONB), entry_class, is_latest, checksum | → app |
| AppAssignment | app_assignments | id, app_id, app_version_id, collector_id (nullable), device_id (nullable), config (JSONB), schedule_type, schedule_value, resource_limits, role, use_latest, enabled | → collector, device, app, app_version |
| Device | devices | id, name, address, device_type, tenant_id, collector_group_id, default_credential_id, labels (JSONB), metadata (JSONB) | → tenant, collector_group, default_credential, assignments[] |
| DeviceType | device_types | id, name, description, category | (10 seeded) |
| Credential | credentials | id, name, credential_type, secret_data (AES-256-GCM encrypted) | |
| CredentialKey | credential_keys | id, name, is_secret | |
| CredentialValue | credential_values | id, credential_id, key_id, value | |
| User | users | id, username, password_hash, role (admin/viewer), timezone, all_tenants, is_active | → tenant_assignments[] |
| Tenant | tenants | id, name, metadata (JSONB) | → user_assignments[] |
| UserTenant | user_tenants | (user_id, tenant_id) composite PK | → user, tenant |
| AlertRule | alert_rules | id, name, rule_type, condition (JSONB), severity, enabled | → states[] |
| AlertState | alert_states | id, rule_id, state (firing/resolved), labels, started_at | → rule |
| ApiKey | api_keys | id, key_hash, key_type (collector/management), collector_id, scopes | → collector |
| RegistrationToken | registration_tokens | id, token_hash, short_code, one_time, used, cluster_id | |
| TlsCertificate | tls_certificates | id, name, cert_pem, key_pem_encrypted, is_active | |
| Template | templates | id, name, config (JSONB) | |
| SnmpOid | snmp_oids | id, name, oid, description | |
| SystemSetting | system_settings | key (PK), value | |

### Konventioner

- Altid `UUID(as_uuid=True)` med `default=uuid.uuid4` for ID'er
- Altid `created_at` og `updated_at` med `server_default="now()"`
- ForeignKey pattern: `ForeignKey("table.id", ondelete="SET NULL")`
- JSONB med `server_default="{}"` for dict-felter

---

## ClickHouse-tabeller (storage/clickhouse.py)

4 domænetabeller + materialized views (ReplacingMergeTree for `_latest`):

| Tabel | Indhold | ORDER BY | Nøglekolonner |
|-------|---------|----------|---------------|
| availability_latency | Ping, HTTP, port checks | (assignment_id, executed_at) | state, rtt_ms, response_time_ms, reachable, status_code |
| performance | CPU, memory, custom metrics | (device_id, component_type, component, executed_at) | component, component_type, metric_names[], metric_values[] |
| interface | Network interface stats | (device_id, if_index, executed_at) | if_name, if_speed_mbps, in/out_octets, in/out_rate_bps, utilization |
| config | Config/discovery data | (device_id, component_type, component, config_key, executed_at) | config_key, config_value, config_hash |

Alle tabeller har: assignment_id, collector_id, app_id, device_id, executed_at, received_at + denormaliserede felter: collector_name, device_name, app_name, tenant_id.

Hver tabel har en `_latest` materialized view (ReplacingMergeTree) der holder seneste resultat per nøgle.

**Query-metoder**: `query_latest()`, `query_history()`, `query_by_device()`, `query_for_alert()`, `insert_by_table()`.

---

## API-endpoints

### Web API (`/v1/`)

| Router | Prefix | Endpoints | Auth |
|--------|--------|-----------|------|
| auth | /v1/auth | POST login, logout, refresh; GET me | Public (login) |
| devices | /v1/devices | GET list (sort/filter/paginate), POST create, GET/:id, PUT/:id, DELETE/:id | require_auth |
| collectors | /v1/collectors | POST register, POST /:id/approve, POST /:id/reject, POST /:id/heartbeat, GET /:id/config, GET list, PUT/:id, DELETE/:id | Mixed |
| collector_groups | /v1/collector-groups | CRUD | require_auth |
| apps | /v1/apps | CRUD apps + versions + assignments | require_auth |
| results | /v1/results | GET list, GET /latest, GET /by-device/:id | require_auth |
| credentials | /v1/credentials | CRUD (secrets aldrig returneret) | require_auth |
| credential_keys | /v1/credential-keys | CRUD | require_auth |
| alerting | /v1/alerts | GET /rules, POST /rules, GET /active | require_auth |
| tenants | /v1/tenants | CRUD | require_auth |
| users | /v1/users | CRUD + PUT /me/timezone + POST /:id/tenants | require_admin (mest) |
| device_types | /v1/device-types | CRUD | require_auth |
| snmp_oids | /v1/snmp-oids | CRUD | require_auth |
| registration_tokens | /v1/registration-tokens | POST create, GET list | require_auth |
| templates | /v1/templates | CRUD + POST /:id/apply | require_auth |
| settings | /v1/settings | GET, PUT | require_admin |
| tls | /v1/settings/tls | GET, POST /generate, POST /upload, POST /deploy | require_admin |
| system | /v1/system | GET /health (concurrent subsystem checks) | require_admin |
| ingestion | /v1 | POST /ingest (legacy) | require_collector_auth |

### Collector API (`/api/v1/`)

| Endpoint | Metode | Formål |
|----------|--------|--------|
| /api/v1/jobs | GET | Hent job assignments (server-side partitioning) |
| /api/v1/jobs/:id | GET | Hent enkelt job |
| /api/v1/apps/:id/metadata | GET | App metadata |
| /api/v1/apps/:id/code | GET | App source code + requirements |
| /api/v1/credentials/:name | GET | Dekrypteret credential |
| /api/v1/results | POST | Push check resultater |

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
- `tenant_ids = None` → unrestricted (admin/api_key)
- `tenant_ids = []` → see nothing
- `tenant_ids = [ids]` → filter

---

## Frontend — sider og komponenter

### Sider (17)

| Side | Route | Formål |
|------|-------|--------|
| LoginPage | /login | Username/password login |
| DashboardPage | / | Stat-kort (devices, up, down, alerts) + tabeller (alerts, collectors, recent results) |
| SystemHealthPage | /system-health | 5 subsystem-kort (PG, CH, Redis, Collectors, Scheduler) med status/latency/detaljer |
| DevicesPage | /devices | Server-side pagination/sort/filter, bulk delete, status dots fra ClickHouse |
| DeviceDetailPage | /devices/:id | 3 tabs: Overview (info+edit), Activity (AvailabilityChart+TimeRangePicker), Settings (assignments CRUD) |
| AppsPage | /apps | App liste med type/target_table/version count |
| AppDetailPage | /apps/:id | 2 tabs: Overview (edit), Versions (CodeEditor, create/edit/delete versions) |
| AssignmentsPage | /assignments | Read-only tabel over alle assignments med søgning |
| AlertsPage | /alerts | 2 tabs: Active Alerts, Alert Rules |
| SettingsPage | /settings/:tab | 10 tabs: Profile, System, Device Types, Collectors, Credentials, SNMP OIDs, Data Retention, TLS, Users, Tenants |
| CollectorsPage | (embedded) | Pending/Active collectors, Groups, Registration Tokens |
| CredentialsPage | (embedded) | Credential Keys + Credentials CRUD |
| UsersPage | (embedded) | User CRUD + tenant assignments |
| TenantsPage | (embedded) | Tenant CRUD med metadata editor |
| DeviceTypesPage | (embedded) | Device type CRUD (built-in kan ikke slettes) |
| SnmpOidsPage | (embedded) | SNMP OID catalog CRUD |
| TemplatesPage | /templates | Template CRUD |

### Feature-komponenter

| Komponent | Formål |
|-----------|--------|
| AddDeviceDialog | Form dialog: name, address, type, tenant (required), group (required), credential (optional) |
| AvailabilityChart | Recharts: availability strip + latency lines, adaptive buckets, gap detection, timezone-aware |
| TimeRangePicker | Dropdown: presets (15m-30d-all) + relative + absolute custom ranges |
| CodeEditor | CodeMirror 6: Python syntax, one-dark theme, resizable |
| KeyValueEditor | Key-value pair editor for metadata/labels |
| StatusBadge | State → farve+label mapping (OK, WARNING, CRITICAL, DOWN, etc.) |

### UI-primitiver (components/ui/)

badge, button, card, dialog, input, label, select, table, tabs

### Sidebar navigation

Dashboard → System Health → Devices → Apps → Assignments → Templates → Alerts → Settings

### Polling

- Lister: 30 sekunder
- Detail views: 15 sekunder
- System Health: 15 sekunder

### React Query patterns

- `useQuery` med `queryKey` og `refetchInterval`
- `useMutation` med `onSuccess: async () => { await qc.invalidateQueries(...) }`
- `apiGet<T>()` returnerer `ApiResponse<T>` = `{status, data}`
- Hooks: `useDevices(params)`, `useCreateDevice()`, `useDeleteDevice()`, etc.

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

### Pool-status

`get_engine().pool` giver adgang til `pool.size()`, `pool.checkedout()`, `pool.overflow()`, `pool.status()`.

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
# Build
docker build --platform linux/amd64 --no-cache -t monctl-central:latest -f docker/Dockerfile.central .

# Push til alle servere
for ip in 41 42 43 44; do
  docker save monctl-central:latest | ssh monctl@10.145.210.$ip 'docker load'
done

# Restart
for ip in 41 42 43 44; do
  ssh monctl@10.145.210.$ip 'cd /opt/monctl/central && docker compose down && docker compose up -d'
done
```

### Collector deploy

```bash
docker build --platform linux/amd64 --no-cache -t monctl-collector:latest -f docker/Dockerfile.collector-v2 packages/collector/
# Compose file: /opt/monctl/collector/docker-compose.yml
```

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
