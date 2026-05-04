# MonCTL Review #2 — Follow-up TODO

**Start here in future sessions.** Sequenced from cheapest-most-valuable to largest-strategic. Each item links back to the finding(s) where the file/line details live.

> Last refresh: **2026-05-04**. Items checked off here have been verified
> against the current source tree (not just claimed in commit messages).
> Many waves were silently absorbed during the post-review push; the few
> that remain are concentrated in Wave 2 (per-collector keys at install
> time) and the longer-tail documentation/observability buckets.

## How to resume

1. Read `README.md` in this directory for context.
2. Pick a wave below. Wave 0 is empty — the customer-upgrade-breaker (M-INST-013) shipped in 0bd8be4 and the CLAUDE.md PAT contradiction was a TODO-side error: CLAUDE.md is correct, the entry has been retired.
3. For each item:
   - Open the referenced finding file for `file:line_range` and fix sketch.
   - Before editing, **re-read the file** — line numbers may have drifted. Grep by the distinctive pattern rather than trusting line numbers.
   - One PR per category ideally; small atomic commits.
4. Mark the item done below (leave the finding ID visible — makes PR descriptions writable in one line).

---

## Wave 0 — Stop the bleeding (XS, ship today)

- [x] **M-INST-013** — `_wait_healthy` now parses JSON and matches `payload["status"] == "healthy"`. Verified 2026-05-04 at `packages/installer/src/monctl_installer/commands/upgrade.py:200-206`.
- [x] **D-CLA-005** — Re-checked: CLAUDE.md "PAT scope for workflow files" matches memory `feedback_pat_workflow_scope`. False alarm in the original review.
- [x] **M-CEN-016** — Each rollup has its own try block per memory `project_rollup_chain_fragility`. Verified 2026-05-04.

## Wave 1 — Customer installer hardening (S–M, security-critical)

- [x] **S-INST-001** — `tarfile.extractall(work, filter='data')` + manual `_safe_extractall` fallback for pre-3.12 hosts. `packages/installer/src/monctl_installer/commands/bundle.py:172-218`.
- [x] **S-INST-004** — `RejectPolicy` default + `--accept-new-hostkeys` flag flips to `AutoAddPolicy`. `packages/installer/src/monctl_installer/remote/ssh.py:225-227`.
- [x] **S-INST-002** — `oauth_issuer` default in central config is `""` (no hardcoded prod IP). Superset template no longer falls back to dev IPs. Verified 2026-05-04.
- [x] **S-INST-003** — `MONCTL_VERIFY_SSL` is templated from `inventory.cluster.tls.effective_verify`. `packages/installer/src/monctl_installer/render/templates/compose/collector.yml.j2:14, 46, 68` + `inventory/schema.py:42-69`.
- [x] **M-INST-010** — `init` rotates secrets only when `regenerate_secrets=True` is explicitly passed; covered by `test_init_force_preserves_existing_secrets` + `test_init_regenerate_secrets_rotates_password`.
- [x] **S-INST-014** — Atomic SFTP put via random `.tmp` + `posix_rename` (`packages/installer/src/monctl_installer/remote/ssh.py`).
- [x] **M-INST-014 / M-INST-015** — `MANIFEST.sha256` shipped + verified at `bundle load`.

## Wave 2 — Per-collector key rollout at install time (CLOSED)

Customer installs now mint per-host collector API keys at deploy time.
Central + installer + deploy + docs all shipped 2026-05-04 across PRs
#186 (Wave 2A), #187 (Wave 2B), #188 (Wave 2C), and the doc closer.

- [x] **M-INST-011 / S-COL-002 / S-X-002** — `monctl_ctl deploy` runs a post-step that POSTs `/v1/collectors/by-hostname/{host}/api-keys`, rewrites `MONCTL_COLLECTOR_API_KEY` in each host's `/opt/monctl/collector/.env`, and restarts the collector. `--skip-register-collectors` opts out for partial deploys; `monctl_ctl register-collectors` is the standalone subcommand. INSTALL.md §5 documents the flow.
- [x] **M-INST-012** — `peer_token_seed` per cluster + `host_peer_token(name)` derives a per-host token via HMAC-SHA256(seed, host_name).
- [ ] **S-CEN-002 (operator opt-in path)** — Soft-deprecation shipped: central emits `collector_shared_secret_used` warnings and exposes `MONCTL_REQUIRE_PER_COLLECTOR_AUTH=true` for operators to enforce strict per-collector auth once their fleet is migrated. Hard-flipping the default would break any install still on shared-secret; intentionally left to operators.
- [x] **S-COL-001** — Cache-node `raise RuntimeError(...)` when `MONCTL_PEER_TOKEN` is unset.

