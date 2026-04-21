# MonCTL Review — Follow-up TODO

**Start here in future sessions.** Sequenced from cheapest-most-valuable to largest-strategic. Each item links back to the finding(s) where the file/line details live.

## How to resume

1. Read `README.md` in this directory for context.
2. Pick a wave below. Start with Wave 1 — they're all S-effort and unlock ~10 HIGH-severity items for almost no work.
3. For each item:
   - Open the referenced finding file for `file:line_range` and fix sketch.
   - Before editing, **re-read the file** — line numbers may have drifted. Grep by the distinctive pattern (e.g. `secure=False`) rather than trusting line numbers.
   - One PR per category ideally; small atomic commits.
4. Mark the item done below (leave the finding ID visible — makes PR descriptions writable in one line).

---

## Wave 1 — Quick wins (all S, mostly HIGH security)

- [x] **F-CEN-001** Gate cookie `secure` flag behind `settings.cookie_secure` (default `True`). `auth/router.py:108-117, 235-239`
- [x] **F-CEN-002** Switch `samesite="lax"` → `"strict"` on auth cookies
- [x] **F-CEN-012** Use `hmac.compare_digest` for shared-secret comparisons in `dependencies.py:427, 437`
- [x] **F-CEN-041** Wrap `asyncio.create_task` in scheduler with a done-callback that logs exceptions
- [x] **F-CEN-044** Replace bare-excepts in `ws/connection_manager.py:67, 136, 189, 247, 267` with structured logging
- [x] **F-CEN-042** Add `asyncio.Lock` around the 30s alerting cycle
- [x] **F-CEN-040** Replace leader-election TOCTOU (`leader.py:92-95`) with atomic Lua script or `SET key val XX EX 30`
- [x] **F-CEN-027** `asyncio.gather` the 4 dashboard CH queries
- [x] **F-CEN-009** Invalidate `api_key:*` and `user_perms:*` Redis entries on credential/role mutations
- [x] **F-COL-011** Validate `app_id`/`connector_id`/`credential_name` regex before URL interpolation in collector client
- [x] **F-COL-020** Add jitter to WS reconnect backoff steps in `ws_client.py:21, 99`
- [x] **F-COL-022** Wrap WS handler invocation in `asyncio.wait_for(..., 30.0)` at `ws_handlers.py:134`
- [x] **F-COL-023** Replace `str(exc)` in WS handler error responses with `type(exc).__name__`
- [x] **F-COL-024** `urllib.parse.quote(container, safe="")` in log-fetch URL at `ws_handlers.py:99`
- [x] **F-COL-047** Startup assertion: `central.url` and `api_key` must be non-empty
- [x] **F-COL-003** Change engine fallback category from `"device"` to `"app"` + log WARN (`polling/engine.py:370-371`)
- [x] **F-COL-002** Wrap `_run_job` body in outer `try/finally` so `self._running.discard` always fires
- [x] **F-APP-001** Remove `snmp_discovery.py:87` stray `snmp.connect(host)`; bump pack
- [x] **F-WEB-010** Add `document.hidden` check to `refetchInterval` in `src/api/hooks.ts`
- [x] **F-WEB-019** Add `ensureUTC(ts)` helper; replace all `timestamp + "Z"` usages
- [x] **F-WEB-014** Set global `staleTime: 5000` on `QueryClient` — already at `10_000` in `main.tsx:13`; stronger than the 5s recommendation, finding based on outdated state
- [x] **F-WEB-005** Replace `window.location.href = "/login"` with router `navigate("/login?next=...")`

## Wave 2 — Mid-effort security + correctness (M)

