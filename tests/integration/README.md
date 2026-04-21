# Integration / e2e harness (F-X-007)

A minimal docker-compose stack + pytest smoke tests that exercise the central
API end-to-end on a fresh database.

## What it covers today

- Central boots from a fresh Postgres + ClickHouse + Redis (migrations run,
  admin user seeded).
- `/v1/health` is reachable unauthenticated.
- Admin can log in and the auth cookies work for subsequent calls.
- Device CRUD roundtrip via `/v1/devices`.

## Running locally

```bash
# Build image + boot stack + run tests + tear down (single command):
./scripts/run_e2e.sh

# Keep the stack up for iterating on tests:
./scripts/run_e2e.sh up
pytest tests/integration -v
./scripts/run_e2e.sh down

# Reuse an already-built monctl-central image:
SKIP_BUILD=1 ./scripts/run_e2e.sh
```

The stack listens on `127.0.0.1:18443` so it coexists with a dev instance on
`8443`. Override via `MONCTL_E2E_BASE_URL`.

## What's intentionally **not** in scope yet

- No collector — phase 2 will boot a stub collector and exercise job pull +
  result forward.
- No HA (single CH, no Patroni, no Sentinel) — these belong in their own
  dedicated harness.
- CI wiring — designed to run nightly; the GitHub Actions job is phase 2.

## Adding a test

Drop a `test_*.py` in `tests/integration/`. The `admin_client` fixture is a
logged-in `httpx.Client` pointed at the stack. `base_url` gives you the raw
URL for unauthenticated requests.
