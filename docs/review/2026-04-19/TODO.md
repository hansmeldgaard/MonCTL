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

- [ ] **F-CEN-001** Gate cookie `secure` flag behind `settings.cookie_secure` (default `True`). `auth/router.py:108-117, 235-239`
- [ ] **F-CEN-002** Switch `samesite="lax"` → `"strict"` on auth cookies
- [ ] **F-CEN-012** Use `hmac.compare_digest` for shared-secret comparisons in `dependencies.py:427, 437`
- [ ] **F-CEN-041** Wrap `asyncio.create_task` in scheduler with a done-callback that logs exceptions
- [ ] **F-CEN-044** Replace bare-excepts in `ws/connection_manager.py:67, 136, 189, 247, 267` with structured logging
- [ ] **F-CEN-042** Add `asyncio.Lock` around the 30s alerting cycle
- [ ] **F-CEN-040** Replace leader-election TOCTOU (`leader.py:92-95`) with atomic Lua script or `SET key val XX EX 30`
- [ ] **F-CEN-027** `asyncio.gather` the 4 dashboard CH queries
- [ ] **F-CEN-009** Invalidate `api_key:*` and `user_perms:*` Redis entries on credential/role mutations
- [ ] **F-COL-011** Validate `app_id`/`connector_id`/`credential_name` regex before URL interpolation in collector client
- [ ] **F-COL-020** Add jitter to WS reconnect backoff steps in `ws_client.py:21, 99`
- [ ] **F-COL-022** Wrap WS handler invocation in `asyncio.wait_for(..., 30.0)` at `ws_handlers.py:134`
- [ ] **F-COL-023** Replace `str(exc)` in WS handler error responses with `type(exc).__name__`
- [ ] **F-COL-024** `urllib.parse.quote(container, safe="")` in log-fetch URL at `ws_handlers.py:99`
- [ ] **F-COL-047** Startup assertion: `central.url` and `api_key` must be non-empty
- [ ] **F-COL-003** Change engine fallback category from `"device"` to `"app"` + log WARN (`polling/engine.py:370-371`)
- [ ] **F-COL-002** Wrap `_run_job` body in outer `try/finally` so `self._running.discard` always fires
- [ ] **F-APP-001** Remove `snmp_discovery.py:87` stray `snmp.connect(host)`; bump pack
- [ ] **F-WEB-010** Add `document.hidden` check to `refetchInterval` in `src/api/hooks.ts`
- [ ] **F-WEB-019** Add `ensureUTC(ts)` helper; replace all `timestamp + "Z"` usages
- [ ] **F-WEB-014** Set global `staleTime: 5000` on `QueryClient`
- [ ] **F-WEB-005** Replace `window.location.href = "/login"` with router `navigate("/login?next=...")`

## Wave 2 — Mid-effort security + correctness (M)

- [ ] **F-CEN-004** Login rate-limit (Redis token bucket) + account lockout
- [ ] **F-CEN-005** Refresh-token rotation + replay detection
- [ ] **F-CEN-006** Server-side session revocation via user `token_version`
- [ ] **F-CEN-014** Join `AppAssignment` on `job_id` to verify caller owns it
- [ ] **F-CEN-015** Scope credential fetch to collector's assigned devices only
- [ ] **F-CEN-016** Ownership check in app-cache push/pull
- [ ] **F-CEN-018** WS token header-auth (not URL query param); central + collector coordination
- [ ] **F-CEN-050** Unit test enumerates mutating routers; fail if touched table missing from `audit/resource_map.py`
- [ ] **F-CEN-026** Column allow-list per results endpoint (no more `SELECT *`)
- [ ] **F-CEN-022** DSL compiler hardening + adversarial test corpus
- [ ] **F-COL-030** Move pip API key out of `PIP_INDEX_URL` env → temp `pip.conf` with 0o600
- [ ] **F-COL-031** Validate pip requirement strings; `--require-hashes`, `--no-build-isolation`
- [ ] **F-COL-026** Add auth on the peer gRPC channel (UDS or shared bearer)
- [ ] **F-COL-036** Enforce max-rows on forwarder SQLite + FIFO drop
- [ ] **F-COL-038** Batch-id + server-side dedup for idempotent forwarder retries
- [ ] **F-COL-044** Regex filter + rate limiting in log shipper
- [ ] **F-APP-004** Typed error categorisation in all 4 SNMP reference apps
- [ ] **F-APP-006** Add `logger.debug` tracing to all 4 reference apps (template for future pollers)
- [ ] **F-APP-011** Bump pack versions + add `scripts/validate_packs.py` to CI
- [ ] **F-WEB-001** DOMPurify-sanitise + proper `sandbox` on `ConfigDataRenderer` iframe
- [ ] **F-WEB-002** Replace `postMessage(..., "*")` with explicit origin
- [ ] **F-WEB-006** Cap & redact error-body stringification in `api/client.ts`
- [ ] **F-WEB-007** Cross-tab logout via `BroadcastChannel`

## Wave 3 — Large initiatives (L)

- [ ] **F-X-001** Per-collector API keys (umbrella: fixes F-CEN-014/015/016 + F-COL-026). **Single biggest return on investment.**
- [ ] **F-CEN-024 + F-CEN-025** Migrate to async ClickHouse client (or pooled sync); remove `_LockedClient` global lock
- [ ] **F-CEN-037** Add `tenant_id` to ClickHouse `logs` table + backfill + ingest path update
- [ ] **F-WEB-025** Add `React.lazy` to 6+ detail pages
- [ ] **F-WEB-026** Split `DeviceDetailPage.tsx` (8025 lines) by tab into routed sub-pages
- [ ] **F-WEB-027** Remove `any`/`as any` casts; prioritise DeviceDetailPage (19), SettingsPage (6), AlertsPage (4)
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

Nothing started yet. First PR should be **Wave 1 → F-CEN-001 (cookie flag)** — smallest, highest security return, no dependencies.
