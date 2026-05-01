# MonCTL Review #2 — Follow-up TODO

**Start here in future sessions.** Sequenced from cheapest-most-valuable to largest-strategic. Each item links back to the finding(s) where the file/line details live.

## How to resume

1. Read `README.md` in this directory for context.
2. Pick a wave below. Wave 0 is "stop the bleeding" — `monctl_ctl upgrade` is currently broken in production (M-INST-013), and the customer installer ships a brand-new attack surface with several un-shipped hardening items.
3. For each item:
   - Open the referenced finding file for `file:line_range` and fix sketch.
   - Before editing, **re-read the file** — line numbers may have drifted. Grep by the distinctive pattern rather than trusting line numbers.
   - One PR per category ideally; small atomic commits.
4. Mark the item done below (leave the finding ID visible — makes PR descriptions writable in one line).

---

## Wave 0 — Stop the bleeding (XS, ship today)

- [ ] **M-INST-013** — `_wait_healthy` matches `"success"` but central returns `"healthy"` — every `monctl_ctl upgrade` aborts. `packages/installer/src/monctl_installer/commands/upgrade.py:197-200`
- [ ] **D-CLA-005** — CLAUDE.md PAT-workflow-scope pitfall contradicts memory `feedback_pat_workflow_scope` (updated 2026-04-21). Delete or rewrite. `CLAUDE.md:348`
- [ ] **M-CEN-016** — Rollup chain shares one try block per cycle; memory `project_rollup_chain_fragility` says "each rollup now has its own try block." Verify whether this regressed or memory is stale; either fix code or update memory. `packages/central/src/monctl_central/scheduler/tasks.py:603-610, 622-634`

## Wave 1 — Customer installer hardening (S–M, security-critical)

The installer is a brand-new attack surface that ships with several insecure defaults. Tackle these before any external customer install.

- [ ] **S-INST-001** — `tarfile.extractall` without `filter='data'` (RCE pre-3.12). `packages/installer/src/monctl_installer/commands/bundle.py:131-148` — S
- [ ] **S-INST-004** — Default `RejectPolicy` for paramiko host keys; load `~/.ssh/known_hosts`. Add `--accept-new-hostkeys` flag. `packages/installer/src/monctl_installer/remote/ssh.py:101-113` — S
- [ ] **S-INST-002** — Replace `os.environ.get("...", "<10.145.210.41>")` with `os.environ["..."]` so missing vars fail loudly. `packages/installer/src/monctl_installer/render/templates/config/superset_config.py.j2:177, 288, 298, 304, 757`; `packages/central/src/monctl_central/config.py:112` — S
- [ ] **S-INST-003** — Make `MONCTL_VERIFY_SSL` a Jinja variable wired to inventory. `packages/installer/src/monctl_installer/render/templates/compose/collector.yml.j2:14, 46, 68` — S
- [ ] **M-INST-010** — `init --force` must refuse if `secrets.env` exists; require `--regenerate-secrets`. Otherwise: catastrophic on running cluster. `packages/installer/src/monctl_installer/commands/init.py:170-174` — S
- [ ] **S-INST-014** — SFTP put: write to `path.tmp` with 0o600 then atomic rename. `packages/installer/src/monctl_installer/remote/ssh.py:84-97` — S
- [ ] **M-INST-014 / M-INST-015** — Add `MANIFEST.sha256` to bundle, verify before extract. Pass `filter='data'` to `extractall` (3.12+). `packages/installer/src/monctl_installer/commands/bundle.py:122-148` — S

## Wave 2 — Per-collector key rollout (umbrella; closes 4 findings)

Customer installs currently bypass the per-collector auth that #117/#118/#122 added. This is the largest single gap from review #1 → review #2: central enforces per-collector identity, but the installer doesn't provision it.

- [ ] **M-INST-011 / S-COL-002 / S-X-002** — `monctl_ctl deploy` post-step that registers each collector via central, writes per-host API keys to `/opt/monctl/collector/.env`, flips `MONCTL_VERIFY_SSL=true` once central CA is provisioned. — L
- [ ] **M-INST-012** — Generate `peer_token` per-host in `secrets.env` (vs. cluster-wide). Or update memory `project_peer_token_per_host` to match cluster-wide reality. — M
- [ ] **S-CEN-002** — Once installer ships per-collector keys, flip `_resolve_caller_collector` default to 401 instead of fall-through. `packages/central/src/monctl_central/collector_api/router.py:1697-1707, 1214-1237` — S
- [ ] **S-COL-001** — Refuse to start collector cache-node if `MONCTL_PEER_TOKEN` is unset. `packages/collector/src/monctl_collector/peer/server.py:228-247` — S

