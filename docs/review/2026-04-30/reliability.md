# Reliability Findings — Review #2 (2026-04-30)

## Summary

- 30 findings; 6 HIGH / 16 MED / 8 LOW
- The serious risks cluster around **WS push happening before DB commit** (R-CEN-001), **buffer-overflow data loss in the CH ingest path** (R-CEN-003), **OS-install lease loss without cancellation** (R-CEN-006), and **collector blocking calls inside async WS handlers** (R-COL-002). Several pre-existing F-CEN-* items from review #1 have been fixed in #2 (leader Lua, WS jitter, alert cycle lock, fresh-assignments per-entity, scheduler done-callback) but the alert/incident engine introduced new fire-and-forget paths in `automations/engine.py` (3 sites) and a real ordering bug in `connectors/router.py::set_latest_version`. The OS-upgrade resume flow looks well-designed but has two subtle holes (instance_id fallback `"?"`, lease loss without driver halt). Forwarder dedup window (900s) is comfortably longer than max retry backoff (300s) — that one's solid.

## Findings

### R-CEN-001 — `set_latest_version` notifies WS before DB commit
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/connectors/router.py:498-525`
**Description**: After `db.execute(update(Collector).values(config_version=...))` the code calls `await db.flush()` and then `ws_manager.notify_config_reload(bumped_ids)` — all *before* the implicit `get_db` commit. If the commit fails, every collector that received the WS push will reload its job list, reading PG state the central just rolled back. Same shape as F-CEN-036 but fleet-wide blast radius.
**Fix sketch**: Move `notify_config_reload` out of the request body. Either commit explicitly inside the handler before notifying, or queue the notify via Redis pub/sub fired from a SQLAlchemy `after_commit` event listener.

### R-CEN-002 — CH write-buffer silently drops every overflowing batch
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/storage/ch_buffer.py:99-111`
**Description**: When an insert fails and the re-buffered total exceeds `_MAX_BUFFER_ROWS=10_000`, the code logs a warning and **falls through without re-buffering anything**. The entire failed batch (`rows`) is silently dropped. Under sustained CH flapping this can drop hundreds of thousands of metric rows per minute with only a debug-level warning.
**Fix sketch**: In the else branch, set `self._buffers[table] = (rows + existing)[-_MAX_BUFFER_ROWS:]` to keep newest rows up to the cap, and log `dropped=len(rows)+len(existing)-_MAX_BUFFER_ROWS`. Or fail loud (re-raise) and rely on upstream backpressure.

### R-CEN-003 — Automations engine spawns 3 fire-and-forget tasks without done-callback
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/automations/engine.py:144-154, 230-240, 293-302`
**Description**: `on_incident_transition`, `evaluate_cron_triggers`, and `trigger_manual` all spawn `asyncio.create_task(self._execute_automation(...))` with no done-callback. F-CEN-041 fixed this for the scheduler tick but the automation engine — which runs *every 30s* and fans out one task per (automation × device) — was missed.
**Fix sketch**: Reuse `_log_task_exception` from `scheduler/tasks.py` (lift to `monctl_central/utils.py`) and attach via `task.add_done_callback(_log_task_exception)` at every site.

### R-CEN-004 — `instance_id` fallback in OS-install lease defaults to `"?"` shared across nodes
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/upgrades/os_service.py:428`
**Description**: `instance_id = getattr(settings, "instance_id", "?")` — if `settings.instance_id` is empty every central node uses the literal `"?"`. The Lua compare in `_refresh_driver_lease` then succeeds for *any* node — two centrals can both hold the lease, both refresh it, both run `execute_os_install_job` on the same job.
**Fix sketch**: Fail loud at startup if `settings.instance_id` is empty; remove the `"?"` fallback. The `main.py` lifespan already generates one if missing.

