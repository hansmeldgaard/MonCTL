# MonCTL — Distributed Monitoring Platform

## Project Overview

MonCTL is a distributed monitoring platform with a central management server and distributed collector nodes. Collectors pull job assignments from central, execute monitoring checks (ping, port, SNMP, custom apps), and forward results back to central for storage in ClickHouse.

## Architecture

```
Browser → HAProxy (VIP 10.145.210.40:443) → central1-4 (:8444)
                                              ├── PostgreSQL (Patroni HA)
                                              ├── ClickHouse (replicated cluster)
                                              └── Redis

Collectors (worker1-4) → poll jobs from central → execute checks → forward results
```

## Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy async, Alembic migrations
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS v4, React Query (TanStack)
- **Time-series storage**: ClickHouse (replicated cluster, 3 nodes)
- **Relational DB**: PostgreSQL 16 (Patroni HA, 2 nodes)
- **Cache**: Redis
- **Proxy**: HAProxy (TLS termination, round-robin to 4 central nodes)
- **Collector**: Python 3.11, gRPC (peer communication), SQLite (local result buffer)
- **Icons**: Lucide React
- **Charts**: Recharts

## Package Structure

```
packages/
├── central/                    # Central management server
│   ├── src/monctl_central/
│   │   ├── main.py             # FastAPI app, lifespan, seed logic
│   │   ├── config.py           # Settings via env vars (MONCTL_ prefix)
│   │   ├── dependencies.py     # DI: get_db, get_clickhouse, require_auth, require_admin
│   │   ├── cache.py            # Redis client wrapper + caching utilities
│   │   ├── storage/
│   │   │   ├── models.py       # SQLAlchemy models (all PostgreSQL tables)
│   │   │   └── clickhouse.py   # ClickHouse client wrapper, schemas, queries
│   │   ├── api/router.py       # Main API router (mounts all sub-routers at /v1/)
│   │   ├── auth/               # JWT cookie auth (login, refresh, me)
│   │   │   ├── router.py       # POST /login, /logout, /refresh, GET /me
│   │   │   └── service.py      # JWT creation/validation, bcrypt hashing
│   │   ├── devices/router.py   # Device CRUD + server-side sort/filter/pagination
│   │   ├── collectors/router.py # Collector registration, approval, heartbeat
│   │   ├── collector_api/router.py # /api/v1/ endpoints collectors call
│   │   ├── apps/router.py      # App CRUD + assignment CRUD
│   │   ├── results/router.py   # Check results query API (reads from ClickHouse)
│   │   ├── credentials/
│   │   │   ├── router.py       # Credential CRUD (secrets never returned)
│   │   │   └── crypto.py       # AES-256-GCM encrypt/decrypt
│   │   ├── credential_keys/router.py  # Reusable credential field definitions
│   │   ├── templates/router.py # Device templates (bulk app assignment)
│   │   ├── alerting/           # Alert rules + evaluation engine
│   │   ├── tls/router.py       # TLS certificate management
│   │   ├── settings/router.py  # System settings (data retention, etc.)
│   │   ├── tenants/router.py   # Multi-tenant support
│   │   ├── users/router.py     # User CRUD + timezone preference
│   │   ├── device_types/router.py # Device type catalogue
│   │   ├── registration_tokens/router.py # Collector registration tokens
│   │   ├── collector_groups/router.py # Collector group management
│   │   └── scheduler/          # Leader election + background tasks
│   ├── frontend/               # React SPA
│   │   └── src/
│   │       ├── main.tsx         # Entry point + React Query client
│   │       ├── App.tsx          # React Router configuration
│   │       ├── api/
│   │       │   ├── client.ts    # fetch() wrapper (apiGet, apiPost, apiPut, apiDelete)
│   │       │   └── hooks.ts     # React Query hooks for ALL API endpoints
│   │       ├── types/api.ts     # TypeScript types for ALL API responses
│   │       ├── lib/utils.ts     # formatDate(dateStr, timezone), timeAgo(), cn()
│   │       ├── hooks/
│   │       │   ├── useAuth.tsx  # Auth context (user, login, logout, refresh)
│   │       │   └── useTimezone.ts # Returns user's timezone preference
│   │       ├── pages/           # One file per page
│   │       ├── components/      # Shared UI components
│   │       └── layouts/         # Sidebar + Header + AppLayout
│   └── alembic/                # Database migrations
├── collector/                  # Collector node
│   └── src/monctl_collector/
│       ├── config.py           # YAML + env config
│       ├── central/api_client.py # HTTP client for /api/v1/
│       ├── polling/
│       │   ├── engine.py       # Min-heap deadline scheduler
│       │   └── base.py         # BasePoller abstract class
│       ├── apps/manager.py     # App download + virtualenv management
│       ├── forward/forwarder.py # Result batching + posting
│       ├── cache/              # Local SQLite + distributed cache
│       ├── cluster/            # Gossip protocol, membership
│       ├── jobs/               # Job scheduling, work stealing
│       └── peer/               # gRPC client/server
├── common/                     # Shared: monctl_common.utils (utc_now, hash_api_key)
└── sdk/                        # SDK package
```

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

