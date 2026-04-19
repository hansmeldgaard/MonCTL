# 99 — Cross-Cutting Findings

**Scope**: issues that span two or more surfaces (central + collector + frontend + apps) — meta-issues worth addressing as single initiatives.
**Date**: 2026-04-19

Unique IDs use prefix `F-X-`.

---

## F-X-001: Shared secret (`MONCTL_COLLECTOR_API_KEY`) is a single point of compromise

- **Severity**: HIGH (security)
- **Surfaces**: central (`dependencies.py:406-443`, `ws/auth.py`), collector (`central/api_client.py`, `central/ws_client.py`)
- **Problem**: Every collector authenticates with the same shared secret, over both REST (`/api/v1/*`) and WebSocket (`/ws/collector`). Compromise any one collector → full access to:
  - Fetch any credential by name (F-CEN-015)
  - Submit results for any device / tenant (F-CEN-014)
  - Push anything into the app cache (F-CEN-016)
- **Fix (cohesive)**: Move to per-collector API keys on the central side. Collector bootstraps with the shared secret _once_ at `register` time, then uses an issued per-collector bearer token thereafter. All `/api/v1/*` endpoints then have a concrete `caller.collector_id` to enforce scope against.
- **Effort**: L (central auth layer + collector storage + rotation workflow)
- **References**: F-CEN-012, F-CEN-014, F-CEN-015, F-CEN-016, F-COL-026

---

## F-X-002: Telemetry / observability into the platform itself is thin

- **Severity**: MED
- **Surfaces**: all
- **Problem**: The platform monitors devices exhaustively but has comparatively little self-observability:
  - No Prometheus-style `/metrics` endpoint on central or collectors
  - Fire-and-forget `asyncio.create_task` in scheduler / collector silently swallow exceptions (F-CEN-041, F-COL-049)
  - WebSocket manager bare-excepts (F-CEN-044)
  - Forwarder drops batches without a durable counter (F-COL-036)
  - `project_backlog_central_observability` memory is already on file
- **Fix (cohesive)**: Emit a small `metrics` table in ClickHouse with `(timestamp, instance, metric_name, value, labels)` and publish counters from the well-known failure points. Surface them on the System Health page.
- **Effort**: L

---

## F-X-003: Audit coverage gap for background-task mutations

- **Severity**: MED
- **Surfaces**: central audit (`audit/db_events.py:118-123`) + scheduler (`scheduler/tasks.py`)
- **Problem**: Audit listener skips `session.new/dirty/deleted` entirely when there's no request context. Alerting transitions, rebalancer weight updates, automation execution, and pack-import seeds happen without any audit trail. Users debugging "who changed X?" see no record.
- **Fix (cohesive)**:
  1. Make `audit/context.py` support a `with system_audit_context(task_name: str): ...` helper.
  2. Wrap every scheduled / WS-triggered task in that context.
  3. Audit rows then land with `auth_type="system"` + `username="task:<name>"`, preserving forensic continuity.
- **Effort**: M
- **References**: F-CEN-031

---

## F-X-004: Error categorisation drift between apps and engine

- **Severity**: MED
- **Surfaces**: apps (`apps/*.py`, `packs/*.json`) + collector engine (`polling/engine.py:370-371`) + alerting engine (central)
- **Problem**: Apps default to `error_category="device"` on every unexpected exception (F-APP-004); the engine _also_ defaults missing categories to `"device"` (F-COL-003). Two layers of defaulting ensure all app bugs look like device problems to the alerting engine. Alert-rate-by-category is noise.
- **Fix (cohesive)**:
  1. Apps: explicit `except TimeoutError → "device"`, `except KeyError/MissingConfig → "config"`, else `"app"`.
  2. Engine: change the fallback default from `"device"` to `"app"` and log a WARN when an app returns no category.
  3. Add a unit test that asserts all `packs/*.json` apps produce an `error_category` on every error path.
- **Effort**: M
- **References**: F-APP-004, F-COL-003

---

## F-X-005: Request/response shape drift between backend and frontend types

- **Severity**: LOW (typing)
- **Surfaces**: central (`api/router.py`) + frontend (`src/types/api.ts`, `src/api/hooks.ts`)
- **Problem**: Response shapes are hand-typed on both sides. The 106 `any` + 29 `as any` on the frontend (F-WEB-027) are largely drift from endpoints that evolved without updating `types/api.ts`. No runtime validation either, so a backend rename silently breaks the UI on prod.
- **Fix (cohesive, two options)**:
  - **Option A (smaller effort)**: Add `zod` schemas on the frontend for the 10-15 most-used response types. Parse responses in `apiGet` to validate and surface errors early.
  - **Option B (larger effort)**: Emit OpenAPI from FastAPI (FastAPI already generates it — just expose it in build), generate TS types + zod with `openapi-typescript-codegen` or `orval`.