## Wave 3 — Reliability bugs in alerting + WS + OS-install (S–M)

The 30s scheduler tick has several latent races and missing done-callbacks. Severity-tier alerting redesign + event-policy rework added new fire-and-forget paths that need the F-CEN-041 treatment.

- [ ] **R-CEN-001** — `set_latest_version` notify-before-commit. Move to `after_commit` event listener or commit explicitly before `notify_config_reload`. `packages/central/src/monctl_central/connectors/router.py:498-525` — M
- [ ] **R-CEN-002** — CH write-buffer: keep newest rows up to cap, log accurate dropped count. `packages/central/src/monctl_central/storage/ch_buffer.py:99-111` — S
- [ ] **R-CEN-003** — Automations engine: 3 fire-and-forget tasks need `add_done_callback(_log_task_exception)`. Lift helper to `monctl_central/utils.py`. `packages/central/src/monctl_central/automations/engine.py:144-154, 230-240, 293-302` — S
- [ ] **R-CEN-004** — Fail loud if `settings.instance_id` is empty; remove the `"?"` fallback. `packages/central/src/monctl_central/upgrades/os_service.py:428` — XS
- [ ] **R-CEN-005** — OS-install lease loss: pass `cancel_event: asyncio.Event`; check between steps. `packages/central/src/monctl_central/upgrades/os_service.py:382-396` — S
- [ ] **R-CEN-006** — `connection_manager.connect()` race: wrap critical section in `asyncio.Lock`. `packages/central/src/monctl_central/ws/connection_manager.py:188-206` — S
- [ ] **R-CEN-008** — `cert_sync_task.add_done_callback(_log_task_exception)`. `packages/central/src/monctl_central/main.py:539` — XS
- [ ] **R-CEN-009** — `hmac.compare_digest` on WS shared-secret. `packages/central/src/monctl_central/ws/auth.py:37` — XS
- [ ] **R-CEN-010** — Polling engine: `time.monotonic()` for deadlines. `packages/collector/src/monctl_collector/polling/engine.py:201, 206, 210, 250` — S
- [ ] **R-CEN-015** — `await asyncio.to_thread(urllib.request.urlopen, ...)` in collector WS handlers. `packages/collector/src/monctl_collector/central/ws_handlers.py:86-91, 100-111` — S

## Wave 4 — Observability (S each; multiplied by O-X-003 helper)

The "log on failure, never count" pattern is repeated ~10 times across the codebase. Build the helper once, then wire every site.

- [ ] **O-X-003** — Build `monctl_central.observability.counters.incr(name, by, labels)` helper backed by Redis HINCRBY with daily key rollover. Expose `GET /v1/observability/counters?prefix=`. — M
- [ ] **O-CEN-001 / O-CEN-002 / O-CEN-005 / O-CEN-006 / O-CEN-007** — Wire scheduler task drops, alert cycle skips, refresh-token replays, login lockouts, per-collector unauthorised counts to the new counter helper. — S each
- [ ] **O-CEN-003** — Audit buffer overflow counter; surface in `/v1/system/health` as new `audit` subsystem. — S
- [ ] **O-CEN-004** — `/health/status` returns `cache_stale: true` + `age_seconds`; frontend top-bar grey on stale. — S
- [ ] **O-CEN-008** — Persist drifted connector names to Redis set `monctl:connectors:drifted`; surface in connector list page. — S
- [ ] **O-CEN-010** — Sentinel `num_sentinels < quorum` check; `degraded` at floor, `critical` below. — S
- [ ] **O-COL-001** — Heartbeat carries `dropped_total` + `dropped_24h`; central stores on `Collector.last_dropped_total`. Surface in collectors list + system health. — M
- [ ] **O-X-001** — Platform-self alerting on degraded subsystems: emit synthetic alert_log rows for `unhealthy_subsystems`, route through IncidentEngine. — M
- [ ] **O-INST-001** — `monctl_ctl deploy` writes `/opt/monctl/.deploy-history.jsonl`; optionally POST to central `/v1/installer/deploy-events`. — M

## Wave 5 — Audit completeness

