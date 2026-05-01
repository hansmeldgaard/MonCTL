# Operability Findings — Review #2 (2026-04-30)

## Summary

- 22 findings: 8 HIGH / 9 MED / 4 LOW / 1 INFO
- Review #1 closed roughly half of F-X-002 by adding sampler tables (`ingestion_rate_history`, `db_size_history`, `host_metrics_history`, `container_metrics_history`) and a `_subsystem_reason` rollup. The other half — durable counters on **failure sites** — remains entirely deferred. There is **no metric infrastructure of any kind** (no `prometheus_client`, no Redis counter primitive, no `counters` table). Every "if X fails, log it" path in the codebase logs once and forgets; there is no way to ask "how many WS errors did we have today?" or "how many forwarder batches got dropped this week?" without grepping logs across 4 nodes.
- The most operationally dangerous gaps are: (1) collector forwarder drops are pure-local — central never knows a collector is shedding load, (2) the alert engine's cycle-overrun lock fires a single WARN log with no aggregate visibility, (3) the audit buffer drops on CH outage are pure-log with no surface, and (4) the `health/status` lightweight endpoint has no client-visible cache age so a frozen cache can lie green for hours.

---

## Findings

### O-CEN-001 — Scheduler task done-callback logs but doesn't count
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:23-31`
- **Description**: `_log_task_exception` is the F-CEN-041 fix — it calls `logger.exception` on each fire-and-forget failure. There is no aggregate visible anywhere. An operator who wants "how many times has `setup_local_apt_source` / `check_os_updates` / `collect_package_inventory` crashed in the last day?" must ssh to every central and grep logs by task name. Because three of these tasks spawn every 30s scheduler tick, a single faulty branch can flap silently behind the per-line `exception` calls.
- **Fix sketch**: Stash a Redis hash `monctl:scheduler:task_failures` keyed by `task_name` and incremented in `_log_task_exception`. Surface in `/v1/system/health` under `scheduler.details.task_failures` with a 24h running window.

### O-CEN-002 — Alert engine cycle-skip log fires once per skip with no aggregate
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:525-527`
- **Description**: F-CEN-042 added `_alert_cycle_lock` that emits `alert_evaluation_skipped_previous_cycle_in_flight` when the previous cycle hasn't finished in 30s. This is THE canary for a degraded ClickHouse / overloaded eval engine, and it's a single WARN line — easy to miss in 4-node logs. There is no counter, no `last_skipped_at` timestamp written to Redis, and the `scheduler` health subsystem reports only leader/TTL — not skip rate. An alert engine that's persistently skipping every other cycle reads as healthy in `/v1/system/health`.
- **Fix sketch**: Increment `monctl:scheduler:alert_skips_24h` (Redis HINCRBY with daily key rollover) on each skip. Add to `_check_scheduler` details. Treat skip-rate >10% over the last hour as `degraded`.

### O-CEN-003 — Audit buffer overflow is pure-log; never surfaced
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/audit/buffer.py:34-39, 65-67`
- **Description**: When ClickHouse is unreachable the audit buffer hits `_MAX_BUFFER=5000` and starts FIFO-dropping rows with `logger.warning("audit_buffer_overflow", dropped=drop)`. The `_drain → ch.insert_audit_mutations` path drops the entire batch on exception with `logger.warning("audit_flush_failed")`. **No counter**, no `last_drop_at`, no surface in system health. Per CLAUDE.md the audit log is the **whitelisted, regulator-facing** mutation history — silent loss is the worst-case outcome.
- **Fix sketch**: Module-level `_dropped_total` counter in `AuditBuffer`; expose via `/v1/system/health` as a new `audit` subsystem. Add to top-bar tooltip when nonzero in last 24h. Persist the counter to Redis so it survives restart.

### O-CEN-004 — `/v1/system/health/status` cache-age not surfaced to client
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/system/router.py:1957-1986`
- **Description**: The lightweight endpoint returns `_last_health_status` which contains `checked_at`. If the full-check refresh fails, the previous cache is returned **as-is** and the client has no visible signal. An operator looking at the top-bar dot sees "healthy" while ClickHouse and Patroni have been down for 30 min.
- **Fix sketch**: After the failed refresh, set `data.cache_stale = true` (or compute `age_seconds`). Frontend top-bar should render the dot in `unknown` (grey) state when `age_seconds > 180`, regardless of the cached `overall_status`.

