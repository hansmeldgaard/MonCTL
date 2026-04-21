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
- [ ] **F-CEN-026** Column allow-list per results endpoint (no more `SELECT *`) — _deferred: raw-tier arrays (`metric_names`/`metric_values`) are the main payload so the `SELECT *` there is justified; rollup tiers are already narrow. A genuine win requires per-call-site column trimming with frontend changes to match_
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
- [ ] **F-CEN-024 + F-CEN-025** Migrate to async ClickHouse client (or pooled sync); remove `_LockedClient` global lock
- [x] **F-CEN-037** `/v1/logs` + `/v1/logs/filters` gated to `require_admin` — logs are infrastructure (docker stdout + app logs from collectors) with no natural tenant attribution; admin-only matches actual use (`SystemHealthPage`, `DockerInfraPage`) and closes the leak without needing a partition column. `tenant_id` DDL column left as default-zero for future use.
- [x] **F-WEB-025** Lazy-load every route via `React.lazy` + `<Suspense>` (#123) — deployed; verified chunked output: `DevicesPage`, `SystemHealthPage`, `DeviceDetailPage` each load on-demand
- [ ] **F-WEB-026** Split `DeviceDetailPage.tsx` (8025 lines) by tab into routed sub-pages
- [x] **F-WEB-027** Remove `any`/`as any` casts — all 29 in DeviceDetailPage/SettingsPage/AlertsPage removed; added `role` to `CheckResult`, typed `pollNow` response shape, introduced local union aliases for iface prefs. Deployed + verified.
- [ ] **F-X-005** Zod schemas on the 10-15 most-used frontend responses (Option A) — or OpenAPI codegen (Option B)
- [ ] **F-X-007** E2E harness: docker-compose central + ClickHouse + stub collector; nightly CI
- [ ] **F-WEB-030** Vitest + RTL on shared primitives
- [ ] **F-X-002** Central observability (ingestion rate, DB size trends, per-node metrics)

## Manual / "not code" follow-ups

- [ ] **Crypto review** `packages/central/src/monctl_central/credentials/crypto.py` — permission-restricted from this session. Verify cipher (AES-GCM vs Fernet), nonce uniqueness, key source, rotation path.
- [ ] **Crypto review** `packages/collector/src/monctl_collector/central/credentials.py` — same.
- [ ] **F-X-008** Add `pip-audit` + `npm audit` to CI
- [ ] **F-X-010** Audit every TLS/SSL call site; gate any `verify=False` behind `MONCTL_INSECURE_TLS=1`
- [ ] **F-X-011** Promote evergreen memory files into `CLAUDE.md` "Known pitfalls" section
- [ ] **Smoke-test the review** — pick 3 random HIGH findings, confirm the file:line refs still point at the described code; re-audit any drift.

---

## Progress

Wave 1 complete. Wave 2 nearly complete (6 merged/open of 8 actionable items; F-CEN-026 column allow-list deferred, F-COL-026 peer gRPC auth subsumed by F-X-001 umbrella).

Related side-fixes landed alongside Wave 2:

- Connector built-in seed is now create-only + warns on drift (closes a latent footgun that could silently downgrade prod connectors on restart). Shipped in #112.
- Collector structlog is now routed through stdlib, so Debug Run captures connector debug lines uniformly in the `logs` panel. Shipped in #112.

Still open from Wave 2: none that are easy. Wave 3 is the next natural batch once deploys land.