- [ ] **S-CEN-018** — Move `api_keys` from `_AUDIT_OPT_OUT` to `TABLE_TO_RESOURCE` (`"api_key"`). Verify `key_hash` redaction. `packages/central/src/monctl_central/audit/resource_map.py` + `tests/unit/test_audit_resource_map_coverage.py:39` — S
- [ ] **S-CEN-019** — Same for `assignment_credential_overrides` (label `"assignment_credential_override"`). — S
- [ ] **S-X-003** — `audit_alert_actions` resource for admin-driven incident state changes (ack/silence/force-clear). — M
- [ ] **S-CEN-009** — `X-Forwarded-For` only trusted from configured `settings.trusted_proxies`. `packages/central/src/monctl_central/audit/request_helpers.py:8-19` — S

## Wave 6 — CI test infrastructure (S, but cross-cutting)

- [ ] **T-X-001** — `.github/workflows/tests.yml` running on `pull_request` with: pytest across `tests/`, `packages/central/tests/`, `packages/installer/tests/`; vitest on the frontend; `python scripts/validate_packs.py`. Mark all required in branch protection. — M
- [ ] **T-X-002** — `pytest --cov` in CI with artifact upload, fail PR on coverage drop. — S
- [ ] **T-X-003** — `e2e_smoke` job that runs `./scripts/run_e2e.sh run` on PR. Replace 2-second poll loop in `tests/integration/test_e2e_smoke.py:62-70` with proper sync. — M
- [ ] **T-X-004** — Configure branch protection on `main` once T-X-001 lands. — XS

## Wave 7 — Test coverage (L; sequenced after T-X-001 so regressions land green)

The biggest gaps are in the new code that landed since #1: alerting engine, incidents engine, OAuth provider, WS hub. Build out coverage one bucket at a time.

- [ ] **T-CEN-001** — `tests/central/test_alerting_engine.py` — fire/escalate/downgrade/clear with healthy tier, fail-closed on CH timeout. — L
- [ ] **T-CEN-002** — `tests/central/test_incidents_engine.py` — incident open/close/escalate/idempotent restart. — L
- [ ] **T-CEN-010** — `tests/central/test_oauth.py` — code flow, invalid client/redirect, code reuse, ID-token claims. — M
- [ ] **T-CEN-011** — `tests/central/test_ws_auth.py` + `test_connection_manager.py` (broadcast unwrap regression test). — M
- [ ] **T-CEN-012** — `tests/central/test_collector_api_jobs.py` — delta-sync `updated_at` sentinel; raw-SQL update without `updated_at` does NOT propagate. — M
- [ ] **T-APP-001** — Vendor the SNMP connector source into `packages/central/tests/fixtures/connectors/snmp.py`; add `test_snmp_connector_compat.py` parameterised over every credential-key alias every prod template emits. — L
- [ ] **T-WEB-001** — Frontend tests: `useColumnConfig.compact()` regression, FlexTable filter+sort, `usePermissions` hook, DeviceDetailPage tab routing. — M
- [ ] **T-X-006** — Single regression test for each Wave-2 fix shipped since Review #1 (#134, #138, #140, #141). — M

## Wave 8 — Performance (S–M; ship after observability so regressions are visible)

- [ ] **P-CEN-001** — `asyncio.gather` definition evaluations in chunks of pool size. `packages/central/src/monctl_central/alerting/engine.py:77-87` — M
- [ ] **P-CEN-002** — Batch `db.get(AlertDefinition/Device, ...)` in dashboard widgets. `packages/central/src/monctl_central/dashboard/router.py:84-97, 167-176` — S
- [ ] **P-CEN-003** — Pre-load Device/Pack/App/AppVersion rows once for `/api/v1/jobs` discovery-injection. `packages/central/src/monctl_central/collector_api/router.py:876-971` — M
- [ ] **P-CEN-004** — Build hash-ring once per `/jobs` call; replace O(n²) bisect.insert with sort. `packages/central/src/monctl_central/collector_api/router.py:301-335` — S
- [ ] **P-INST-005** — Cache one paramiko `SSHClient` per host inside `SSHRunner`; parallelise host loop in `deploy()`. `packages/installer/src/monctl_installer/remote/ssh.py:99-117` + `commands/deploy.py:74-104` — M
- [ ] **P-CEN-006** — Single SQL for `_sync_alert_instances` insert-missing-rows. `packages/central/src/monctl_central/scheduler/tasks.py:481-498` — S
- [ ] **P-CEN-008** — Add `step_seconds` bucketing to `query_ingestion_rate_history`. `packages/central/src/monctl_central/storage/clickhouse.py:3284-3314` + `system/router.py:2241-2248` — S

