# Performance Findings — Review #2 (2026-04-30)

## Summary

- 31 findings: 6 HIGH / 13 MED / 9 LOW / 3 INFO
- Async pool work (#128/#130) is solid — zero remaining sync `client.query` call sites in routers were found outside `to_thread`. Bucketing helpers (`project_metrics_history_bucketing`) are correctly applied to host/container/db-size history.
- The largest hot spots are **alerting engine serial fan-out** (definitions × tiers × a freshness query), **dashboard N+1 device/definition lookups**, and the **installer's connection-per-call SSH layer** which serializes a 4-central + 4-worker deploy.
- Two `_history` endpoints sneak past server-side bucketing (`/ingestion-rate-history`, also raw `_get_client().query` paths in `apps/router.py` discovery + alert metrics that scan whole `config`/`performance` with no time bound).
- Hash-ring is rebuilt from scratch **per assignment** in both rebalancer and the request-time `/jobs` partitioner — cheap per call but multiplies by N assignments per request.

---

## Findings

### P-CEN-001 — Alert engine evaluates definitions sequentially; each def fires K+2 CH queries serially
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/alerting/engine.py:77-87, 226-235, 766-768`
- **Description**: `evaluate_all` iterates definitions in a Python `for` loop. Each definition fires one ClickHouse query per non-healthy tier, optionally one for the healthy tier, and one freshness query. With ~50 definitions × 2 tiers each, the cycle is 150+ serial CH round-trips. Pool size is 8 — most slots stay idle. A slow ClickHouse cycle can spill past the 30s scheduler interval and trigger the `_alert_cycle_lock.locked() → skip` path.
- **Fix sketch**: `asyncio.gather` definition evaluations in chunks (chunk size ~8 to match pool). Definitions are independent; only the final `await session.commit()` needs serialization. For per-tier work inside one def, also gather the per-tier `_execute_compiled_query` calls + the freshness query.

### P-CEN-002 — Dashboard `_alert_summary` and `_device_health` issue N+1 per-row `db.get` calls
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/dashboard/router.py:84-97, 167-176`
- **Description**: After fetching the top-10 firing entities, lines 85-87 do `await db.get(AlertDefinition, ...)` and `await db.get(Device, ...)` **inside a Python for-loop** — 20 round-trips for one widget. `_device_health` worst-10 does the same. Dashboard refreshes every 15s, so this is ≥30 PG queries/15s/active operator just for this endpoint.
- **Fix sketch**: Single batch fetch — `select(AlertDefinition).where(AlertDefinition.id.in_(def_ids))` and `select(Device).where(Device.id.in_(device_ids))`, build a dict, then iterate.

### P-CEN-003 — `/api/v1/jobs` discovery-injection has nested N+1 across packs and pack apps
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/collector_api/router.py:876-971`
- **Description**: For **every** flagged device, the code does: `db.get(Device)` + per-credential `select(Credential.name)` + per-`pack_uid` `select(Pack)` + per-pack `select(App).where(pack_id=...)` + per-pack-app `select(AppVersion).where(is_latest)`. With ~50 collectors polling `/jobs` every 60s and N flagged devices each with 5+ pack apps, that's 5+ PG queries per flagged-device per `/jobs` call.
- **Fix sketch**: Pre-load all `Device` rows for `discovery_device_ids` in one `WHERE id.in_(...)` query before the for-loop. Pre-load `Pack` + `App` + latest `AppVersion` rows once for all `auto_assign_packs` referenced across the flagged set.

### P-CEN-004 — Per-assignment hash-ring rebuild in `/jobs` and rebalancer
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/collector_api/router.py:301-335` (called at 550); `scheduler/tasks.py:1672-1701` (called at 1600)
- **Description**: `_weighted_job_owner` rebuilds the entire vnode ring (≥100 vnodes per host × N hosts × 100ns per SHA256 hash + bisect.insert at O(n)) for **every assignment**. For a group with 20k unpinned assignments and 4 collectors that's 20k × 400 = 8M SHA256 ops + O(n²) inserts on every `/jobs` request.
- **Fix sketch**: Build the ring once per call (outside the comprehension), pass `(ring_hashes, ring_nodes)` to a `_lookup_owner(key, ring_hashes, ring_nodes)` helper. Replace the O(n²) `insert` with a single `sort` after collecting all (h, hostname) pairs.

### P-INST-005 — Installer `deploy()` iterates hosts serially; SSH opens a fresh connection per call
- **Severity**: HIGH
- **File**: `packages/installer/src/monctl_installer/commands/deploy.py:74-104`; `remote/ssh.py:51-97`
- **Description**: `deploy()` walks `for host in inv.hosts:` with no parallelism even though `SSHRunner.run_many` exists. Each host does ~5 projects × 5+ SCP ops + `docker compose up -d` (10-30s). For an 8-host cluster, expected wall time is ~5–10 minutes vs ~60s with parallel host fan-out. Worse, every `runner.run()` and `runner.put()` reopens the SSH+SFTP connection (no persistent session), adding ~200ms TCP+auth overhead × 50+ ops/host. `upgrade.py:108-111` has the same bug.
- **Fix sketch**: (1) Cache one paramiko `SSHClient` per host inside `SSHRunner` (close on exit). (2) Replace `for host` with `run_many` + a per-host `_apply_host()` callable so all hosts deploy in parallel. Keep central deploys serialized for the leader-election handoff, but workers and clickhouse hosts can run in parallel.

### P-CEN-006 — `_sync_alert_instances` runs 2N PG queries (N = enabled definitions) on the leader every 5 min
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:481-498`
- **Description**: For each enabled `AlertDefinition`, the code runs `select(AppAssignment).where(app_id=def.app_id)` + `select(AlertEntity.assignment_id).where(definition_id=def.id)` — 2 round-trips per definition. With ~50 definitions, that's 100 PG queries per sync cycle.
- **Fix sketch**: Single SQL query that produces missing `(definition_id, assignment_id, device_id)` triples to insert: `INSERT INTO alert_entities ... SELECT defn.id, ass.id, ass.device_id FROM alert_definitions defn JOIN app_assignments ass ON ass.app_id = defn.app_id WHERE defn.enabled AND ass.enabled AND NOT EXISTS (SELECT 1 FROM alert_entities WHERE definition_id = defn.id AND assignment_id = ass.id)`.

### P-CEN-007 — Alert metrics discovery scans whole `config` / `performance` tables with no time bound
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/apps/router.py:2231-2238` (config), 2323-2335 (performance), 2345-2350 (config keys)
- **Description**: `SELECT DISTINCT config_key FROM config WHERE app_id = X` and `SELECT DISTINCT arrayJoin(metric_names) FROM performance WHERE app_id = X` are full-table-scan-for-app-id. The `performance` table is unbounded over time (90d retention typically) — every UI load of the alert-metrics editor scans the whole partition history of that app.
- **Fix sketch**: Add `executed_at >= now() - interval 7 day`. New metrics surface within 7d; old ones disappear from the editor — that's an acceptable tradeoff vs scanning 90d of `performance`.

### P-CEN-008 — `/v1/system/ingestion-rate-history` does not bucket; LIMIT silently truncates
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/system/router.py:2241-2248`; `storage/clickhouse.py:3284-3314`
- **Description**: Per memory `feedback_per_row_multiplier_hits_limit`, history endpoints with N rows/sample need server-side `toStartOfInterval`. `db_size_history`, `host_metrics_history`, `container_metrics_history` use `_bucket_step_for_range` correctly, but `query_ingestion_rate_history` has no `step_seconds` parameter. With 7 ingestion tables × 5-min sampling × 7 days = 14k rows; LIMIT 10000 silently drops the oldest. Beyond 30d the chart stops at the LIMIT cutoff with no error.
- **Fix sketch**: Mirror the `db_size_history` pattern: accept `step_seconds`, when set wrap query with `toStartOfInterval(timestamp, INTERVAL {step:UInt32} SECOND)` + `GROUP BY` + aggregate `avg(rows_per_second)`. Pass `_bucket_step_for_range(...)` from the router.

### P-CEN-009 — `_count_all` ingestion sampler runs 7 sequential CH queries inside one `to_thread`
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:1366-1381`
- **Description**: 7 tables × per-table `count_rows_since(tbl, 300)` serialized inside `_run_sync`. ~3.5s every 5 minutes which holds a pool slot the whole time.
- **Fix sketch**: One query with `UNION ALL` per table or `multiIf`. Or `asyncio.gather(*[asyncio.to_thread(self._ch.count_rows_since, t, 300) for t in tables])`.

### P-CEN-010 — AutomationEngine cron path: per-device serial CH cooldown lookup
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/automations/engine.py:208-228`
- **Description**: For each cron automation × each resolved device, the code calls `await asyncio.to_thread(self._ch.get_last_rba_run_time, automation_id, device_id)` inside two nested loops. With 5 cron automations × 200 devices that's 1000 serialized CH queries every cron eval cycle (30s).
- **Fix sketch**: Add `get_last_rba_run_times_batch(automation_id, device_ids: list[str])` that returns `{device_id: last_run_dt}` in one query (`GROUP BY device_id`). Call once per automation outside the device loop.

### P-CEN-011 — Audit buffer flush rate caps at 100 rows/sec; high-churn periods drop
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/audit/buffer.py:17-67`
- **Description**: `_FLUSH_BATCH=500` × `_FLUSH_INTERVAL_SEC=5.0` = 100 rows/s sustained. A bulk-import or template apply that fires 5k+ mutations in a few seconds will fill `_MAX_BUFFER=5000` and start dropping. Drop also does `self._rows = self._rows[drop:]` which is O(n) Python list copy. ClickHouse async_insert can handle 10k+ rows/s.
- **Fix sketch**: (1) Bump batch to 2000 and interval to 1.0s (10x throughput). (2) Replace `list[drop:]` slice with a `collections.deque(maxlen=_MAX_BUFFER)` so overflow drops are O(1).

### P-CEN-012 — `docker_push` ingest serializes 4 ClickHouse inserts that could `gather`
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/collector_api/docker_push.py:182-238`
- **Description**: Per push, the code awaits `insert_container_metrics`, then `insert_host_metrics`, then `insert(logs)` sequentially via `to_thread`. With 8 hosts × 15s push interval = ~32 inserts/min plus log lines. Each `to_thread` round-trip is ~5-20ms; sequential ~60ms vs parallel ~20ms.
- **Fix sketch**: Wrap the three inserts in `asyncio.gather(...)` — they're independent CH inserts on different tables.

### P-CEN-013 — System health top-bar `/health/status` re-evaluation lacks a lock
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/system/router.py:1853-1986`
- **Description**: `_last_health_status` is a global module variable. When the cache is stale, two concurrent admin requests both observe `stale=True` and both call `_compute_overall_status` (a 12-task `asyncio.gather` including a 15s ClickHouse query). With 4 central nodes each having their own globals + admin browser tabs polling, fan-out is amplified.
- **Fix sketch**: Wrap the refresh in a module-level `asyncio.Lock`. Inside the lock, re-check staleness so the second waiter returns the just-refreshed cache. Optional: store cache in Redis with a TTL so all 4 central nodes share it.

### P-CEN-014 — `_check_docker_infrastructure` loops through pushed hosts with serial Redis GETs
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/system/router.py:1646-1672`; `docker_infra/router.py:144-178`
- **Description**: For each pushed worker host, sequential `await get_docker_push(label, "stats")` and `await get_docker_push(label, "system")` — 2 Redis round-trips per host serialized. With 6 worker hosts, 12 sequential awaits.
- **Fix sketch**: Use a Redis pipeline (already shown working in `cache.py:get_previous_counters_batch`). Or `asyncio.gather` the per-host `get_docker_push` calls.

### P-CEN-015 — `_finalize_eligibility_runs` runs serial count-per-run CH queries
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:1715-1749`
- **Description**: For each running eligibility run, the code fires a separate `SELECT countIf(...) FROM eligibility_results WHERE run_id = X`. With 5+ active discovery runs that's 5 sequential queries per cycle.
- **Fix sketch**: One `SELECT run_id, countIf(eligible != 2) AS done, countIf(eligible = 1) AS elig, ... FROM eligibility_results WHERE run_id IN (...) GROUP BY run_id`.

### P-CEN-016 — Scheduler tick runs all heavy evaluators sequentially
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:84-99`
- **Description**: On the leader, every 30s tick runs `_health_check` → `_evaluate_system_health` → `_evaluate_alerts` → `_evaluate_incidents` → `_evaluate_cron_automations` → `_run_rollups` serially. A 25s alert eval cycle + 5s rollup = pushed past the 30s budget.
- **Fix sketch**: Split into two coroutine groups: serial `[alerts → incidents]` (incidents reads AlertEntity from the alert eval write), then `gather(cron, system_health_check, rollup_check)`.

### P-CEN-017 — Several `useQuery` hooks bypass the `POLL_LIST/POLL_DETAIL` document-hidden guard
- **Severity**: MED
- **File**: `packages/central/frontend/src/api/hooks.ts:752, 2479, 2504, 3102, 3141, 3190, 3222, 3266, 3665, 3674, 3684, 3700, 3712, 3951, 3961, 3996, 4024, 4102, 4131, 4146` (plus 8 more)
- **Description**: ~30 hooks use raw numeric `refetchInterval: 5_000` or `30_000` instead of the `POLL_LIST` / `POLL_DETAIL` lambda. React Query v5 pauses on hidden tabs by default — if that default flips in a minor upgrade, every numeric-interval hook keeps polling in the background. Includes hot ones at 3s (`useUpgradeJob`), 5s (`useEligibilityRuns`, `useDockerContainerLogs`, `useUpgradeJobs`).
- **Fix sketch**: Add `POLL_FAST` (5s), `POLL_REALTIME` (3s) helpers using the same `document.hidden` pattern. Replace the raw numeric refetchIntervals.

### P-CEN-018 — FlexTable rebuilds every row and column on every parent re-render
- **Severity**: MED
- **File**: `packages/central/frontend/src/components/FlexTable/FlexTable.tsx:149-169`
- **Description**: `<TableBody>` maps `rows.map` and inside that maps `orderedVisibleColumns.map` calling `col.cell(row)` directly — no `React.memo` on the row, no memoization of the rendered cell. Combined with `refetchInterval: POLL_LIST=30s` returning fresh data each cycle, the whole table re-renders every 30s. For lists with 200+ rows × 10 columns = 2000 cell function calls every refresh.
- **Fix sketch**: Wrap the row component (`<TableRow key={...}>...`) in `React.memo` keyed on `(row, columnsKey)` so unchanged rows skip render.

### P-CEN-019 — Alert engine builds entity-id lookup dict O(N) per row per definition
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/alerting/engine.py:653-682`
- **Description**: `_evaluate_config_changed` constructs `inst_lookup` then iterates `for row in rows: for (aid, ek), inst in inst_lookup.items(): if ek == entity_key or ek == "":` — a linear scan over `inst_lookup` for every row. Quadratic O(rows × instances). For a definition with 1000 entities × 200 changed rows = 200k iterations.
- **Fix sketch**: Build a second lookup keyed on `entity_key` only: `by_entity_key: dict[str, list[AlertEntity]]`. Single dict lookup per row.

### P-COL-020 — walk_multi safety cap is 500 iterations + 20k rows; on a chassis with 10k interfaces this caps mid-poll
- **Severity**: MED
- **File**: `connectors/snmp.py:258, 297-298`
- **Description**: `walk_multi` exits at `total_rows >= 20000` or 500 PDU iterations. For ifTable with 8 columns × 10k interfaces = 80k rows; for entity_mib_inventory with hundreds of entities × 12 columns also approaches the cap. When the cap fires, the result is truncated silently (no error), and downstream interface-rate calculations are corrupted.
- **Fix sketch**: Make the row cap configurable per poller (`context.config.get("max_rows", 50000)`). Log a warning when truncation occurs.

### P-CEN-021 — Cache `get_previous_counters` (single, non-batch) still exists
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/cache.py:341-387`
- **Description**: Single-interface fallback path does a one-OID-at-a-time CH query on cache miss. The batch version exists and is used by the perf hot path. No remaining single-call call sites in production code, but the function exists.
- **Fix sketch**: Mark as deprecated or delete; redirect to `get_previous_counters_batch([interface_id])`.

### P-CEN-022 — `query_audit_mutations` count + data are sequential CH queries; could `gather`
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/storage/clickhouse.py:3367-3383`
- **Description**: `query_audit_mutations` runs the count query then the data query sequentially in the same blocking thread. Both share the same `WHERE`.
- **Fix sketch**: Gather them in `to_thread` outside, or use ClickHouse `WITH TOTALS` extension.

### P-CEN-023 — Audit middleware runs `BaseHTTPMiddleware` (Starlette) — known per-request overhead
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/audit/middleware.py:33-58`
- **Description**: `BaseHTTPMiddleware` adds a Python coroutine + thread-pool overhead per request. Starlette docs explicitly warn against it for high-perf paths. At ~50 req/s/central node this adds measurable latency.
- **Fix sketch**: Convert to plain ASGI middleware (`async def __call__(self, scope, receive, send)`) — saves ~0.5ms per request and a thread-pool slot.

### P-CEN-024 — Health check `_check_postgresql` runs 4 PG queries serially
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:235-273`
- **Description**: 4 sequential `await db.execute(text(...))` calls (replication lag, cache hit, etc.). Could `gather` them on a single connection. Saves ~10-30ms per health check (every 30s).
- **Fix sketch**: `asyncio.gather` independent metric queries on a single AsyncSession.

### P-WEB-025 — `staleTime: 10_000` + `refetchOnWindowFocus: true` causes refetch storm on tab return
- **Severity**: LOW
- **File**: `packages/central/frontend/src/main.tsx:13-14`
- **Description**: Coming back to a backgrounded tab triggers refetch on every active query whose data is older than 10s — for a user with the device-detail page open (~6 active queries), that's 6 simultaneous requests on tab refocus.
- **Fix sketch**: Either bump `staleTime` to 30s (matching `POLL_LIST`) or disable `refetchOnWindowFocus` for known-polling queries.

### P-CEN-026 — `_check_collectors` builds a Python dict lookup of weights per row
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/system/router.py:1290-1357`
- **Description**: For each collector row, `peer_states.get("_system_resources")` plus several CPU/mem/threshold computations. With 200+ collectors, the per-row capacity computation runs ~30 ops × 200 = 6000 ops every 30s. Negligible at current scale.
- **Fix sketch**: Cache `peer_states.get("_system_resources")` once per collector — already in memory but JSONB deserialization happens on each access.

### P-CEN-027 — `_resolve_device_credential_name` re-iterates `app.connector_bindings` per row
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/apps/router.py:731-752` (called for every row at line 823)
- **Description**: For each assignment in `list_assignments`, walks `app.connector_bindings`. With 500 assignments × 3 bindings each = 1500 iterations to render a single page.
- **Fix sketch**: Pre-compute `app_id → list[connector_type]` once before the response-builder loop.

### P-INST-028 — Installer SSH `_connect` does no host-key caching across calls
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/remote/ssh.py:99-117`
- **Description**: Every `run()` and `put()` instantiates a fresh `paramiko.SSHClient` and calls `connect()` — TCP handshake + auth ~200ms each. A deploy is doing 50+ ops × 200ms = 10s of pure auth overhead per host.
- **Fix sketch**: Cache one client per host inside `SSHRunner` (lazy-init, close on `__exit__`/explicit `.close()`).

### P-CEN-029 — Connector `_make_client` doesn't multi-host load-balance
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/storage/clickhouse.py:1573-1587`
- **Description**: `_make_client` always uses `self._hosts[0]` — every pool slot connects to the same CH replica. With 2 ClickHouse nodes, all read queries hit one (the other is idle).
- **Fix sketch**: Round-robin across `self._hosts` per slot creation: `host=self._hosts[slot_idx % len(self._hosts)]`.

### P-CEN-030 — Infra status endpoint `_check_alerts_standalone` opens its own DB session
- **Severity**: INFO
- **File**: `packages/central/src/monctl_central/system/router.py:1745-1763`
- **Description**: Each `_*_standalone` health check opens its own `factory()` AsyncSession — that's 3 extra PG sessions per `/health` call.
- **Fix sketch**: Take the request session and pass it explicitly to the standalone wrappers.

### P-WEB-031 — `useUpgradeJob` polls at 3s with no automatic stop on `done` state
- **Severity**: INFO
- **File**: `packages/central/frontend/src/api/hooks.ts:3955-3962`
- **Description**: An upgrade job that completes is still polled at 3s indefinitely as long as the page is open.
- **Fix sketch**: `refetchInterval: (q) => q.state.data?.status === "completed" ? false : 3000`.

### P-COL-032 — Connector v1.4.4 walk_multi has no per-column cap, only global cap
- **Severity**: INFO
- **File**: `connectors/snmp.py:255, 297`
- **Description**: `total_rows >= 20000` is a global cap across all OIDs. If one OID has 19k rows, the others get 1k between them and silently truncate.
- **Fix sketch**: Track per-base row count and drop a base from `active` when its individual count reaches `max_per_base` (default 10000); keep the global as a safety net.
