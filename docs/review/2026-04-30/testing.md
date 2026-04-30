# Testing Findings — Review #2 (2026-04-30)

## Summary

- **24 findings**: 9 HIGH / 9 MED / 4 LOW / 2 INFO
- **No CI gate runs Python or frontend tests on PRs.** `security-audit.yml` is the only Python CI; `release.yml` only builds images. There is no test workflow.
- **Test:source ratio ~10:1.** `packages/central/src` ~45.5k LoC, central tests ~1.6k LoC. Total tests across all surfaces: ~5.4k LoC over 25 test files.

| Subsystem (LoC)                             | Tests?              | Quality                     |
| ------------------------------------------- | ------------------- | --------------------------- |
| `auth/oauth.py` (511 LoC)                   | **None**            | —                           |
| `alerting/engine.py` (814 LoC)              | **None**            | DSL unit tests only         |
| `incidents/engine.py` (814 LoC)             | **None**            | —                           |
| `alerting/threshold_sync.py` (120)          | **None**            | —                           |
| `alerting/instance_sync.py` (91)            | **None**            | —                           |
| `incident_rules/router.py` (460)            | **None**            | —                           |
| `collector_api/router.py` (2698 LoC)        | Partial (auth only) | ~5 mocked tests             |
| `ws/connection_manager.py` (456)            | **None**            | —                           |
| `ws/auth.py` (72)                           | **None**            | —                           |
| `audit/db_events.py` (159)                  | **None**            | resource-map coverage only  |
| Installer (3.2k LoC)                        | 1.3k LoC, 11 files  | All `SSHRunner` is faked    |
| Collector (6.9k LoC)                        | 246 LoC, 2 files    | only peer-auth + pip-validate |
| Frontend (~140 .tsx files)                  | 2 test files        | utils + useListState only   |
| `walk_multi` SNMP connector path            | **None**            | shipped in 5 packs          |
| Severity-tier eval (PR #38)                 | **None**            | DSL only                    |
| Event-policy rework (PRs #20–#33)           | **None**            | —                           |
| ClickHouse pool                             | Yes                 | `test_clickhouse_pool.py`   |
| Eligibility OID                             | Yes                 | `test_eligibility.py` (450 LoC) |

**Executive summary:** Coverage breadth has grown since Review #1 (DSL adversarial corpus, peer-auth, pip-validate, audit-map, eligibility, CH pool, installer surface), but it has **not kept up with the major new subsystems shipped this cycle**. The alerting engine, incidents engine, OAuth provider, WS hub, and walk_multi connector path — all critical-path code — have **zero tests**. The most acute structural problem is that **no CI workflow runs `pytest` or `vitest` on a PR**. A PR that breaks login, the alerting engine, OAuth, or the installer can land green. Re-add a test workflow before treating any other finding here as urgent.

---

## Findings

### CI / workflow gaps

### T-X-001 — No PR CI runs pytest, vitest, or pack validation
**Severity**: HIGH
**File**: `.github/workflows/` (4 files: claude.yml, claude-code-review.yml, release.yml, security-audit.yml)
**Description**: Of the four workflows, two are Claude wrappers, `release.yml` triggers only on tag push, and `security-audit.yml` runs `pip-audit` + `npm audit` on PRs that touch `pyproject.toml` / `package.json`. **None of them invoke `pytest`, `vitest`, or `scripts/validate_packs.py`.** PRs that delete or break tests cannot be detected by branch protection because there is no required check.
**Fix sketch**: Add `.github/workflows/tests.yml` that runs on `pull_request` with three jobs: pytest against `tests/`, `packages/central/tests/`, `packages/installer/tests/`; vitest on the frontend; `python scripts/validate_packs.py`. Mark all required in branch protection.

### T-X-002 — No coverage reporting in CI
**Severity**: MED
**File**: `packages/central/pyproject.toml:65-67`, `.github/workflows/`
**Description**: `[tool.coverage.run]` exists in `packages/central/pyproject.toml` and `pytest-cov>=5.0` is a dev dep, but no workflow invokes `pytest --cov`.
**Fix sketch**: In CI test job, run `pytest --cov=monctl_central --cov-report=xml`, upload artifact, fail PR on coverage drop on touched files below 60%.

### T-X-003 — `e2e_smoke` harness never runs in CI
**Severity**: MED
**File**: `scripts/run_e2e.sh`, `docker/docker-compose.e2e.yml`, `tests/integration/test_e2e_smoke.py:1-71`
**Description**: F-X-007 phase 1 shipped the harness, but `run_e2e.sh` is invoked only manually. The compose file rots the moment the API surface drifts. The test file has a 2-second poll loop after DELETE (line 62-70) which is exactly the flaky-test smell.
**Fix sketch**: Add an `e2e` job to the new tests workflow. Replace polling loop with a no-cache request or fix the FastAPI yield-commit ordering at the source.

### T-X-004 — Branch protection cannot be enforced without required checks
**Severity**: MED
**File**: `.github/workflows/`
**Description**: Without a test workflow, GitHub branch protection has nothing to require. The `feedback_squash_merge_drops_dev_fixes` memory is exactly this risk.
**Fix sketch**: Once T-X-001 lands, configure branch protection on `main` to require: tests, vitest, validate_packs, pip-audit, npm-audit. Tie reviewer dismiss-on-update.

### T-X-005 — `security-audit.yml` log artifact has no consumer
**Severity**: LOW
**File**: `.github/workflows/security-audit.yml:40-63`
**Description**: Nightly schedule produces JSON output but `audit.json` is never uploaded as an artifact and only printed to stdout. If a HIGH/CRITICAL is reported, no one is notified.
**Fix sketch**: Add `actions/upload-artifact` for `audit.json`, post to a webhook, or open a labelled issue automatically.

---

### Central — alerting / incidents / events

### T-CEN-001 — Alerting engine has zero tests
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/alerting/engine.py:1-814`
**Description**: 814-line engine implementing PR #38's tier model has **no test file**. `tests/central/test_dsl_*.py` covers only the DSL compiler. Healthy-tier signal handling, escalate→downgrade transitions exist only as production code.
**Fix sketch**: Add `tests/central/test_alerting_engine.py` with a fake CH client. Cover: fire→escalate→downgrade→clear with healthy tier; blank-healthy auto-clear; fail-closed on CH timeout (preserve active alert). Mirror the per-row freshness check from `feedback_per_entity_filtering` as a regression test.

### T-CEN-002 — Incidents engine has zero tests
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/incidents/engine.py:1-814`
**Description**: 814 LoC of correlation/promotion logic from PRs #20–#33. The `project_incidents_next` memory itself flags "Incidents subsystem needs review after tier redesign; stale child-rule wiring points at merged-away defs".
**Fix sketch**: Add `tests/central/test_incidents_engine.py`: incident open on first matching policy hit, close on healthy clear, tier upgrade transitions, idempotency on engine restart.

### T-CEN-003 — Threshold + instance sync workers untested
**Severity**: MED
**File**: `packages/central/src/monctl_central/alerting/threshold_sync.py:1-120`, `alerting/instance_sync.py:1-91`
**Description**: PR #134 (threshold-name collision) was fixed at the DSL layer; the sync layer's role in that bug has no test asserting it.
**Fix sketch**: Add a SQLite-backed unit test that runs `sync_thresholds()` with two tiers compiling to the same threshold name and asserts only one row materialises with the correct value.

### T-CEN-004 — `audit/db_events.py` SQLAlchemy listener has no behavioural test
**Severity**: MED
**File**: `packages/central/src/monctl_central/audit/db_events.py:1-159`
**Description**: `test_audit_resource_map_coverage.py` proves the *whitelist* is complete, but the actual `before_flush` listener that walks `session.new/dirty/deleted`, extracts `attrs.history`, and stages rows is untested.
**Fix sketch**: Use the existing SQLite session fixture, perform Device CRUD, and assert the audit context buffer gained the expected rows with redacted password fields.

### T-CEN-005 — Redaction in `audit/diff.py` not unit-tested
**Severity**: MED
**File**: `packages/central/src/monctl_central/audit/diff.py:1-75`
**Description**: Per CLAUDE.md the redactor matches `password`, `api_key`, `token`, `secret`, `jwt_secret`, `credential_value`, `private_key`. There's no test asserting the patterns match the documented set or that nested JSONB fields are redacted.
**Fix sketch**: Add `test_audit_diff.py` parameterised over each documented field name and a few negatives (e.g. `passwordless_login`).

---

### Central — auth / OAuth / WS / collector_api

### T-CEN-010 — OAuth2 provider has zero tests
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/auth/oauth.py:1-511`
**Description**: 511-line OAuth provider shipped for Superset SSO with **no tests**. CLAUDE.md calls out 9 quirks (manifest prefix, Location rewrite, DispatcherMiddleware) any of which could regress.
**Fix sketch**: Add `tests/central/test_oauth.py`: code-flow happy path, invalid `client_id`, invalid `redirect_uri` (exact-match), code reuse rejected, missing/empty `oauth_redirect_uris`, ID-token claims correctness.

### T-CEN-011 — WS auth + connection manager have zero tests
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/ws/auth.py:1-72`, `ws/connection_manager.py:1-456`
**Description**: PR #115/#120/#122 added per-collector key + WS auth header. Server-side WS auth has no tests. `feedback_broadcast_command_unwrap` is a recently-fixed bug class with no regression test.
**Fix sketch**: Add `tests/central/test_ws_auth.py` exercising `verify_collector_token`. Add `test_connection_manager.py` covering `broadcast_command` payload-unwrapping (the fixed bug) and target filtering.

### T-CEN-012 — `collector_api/router.py` (2698 LoC) only auth-tested
**Severity**: HIGH
**File**: `packages/central/src/monctl_central/collector_api/router.py:1-2698`
**Description**: 2698 LoC handling `/api/v1/jobs`, `/api/v1/results`, `/api/v1/credentials`. Delta-sync `updated_at > since` (CLAUDE.md "Known pitfalls") has no test.
**Fix sketch**: Add SQLite fixtures: (1) creating an assignment makes it visible to delta-sync; (2) updating with `onupdate=now()` propagates; (3) raw-SQL update without `updated_at` does NOT propagate (sentinel for the documented gotcha).

### T-CEN-013 — Per-collector key `/jobs` enforcement covered, but `/results` and `/credentials` are not
**Severity**: MED
**File**: `tests/central/test_collector_auth.py:111-228`
**Description**: F-CEN-014 enforcement is asserted for `/jobs`. `/results` and `/credentials` POST endpoints accept the same `auth` dict but no test that they reject mismatched `collector_id`.
**Fix sketch**: Apply same parameterised test pattern for the result-ingest and credential-fetch endpoints.

---

### Connectors / packs / apps / walk_multi

### T-APP-001 — `walk_multi` SNMP connector path has no test
**Severity**: HIGH
**File**: SNMP connector source ships in `packs/snmp-core.json`
**Description**: `walk_multi` shipped in 5 packs (entity_mib_inventory, cisco_env_health, cisco_cpu_memory, cisco_health_status, juniper_health_status). The connector source isn't in the repo, so connector regressions are caught only at runtime in prod. **No test exercises the multi-OID walk path** — `feedback_connector_version_fallback` notes the SNMPv3 fleet-wide outage.
**Fix sketch**: Vendor the SNMP connector source into `packages/central/tests/fixtures/connectors/snmp.py` and add `tests/central/test_snmp_connector_compat.py` parameterised over every credential-key alias every prod template emits.

### T-APP-002 — Pack validation script doesn't enforce required_connectors aliases
**Severity**: LOW
**File**: `scripts/validate_packs.py:90-95`, `tests/central/test_pack_validation.py:96-114`
**Description**: `validate_packs.py` checks `required_connectors` is `list[str]` but doesn't check the value is a known connector type. A typo (`snmp_v3`) would not surface until runtime when the pack is imported.
**Fix sketch**: Maintain `_KNOWN_CONNECTOR_TYPES` in the validator; reject unknown values.

### T-APP-003 — Pack validation has no `error_category` audit
**Severity**: LOW
**File**: `scripts/validate_packs.py:90-115`
**Description**: CLAUDE.md mandates every error `PollResult` set `error_category` to `"device" | "config" | "app"`. Pack validation runs `compile()` but doesn't AST-walk to assert each `PollResult(...)` with non-empty `error=` also passes `error_category=`.
**Fix sketch**: Use `ast.NodeVisitor` to find `PollResult` constructions; assert that any `keywords` containing `error=...` (non-empty) also has `error_category=`.

### T-APP-004 — Pack-import path is not tested (connector_declaration only at parser level)
**Severity**: LOW
**File**: `packages/central/tests/unit/test_connector_declaration.py:1-206`
**Description**: AST extractor for `required_connectors` is well-tested. Integration: when a pack JSON is imported, does central correctly pre-create one slot per declared connector, and are slot bindings idempotent? `feedback_pack_first_import_race` flags exactly this surface as racy on HA.
**Fix sketch**: Add a SQLite-backed test that imports a tiny pack and asserts `app_connector_bindings` has the expected rows. Re-import and assert idempotency.

---

### Installer

### T-INST-001 — Every installer test mocks `SSHRunner` — no integration coverage
**Severity**: MED
**File**: `packages/installer/tests/test_deploy.py:29-58`, `test_preflight.py:14-25`, `test_status.py:13-19`, `test_upgrade.py:22-46`
**Description**: All 11 installer test files use `FakeRunner` / `StubRunner`. The actual `paramiko` SSH path in `remote/ssh.py` (130 LoC) is unexercised. Customer onboarding bet on this CLI.
**Fix sketch**: Add `tests/installer/integration/test_ssh.py` that boots a sshd via testcontainers and exercises the real `SSHRunner`. Gate behind a `slow` marker.

### T-INST-002 — `test_dry_run_does_not_touch_state` assertion is structurally weak
**Severity**: LOW
**File**: `packages/installer/tests/test_deploy.py:123-132`
**Description**: The assertion `assert all(... or len(runner.uploads) == 0)` short-circuits on `len(runner.uploads) == 0`, always true on first deploy.
**Fix sketch**: Drop the compound `or`: `assert runner.uploads == {}` and add `assert all("docker compose up" not in cmd for _, cmd in runner.runs)` separately.

### T-INST-003 — No test for `remote/preflight.py` failure-aggregation edge cases
**Severity**: LOW
**File**: `packages/installer/tests/test_preflight.py:54-165`, `remote/preflight.py:1-271`
**Description**: Five tests cover a few cases but no test for: rc=1 with mixed stderr; `df -BG` returning non-numeric; multi-host plan where one host fails and others pass.
**Fix sketch**: Parameterise the responder by fault-class; assert `preflight.results` aggregates per-host correctly.

### T-INST-004 — `test_init.py:test_cli_init_interactive_single_host` is brittle re: prompt order
**Severity**: LOW
**File**: `packages/installer/tests/test_init.py:94-126`
**Description**: Feeds 11 newline-separated answers in a specific order. Any reorder of prompts silently breaks the binding; subsequent assertions might still pass via defaults.
**Fix sketch**: Use `click`'s `runner.invoke(input=...)` with explicit per-prompt expectations or break the wizard into individual functions.

---

### Frontend / Vitest

### T-WEB-001 — Only 2 frontend test files for ~140 .tsx components
**Severity**: HIGH
**File**: `packages/central/frontend/src/lib/utils.test.ts`, `hooks/useListState.test.tsx`
**Description**: F-WEB-030 set up vitest+jsdom+RTL but only `formatBytes`/`formatUptime`/`timeAgo` and `useListState` are tested. Zero React component tests, zero page tests, zero API hook tests. PR #132/#133 (DeviceDetailPage tab split — 12 tabs) shipped without a single Vitest assertion.
**Fix sketch**: Add tests for: `useColumnConfig.compact()` preserving `hidden:false`; FlexTable filter+sort interaction; `usePermissions` hook gating; DeviceDetailPage tab routing.

### T-WEB-002 — Schema-drift telemetry has no test
**Severity**: LOW
**File**: `packages/central/frontend/src/api/client.ts` (`apiGetSafe`)
**Description**: `feedback_schema_drift_telemetry` documents `apiGetSafe` is console.warn telemetry. No test asserts that a schema mismatch logs a warning rather than throwing.
**Fix sketch**: Add `client.test.ts` with two cases: schema-match (no warn), schema-drift (one console.warn, returns parsed data anyway).

---

### Cross-cutting

### T-X-006 — No regression tests for fixes shipped since Review #1
**Severity**: MED
**File**: Multiple PRs since Review #1
**Description**: PR #134 (threshold-name collision — only DSL-layer test exists), PR #138 (device thresholds tab repair), PR #140 (sidecar push env), PR #141 (db_size_history bucketing — no `test_metrics_history_bucketing.py`).
**Fix sketch**: For every Wave-2 review item that's marked done, add a single failing-on-old-code test. The DSL equality-literal test is the model.

### T-X-007 — Test environment files leak credentials into git-tracked configs
**Severity**: INFO
**File**: `docker/docker-compose.e2e.yml:62-64`
**Description**: Hex strings for `MONCTL_ENCRYPTION_KEY` and `MONCTL_JWT_SECRET_KEY` are committed in plaintext. Test-only, but they look like production secrets.
**Fix sketch**: Move them to `.env.e2e` (gitignored or `.example` only) and pass via `env_file:`. Or generate at boot via the harness `up` step.

### T-X-008 — No fuzz / property-based tests
**Severity**: INFO
**File**: Repo-wide
**Description**: The DSL adversarial corpus is curated but not fuzzed. `hypothesis` isn't a dependency. The DSL is the highest-leverage place to add property-based tests.
**Fix sketch**: Add `hypothesis` to central dev-deps; property test that for any string the tokenizer accepts, the compiled SQL has matched quotes and no SQL keywords outside the predefined HAVING clause.