## Wave 9 — DDL idempotence (S–M; ship before next CH cluster expansion)

- [ ] **M-CEN-003 / M-CEN-004** — Add `ON CLUSTER` to all 30+ ALTER statements in `clickhouse.py`. `packages/central/src/monctl_central/storage/clickhouse.py:1832-1881, 1971-2008` — S
- [ ] **M-CEN-006** — Drop `try/except: pass` around DDL loops; log at WARNING with full SQL. — XS
- [ ] **M-CEN-005** — Generic `_ensure_mv_columns(name, expected_cols)` helper for `*_latest` MV drift detection. `packages/central/src/monctl_central/storage/clickhouse.py:1888-1931` — M

## Wave 10 — Documentation cleanup (S each; grouped for one PR)

- [ ] **D-X-001** — Move `app_create.md` to `docs/app-development-guide.md` and link from README + CLAUDE.md. — XS
- [ ] **D-X-002** — Add `docs/env-reference.md` enumerating every `MONCTL_*` env var. — M
- [ ] **D-CLA-003** — Update CLAUDE.md package structure pack list (8 packs, no version suffix). — XS
- [ ] **D-CLA-004** — Append 6 new "Known pitfalls" entries from memory. — S
- [ ] **D-CLA-006** — Add "deploy.sh is maintainer-only" preface to CLAUDE.md Building & Deploying. — XS
- [ ] **D-CEN-011** — Add OAuth2 provider bullet to CLAUDE.md auth section. — XS
- [ ] **D-CEN-020** — Audit `tags=` on every `@router.*` decorator across new endpoints. Document tag taxonomy in CLAUDE.md API Conventions. — S
- [ ] **D-X-017** — Mark `docs/event-policy-rework.md` as superseded or delete. — XS
- [ ] **D-X-018** — `docs/pack-format.md` — pack JSON schema reference. — M
- [ ] **D-X-019** — Connector / BasePoller lifecycle section in `app_create.md`. — S
- [ ] **D-X-021** — `docs/disaster-recovery.md` — Patroni split-brain, ClickHouse replica wipe, central node lost runbooks. — L
- [ ] **D-COL-013** — Either retire `docs/collector-deployment-guide.md` or rewrite §4 to use `monctl_ctl deploy`. — M
- [ ] **D-INST-008 / D-INST-009** — Fix INSTALL.md PyPI vs. wheel order; reconcile installer version (0.1.0 vs 1.0.0). — XS

## Manual / "not code" follow-ups

- [ ] **CLAUDE.md "Known pitfalls"** — promote `project_rollup_chain_fragility` if M-CEN-016 confirms regression; otherwise update memory.
- [ ] **`feedback_pat_workflow_scope`** — D-CLA-005 confirms CLAUDE.md is wrong; either update CLAUDE.md or update memory based on current PAT state.
- [ ] **AAD binding + ciphertext version prefix** for `credentials/crypto.py` — deferred from #1; still open.
- [ ] **F-X-007 phase 2** — stub-collector E2E roundtrip; deferred from #1; T-X-003 captures the gap.
- [ ] **F-COL-031 hash enforcement** — deferred until packs supply hashes; still open.
- [ ] **CVE workflow** — `pip-audit` + `npm audit` runs nightly (#136); add an issue-creation step or webhook so HIGH findings reach a human.
- [ ] **Smoke-test the review** — pick 3 HIGH findings at random, open `file:line_range`, confirm code matches description.

---

## Progress

Wave 0 — pending. The `monctl_ctl upgrade` `_wait_healthy` regex bug is breaking customer upgrades right now and should land first.

Severity calibration: 42 HIGH findings vs. 21 in Review #1 — half is the brand-new customer installer attack surface, the other half is test-coverage gaps that #1 deferred. Effort-to-fix is still skewed small (most fixes are S, a handful M).

Carry-overs from #1 still open as of 2026-04-30:
- F-CEN-004 (login rate-limit) — confirmed open in S-CEN-004
- F-CEN-018 (WS query-param token fallback) — confirmed open in S-CEN-001
- AAD binding + ciphertext version prefix — explicitly deferred
- F-X-007 phase 2 — explicitly deferred at phase 1 landing
- F-COL-031 hash enforcement — deferred until packs supply hashes
