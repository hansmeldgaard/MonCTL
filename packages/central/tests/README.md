# MonCTL Central — Tests

## Krav

- Docker (ingen lokal Python-installation nødvendig)

## Kør alle unit tests

```bash
cd ~/MonCTL

docker run --rm -v $(pwd):/app -w /app/packages/central python:3.11-slim bash -c '
  pip install -q aiosqlite factory-boy pytest pytest-asyncio httpx \
    fastapi uvicorn "sqlalchemy[asyncio]" asyncpg alembic redis \
    clickhouse-connect pydantic pydantic-settings structlog msgpack \
    python-multipart bcrypt cryptography PyJWT apscheduler \
    -e /app/packages/common -e /app/packages/central 2>/dev/null &&
  python -m pytest tests/unit/ -v
'
```

## Kør specifikke tests

Tilføj `-k` for at filtrere:

```bash
# Kun auth tests
python -m pytest tests/unit/ -v -k test_auth

# Kun en specifik test
python -m pytest tests/unit/test_devices.py::TestDeviceCreate::test_create_device -v

# Kun en hel fil
python -m pytest tests/unit/test_settings.py -v
```

## Test-struktur

```
tests/
├── conftest.py              # Root: auto-markers, shared fixtures
├── factories.py             # Factory-boy factories (Device, App, User, Credential)
├── unit/
│   ├── conftest.py          # SQLite in-memory engine, mock CH/Redis, FastAPI test client
│   ├── test_auth.py         # Login, logout, refresh, /me, idle timeout
│   ├── test_apps.py         # App CRUD, versions, clone
│   ├── test_devices.py      # Device CRUD, filtering, pagination
│   ├── test_settings.py     # System settings, idle timeout preference
│   └── test_users.py        # User CRUD, timezone, self-delete protection
└── integration/             # (tom — kræver docker-compose.test.yml med PG + CH)
```

## Markers

| Marker | Beskrivelse | Kørsel |
|--------|-------------|--------|
| `unit` | SQLite in-memory, ingen Docker-services | Default (kører automatisk) |
| `pg_only` | Kræver PostgreSQL (constraint-tests) | `pytest -m pg_only` |
| `integration` | Kræver PG + ClickHouse + Redis | `pytest -m integration` |

Default kørsel filtrerer `pg_only` og `integration` fra.

## Sådan virker det

- **SQLite in-memory** erstatter PostgreSQL — JSONB mappes til JSON, `now()` til `CURRENT_TIMESTAMP`
- **ClickHouse** er mocked (alle queries returnerer tomme resultater)
- **Redis** er mocked (cache-opslag returnerer `None`)
- **FastAPI lifespan** er disabled (ingen DB-connection ved startup)
- Hver test får sin egen session der rulles tilbage efter test

## Tilføj nye tests

1. Opret en ny fil i `tests/unit/`, f.eks. `test_collectors.py`
2. Brug `auth_client` fixture til autentificerede requests
3. Brug `client` fixture til uautentificerede requests
4. Brug factories fra `tests/factories.py` til test-data

Eksempel:

```python
from httpx import AsyncClient

class TestMyFeature:
    async def test_something(self, auth_client: AsyncClient):
        resp = await auth_client.get("/v1/my-endpoint")
        assert resp.status_code == 200
```
