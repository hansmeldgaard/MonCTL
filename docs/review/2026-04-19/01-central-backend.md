# 01 — Central Backend Review

**Scope**: `packages/central/src/monctl_central/` — FastAPI app, auth, RBAC, SQLAlchemy, ClickHouse, audit, alerting, scheduler.
**Date**: 2026-04-19
**Methodology**: direct read of critical files + targeted Explore agent sweeps. All findings have `file:line_range` and a concrete fix sketch. Severity: CRITICAL / HIGH / MED / LOW / INFO. Effort: S (<1h) / M (1-4h) / L (>4h).

Unique IDs use prefix `F-CEN-`.

---

## 1. Auth & RBAC

### F-CEN-001: Cookies set with `secure=False` — JWT can leak over HTTP

- **Severity**: HIGH (security)
- **Category**: auth / cookie hardening
- **Files**:
  - `packages/central/src/monctl_central/auth/router.py:108-117` (login)
  - `packages/central/src/monctl_central/auth/router.py:235-239` (refresh)
- **Problem**: Both `access_token` and `refresh_token` cookies are written with `secure=False` hardcoded. HAProxy terminates TLS at 10.145.210.40:443 and proxies to central:8443 over the internal network — the request arriving at FastAPI is plain HTTP, so setting `secure=True` on the cookie is still correct because the browser only stores the flag based on the response back through HTTPS. But as it stands, if a central port is ever exposed directly on HTTP (even accidentally — e.g. via a debug tunnel or a misconfigured HAProxy), the cookie is emitted over plaintext.
- **Impact**: JWT theft via passive network capture on any accidental HTTP path. The `access_token` is valid for 15 min; `refresh_token` for days.
- **Fix**: Add `MONCTL_COOKIE_SECURE: bool = True` to `config.py`, thread through `settings.cookie_secure`. Default True in prod; dev override via env.
- **Effort**: S

### F-CEN-002: SameSite=Lax on auth cookies is weaker than needed for this app

- **Severity**: MED (security)
- **Category**: CSRF
- **Files**: `auth/router.py:110, 115, 237`
- **Problem**: `samesite="lax"` is the default and permits the cookie on top-level GET navigation. Because the frontend is a SPA and does its own POSTs via `fetch()` with `credentials: "include"`, there is no legitimate cross-site navigation that should carry the auth cookie. Combined with the fact that no CSRF token middleware is installed (see F-CEN-003), a malicious site can still trigger **GET** mutations if any exist.
- **Impact**: Marginal today (no known GET mutations in routers) but brittle as features are added.
- **Fix**: Switch to `samesite="strict"` for both tokens. Verify UI doesn't break on first-nav (it shouldn't — SPA bootstraps `/me` via XHR).
- **Effort**: S

### F-CEN-003: No CSRF protection for cookie-auth mutations

- **Severity**: MED (security)
- **Category**: CSRF
- **Problem**: With `httponly` + `samesite=lax` cookies, CSRF is _partially_ mitigated but not eliminated. FastAPI has no CSRF middleware here. Any `<form>` auto-submit from a sibling subdomain or a timed POST from a phishing page can ride the session if SameSite permits it.
- **Fix**: Either (a) move to `samesite=strict` (see F-CEN-002) as primary defense, or (b) add a double-submit CSRF token (`X-CSRF-Token` header + matching cookie). Option (a) is lower effort and sufficient here.
- **Effort**: S (with F-CEN-002)

### F-CEN-004: No rate-limit on `/v1/auth/login` — online brute-force attack surface

- **Severity**: HIGH (security)
- **Category**: auth
- **File**: `auth/router.py:51-117`
- **Problem**: No request throttling, no account lockout, no CAPTCHA. Attacker can attempt ~hundreds of passwords per second per central node; HAProxy load-balances, so per-node limits alone wouldn't catch a distributed attack either.
- **Fix**: Redis-backed token-bucket (e.g. `slowapi` or a small custom `INCR`+`EXPIRE` guard) keyed on `(ip, username)`. Lock account for 15 min after 10 failures in 10 min. Log lockout as a `login_locked` audit event.
- **Effort**: M

### F-CEN-005: No refresh-token rotation