Naming convention: `<8-char alphanumeric id>_<snake_case_description>.py` with sequential down_revision chain.

```python
revision = "m5n6o7p8q9r0"
down_revision = "n6o7p8q9r0s1"  # Previous migration

def upgrade() -> None:
    op.create_table(
        "my_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
    )

def downgrade() -> None:
    op.drop_table("my_entities")
```

Migrations run automatically on container startup with an advisory lock (safe for multi-instance).

### Step 3: Backend Router

**File**: `packages/central/src/monctl_central/my_feature/router.py`

```python
"""My feature endpoints."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from monctl_central.dependencies import get_db, require_auth
from monctl_central.storage.models import MyEntity
from monctl_common.utils import utc_now

router = APIRouter()

def _fmt(e: MyEntity) -> dict:
    return {
        "id": str(e.id),
        "name": e.name,
        "description": e.description,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }

class CreateRequest(BaseModel):
    name: str
    description: str | None = None

@router.get("")
async def list_entities(db: AsyncSession = Depends(get_db), auth: dict = Depends(require_auth)):
    rows = (await db.execute(select(MyEntity).order_by(MyEntity.name))).scalars().all()
    return {"status": "success", "data": [_fmt(e) for e in rows]}

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_entity(req: CreateRequest, db: AsyncSession = Depends(get_db), auth: dict = Depends(require_auth)):
    entity = MyEntity(name=req.name, description=req.description)
    db.add(entity)
    await db.flush()
    return {"status": "success", "data": _fmt(entity)}

@router.put("/{entity_id}")
async def update_entity(entity_id: str, req: CreateRequest, db: AsyncSession = Depends(get_db), auth: dict = Depends(require_auth)):
    entity = await db.get(MyEntity, uuid.UUID(entity_id))
    if not entity:
        raise HTTPException(status_code=404, detail="Not found")
    entity.name = req.name
    entity.updated_at = utc_now()
    return {"status": "success", "data": _fmt(entity)}

@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(entity_id: str, db: AsyncSession = Depends(get_db), auth: dict = Depends(require_auth)):
    entity = await db.get(MyEntity, uuid.UUID(entity_id))
    if not entity:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(entity)
```

**Register in** `api/router.py`:
```python
from monctl_central.my_feature.router import router as my_feature_router
api_router.include_router(my_feature_router, prefix="/my-entities", tags=["my-feature"])
```

### Step 4: TypeScript Types

**File**: `packages/central/frontend/src/types/api.ts`

```typescript
export interface MyEntity {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}
```

### Step 5: React Query Hooks

**File**: `packages/central/frontend/src/api/hooks.ts`

```typescript
export function useMyEntities() {
  return useQuery({
    queryKey: ["my-entities"],
    queryFn: () => apiGet<MyEntity[]>("/my-entities"),
    select: (res) => res.data,
    refetchInterval: 30_000,
  });
}

export function useCreateMyEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      apiPost<MyEntity>("/my-entities", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["my-entities"] });
    },
  });
}

export function useDeleteMyEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/my-entities/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["my-entities"] });
    },
  });
}
```