- [x] **F-CEN-004** Login rate-limit (Redis token bucket) + account lockout
- [x] **F-CEN-005** Refresh-token rotation + replay detection (#105)
- [x] **F-CEN-006** Server-side session revocation via user `token_version` (#105)
- [x] **F-CEN-014** Join `AppAssignment` on `job_id` to verify caller owns it (#107)
- [x] **F-CEN-015** Scope credential fetch to collector's assigned devices only (#107)
- [x] **F-CEN-016** Ownership check in app-cache push/pull (#107)
- [x] **F-CEN-018** WS token header-auth (not URL query param); central + collector coordination (#115)
- [x] **F-CEN-050** Unit test enumerates mutating routers; fail if touched table missing from `audit/resource_map.py` (#108)
- [x] **F-CEN-026** Column allow-list per results endpoint (no more `SELECT *`) — **closed, won't fix**. Re-audited 2026-04-21: `availability_latency`, `performance`, `interface`, `config` tables contain no secret-bearing columns — just IDs, timestamps, metric values, and denormalised `device_name`/`app_name`/`tenant_id/name` for join-free reads. `metric_names`/`metric_values` arrays on raw tiers are the actual payload so `SELECT *` is correct there; rollup tiers are already narrow. No data-leak vector identified. Allow-listing would be churn with no security gain and would force frontend changes every time a column is added.
- [x] **F-CEN-022** DSL compiler hardening + adversarial test corpus (#114)
- [x] **F-COL-030** Move pip API key out of `PIP_INDEX_URL` env → temp `pip.conf` with 0o600
- [x] **F-COL-031** Validate pip requirement strings; `--require-hashes`, `--no-build-isolation` (#110 — allowlist + argv flag rejection; hash enforcement deferred until packs supply hashes)
- [x] **F-COL-026** Add auth on the peer gRPC channel (#122) — `MONCTL_PEER_TOKEN` env var + gRPC interceptors on both ends; deployed and enforcing on all 4 worker hosts as of 2026-04-21
- [x] **F-COL-036** Enforce max-rows on forwarder SQLite + FIFO drop
- [x] **F-COL-038** Batch-id + server-side dedup for idempotent forwarder retries (#113)
- [x] **F-COL-044** Regex filter + rate limiting in log shipper
- [x] **F-APP-004** Typed error categorisation in all 4 SNMP reference apps (#106)
- [x] **F-APP-006** Add `logger.debug` tracing to all 4 reference apps (template for future pollers) (#106)
- [x] **F-APP-011** Bump pack versions + add `scripts/validate_packs.py` to CI (#111)
- [x] **F-WEB-001** DOMPurify-sanitise + proper `sandbox` on `ConfigDataRenderer` iframe (#109 — sandbox tightened; DOMPurify deferred since sandbox alone neutralises the XSS)
- [x] **F-WEB-002** Replace `postMessage(..., "*")` with explicit origin
- [x] **F-WEB-006** Cap & redact error-body stringification in `api/client.ts`
- [x] **F-WEB-007** Cross-tab logout via `BroadcastChannel`

## Wave 3 — Large initiatives (L)

- [x] **F-X-001** Per-collector API keys — **Phase 1+2 (#120), Phase 3 (#121), Phase 4 (#122) all shipped**. Central accepts per-collector keys on `/api/v1/*`; collector prefers its per-collector key over the shared secret on all REST + WS calls; ownership enforced on `/jobs`, `/results`, `/credentials`, `/app-cache/push`; peer gRPC channel now authenticated via shared token (F-COL-026). **Remaining**: sunset the `/api/v1/*` shared secret once fleet has fully migrated.
- [x] **F-CEN-024 + F-CEN-025** Migrate to async ClickHouse client (or pooled sync); remove `_LockedClient` global lock — **F-CEN-024** shipped in #128 (connection pool replaces `_LockedClient`); **F-CEN-025** shipped in #130 (`asyncio.to_thread` wrap on the sync call sites)
- [x] **F-CEN-037** `/v1/logs` + `/v1/logs/filters` gated to `require_admin` — logs are infrastructure (docker stdout + app logs from collectors) with no natural tenant attribution; admin-only matches actual use (`SystemHealthPage`, `DockerInfraPage`) and closes the leak without needing a partition column. `tenant_id` DDL column left as default-zero for future use.
- [x] **F-WEB-025** Lazy-load every route via `React.lazy` + `<Suspense>` (#123) — deployed; verified chunked output: `DevicesPage`, `SystemHealthPage`, `DeviceDetailPage` each load on-demand
- [x] **F-WEB-026** Split `DeviceDetailPage.tsx` (8025 lines) by tab into routed sub-pages — **phase 1** (#132) split into per-file modules under `pages/devices/`; **phase 2** (#133) wired React Router tab routes + `React.lazy` per tab so each chunk loads on demand. `DeviceDetailPage.tsx` is now a 509-line shell.
- [x] **F-WEB-027** Remove `any`/`as any` casts — all 29 in DeviceDetailPage/SettingsPage/AlertsPage removed; added `role` to `CheckResult`, typed `pollNow` response shape, introduced local union aliases for iface prefs. Deployed + verified.
- [x] **F-X-005** Zod schemas on the 6 highest-traffic responses (Device, Collector, AlertEntity, AlertDefinition, AlertLogEntry, DashboardSummary). New `apiGetSafe()` helper runs `safeParse` and logs drift as a `console.warn` without blocking the UI. Verified against live prod data — zero drift warnings. Adding more schemas is a mechanical extension.
- [x] **F-X-007** E2E harness — phase 1: `docker/docker-compose.e2e.yml` boots postgres + redis + clickhouse + central on isolated ports, `scripts/run_e2e.sh` orchestrates build → `up --wait` → pytest → `down -v`. 3 seed tests in `tests/integration/test_e2e_smoke.py` (unauth /v1/health, admin login + /auth/me, device CRUD roundtrip) run in <1s against the fresh stack. Found + worked around a real yield-dependency race: FastAPI commits sessions AFTER the response returns, so DELETE → list can see stale state; test polls /devices/{id} for 404 instead. Phase 2 (stub collector + job dispatch round-trip + nightly CI wiring) deferred.
- [x] **F-WEB-030** Vitest + RTL harness in place. 21 tests across `formatBytes`/`formatUptime`/`timeAgo`, `useListState` (5 scenarios), and `ClearableInput` (4 scenarios incl. the focus-preservation regression anchor). `npm test` / `test:watch` scripts; test files excluded from prod tsc build via `tsconfig.app.json` exclude + dedicated `tsconfig.vitest.json`. Schema tests deferred — they live in the F-X-005 branch and will land once #126 merges.
- [x] **F-X-002** Central observability — verified already shipped (backlog memory was stale). `ingestion_rate_history`, `db_size_history`, `host_metrics_history`, and `container_metrics_history` tables exist; leader-only samplers `_sample_ingestion_rates` (5 min) + `_sample_db_sizes` (15 min) run, and the docker-stats sidecars on central1-4 push to `/api/v1/docker-stats/push` every ~15s (22k+ rows per central since 2026-04-17). `IngestionRateChart`, `DbSizeHistoryChart`, and `HostMetricsChart` render all series on System Health. Attempted a redundant central-sidecar puller during this session and rolled back after CH showed central1-4 already sampled via the push path. Remaining F-X-002-adjacent: durable counters for Wave 1 failure sites (scheduler task failures, WS bare-except count, forwarder drops) — deferred; failures log today but don't count.

## Manual / "not code" follow-ups

- [x] **Crypto review** both `credentials` files — audit at `crypto-review.md`. No critical issues. Central uses AES-256-GCM + per-message `os.urandom(12)` nonce; collector uses Fernet (AES-128-CBC + HMAC). Three low-priority gaps flagged: (1) collector ephemeral-key warning — **shipped** as a one-liner in this batch; (2) central ciphertext version prefix for future rotation — deferred; (3) AAD binding to row ID — deferred.
- [x] **F-X-008** Add `pip-audit` + `npm audit` to CI — `.github/workflows/security-audit.yml` runs nightly + on dep-file PRs. `pip-audit` installs all four local packages and fails on HIGH/CRITICAL only (all findings listed). `npm audit --audit-level=high --omit=dev` on the frontend. **Needs user to commit** — PAT lacks `workflow` scope.
- [x] **F-X-010** Audit every TLS/SSL call site; gate any `verify=False` behind `MONCTL_INSECURE_TLS=1` — audit doc at `tls-audit.md`. No silent disabling in prod runtime; every call site gated by a named env var with safe default. Flipped `docker-stats-server.py` code-level default `PUSH_VERIFY_SSL=false → true` (compose files already set the env explicitly, so no fleet behaviour change). Warning comment added in `docs/action-development-guide.md:193`.
- [x] **F-X-011** Promote evergreen memory files into `CLAUDE.md` "Known pitfalls" section — added 12 entries covering: nullable DB-field reads, collector delta-sync `updated_at`, ClickHouse MV schema changes, poller timing + error categorisation, poller debug logging, connector credential-key fallbacks, per-entity batch freshness filtering, frontend `node_modules` shadow, gRPC stub relative imports, zod-as-telemetry, alembic rebase hygiene, PAT workflow scope.
- [x] **Smoke-test the review** — picked 3 HIGH findings marked fixed and verified in current code (2026-04-21):
  - **F-CEN-001** cookies: `auth/router.py:267,272,443,448` all now `httponly=True, samesite="strict", secure=settings.cookie_secure`. Verified.
  - **F-CEN-014** collector job ownership: `collector_api/router.py:208,277,285,491` enforce `AppAssignment.collector_id == caller.id` on `/jobs` and `/results` paths. Verified.
  - **F-CEN-037** logs admin gate: `logs/router.py:99,191` on `query_logs` + `get_filters` both use `Depends(require_admin)`. Verified.

---

## Progress

Wave 1 complete. Wave 2 complete (F-CEN-026 formally closed as won't-fix after re-audit).

Related side-fixes landed alongside Wave 2:

- Connector built-in seed is now create-only + warns on drift (closes a latent footgun that could silently downgrade prod connectors on restart). Shipped in #112.
- Collector structlog is now routed through stdlib, so Debug Run captures connector debug lines uniformly in the `logs` panel. Shipped in #112.

Wave 3 complete (2026-04-21): F-X-001 (per-collector keys), F-X-002 (central observability), F-X-005 (zod schemas), F-X-007 phase 1 (E2E harness), F-WEB-025 (lazy routes), F-WEB-026 (DeviceDetailPage split phase 1+2), F-WEB-027 (strip `any`), F-WEB-030 (Vitest harness), F-CEN-024/025 (async ClickHouse), F-CEN-037 (logs admin-only) all shipped.

Manual follow-ups (2026-04-21):

- F-X-010 TLS audit → `tls-audit.md`; no silent disabling, `docker-stats-server.py` default flipped to `verify=true`.
- F-X-011 memory promotion → "Known pitfalls" section in `CLAUDE.md` with 12 entries.
- F-X-008 `pip-audit` + `npm audit` workflow → `.github/workflows/security-audit.yml`. Needs user to commit (PAT lacks `workflow` scope).
- Smoke-test → 3 HIGH findings re-verified in-tree, no drift.

Still open:

- Crypto review (both `credentials/crypto.py` files) — blocked on lifting path restriction in `.claude/settings.local.json`.
- F-X-007 phase 2 (stub collector + job dispatch round-trip + nightly CI wiring) — explicitly deferred in phase 1 landing.