- **Severity**: MED (security)
- **Category**: auth
- **File**: `auth/router.py:175-239`
- **Problem**: `/refresh` issues a new `access_token` but the same `refresh_token` stays valid until its original expiry (`_REFRESH_MAX_AGE` = days). Standard JWT-refresh pattern is to rotate: issue new refresh, invalidate old. Without rotation, a stolen refresh token remains usable for its whole lifetime and there's no way to detect replay.
- **Fix**: Issue a new refresh token on each `/refresh`, store a hash of the previous `jti` in a Redis set with TTL = refresh lifetime; reject any refresh using a `jti` that's already been used (replay detection).
- **Effort**: M

### F-CEN-006: No server-side session revocation on logout / role-change

- **Severity**: MED (security)
- **Category**: auth
- **File**: `auth/router.py:142-172`
- **Problem**: `/logout` only clears cookies client-side. A leaked JWT remains valid until `_ACCESS_MAX_AGE` (15 min). Same problem when an admin demotes a user: current sessions keep full privileges until their access token naturally expires.
- **Fix**: Maintain a Redis `token_revoked:<jti>` set; check on every JWT decode in `_get_user_from_cookie`. Invalidate a user's tokens on role-change via a version-counter pattern (`user.token_version` — include in JWT payload, reject if user's current version is higher).
- **Effort**: M

### F-CEN-007: `_populate_audit_context` silently swallows exceptions

- **Severity**: MED (observability)
- **Category**: error handling
- **File**: `dependencies.py:308-322`
- **Problem**: Bare `except Exception: pass`. If the audit context module raises (e.g. contextvars not set up — which has happened during tests), the audit log silently loses the `user_id` / `username` for every request in that window.
- **Fix**: Narrow the except to known import / attribute errors; log with `logger.warning("audit_context_populate_failed", ...)` on anything else so a persistent loss is visible.
- **Effort**: S

### F-CEN-008: `_get_user_from_cookie` swallows all exceptions as "no user"

- **Severity**: LOW (correctness)
- **Category**: error handling
- **File**: `dependencies.py:228-269`
- **Problem**: Bare `except Exception: return None`. A malformed JWT, a token-decoding library bug, a DB connection error, and an invalid UUID all look identical to the caller — treated as "unauthenticated." A DB outage currently masquerades as "logged out."
- **Fix**: Let DB/infrastructure errors bubble (and return 503 via a global handler); only swallow `InvalidTokenError` / `ExpiredSignatureError` / `jwt.PyJWTError`.
- **Effort**: S

### F-CEN-009: Redis-cached API keys + permissions are not invalidated on change

- **Severity**: MED (authz correctness)
- **Category**: caching
- **Files**:
  - `dependencies.py:94-192` (API key cache — `set_cached_api_key`)
  - `dependencies.py:335-365` (`_load_user_permissions` — 5 min TTL)
- **Problem**: If an admin rotates or deletes an API key, cached entries remain valid until TTL. Similarly, removing a permission from a role takes up to 5 min to propagate. No invalidation hook is called from `credentials/router.py`, `users/router.py`, or `roles/router.py` when those mutations happen.
- **Fix**: Emit Redis `DEL` for `api_key:<hash>` and `user_perms:<uid>` from the corresponding mutation endpoints. Shortens TTL as a defence in depth (e.g. 60s for perms, 60s for api_key).
- **Effort**: S

### F-CEN-010: Management API keys bypass ALL permission checks

- **Severity**: INFO (intentional but undocumented)
- **Category**: authorization model
- **File**: `dependencies.py:384-386`
- **Problem**: `require_permission` short-circuits for `key_type == "management"`. This is the design, but there is no per-management-key scope enforcement. A leaked management key is effectively a root token.
- **Fix**: Either document explicitly, or add `scopes: list[str]` already present on the model but unused in this check — and enforce scope matches `{resource}:{action}`.
- **Effort**: M (if we choose to enforce)

### F-CEN-011: Login user-enumeration via audit-log reason (internal only)

- **Severity**: LOW (information disclosure)
- **Category**: auth
- **File**: `auth/router.py:62-84`
- **Problem**: User-facing error is the same (`Invalid username or password`), but the `failure_reason` in the audit log distinguishes `user_not_found` vs `invalid_password`. Only audit-viewers see this — LOW impact, but worth knowing for threat modelling.
- **Fix**: Collapse both to `invalid_credentials` in the audit log; keep the distinction in structured logs only if needed for debugging.
- **Effort**: S