### Step 6: Page Component

**File**: `packages/central/frontend/src/pages/MyPage.tsx`

Standard page structure pattern (see existing pages for reference):
- Import hooks from `@/api/hooks.ts`
- Import UI components from `@/components/ui/`
- Loading state with `<Loader2>` spinner
- Empty state with icon + message
- Table or card layout for data
- Dialog for create/edit forms
- Use `formatDate(dateStr, tz)` with `useTimezone()` for all timestamps

### Step 7: Routing + Navigation

**`App.tsx`**: Add `<Route path="my-feature" element={<MyPage />} />`

**`layouts/Sidebar.tsx`**: Add to `navItems` array:
```typescript
{ to: "/my-feature", icon: MyIcon, label: "My Feature", end: false },
```

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
- Actions: `/collectors/{id}/approve`, `/templates/{id}/apply`
- Sub-resources: `/users/{id}/tenants`

### Multi-Tenant Filtering

```python
from monctl_central.dependencies import apply_tenant_filter
stmt = select(Device)
stmt = apply_tenant_filter(stmt, auth, Device.tenant_id)
```

### Error Handling

```python
raise HTTPException(status_code=400, detail="Invalid input")
raise HTTPException(status_code=404, detail="Not found")
raise HTTPException(status_code=409, detail="Already exists")
```

---

## Frontend API Client

**`api/client.ts`** wraps `fetch()` with:
- `credentials: "include"` (sends cookies)
- Auto-redirect to `/login` on 401
- JSON content-type
- Functions: `apiGet<T>()`, `apiPost<T>()`, `apiPut<T>()`, `apiDelete()`
- Returns `ApiResponse<T>` = `{status: string, data: T}`

---

## Database

### PostgreSQL Models (storage/models.py)

Key models: Device, Collector, CollectorCluster, CollectorGroup, App, AppVersion, AppAssignment, Credential, CredentialKey, CredentialValue, User, UserTenant, Tenant, AlertRule, AlertState, SystemSetting, TlsCertificate, Template, RegistrationToken, ApiKey, SnmpOid, DeviceType

### ClickHouse (storage/clickhouse.py)

- `check_results`: Time-series check results (TTL 90 days)
- `check_results_latest`: Materialized view (ReplacingMergeTree) — latest per assignment
- `events`: Collector events (TTL 30 days)
- Query via: `ch.query_history()`, `ch.query_latest()`, `ch.insert_results()`

### Timestamps

- All stored in UTC (`DateTime(timezone=True)`)
- Frontend uses `formatDate(dateStr, timezone)` from `lib/utils.ts`
- User timezone stored in `User.timezone` column, accessed via `useTimezone()` hook
- Charts (`AvailabilityChart`, `TimeRangePicker`) accept `timezone` prop

---

## Building & Deploying

- Build locally: `docker build --platform linux/amd64 --no-cache -t monctl-central:latest -f docker/Dockerfile.central .`
- Push: `docker save monctl-central:latest | ssh hans@192.168.1.41 'docker load'`
- Distribute to central2-4 similarly
- Restart: `ssh hans@<ip> 'cd /opt/monctl/central && docker compose -f docker-compose.central.yml down && docker compose -f docker-compose.central.yml up -d'`
- No npm/node on servers — Dockerfile handles frontend build
- No package-lock.json — uses `npm install` (not `npm ci`)
- Always use `--no-cache` when rebuilding after source changes
- Use `docker compose up -d` (not `restart`) to pick up new images

### Server Inventory

| Role     | Hosts          | IPs                    |
|----------|----------------|------------------------|
| Central  | central1-4     | 10.145.210.41 - .44    |
| Workers  | worker1-4      | 10.145.210.31 - .34    |
| VIP      | (keepalived)   | 10.145.210.40          |

SSH user: `monctl` for all servers.

### Code Style

- Python: ruff with line-length 100, target Python 3.11
- TypeScript: standard React conventions, path aliases `@/`
- Communicate in Danish when the user writes in Danish