### R-CEN-005 — OS-install driver continues working after losing its lease
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/upgrades/os_service.py:382-396`
**Description**: When `_refresh_driver_lease` discovers the lease is taken by another central, it logs and returns. **The outer `execute_os_install_job` task is not cancelled or signalled** — it keeps running steps on a job whose lease is now held by a different leader.
**Fix sketch**: Pass a `cancel_event: asyncio.Event` from `execute_os_install_job` into `_refresh_driver_lease`; `set()` it on lease loss. The driver loop in `_run_steps` should check the event between steps and exit cleanly.

### R-CEN-006 — Connection-manager.connect() race replaces in-flight reconnect
**Severity**: MED
**File**: `packages/central/src/monctl_central/ws/connection_manager.py:188-206`
**Description**: `connect()` checks `if collector_id in self._connections`, then `await old.stop_keepalive()` and `await old.websocket.close(...)` — both yield. Two concurrent reconnects from the same collector_id both observe the same `old`, both close it, both register their new connection. The first WS is **left open** but unreferenced — keepalive task is gone, but the underlying TCP socket and aiohttp session leak.
**Fix sketch**: Wrap the connect critical section in an `asyncio.Lock` (per ConnectionManager). Or use atomic dict swap.

### R-CEN-007 — pubsub subscriber leaked across error reconnects
**Severity**: MED
**File**: `packages/central/src/monctl_central/ws/connection_manager.py:404-428`
**Description**: `_command_listener_loop` creates `pubsub = r.pubsub()` and subscribes inside the outer `try`. On any exception, it sleeps 2s and reenters the loop, where a fresh `r.pubsub()` is created without unsubscribing or closing the prior one. A flapping Redis connection accumulates orphaned subscribers.
**Fix sketch**: Either move pubsub creation outside the loop and `await pubsub.aclose()` in `finally`, or call `await pubsub.unsubscribe()` + `await pubsub.aclose()` inside the except block before retrying.

### R-CEN-008 — `cert_sync_task` has no done-callback
**Severity**: MED
**File**: `packages/central/src/monctl_central/main.py:539`
**Description**: Same pattern F-CEN-041 fixed for scheduler tasks but missed here. If the cert sync loop crashes, it dies silently and TLS certs never refresh.
**Fix sketch**: `cert_sync_task.add_done_callback(_log_task_exception)`.

### R-CEN-009 — WS shared-secret compared with `==` (timing leak, parallel to F-CEN-012)
**Severity**: MED
**File**: `packages/central/src/monctl_central/ws/auth.py:37`
**Description**: `if shared_secret and token == shared_secret and collector_id_hint:` — non-constant-time string compare on `MONCTL_COLLECTOR_API_KEY` over the WebSocket auth path. F-CEN-012 was scoped to HTTP basic in `dependencies.py`; this sibling site was missed.
**Fix sketch**: `import hmac; if shared_secret and hmac.compare_digest(token, shared_secret) and collector_id_hint:`.

### R-CEN-010 — Polling engine deadlines use wall-clock `time.time()`
**Severity**: MED
**File**: `packages/collector/src/monctl_collector/polling/engine.py:201, 206, 210, 250`
**Description**: All deadlines computed off `time.time()` (wall clock). NTP step on the collector host shifts every queued deadline. A backwards step makes every job re-fire instantly (storm against central).
**Fix sketch**: Use `time.monotonic()` for deadlines (relative scheduling); only convert to wall-clock for log lines / metrics.

### R-CEN-011 — LogShipper dedup timestamp only updates for dict log lines
**Severity**: MED
**File**: `packages/collector/src/monctl_collector/central/log_shipper.py:221-224`
**Description**: `self._last_timestamps[name] = last["timestamp"]` only fires when `last is dict`. Containers that emit raw-string log lines never advance their per-container cursor. Every shipper cycle re-ships the same 200 tail lines.
**Fix sketch**: For raw-string lines, parse the Docker timestamp prefix and feed it into `_last_timestamps[name]` even when `last` is a string.

### R-CEN-012 — Forwarder buffer cap drops sent rows preferentially over unsent
**Severity**: MED
**File**: `packages/collector/src/monctl_collector/cache/local_cache.py:455-471`
**Description**: `drop_oldest_results` deletes from `results ORDER BY created_at LIMIT N` with no `WHERE sent=0` filter. The oldest rows are usually `sent=1` rows that haven't been cleaned by the 24h cleanup yet. The buffer cap therefore evicts already-sent rows first, doing zero useful work to relieve actual unsent backlog.
**Fix sketch**: Two-pass — first try `DELETE FROM results WHERE sent=1 ORDER BY created_at LIMIT N`, then if still over cap, drop oldest unsent.

### R-CEN-013 — `_check_eligibility` silently passes unknown check types
**Severity**: MED
**File**: `packages/central/src/monctl_central/discovery/service.py:561-583`
**Description**: The loop has explicit handlers for `"exists"` and `"equals"`. Any other `check_type` value (typo in pack JSON like `"matches"` or `"contains"`) falls through both branches and the iteration continues — meaning the check is treated as **passing** by default. A pack author who shipped a `"contains"` check would auto-assign the app to every device.
**Fix sketch**: Add `else: logger.warning("eligibility_unknown_check_type", check_type=check_type, oid=oid); return False` (fail-closed).

### R-CEN-014 — `_check_eligibility` AttributeError if probe returns non-string
**Severity**: MED
**File**: `packages/central/src/monctl_central/discovery/service.py:577`
**Description**: `probe_value.lstrip(".")` assumes string. A SNMP value that decodes to bytes that survive the hex-prefix branch could still hit `lstrip` on a non-string, escaping back to the eligibility-run loop and failing for that device.
**Fix sketch**: `if not isinstance(probe_value, str): probe_value = str(probe_value); ...`.

### R-CEN-015 — WS handlers in collector use blocking `urllib.request` inside async coroutine
**Severity**: MED
**File**: `packages/collector/src/monctl_collector/central/ws_handlers.py:86-91, 100-111`
**Description**: `handle_docker_health` and `handle_docker_logs` call `urllib.request.urlopen(req, timeout=5)` — a synchronous blocking call inside an `async def`. The entire WS reader loop on the cache-node is blocked for up to 10s per call. A wedged sidecar blocks every other WS-routed operation.
**Fix sketch**: Replace with `await asyncio.to_thread(urllib.request.urlopen, ...)` or migrate to `aiohttp.ClientSession`.

### R-CEN-016 — `WebSocketClient._handle_message` swallows handler errors with class name only
**Severity**: LOW
**File**: `packages/collector/src/monctl_collector/central/ws_client.py:161-168`
**Description**: WS reply only carries `type(exc).__name__`. Operator looking at central UI sees `HANDLER_ERROR / KeyError` with no clue what the key was.
**Fix sketch**: Include a short hash of the exception message (`hashlib.sha256(str(exc).encode()).hexdigest()[:8]`) so operator can correlate UI to collector log line.

### R-CEN-017 — `_resume_orphaned_os_jobs` task error swallowed in done-callback
**Severity**: LOW
**File**: `packages/central/src/monctl_central/scheduler/tasks.py:1230-1244`
**Description**: `_clear_tracking` reads `t.exception()` and only logs at `warning` level. Real exceptions deserve `exception()` with stack trace.
**Fix sketch**: Reuse the shared `_log_task_exception` helper instead of the inline lambda; standardise.

### R-CEN-018 — Threshold-name uniqueness enforced only by DB constraint, no API-level pre-check
**Severity**: LOW
**File**: `packages/central/src/monctl_central/alerting/threshold_sync.py:89-103`
**Description**: With concurrent definition uploads, both can pass the in-memory check and try to insert. The DB UNIQUE constraint will reject one with `IntegrityError`, but the surrounding session rolls back the entire definition transaction.
**Fix sketch**: Catch `IntegrityError`, refresh `existing_vars`, retry once. Or centralise behind a single advisory lock.

### R-CEN-019 — Eligibility run finalize uses `_run_sync` per-iteration query inside thread
**Severity**: LOW
**File**: `packages/central/src/monctl_central/scheduler/tasks.py:1710-1754`
**Description**: One CH count query per running run. The inner loop holds a single CH client borrowed from the pool for the entire batch — blocks every other CH caller.
**Fix sketch**: Re-acquire the client per-run, or batch the count queries into one `WHERE run_id IN (...)` with `groupArrayIf`.

### R-CEN-020 — Daily rollup error path advances `_last_daily_rollup` only on hourly success
**Severity**: LOW
**File**: `packages/central/src/monctl_central/scheduler/tasks.py:618-634`
**Description**: If `_daily_rollup` fails, `_last_daily_rollup = now` is **not** set. Every 30s the leader re-runs the same expensive ALTER DELETE chain.
**Fix sketch**: Same pattern as hourly — set `_last_daily_rollup = now` in the except.

### R-CEN-021 — `_run_steps` re-entered from `advance_collector_job` shares session
**Severity**: LOW
**File**: `packages/central/src/monctl_central/upgrades/os_service.py:836-857`
**Description**: After the inner call returns, `await db.refresh(job, ["steps"])` re-fetches but the outer loop's `steps` variable is already iterated. If `_run_steps` mutates the same job, the outer view of `steps` is stale and may double-process or skip steps.
**Fix sketch**: After calling `_run_steps`, return immediately from `advance_collector_job`.

### R-COL-022 — Forwarder `run` loop doesn't sleep on success path
**Severity**: LOW
**File**: `packages/collector/src/monctl_collector/forward/forwarder.py:96-105`
**Description**: After a successful flush returning `sent > 0`, the loop **immediately loops** without any sleep. If SQLite has a slow burst of 100k rows, the forwarder pegs the event loop continuously.
**Fix sketch**: Add `await asyncio.sleep(0)` after `sent > 0` to yield, or sleep 100-500ms between successful batches when the batch was full.

### R-CEN-023 — `notify_config_reload` swallows every per-collector error with `debug` log
**Severity**: LOW
**File**: `packages/central/src/monctl_central/ws/connection_manager.py:381-389`
**Description**: Operator sees "ws_notified: 6" in the API response and assumes 6 of 8 collectors reloaded; in fact 2 had real errors silently dropped.
**Fix sketch**: Bump to `warning` level.

### R-CEN-024 — Audit DB-event capture bare-except on SQLAlchemy inspection
**Severity**: LOW
**File**: `packages/central/src/monctl_central/audit/db_events.py:40-41, 54-55, 68-69, 148-149`
**Description**: F-CEN-030 from review #1 — confirmed still present. Bare `except Exception: return {}` for attribute introspection.
**Fix sketch**: As prior review — narrow to `AttributeError`/`KeyError`, log everything else with `logger.exception`.

### R-CEN-025 — Forwarder marks 422-validation-error rows as sent forever
**Severity**: LOW
**File**: `packages/collector/src/monctl_collector/forward/forwarder.py:154-164`
**Description**: If 422 is being returned for *every* batch (e.g. central deployed a stricter Pydantic schema that the collector hasn't caught up to), the entire forwarder buffer drains into the void with one error log per batch.
**Fix sketch**: Track a `_consecutive_422` counter; after N batches in a row failing validation, stop draining and back off. Surface via `/health`.

### R-CEN-026 — `_evaluate_system_health` per-section bare-excepts under nested try
**Severity**: LOW
**File**: `packages/central/src/monctl_central/scheduler/tasks.py:253-254, 270-271, 290-291, 302-303, 317-318`
**Description**: Five inner `except Exception: pass` for individual PG health queries. A fundamental change to PG schema silently disables that subsystem's health check forever.
**Fix sketch**: Replace `pass` with `logger.debug("pg_health_subcheck_failed", check=..., exc_info=True)`.

### R-INST-027 — Installer `upgrade` saves state mid-failure (state drift)
**Severity**: LOW
**File**: `packages/installer/src/monctl_installer/commands/upgrade.py:148-157`
**Description**: `_upgrade_host` updates `state[project] = digest` after each successful project apply. If project N+1 fails, the loop returns "failed" without calling `_save_remote_state`. State write is skipped, so on next run we re-apply project N (idempotent — fine, but wastes ~30s of compose-up time).
**Fix sketch**: Call `_save_remote_state(host, runner, state)` *inside* the loop after each successful project apply.

### R-INST-028 — Installer `upgrade` cannot undo a failed canary
**Severity**: LOW
**File**: `packages/installer/src/monctl_installer/commands/upgrade.py:80-97`
**Description**: When canary fails health check, `UpgradeAborted` is raised but the canary host is left running on the new (broken) image. HAProxy still routes traffic to it. Operator must manually intervene.
**Fix sketch**: On canary failure, attempt automatic re-deploy with the previous tag (read from `state["__installer_version__"]`).

### R-CEN-029 — `_release_driver_lease` uses `await` inside `finally` without timeout
**Severity**: LOW
**File**: `packages/central/src/monctl_central/upgrades/os_service.py:399-409, 491-492`
**Description**: If Redis is partitioned during shutdown, the eval blocks indefinitely and `execute_os_install_job` never returns.
**Fix sketch**: Wrap in `asyncio.wait_for(... , timeout=5.0)` and log on timeout.

### R-CEN-030 — `_evaluate_definition` swallows compile error per-tier but loses partial work
**Severity**: LOW
**File**: `packages/central/src/monctl_central/alerting/engine.py:144-154`
**Description**: When any tier fails to compile, the whole definition is skipped for the cycle. The next cycle tries again; same compile error fires again — log spam every 30s.
**Fix sketch**: Cache compile results on the `AlertDefinition` model. Re-validate only when the definition's `updated_at` advances.