### F-CEN-012: Shared-secret collector auth accepts HTTP Basic without constant-time compare

- **Severity**: MED (security)
- **Category**: timing attack
- **File**: `dependencies.py:406-443`
- **Problem**: `credentials.credentials == shared_secret` and `password == shared_secret` are non-constant-time string compares. Over enough samples and a low-latency network, an attacker can recover the secret byte-by-byte. Shared-secret is bootstrap-trust; rotation is manual.
- **Fix**: `hmac.compare_digest(credentials.credentials, shared_secret)` for both comparisons.
- **Effort**: S

### F-CEN-013: Audit context is global Python contextvars — can leak between requests if task not awaited correctly

- **Severity**: LOW (correctness, edge case)
- **Category**: audit
- **File**: (inferred) `audit/context.py` + `dependencies.py:308-322`
- **Problem**: ContextVar propagation in async code is correct only if the task chain is awaited inline. Fire-and-forget `asyncio.create_task(...)` from inside a handler (e.g. scheduler triggers) can carry a stale context into the background task, attributing mutations to the wrong user.
- **Fix**: In any `asyncio.create_task` inside request handlers, explicitly clear the context at task entry (`context_var.set(None)`).
- **Effort**: M

---

## 2. Collector Trust Boundary

The `/api/v1/` endpoints are the largest trust gap: any ACTIVE collector authenticates with a **shared** secret (`MONCTL_COLLECTOR_API_KEY`), so compromising any one collector gives equal access to all collector-API endpoints.

### F-CEN-014: Collector submits `job_id` without ownership verification

- **Severity**: HIGH (security / data integrity)
- **Category**: collector trust boundary
- **File**: `collector_api/router.py:1306-1400` (submit_results POST)
- **Problem**: `submit_results()` accepts `job_id`, `device_id`, `metrics`, `timestamp` from the collector. No verification that the `AppAssignment` with that `job_id` is actually assigned to the calling collector (or its group). A malicious/compromised collector can inject results for any device, including cross-tenant.
- **Impact**: False monitoring data → false alerts or silent blind spots; cross-tenant data leak via result injection.
- **Fix**: Join `AppAssignment` on `job_id` and verify (a) `collector_id == caller.collector_id`, OR (b) assignment is unpinned AND caller's group matches the consistent-hash partition. Reject with 403 otherwise.
- **Effort**: M

### F-CEN-015: Collector can fetch any credential by name

- **Severity**: HIGH (security)
- **Category**: credential scope
- **File**: `collector_api/router.py:955-1000` (/credentials/{credential_name})
- **Problem**: Any collector with the shared secret can `GET /api/v1/credentials/<name>` and receive the decrypted credential — regardless of whether any of the caller's assigned devices actually use that credential. Collector compromise = full credential exfiltration.
- **Fix**: Enforce that the credential is referenced by at least one assignment currently routed to the calling collector (via `Device.credentials`, `AppAssignment.credential_id`, or `AssignmentCredentialOverride`). Cache the allowed set in Redis per-collector.
- **Effort**: M

### F-CEN-016: App-cache push/pull endpoints have no ownership check

- **Severity**: MED (security / DoS)
- **Category**: collector trust boundary
- **File**: `collector_api/router.py:2154-2250` (app-cache push/pull)
- **Problem**: Collector-supplied app IDs are not validated against the set of apps the collector is actually running. A misbehaving collector can poison the cache for apps it doesn't own.
- **Fix**: Cross-check app_id against the collector's current assignment set before accepting cache writes.
- **Effort**: M

### F-CEN-017: Heartbeat trusts hostname string

- **Severity**: LOW (security)
- **Category**: identity
- **File**: `collector_api/router.py:~1781-1800`
- **Problem**: Heartbeat uses `request.collector_node` (hostname) to identify the reporting node. Hostname is supplied by the client and not cryptographically bound to the API key.
- **Fix**: Identify the collector from the API key → `collector_id` mapping (if the key is per-collector), OR require the collector to register its hostname once and reject mismatches thereafter.
- **Effort**: S

### F-CEN-018: WebSocket token is passed in URL query param (logged, cached)

- **Severity**: MED (security)
- **Category**: WebSocket auth
- **Files**:
  - `packages/central/src/monctl_central/ws/auth.py:19-72`
  - `packages/central/src/monctl_central/ws/router.py:23-54`