- **Effort**: M (A) / L (B)

---

## F-X-006: Secret redaction is substring-based and distributed

- **Severity**: MED (secret leakage)
- **Surfaces**: central audit (`audit/diff.py`), collector log shipper, frontend error display (F-WEB-006)
- **Problem**: Each layer has its own hand-curated redaction list. A new field like `auth_bearer` would leak in audit logs, shipped container logs, and the UI — three separate places to fix.
- **Fix (cohesive)**: A single `common/redact.py` that both central and collector depend on, with a shared regex (`(?i)(password|secret|token|api_key|private_key|bearer|credential_|jwt_)`) and a hook for model-level redaction. Frontend uses the same regex in `client.ts` error display.
- **Effort**: M

---

## F-X-007: No end-to-end integration tests for the critical path

- **Severity**: MED (regression risk)
- **Surfaces**: all
- **Problem**: Existing backend unit tests (~8 files, ~50 tests) cover router/service layers. There's zero coverage on:
  - Central→collector job dispatch round trip
  - Result ingestion→ClickHouse→alert evaluation→UI display
  - Multi-tenant isolation under edge cases (transfer, delete)
  - Credential rotation propagation
- **Fix (cohesive)**: A small `tests/e2e/` harness using docker-compose to spin up central + ClickHouse + one stub collector. Exercise the golden paths listed above. Run on CI nightly (too slow per-PR).
- **Effort**: L

---

## F-X-008: No CVE / dependency scan

- **Severity**: MED
- **Surfaces**: central (`pyproject.toml`), collector (`pyproject.toml`), frontend (`package.json`)
- **Problem**: Not a code issue per se, but worth mentioning: no `pip-audit` or `npm audit` in CI. Given the AI-written nature of much of the code, third-party dependency posture is especially worth monitoring.
- **Fix**: Add `pip-audit` and `npm audit --audit-level=high` as CI jobs.
- **Effort**: S

---

## F-X-009: The "shared secret in URL query param" pattern appears twice

- **Severity**: MED (security)
- **Surfaces**: WS auth (`ws/auth.py`, `ws/router.py`), log-shipper URLs (`central/log_shipper.py`)
- **Fix (cohesive)**: Enforce a repo-wide lint / code-review check: no query-param-based auth. Always bearer-header.
- **Effort**: S (policy + one-time refactor already scoped above)
- **References**: F-CEN-018, F-COL-021

---

## F-X-010: TLS verification posture unknown

- **Severity**: MED (security — unverified)
- **Surfaces**: collector → central (`central/api_client.py`), collector → cache-node (peer), log shipper
- **Problem**: The codebase references TLS settings but no single place documents whether `verify=False` is ever set and under what conditions. On self-signed certs (HAProxy VIP), `verify=True` fails; easy to silently disable.
- **Fix**: Audit every `httpx.Client`, `aiohttp.ClientSession`, and `websockets.connect` call site for `verify=`/`ssl=` settings. Document the intended posture. Any `verify=False` should be gated on an explicit `MONCTL_INSECURE_TLS=1` env var (not default).
- **Effort**: S (audit) + S (gate env var)

---

## F-X-011: Many "known landmines" live only in memory files

- **Severity**: LOW (maintainability)
- **Surfaces**: all
- **Problem**: `feedback_app_timing_placement`, `feedback_ch_mv_schema_migrations`, `project_rollup_chain_fragility`, `feedback_per_entity_filtering`, etc. are captured in the auto-memory system. New contributors (human or AI) don't read those — the knowledge stays locked.
- **Fix**: Promote the evergreen ones (timing hygiene, MV migrations, rollup drift, per-entity filtering) into `CLAUDE.md` under a "Known pitfalls" section. Keep memory files as the transient scratchpad.
- **Effort**: S

---

## Summary

| Severity  | Count  |
| --------- | ------ |
| HIGH      | 1      |
| MED       | 8      |
| LOW       | 2      |
| **Total** | **11** |

**Priority initiative**: **F-X-001** (per-collector API keys) — unlocks fixes F-CEN-014, F-CEN-015, F-CEN-016 and gives the whole collector trust boundary a stable foundation. Treat this as the single most valuable multi-week project from the review.