## Wave 3 — Reliability bugs in alerting + WS + OS-install

- [x] **R-CEN-001** — `await db.commit()` runs before `notify_config_reload`. R-CEN-001 marker at `packages/central/src/monctl_central/connectors/router.py:510-517`.
- [x] **R-CEN-002** — Keep-newest overflow + accurate dropped counter. Counter wired through `incr("ch_buffer.dropped...")`.
- [x] **R-CEN-003** — Helper `_log_task_exception` lifted; automation engine fire-and-forget paths use `add_done_callback`.
- [x] **R-CEN-004** — Fail loud on empty `instance_id`; `"?"` fallback removed. R-CEN-004 marker in `upgrades/os_service.py`.
- [x] **R-CEN-005** — `cancel_event: asyncio.Event | None` threaded through `_run_steps`, checked between steps. R-CEN-005 marker in `os_service.py:472-602`.
- [x] **R-CEN-006** — `connection_manager._connect_lock = asyncio.Lock()` wraps the connect critical section.
- [x] **R-CEN-008** — `cert_sync_task.add_done_callback(_log_task_exception)` shipped.
- [x] **R-CEN-009** — `hmac.compare_digest` on WS shared-secret path. R-CEN-009 marker in `ws/auth.py`.
- [x] **R-CEN-010** — `time.monotonic()` for polling deadlines (NTP step-safe). R-CEN-010 marker in `polling/engine.py:117-141, 208`.
- [x] **R-CEN-015** — `await asyncio.to_thread(_urlopen_blocking, ...)` in collector WS handlers. R-CEN-015 marker in `ws_handlers.py:84-119`.

## Wave 4 — Observability

- [x] **O-X-003** — `monctl_central.observability.counters` module shipped: Redis HINCRBY with daily rollover + `incr/sum_recent/all_counters`. `GET /v1/observability/counters` admin endpoint exposes the readout.
- [x] **O-CEN-001 / O-CEN-002 / O-CEN-005 / O-CEN-006 / O-CEN-007** — Wired to the new counter helper across scheduler/alerting/audit/auth call sites.
- [x] **O-CEN-003** — `audit` subsystem in `/v1/system/health`; buffer-overflow drops surface as `audit.dropped_count` counter.
- [x] **O-CEN-004** — `/health/status` returns `cache_stale: bool` + `age_seconds` so the top-bar can render a stale state.
- [ ] **O-CEN-008** — Persist drifted connector names to Redis set `monctl:connectors:drifted`; surface in connector list page. — S (open)
- [x] **O-CEN-010** — Sentinel quorum check; degraded at floor.
- [x] **O-COL-001** — Heartbeat carries forwarder dropped counters; central stores + surfaces.
- [ ] **O-X-001** — Platform-self alerting on degraded subsystems via synthetic alert_log rows routed through IncidentEngine. — M (open)
- [ ] **O-INST-001** — `monctl_ctl deploy` writes `/opt/monctl/.deploy-history.jsonl`; optionally POST to central `/v1/installer/deploy-events`. — M (open)

## Wave 5 — Audit completeness

- [x] **S-CEN-018** — `api_keys` mapped in `TABLE_TO_RESOURCE` as `"api_key"` with `key_hash` redaction.
- [x] **S-CEN-019** — `assignment_credential_overrides` mapped as `"assignment_credential_override"`.
- [ ] **S-X-003** — `audit_alert_actions` resource for admin-driven incident state changes (ack/silence/force-clear). — M (open)
- [x] **S-CEN-009** — `X-Forwarded-For` only trusted from configured `settings.trusted_proxies`.

## Wave 6 — CI test infrastructure

- [x] **T-X-001 / T-X-002 / T-X-003 / T-X-004** — `.github/workflows/tests.yml` runs pytest+coverage / vitest / pack-validate / e2e-smoke on every PR; T-X-004 branch protection requires the four required checks.

## Wave 7 — Test coverage