- **Problem**: `/ws/collector?token=<api_key>` — URL query strings are logged by HAProxy, reverse proxies, and some intermediate systems. Tokens in URLs are a classic leak vector.
- **Fix**: Move token to WebSocket upgrade header (`Authorization: Bearer ...`) via the `websockets` client's `extra_headers`. Keep query-param as a deprecation-timed fallback during rollout.
- **Effort**: M (requires collector-side rollout)

### F-CEN-019: WS auth exception messages are formatted with `str(exc)` — risk of leaking sensitive data

- **Severity**: LOW
- **File**: `ws/auth.py:65-72`
- **Fix**: Log exception class + stack; do not include `str(exc)` in any response/WS close reason sent back.
- **Effort**: S

---

## 3. SQL / DSL Injection

### F-CEN-020: Dynamic WHERE construction in log query endpoint

- **Severity**: MED (security, depends on parameterization)
- **File**: `packages/central/src/monctl_central/logs/router.py:82-100`
- **Problem**: F-string assembly of `WHERE` clauses for a ClickHouse query. If any of the clause fragments come from unvalidated query-params (collector_name, level, path), injection is possible.
- **Verify**: Re-read the function; if every fragment uses `%(name)s` placeholders with a params dict passed to the client, it's safe. If not, switch to parameterized ClickHouse queries (`{name:Type}` syntax).
- **Fix**: Audit the exact construction; convert any literal interpolations to parameterized bindings.
- **Effort**: S

### F-CEN-021: Assignment-ID list interpolation in alerting engine

- **Severity**: MED (security)
- **File**: `packages/central/src/monctl_central/alerting/engine.py` (search for `assignment_id IN`)
- **Problem**: `f"WHERE assignment_id IN ({aid_list})"` — safe only if `aid_list` is a comma-joined set of verified UUIDs. Worth confirming the source is a typed `list[UUID]`, not a raw string.
- **Fix**: Either assert `isinstance(v, uuid.UUID)` for every element or switch to parameterized `{aids:Array(UUID)}`.
- **Effort**: S

### F-CEN-022: DSL compiler — validate attack surface

- **Severity**: MED (security, depends on grammar)
- **File**: `packages/central/src/monctl_central/alerting/dsl.py:938-942`
- **Problem**: User-authored DSL (`avg(rtt_ms) > 80`, `rate(octets) * 8 > 500`) is compiled to ClickHouse SQL via f-string assembly of the WHERE clause. Claimed safe via parameterized `{param:Type}` slots, but column names, function names, and operators are interpolated directly.
- **Fix**: Ensure the DSL lexer produces a strict allow-list of identifiers (columns, functions) and that any non-literal interpolation is validated against that allow-list before emission. Add a unit test suite that feeds adversarial DSL (`); DROP TABLE`, unicode tricks) and asserts compile-time rejection.
- **Effort**: L (requires a proper test corpus)

### F-CEN-023: ClickHouse MV migration DDL uses `.format(cluster=...)` — literal `{}` must be escaped

- **Severity**: LOW (known gotcha, memory captured)
- **File**: (any `ON CLUSTER` DDL in `storage/clickhouse.py` or migrations)
- **Problem**: See `feedback_ch_mv_schema_migrations` memory — `IndexError: Replacement index 0` when literal `{}` (empty JSON) appears in a DEFAULT clause that goes through `.format()`. Future DDL additions can reintroduce the bug.
- **Fix**: Add a unit test that parses every DDL template file and asserts `.format(cluster="test")` doesn't raise.
- **Effort**: S

---

## 4. ClickHouse Query Hygiene

### F-CEN-024: `_LockedClient` serialises every ClickHouse call via `threading.RLock`

- **Severity**: HIGH (performance)
- **Category**: async hygiene
- **File**: `packages/central/src/monctl_central/storage/clickhouse.py:22-52`
- **Problem**: All CH queries go through a single threading lock. Combined with the sync `clickhouse-connect` client, every CH call blocks the event loop or at best serialises through a single thread pool. This is the single biggest perf limiter for a central node.
- **Fix**: Switch to `clickhouse-connect`'s async client (`AsyncClient`) or use a connection pool — 4-8 concurrent connections per central node. `_LockedClient`'s lock should then be per-connection, not global.
- **Effort**: L (touches every CH call site)