### O-CEN-005 — Refresh-token replay only emits a single WARN line
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/auth/router.py:411-429`
- **Description**: A replay of a refresh token is a strong compromise indicator. The handler does write an `audit_login_events` row with `failure_reason="refresh_token_replay"` AND a `logger.warning(...)`, but there is no aggregate alert path. An operator unaware of replay logs would not be paged.
- **Fix sketch**: Add an `incident_rule` seeded by default that fires on `audit_login_events.failure_reason = 'refresh_token_replay'` (count > 0 in last 5 min). As secondary defence, increment a Redis `monctl:auth:replay_24h` counter and surface it in system health under a new `security` subsystem.

### O-CEN-006 — Login-rate-limit lock-outs aren't aggregated for trending
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/auth/router.py:50-96`
- **Description**: F-CEN-004 lockouts write `audit_login_events.event_type='login_locked'`. Good — but there is **no aggregation surface**. If a brute-force run hammers 50 accounts in 10 minutes, ops sees nothing on the top bar / dashboards.
- **Fix sketch**: Either (a) seed a default alert definition that queries the audit_login_events table for high `login_locked` rates, or (b) add a small Redis hash `monctl:auth:locks_today` HINCRBY'd in `_record_login_failure` and read by a new `security` system-health subsystem.

### O-CEN-007 — Per-collector ownership rejection emits per-event logs only
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/collector_api/router.py:1697-1707, 2089`
- **Description**: F-CEN-014's `_caller_owns_assignment` rejection logs `collector_results_unauthorised` and increments a per-request `unauthorised` counter that is then **echoed back in the HTTP response** to the offending collector — but never aggregated in central. The scenario this guards against is exactly a misbehaving / compromised collector trying to claim other collectors' jobs; that collector is the one reading the response.
- **Fix sketch**: After processing the batch, if `unauthorised > 0` server-side: HINCRBY `monctl:collector:unauthorised:{collector_id}` and surface in the `collectors` system-health subsystem. Promote to `degraded` if any single collector has >100 in 24h.

### O-CEN-008 — Connector seed drift is INFO-logged, never surfaced
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/main.py:415-424`
- **Description**: At every central startup, `_check_connector_drift` runs and emits `logger.info("connector_seed_drift_detected", ...)` when an installed connector version's checksum differs from the seed bytes. INFO level + log-only means the next time someone redeploys central, the patch silently goes back to seed bytes. Per memory `feedback_check_memory_before_writing_code`, this exact class of drift is the one with fleet-wide blast radius.
- **Fix sketch**: Persist drifted connector names to a Redis set `monctl:connectors:drifted` with no TTL. Surface in the connector list page (badge) and in system health (warning subsystem).

### O-CEN-009 — OS-install-job orphan resume has no operator UI
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:1196-1244`
- **Description**: Memory `project_os_install_resume` says the resume mechanism survives a leader's death mid-poll. But: (a) `_clear_tracking` logs `os_install_job_resume_ended_badly` on exception and **does not change the DB row** — the job stays `status='running'` forever and gets re-spawned every cycle. (b) There's no UI for "show me jobs that have been running >1h" or "show me jobs that have been resumed >3 times".
- **Fix sketch**: Track per-job resume-attempt count in `os_install_jobs.resume_count` (new column). Add a "Stuck jobs" tab to the OS upgrade page that lists running-jobs with `started_at < now() - interval '2h'`.

### O-CEN-010 — Sentinel <quorum count never goes degraded
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/system/router.py:1183-1238`
- **Description**: `_check_redis` reads `num_sentinels` from `SENTINEL master <name>` and stores it in `sentinel_info`. The status decision only flips to `degraded` on `s_down` flag — it does **not** check that `num_sentinels >= quorum`. With 3 sentinels and quorum=2, losing 1 sentinel passes silently — but losing a 2nd would tip the cluster into split-brain risk territory.
- **Fix sketch**: After fetching `sentinel_info`, compare `num_sentinels` to `int(quorum)`. If `num_sentinels == quorum` → `degraded` with reason `"sentinel quorum at floor"`. If `num_sentinels < quorum` → `critical`.