- [x] **T-CEN-001** — `tests/unit/test_alerting_engine.py` (PR #172).
- [x] **T-CEN-002** — `tests/unit/test_incidents_engine.py` (PR #175).
- [x] **T-CEN-010** — `tests/unit/test_oauth.py` (PR #173).
- [x] **T-CEN-011** — `tests/unit/test_ws_auth.py` (PR #174).
- [x] **T-CEN-012** — `tests/unit/test_collector_api_jobs.py` (PR #177).
- [x] **T-APP-001** — `tests/unit/test_snmp_connector.py` covers credential-key fallback + walk_multi (PR #178).
- [ ] **T-WEB-001** — Frontend tests: `useColumnConfig.compact()` regression, FlexTable filter+sort, `usePermissions` hook, DeviceDetailPage tab routing. — M (open)
- [ ] **T-X-006** — Single regression test for each Wave-2 fix shipped since Review #1 (#134, #138, #140, #141). — M (open)
- [x] **S-CEN-010 (executor)** — `test_action_executor.py` pins env-allowlist + format-fix (PR #179).

## Wave 8 — Performance

- [x] **P-CEN-001** — Chunked `asyncio.gather` in alerting engine; per-def session isolation.
- [x] **P-CEN-002** — Batched `db.get` → `select(...).where(.in_(...))` in dashboard.
- [x] **P-CEN-003** — Pre-loaded discovery-injection lookups.
- [x] **P-CEN-004** — Hash-ring built once per `/jobs` call.
- [x] **P-INST-005** — `ThreadPoolExecutor(max_workers=max_parallel_hosts)` parallelises host loop.
- [x] **P-CEN-006** — Single SQL for missing-row sync.
- [x] **P-CEN-008** — `step_seconds` bucketing in `query_ingestion_rate_history`.

## Wave 9 — DDL idempotence

- [x] **M-CEN-003 / M-CEN-004** — `_apply_on_cluster` helper injects `ON CLUSTER '<name>'` for ALTER statements.
- [ ] **M-CEN-006** — Drop `try/except: pass` around DDL loops; log at WARNING with full SQL. — XS (open)
- [ ] **M-CEN-005** — Generic `_ensure_mv_columns` helper for `*_latest` MV drift detection. — M (open)

## Wave 10 — Documentation cleanup

- [ ] **D-X-002** — Add `docs/env-reference.md` enumerating every `MONCTL_*` env var. — M
- [ ] **D-CLA-004** — Append remaining new "Known pitfalls" entries from memory. — S
- [ ] **D-CEN-020** — Audit `tags=` on every `@router.*` decorator; document tag taxonomy in CLAUDE.md API Conventions. — S
- [ ] **D-X-018** — `docs/pack-format.md` — pack JSON schema reference. — M
- [ ] **D-X-019** — Connector / BasePoller lifecycle section in `app_create.md`. — S
- [ ] **D-X-021** — `docs/disaster-recovery.md` — Patroni split-brain, ClickHouse replica wipe, central node lost runbooks. — L
- [ ] **D-COL-013** — Either retire `docs/collector-deployment-guide.md` or rewrite §4 to use `monctl_ctl deploy`. — M
- [x] **D-X-001 / D-CLA-003 / D-CLA-006 / D-CEN-011 / D-X-017 / D-INST-008 / D-INST-009** — Doc cleanup PR shipped (#169).

## Security carry-overs (HIGH severity)

- [x] **S-CEN-004** — `/v1/auth/login` rate limit + lockout (10-fail / 10-min window, 15-min lockout, audit + counter wiring).
- [x] **S-CEN-010** — Action automations: env allowlist (no MonCTL secret leaks) + admin gate for `target=central` create/edit (PR #179).
- [x] **S-X-002** — Customer installer per-collector key rollout — Wave 2 closer (PRs #186/#187/#188).

## Manual / "not code" follow-ups

- [ ] **AAD binding + ciphertext version prefix** for `credentials/crypto.py` — deferred from #1; still open.
- [ ] **F-X-007 phase 2** — stub-collector E2E roundtrip; deferred from #1; the e2e-smoke job is currently failing on the docker-compose stack and needs investigation.
- [ ] **F-COL-031 hash enforcement** — deferred until packs supply hashes; still open.
- [ ] **CVE workflow** — `pip-audit` + `npm audit` run nightly; add an issue-creation step or webhook so HIGH findings reach a human.

---

## Progress

**All 9 HIGH-severity testing findings closed.** All 7 HIGH-severity
security findings closed (Wave 2 closer 2026-05-04 across #186/#187/#188).
Reliability + perf + observability essentially closed.

Remaining open is the longer-tail docs bucket plus a couple of MED
operability items (`O-X-001` platform-self alerting, `T-WEB-001`
broader frontend tests, `T-X-006` regression-per-fix coverage of
PRs #134/#138/#140, `S-X-003` audit_alert_actions). None are HIGH
severity.