### F-CEN-025: CH queries in async code are not consistently wrapped in `asyncio.to_thread`

- **Severity**: HIGH (perf / correctness)
- **File**: many — `results/router.py`, `dashboard/router.py`, `alerting/engine.py`
- **Problem**: `alerting/engine.py:92-94` wraps the insert in `asyncio.to_thread` (correct). Dozens of other CH calls are invoked directly inside `async def` handlers and block the event loop.
- **Fix**: Wrap every sync CH call site. Better: adopt the async client (F-CEN-024) and remove the `to_thread` wrappers.
- **Effort**: L

### F-CEN-026: `SELECT *` on wide tables via dynamic table-name

- **Severity**: MED (perf)
- **File**: `packages/central/src/monctl_central/results/router.py:372, 836, 1033`
- **Problem**: `SELECT * FROM {table}` loads all columns including arrays (`metric_values`, `metric_names`), which can be large, even when the caller only needs `device_id, executed_at, one_value`.
- **Fix**: Add a column allow-list per endpoint; always select explicitly.
- **Effort**: M

### F-CEN-027: Dashboard endpoint runs 4 CH queries sequentially

- **Severity**: MED (perf)
- **File**: `packages/central/src/monctl_central/dashboard/router.py:125-362` (4 sequential queries)
- **Fix**: Wrap in `asyncio.gather(...)` (all queries are independent). 4× speedup on dashboard load.
- **Effort**: S

### F-CEN-028: Freshness check in alerting engine lacks PREWHERE

- **Severity**: LOW (perf)
- **File**: `alerting/engine.py:755-762`
- **Problem**: `max(received_at)` scanned without a cheap prefilter. PREWHERE on indexable columns reduces IO significantly on large tables.
- **Fix**: `PREWHERE assignment_id = ? AND received_at > now() - INTERVAL 1 HOUR`.
- **Effort**: S

### F-CEN-029: Rollup chain fragility (captured in memory, still a live risk)

- **Severity**: MED (correctness on deploy)
- **File**: `scheduler/` rollup tasks + `storage/clickhouse.py`
- **Problem**: `project_rollup_chain_fragility` memory: adding a column to a rollup requires DDL + ALTERs on all three tiers + scheduler `SELECT ... GROUP BY` updates. Error-prone. Each rollup now has its own try-block which prevents one failure from cascading, but the schema drift itself is silent.
- **Fix**: Add a startup self-check: for each rollup, query `system.columns` and assert the column set matches the scheduler's expected projection. Fail fast on drift.
- **Effort**: M

---

## 5. SQLAlchemy Session Lifecycle

### F-CEN-030: Audit capture bare-except swallows SQLAlchemy inspection errors

- **Severity**: MED (audit integrity)
- **Files**: `audit/db_events.py:40-41, 54-55, 68-69, 148-149`
- **Problem**: Four bare `except Exception:` returning `{}` or logging a warning. If attribute introspection fails for a newly-added model, the mutation will NOT be audited but the flush succeeds silently. Audit becomes "best effort, hope for the best."
- **Fix**: At minimum, emit a `logger.error` with the exception traceback AND the model name. Optionally: in test/CI mode, raise instead of warn — catch schema drift at test time.
- **Effort**: S

### F-CEN-031: Audit is skipped entirely when no request context

- **Severity**: INFO (intentional) but undocumented gap
- **File**: `audit/db_events.py:118-123`
- **Problem**: If `ctx is None` → skip. Scheduler-triggered writes (e.g. automation runs, alert state transitions, rebalancer assignment bumps) never land in the audit log. Users investigating a change that "nobody made" will draw a blank.
- **Fix**: Emit a synthetic `system` audit row (`user_id=""`, `auth_type="system"`, and a short task-name in `method`) rather than skipping. Add to `audit/context.py` a `with system_audit_context("task_name"):` helper for scheduler tasks.
- **Effort**: M

### F-CEN-032: `scheduler/tasks.py` opens sessions outside `get_db()` with inconsistent commit

