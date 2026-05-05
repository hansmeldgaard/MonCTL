# MonCTL Review #2 — Follow-up TODO

**Start here in future sessions.** Sequenced from cheapest-most-valuable to largest-strategic. Each item links back to the finding(s) where the file/line details live.

> Last refresh: **2026-05-05**. Items checked off here have been verified
> against the current source tree (not just claimed in commit messages).
> Wave 2 (per-collector keys at install time) closed 2026-05-04; the
> Wave 4 / 7 / 9 partial-opens at the previous refresh have all shipped
> in PRs #168, #181–#185, #190, #191. Remaining work is the longer-tail
> docs bucket plus a handful of MED items (`S-X-003`, `T-WEB-001`
> remainder, `T-X-006` remainder for PRs #134/#138/#140).

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
- [x] **O-CEN-008** — Drifted connector names persisted to Redis set `monctl:connectors:drifted`; surfaced via `_check_connectors` system-health subsystem (PR #181, `tests/unit/test_connectors_drift_health.py`).
- [x] **O-CEN-010** — Sentinel quorum check; degraded at floor.
- [x] **O-COL-001** — Heartbeat carries forwarder dropped counters; central stores + surfaces.
- [x] **O-X-001** — `_subsystem_health_checks()` shapes every `_check_*` into the existing fire/clear loop; degraded → warning, critical → critical alert_log rows routed through IncidentEngine (PR #190, `tests/unit/test_subsystem_health_alerts.py`).
- [x] **O-INST-001** — `monctl_ctl deploy` writes `/opt/monctl/.deploy-history.jsonl` per host on every `_apply_project` (PR #184). POST-to-central side intentionally deferred (would need a new endpoint + connected-mode plumbing for marginal value over the JSONL; revisit if customer asks).

## Wave 5 — Audit completeness

- [x] **S-CEN-018** — `api_keys` mapped in `TABLE_TO_RESOURCE` as `"api_key"` with `key_hash` redaction.
- [x] **S-CEN-019** — `assignment_credential_overrides` mapped as `"assignment_credential_override"`.
- [x] **S-X-003** — `record_manual_action` helper in `audit/manual.py` stages a row on the request-scoped `AuditContext.mutations` list with the same shape the auto-listener produces. Wired at the two surfaces that mutate `incidents` / `alert_entities` (both opted out of the auto-listener to avoid engine-tick noise): `POST /v1/incidents/clear` → `incident_action` (action=`clear`), `PUT /v1/alerts/instances/{id}` enabled-flip → `alert_entity_action` (action=`silence` / `unsilence`). Pinned by `tests/unit/test_audit_manual_actions.py` (5 tests covering shape, both resource types, redaction, no-context safety, empty-diff handling).
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
- [~] **T-WEB-001** — `usePermissions` hook + `useColumnConfig.compact()` regression tests shipped (PR #183). FlexTable filter+sort and DeviceDetailPage tab-routing tests still open. — S (partial)
- [x] **T-X-006** — Regression tests for every Wave-2 fix shipped since Review #1 are now in place: PR #134 → `tests/central/test_dsl_equality_literals.py`; PR #138 → `packages/central/tests/unit/test_device_thresholds_post_pr38.py`; PR #140 → `tests/test_compose_sidecar_push_env.py`; PR #141 → `packages/central/tests/unit/test_bucket_step.py`.
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

- [x] **M-CEN-003 / M-CEN-004 / M-CEN-006** — `_apply_on_cluster` helper injects `ON CLUSTER '<name>'` for ALTERs; the bare `try/except: pass` around DDL loops became per-statement WARNING logs with full SQL in the same PR (#168).
- [x] **M-CEN-005** — Generic `_ensure_mv_columns` helper rebuilds drifted `*_latest` MVs (PR #182, `tests/unit/test_mv_drift_rebuild.py`).

## Wave 10 — Documentation cleanup

- [x] **D-X-002** — `docs/env-reference.md` enumerates every `MONCTL_*` env var; refreshed for `MONCTL_REQUIRE_PER_COLLECTOR_AUTH` in PR #191.
- [x] **D-CLA-004** — Six new pitfalls appended to CLAUDE.md from feedback memory: empty UI as a 500, compose orphan cleanup, httpx 0.28 cookies no-op, deploying off a stale branch rolling back sibling fixes, diffing prod `is_latest` before bumping a connector, re-investigating raw data when a symptom recurs.
- [x] **D-CEN-020** — Tagged the two `/api/v1/*` parent routers (`collector-api`, `docker-push`) at `main.py` mount time so OpenAPI no longer drops them in the unnamed "default" bucket; documented the include-time-tags convention + canonical mount points (`api/router.py`, `main.py`) under CLAUDE.md API Conventions. Verified end-to-end via `app.openapi()`: 43 distinct tags, zero untagged endpoints.
- [x] **D-X-018** — `docs/pack-format.md` (~420 lines) covers top-level fields, all 8 valid `contents` sections (apps, connectors, credential_templates, snmp_oids, device_templates, device_categories, device_types, label_keys) with field-level reference tables, the three-layer versioning model (pack / app+connector / `monctl_pack` schema), skip-resolution import order, and a copy-pasteable worked example. CLAUDE.md "App & Pack System" + `app-development-guide.md` Pack JSON Structure both link to it.
- [x] **D-X-019** — `docs/app-development-guide.md` now has an "Engine Lifecycle — What Happens Per Job" section: 8 numbered steps (app load → credential resolve → connector instantiate+connect → context build → setup/poll/timeout → error-category guard → connector close → gc.collect + malloc_trim) with the failure-classification mapping per phase, plus the two rules the lifecycle imposes on app authors (never call `connector.connect()`; no module-globals because the engine returns memory each job).
- [x] **D-X-021** — `docs/disaster-recovery.md` (~440 lines) ships five runbooks for the 3 a.m. operator: (1) central node lost, (2) Patroni split-brain / etcd stale leader (etcd reset + force re-election + `patronictl reinit`), (3) ClickHouse replica wiped (auto-cleanup explanation + manual `SYSTEM DROP REPLICA` fallback), (4) Redis Sentinel quorum corrupt (coordinated 3-sentinel restart pattern), (5) total cluster loss restore from backups (with the `secrets.env` / `MONCTL_ENCRYPTION_KEY` recovery decision tree). Each ends with a `monctl_ctl status` verify block. Cross-linked from `TROUBLESHOOTING.md` "Where to look next" and `INSTALL.md` §9 Day-two operations.
- [x] **D-COL-013 / D-COL-014** — `docs/collector-deployment-guide.md` reframed as per-host reference rather than a deployment runbook: the maintainer-only "MAINTAINER REFERENCE" banner is gone, §4 now points at `monctl_ctl deploy` + INSTALL.md and explains the rendered `.env` (per-host key, peer-token-seed derivation, `VERIFY_SSL` defaulting to `true`), the prod-IP `10.145.210.40` references in §2 / §8 are removed, and the `VERIFY_SSL=false` example is replaced with a default-true block + a note on when to flip it (closes D-COL-014).
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

**All 42 HIGH-severity findings closed.** Wave 2 (per-collector keys
at install time), Wave 4 (observability), Wave 5 (audit completeness),
Wave 7 (test coverage), Wave 8 (perf), Wave 9 (DDL idempotence) all
substantively closed.

Wave 10 (docs) is also fully closed across PRs #169, #191, #192,
#193, #194, #195, #196, #198 — covering env-reference, CLAUDE.md
pitfalls, OpenAPI tag taxonomy, app-dev lifecycle, collector guide
rewrite + verify_ssl fix, pack-format reference, and disaster-recovery
runbooks.

Remaining open is the Wave 7 frontend long-tail (FlexTable filter+sort

- DeviceDetailPage tab-routing in `T-WEB-001`) plus the four manual
  "not code" follow-ups from Review #1: AAD binding + ciphertext version
  prefix on `credentials/crypto.py`, F-X-007 phase 2 (e2e-smoke flake),
  F-COL-031 hash enforcement, and the CVE workflow human-routing step.