### O-CEN-011 — Pack import race produces same log shape as real failure
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/main.py:220-221`
- **Description**: Per memory `feedback_pack_first_import_race`, on first-time deploy of a NEW pack across 4 central nodes, N-1 lose the unique-violation race and log `builtin_pack_import_failed` with `error="UniqueViolationError ..."`. Real pack-corruption failures emit the same WARN line.
- **Fix sketch**: Catch `IntegrityError` (or `UniqueViolationError` specifically) separately and emit `logger.debug("pack_import_lost_race_benign", pack=pack_file, pack_uid=pack_uid)`.

### O-CEN-012 — Logs API has no tenant scope; admin-only is too coarse
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/logs/router.py:99, 191`
- **Description**: `GET /v1/logs` and `GET /v1/logs/filters` both gate on `require_admin`. There's no `apply_tenant_filter` and the `logs` table doesn't even carry a `tenant_id` column. A tenant admin who wants to see why their collectors are unhealthy must escalate to a full platform admin.
- **Fix sketch**: Add `tenant_id` to the `logs` ClickHouse table (denormalised from `collector.tenant_id` at ingest). Switch the auth gate to `require_permission("logs", "view")` (new permission) and apply tenant scoping.

### O-CEN-013 — OAuth provider error paths log nothing
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/auth/oauth.py:302-389`
- **Description**: Every error path in `/v1/oauth/token` raises `HTTPException` with no logging. `invalid_client`, `invalid_grant`, `user_inactive`, replayed authorization codes — all silent server-side. If a Superset misconfig starts producing thousands of `invalid_client` 401s, there is **no log**.
- **Fix sketch**: Add `logger.warning("oauth_token_failed", reason="invalid_client", client_id=client_id, grant_type=grant_type)` to each error path. Optionally write to `audit_login_events` with `event_type="oauth_token_failed"`.

### O-COL-001 — Forwarder dropped batches never reported to central
- **Severity**: HIGH
- **File**: `packages/collector/src/monctl_collector/forward/forwarder.py:180-199`; `central/api_client.py:262-321`
- **Description**: When central is unreachable for days the forwarder hits `_MAX_BUFFER_ROWS=10_000_000` and FIFO-drops oldest rows. `_dropped_total` is tracked in-process and logged at WARN, but the heartbeat payload (`load_score`, `worker_count`, etc.) does **not** carry `dropped_total`. Central has zero visibility that collector X is shedding load.
- **Fix sketch**: Add `dropped_total` and `dropped_24h` to the heartbeat `system_resources` block. Central stores it on `Collector.last_dropped_total`. Promote `collectors` system-health subsystem to `degraded` for any collector with `dropped_24h > 0`.

### O-COL-002 — Log-shipper drop counts never reach central
- **Severity**: LOW
- **File**: `packages/collector/src/monctl_collector/central/log_shipper.py:88-97, 179-208`
- **Description**: `_dropped_secret` (logs containing redacted-pattern matches) and `_dropped_rate` (over-the-cap) are tracked locally and logged every 5 min if nonzero. Secret-redaction drops in particular are a security-positive signal.
- **Fix sketch**: Same delivery channel as O-COL-001: piggyback in heartbeat. Surface in collectors list as a tooltip on the log-shipper status dot.

### O-COL-003 — Job execution error category fallback is silent in aggregate
- **Severity**: LOW
- **File**: `packages/collector/src/monctl_collector/polling/engine.py:380-388`
- **Description**: When an app fails to set `error_category` the engine forces `"app"` and emits `logger.warning("app_missing_error_category", ...)`. Per CLAUDE.md this is mandatory, and a missing one is "almost always an app bug". There's no aggregate "which apps are missing error_category most often this week?" view.
- **Fix sketch**: Either (a) push a SQL view `app_missing_error_category_count_7d` over the `logs` ClickHouse table, exposed on the App detail page, or (b) emit a separate ClickHouse insert into a new `collector_events` table.

### O-INST-001 — `monctl_ctl deploy` writes no audit/history; failures leave operator in the dark
- **Severity**: HIGH
- **File**: `packages/installer/src/monctl_installer/commands/deploy.py:56-104`
- **Description**: `deploy()` writes a `.state.json` per-host with project digest, but there's **no per-run log file**, no audit trail, no way to answer "when did we last deploy central, and did it succeed on all 4 nodes?". `DeployOutcome` is returned as Python objects to the CLI which prints once and exits. If the operator's tmux session dies mid-deploy, the only artifact left is the partially-updated `.state.json` files.
- **Fix sketch**: Write `/opt/monctl/.deploy-history.jsonl` on each host on every `_apply_project` (one line per project per run with status, sha, started_at, finished_at, installer_version). When the inventory is `--mode=connected`, also POST to a new `POST /v1/installer/deploy-events` endpoint on central.

### O-INST-002 — Installer `.state.json` corruption is swallowed
- **Severity**: MED
- **File**: `packages/installer/src/monctl_installer/commands/deploy.py:145-154`
- **Description**: `_load_remote_state` on a corrupt JSON or unreachable host falls through to `return {}`, which makes the deploy treat the host as fresh and re-applies every project. Re-applying postgres/etcd/clickhouse on a healthy host that just had a transient SSH glitch is **destructive surprise**.
- **Fix sketch**: On `SSHError` re-raise (operator should know SSH is broken). On `json.JSONDecodeError`, emit warning and back the file up to `.state.json.bak.<ts>`.

### O-X-001 — No platform-self alerting on degraded subsystems
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/system/router.py:1820-1850`; `scheduler/tasks.py:194-460`
- **Description**: `_evaluate_system_health` writes platform-self alerts to `alert_log` for **threshold breaches only** (CPU, mem, disk, etc.). It does NOT fire when a subsystem in `_check_*` returns `status='critical'` or `status='degraded'`. So if Patroni reports critical, Redis sentinel reports degraded, ClickHouse keeper reports unreachable — there is no alert, no email, no automation hook.
- **Fix sketch**: At the end of `_evaluate_system_health`, for every subsystem in `unhealthy_subsystems`, emit an alert_log row with `definition_id` = a synthetic UUID per subsystem (e.g. `subsystem_critical_postgresql`). Existing `IncidentEngine` then escalates them via the standard automation pipeline.