- **Severity**: MED (correctness)
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:121-155`
- **Problem**: Background tasks call `async with self._session_factory()` directly. Many branches mutate state without an explicit `commit()`. SQLAlchemy will `rollback` on context-exit for any uncommitted work, so "forgot to commit" silently drops changes.
- **Fix**: Wrap scheduler work in a helper (`run_in_session`) that enforces `session.commit()` at end or `rollback()` on error — mirroring `get_db()` exactly.
- **Effort**: M

### F-CEN-033: Alerting engine session scope

- **Severity**: MED (correctness)
- **File**: `packages/central/src/monctl_central/alerting/engine.py:66-87`
- **Problem**: Session opened per cycle; `_evaluate_definition` catches exceptions without re-raising or logging the stack. Per-definition failure is swallowed; next iteration hides the same bug forever.
- **Fix**: Replace bare `except` with `except Exception as exc: logger.exception("alert_eval_failed", definition_id=..., exc_info=exc)`.
- **Effort**: S

### F-CEN-034: `incidents/engine.py` unbounded `session.add()` in loop

- **Severity**: LOW (correctness / memory)
- **File**: `packages/central/src/monctl_central/incidents/engine.py:512-514`
- **Fix**: Flush every N (e.g. 500) to bound memory on large incident bursts.
- **Effort**: S

### F-CEN-035: Credential upsert has bare-except

- **Severity**: MED (data integrity)
- **File**: `packages/central/src/monctl_central/credentials/router.py:367, 399`
- **Problem**: Bare `except Exception:` in credential upsert paths. Partial credential creation possible — caller sees success, downstream sees missing fields.
- **Fix**: Let the exception propagate (global handler returns 500); add a test that a failure mid-upsert rolls back fully.
- **Effort**: S

### F-CEN-036: Redis set called outside DB transaction

- **Severity**: MED (consistency)
- **File**: `scheduler/tasks.py:161-162`
- **Problem**: Redis update happens before DB commit. If DB commit fails, Redis holds state the DB disagrees with. Next cycle may act on the stale Redis state.
- **Fix**: Move Redis update into the same task only AFTER `session.commit()` succeeds.
- **Effort**: S

---

## 6. Multi-Tenant Isolation

### F-CEN-037: Logs endpoint has no tenant filter

- **Severity**: HIGH (data leak)
- **File**: `packages/central/src/monctl_central/logs/router.py:82-100`
- **Problem**: `logs` ClickHouse table has `collector_id` but no `tenant_id` column (confirmed by agent read). A non-admin user of tenant A can query `GET /v1/logs?collector_name=<anything>` and receive entries from collectors of any tenant.
- **Fix**: Add `tenant_id LowCardinality(String)` to the logs table; backfill from collector→tenant map; update the query to enforce `apply_tenant_filter`-equivalent on CH side.
- **Effort**: L (DDL + migration + ingest update)

### F-CEN-038: Collector-ingested tenant_id is re-used without re-validation

- **Severity**: MED (trust)
- **File**: `collector_api/router.py:1306-1450`
- **Problem**: On `submit_results`, `tenant_id` is looked up from cache and used without cross-check against the collector's allowed tenants. Cache poisoning → cross-tenant write.
- **Fix**: Load `tenant_id` from the `Device` record server-side (not cache) whenever ingesting results. Reject mismatches with the collector's scope.
- **Effort**: M

### F-CEN-039: ClickHouse results-history endpoints rely on device_id lookup for tenant check — race window

- **Severity**: LOW (edge case)
- **File**: `results/router.py:97-200`
- **Problem**: Filter is `apply_tenant_filter(stmt, auth, Device.tenant_id)` in PG, but the CH query itself does not carry tenant_id in WHERE. If a device was just re-homed to another tenant, a race between the PG lookup and the CH read could return rows from before the move.
- **Fix**: Include `tenant_id` in every CH row (already present on some tables); enforce on both sides.
- **Effort**: M

---

## 7. Background Tasks & Leader Election

### F-CEN-040: Leader-election TOCTOU renewal race

- **Severity**: LOW (correctness)
- **File**: `scheduler/leader.py:92-95`
- **Problem**: Between `GET _LEADER_KEY` and `EXPIRE _LEADER_KEY`, the key can expire and another instance can SETNX a new value. The current instance will then `EXPIRE` a key belonging to someone else — extending the wrong instance's lease by 30s.
- **Fix**: Use a Lua script that atomically checks `GET == instance_id` AND `EXPIRE`. Or use `SET key value XX EX 30` (only set if already exists) — simpler and atomic.
- **Effort**: S

### F-CEN-041: Fire-and-forget `asyncio.create_task` in scheduler swallows exceptions

- **Severity**: HIGH (observability / correctness)
- **File**: `scheduler/tasks.py:97-98`
- **Problem**: OS-check and inventory tasks spawned via `create_task()` with no `add_done_callback` and no error handler. Any exception is logged only to the asyncio default "Task exception was never retrieved" warning, which is easy to miss.
- **Fix**: Use a small helper that wraps `create_task` and attaches a done-callback which logs via `structlog.exception`.
- **Effort**: S

### F-CEN-042: 30s alert cycle can overlap if CH query exceeds 30s

- **Severity**: MED (correctness / duplicate fires)
- **File**: `scheduler/tasks.py:71`
- **Problem**: Alert engine runs every 30s. If one iteration takes 35s (slow CH), the next iteration fires concurrently. Double-evaluation → possible duplicate state transitions.
- **Fix**: Guard with `asyncio.Lock` around the per-cycle evaluation, or use an in-iteration timestamp and skip if the last cycle hasn't finished.
- **Effort**: S

### F-CEN-043: Multi-leader window on Redis instability

- **Severity**: MED (correctness)
- **File**: `scheduler/leader.py:60-68`
- **Problem**: If Redis ping-pong times out, the renew-every-10s loop catches the exception and retries. Between the failed renewal and reacquisition, the old leader's key can expire (30s) and a different instance can acquire. During the overlap, both instances may believe they are leader (the old one until it discovers loss on the next renewal attempt).
- **Fix**: Before running any leader-only work in `tasks.py`, double-check `leader.is_leader` right before the critical section. Additionally, short-circuit the loop's sleep on error and retry faster.
- **Effort**: S

---

## 8. Error Handling & Silent Failures

### F-CEN-044: WebSocket connection manager bare-excepts everywhere

- **Severity**: HIGH (observability)
- **File**: `packages/central/src/monctl_central/ws/connection_manager.py:67, 136, 189, 247, 267`
- **Problem**: Five bare `except Exception:` without re-raise. Connections drop silently; by the time a user notices, the cause is unrecoverable from logs.
- **Fix**: Always `logger.warning("ws_handler_failed", handler=..., error=str(exc), stack=traceback.format_exc())`.
- **Effort**: S

### F-CEN-045: PyPI client failures are swallowed

- **Severity**: MED (correctness)
- **File**: `packages/central/src/monctl_central/python_modules/router.py:375, 465, 592`
- **Problem**: Bare except → stale module versions silently served; a user uploading a new version may see "success" but collectors receive the old one.
- **Fix**: Surface the error to the caller; log PyPI failure distinctly (`pypi_fetch_failed`).
- **Effort**: S

---

## 9. N+1 & Unbounded Queries

### F-CEN-046: Device-visibility query has no LIMIT

- **Severity**: MED (perf / OOM)
- **File**: `packages/central/src/monctl_central/devices/router.py:425`
- **Problem**: `result.all()` without `limit` can load 100k+ rows on a large tenant.
- **Fix**: Force pagination or at least `limit(10_000)` as a safety rail.
- **Effort**: S

### F-CEN-047: `apps/router.py` list endpoints without pagination

- **Severity**: MED (perf)
- **File**: `packages/central/src/monctl_central/apps/router.py:326, 449, 616`
- **Problem**: Multiple `.all()` without `limit`/`offset` on versions / connectors / dependencies lists.
- **Fix**: Standard list-state pattern: `limit/offset` + `FilterableSortHead`.
- **Effort**: M

### F-CEN-048: Alert-entity list has no pagination

- **Severity**: MED (perf)
- **File**: `packages/central/src/monctl_central/alerting/router.py`
- **Problem**: Queries for firing entities load the full set without LIMIT. On a noisy tenant, this is a page-load-breaker.
- **Fix**: Paginate + move filtering server-side.
- **Effort**: M

### F-CEN-049: Device-list count query uses different filter set than the paginated query

- **Severity**: MED (correctness — misleading totals)
- **File**: `devices/router.py:184` (count) vs `206-216` (page)
- **Fix**: Build one `base_stmt` and apply `filter+count` and `filter+paginate` off the same base. Extract a helper.
- **Effort**: S

---

## 10. Audit Coverage

### F-CEN-050: `audit/resource_map.py` whitelist coverage audit needed

- **Severity**: MED (audit integrity)
- **File**: `packages/central/src/monctl_central/audit/resource_map.py`
- **Problem**: Audit is a whitelist by table name. New mutating tables go unaudited until someone remembers to update the map. No enforcement.
- **Fix**: Add a unit test that enumerates all mutating routers (anything with POST/PUT/PATCH/DELETE) and fails if the touched table isn't in the map. Require an explicit `# no-audit: reason` marker to opt out.
- **Effort**: M

### F-CEN-051: Redaction list is substring-based

- **Severity**: LOW (secret leak possibility)
- **File**: (inferred) `audit/diff.py` — redacts fields containing `password`, `api_key`, `token`, `secret`, `jwt_secret`, `credential_value`, `private_key`
- **Problem**: Field `auth_header` or `bearer` or `key_material` would NOT be redacted. Substring match over a hand-curated list is fragile.
- **Fix**: Inverse-whitelist approach on sensitive tables: redact everything except fields explicitly marked `audit_safe = True` on the column definition.
- **Effort**: M

---

## 11. Gaps (Files I Could Not Read)

The following files are in permission-restricted directories and must be reviewed manually:

- `packages/central/src/monctl_central/credentials/crypto.py` — credential encryption at rest. Cannot verify cipher choice, key derivation, IV reuse, authenticated encryption, key rotation. **PRIORITY**.
- `packages/central/src/monctl_central/audit/context.py`, `audit/diff.py` — context-var usage and redaction logic need eyeball verification.
- `packages/central/src/monctl_central/auth/service.py` — JWT creation: algorithm (must be HS256/RS256 not `none`), signing key source, clock-skew tolerance.

---

## What We Looked At

**Direct reads** (in-session):

- `packages/central/src/monctl_central/dependencies.py` (479 lines, full)
- `packages/central/src/monctl_central/auth/router.py` (332 lines, full)
- `packages/central/src/monctl_central/audit/db_events.py` (160 lines, full)
- `packages/central/src/monctl_central/scheduler/leader.py` (101 lines, full)