### O-X-002 — No dashboards over `alert_log` (fire-rate, MTTR, top-firing entities)
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/alerting/router.py:790-840`
- **Description**: `alert_log` ClickHouse table captures every fire/escalate/downgrade/clear with full context, but the only API consumer is `GET /v1/alerts/log`. No "top 10 noisy alerts this week" widget, no MTTR-by-tier chart, no fire-rate-per-device.
- **Fix sketch**: Add `/v1/alerts/stats?from=&to=&group_by=definition|device|tier` → returns count(action=fire), avg(time_to_clear), p95. Wire into a new "Alerts → Insights" tab. This is exactly what Superset is for if you want zero-code; ship a default Superset dashboard JSON in `superset/`.

### O-X-003 — No platform-side counters table; everything is one-shot logs
- **Severity**: INFO (architectural)
- **File**: cross-cutting
- **Description**: There is no `prometheus_client`, no `/metrics` endpoint, no Redis-backed counter helper. Every drop, every WS error, every silent-fallback path uses one-shot `logger.warning` calls. Adding counters is currently a per-site copy-paste exercise. Findings O-CEN-001 through O-CEN-007 all individually expensive to fix.
- **Fix sketch**: Introduce `monctl_central.observability.counters` with `incr(name: str, by: int = 1, labels: dict | None = None)` that HINCRBY's on a Redis hash keyed by UTC day. Expose `GET /v1/observability/counters?prefix=` for ad-hoc queries.

### O-X-004 — Ingestion-rate sampler doesn't cover `audit_mutations` or `alert_log`
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/scheduler/tasks.py:111-113` (sampler entrypoint, full body in `_sample_ingestion_rates`)
- **Description**: `ingestion_rate_history` samples a configured set of tables every 5 min — which includes `availability_latency`, `interface`, `performance`, `config` etc. but nothing for `audit_mutations` or `alert_log`. These are the highest-leverage tables operationally.
- **Fix sketch**: Add `audit_mutations` and `alert_log` to the table list in `_sample_ingestion_rates`. The chart already ranges across whatever the sampler stores so no UI work needed.