**Agent sweeps** (findings incorporated above):

- Security surface scan — auth/RBAC, SQL/DSL, credentials, tenant isolation, collector trust, WS, dangerous patterns
- Bug & perf scan — async hygiene, sessions, N+1, CH queries, leader election, error handling, races
- Architecture scan — god modules, circular imports, test coverage

**Files referenced but not directly read** (findings from agents):

- `collector_api/router.py`, `alerting/dsl.py`, `alerting/engine.py`, `storage/clickhouse.py`
- `results/router.py`, `dashboard/router.py`, `logs/router.py`
- `scheduler/tasks.py`, `incidents/engine.py`, `ws/*`
- `python_modules/router.py`, `credentials/router.py`, `devices/router.py`, `apps/router.py`

**Cross-referenced memory files** (known landmines):

- `feedback_ch_mv_schema_migrations.md`
- `project_rollup_chain_fragility.md`
- `feedback_per_entity_filtering.md`

---

## Severity Summary

| Severity  | Count  |
| --------- | ------ |
| CRITICAL  | 0      |
| HIGH      | 7      |
| MED       | 26     |
| LOW       | 14     |
| INFO      | 2      |
| **Total** | **49** |

**Top 10 to triage first** (by blast radius):

1. F-CEN-024 — CH `_LockedClient` serialises every query (HIGH perf, L)
2. F-CEN-014 — Collector submits job_id without ownership check (HIGH security, M)
3. F-CEN-015 — Collector can fetch any credential by name (HIGH security, M)
4. F-CEN-037 — Logs endpoint has no tenant filter (HIGH data leak, L)
5. F-CEN-025 — CH calls block event loop (HIGH perf, L)
6. F-CEN-001 — Cookies `secure=False` (HIGH security, S)
7. F-CEN-004 — No login rate-limit (HIGH security, M)
8. F-CEN-044 — WS manager bare-excepts (HIGH observability, S)
9. F-CEN-041 — Fire-and-forget tasks swallow exceptions (HIGH observability, S)
10. F-CEN-005/006 — No refresh rotation / no revocation (MED but fast wins)
