# MonCTL Code Review #2 — 2026-04-30

Eleven days after Review #1 closed Waves 1–3, ~60 commits have landed including three big new surfaces (customer installer, Superset SSO, severity-tier alerting redesign) and one full subsystem rewrite (event policy). This is a fresh top-to-bottom audit organised by topic — not by surface as in #1 — at the user's request.

## Deliverable

Seven topical reports + this index + a sequenced TODO. Every finding carries `file:line_range`, severity, and a concrete fix sketch. **No code is changed during this review** — same explicit triage-first decision as #1.

## Reports

| #   | Topic                                           | Findings | HIGH |
| --- | ----------------------------------------------- | -------- | ---- |
| 1   | [security.md](./security.md)                    | 47       | 7    |
| 2   | [performance.md](./performance.md)              | 31       | 6    |
| 3   | [reliability.md](./reliability.md)              | 30       | 6    |
| 4   | [testing.md](./testing.md)                      | 24       | 9    |
| 5   | [operability.md](./operability.md)              | 22       | 8    |
| 6   | [migration-safety.md](./migration-safety.md)    | 19       | 4    |
| 7   | [documentation.md](./documentation.md)          | 22       | 2    |
|     | **Total**                                       | **195**  | **42** |

## Severity counts

| Severity  | Sec | Perf | Rel | Test | Ops | Mig | Doc | **Total** |
| --------- | --- | ---- | --- | ---- | --- | --- | --- | --------- |
| CRITICAL  | 0   | 0    | 0   | 0    | 0   | 0   | 0   | **0**     |
| HIGH      | 7   | 6    | 6   | 9    | 8   | 4   | 2   | **42**    |
| MED       | 20  | 13   | 16  | 9    | 9   | 9   | 8   | **84**    |
| LOW       | 16  | 9    | 8   | 4    | 4   | 6   | 8   | **55**    |
| INFO      | 4   | 3    | 0   | 2    | 1   | 0   | 4   | **14**    |
| **Total** | **47** | **31** | **30** | **24** | **22** | **19** | **22** | **195** |

No CRITICAL findings, but 42 HIGH items vs. 21 in #1 — half of that is the customer installer (brand-new attack surface) and the test-coverage bucket (which #1 called out under F-X-007 but didn't audit comprehensively). Effort-to-fix is still skewed small (most fixes are S, a handful M).

## Top 25 to triage first (HIGH + critical-path MED)

### Customer installer (security + reliability)

1. **M-INST-013** — `_wait_healthy` regex matches `"success"`, but central returns `"healthy"` — every `monctl_ctl upgrade` aborts in production — S
2. **M-INST-010** — `init --force` regenerates ALL secrets, can wipe prod cluster auth — S
3. **M-INST-011 / S-COL-002 / S-X-002** — Installer ships shared `MONCTL_COLLECTOR_API_KEY` to every collector; bypasses per-collector auth from #120-#122 — M
4. **S-INST-001 / M-INST-015** — `tarfile.extractall` with no filter on customer-supplied bundles (RCE pre-3.12) — S
5. **S-INST-002** — Hardcoded prod IPs as Superset config defaults ship to customers — S
6. **S-INST-003** — Customer collector deploys with `MONCTL_VERIFY_SSL: "false"` hardcoded — S
7. **S-INST-004** — `paramiko.AutoAddPolicy()` MITM on first SSH connection + agent forwarding — S
8. **R-INST-001** — Installer `deploy()` has no transactional rollback on partial failure — M
9. **O-INST-001** — `monctl_ctl deploy` writes no audit/history; failures leave operator in the dark — M

### Central — alerting / OAuth / WS / collector-API

10. **R-CEN-001** — `set_latest_version` notifies WS *before* DB commit; rollback → fleet reads stale state — S
11. **R-CEN-002** — CH write-buffer silently drops every overflowing batch (data loss) — S
12. **R-CEN-003** — Automations engine spawns 3 fire-and-forget tasks without done-callback — S
13. **R-CEN-004 / R-CEN-005** — OS-install lease loss without driver halt; instance_id `"?"` fallback shared — S
14. **S-CEN-004** — `/v1/auth/login` still has no rate limit / lockout (carry-over F-CEN-004) — M
15. **S-CEN-010** — Action automations with `automation:create` execute arbitrary Python on central w/ secrets in env — M
16. **P-CEN-001 / P-CEN-006** — Alert engine evaluates definitions sequentially; `_sync_alert_instances` 2N PG queries — M

### Operability / observability

17. **O-CEN-002** — Alert engine cycle-skip log fires once per skip with no aggregate — S
18. **O-CEN-003** — Audit buffer overflow drops are pure-log; never surfaced — S
19. **O-CEN-004** — `/v1/system/health/status` cache-age not surfaced; frozen cache lies green — S
20. **O-CEN-010** — Sentinel `<quorum` count never goes degraded — S
21. **O-COL-001** — Forwarder dropped batches never reported to central via heartbeat — S
22. **O-X-001** — No platform-self alerting on degraded subsystems — M

### Tests / CI

23. **T-X-001** — No PR CI runs pytest, vitest, or pack validation. Branch-protection has nothing to enforce — S
24. **T-CEN-001 / T-CEN-002 / T-CEN-010 / T-CEN-011** — Alerting/incidents engines, OAuth provider, WS hub all have **zero tests** — L
25. **T-APP-001** — `walk_multi` SNMP connector path has no test (5 packs use it; one prior fleet-wide outage) — M

### Migration safety / DDL

26. **M-CEN-003 / M-CEN-006** — `ALTER TABLE … ADD COLUMN/INDEX` runs without `ON CLUSTER`; errors silently swallowed — S
27. **M-CEN-016** — Rollup chain regressed: shared try block per cycle, contradicts memory `project_rollup_chain_fragility` — S

### Documentation

28. **D-X-001 / D-X-002** — `app_create.md` orphaned at repo root + no central env-var reference — S each
29. **D-CLA-005** — CLAUDE.md PAT-workflow-scope pitfall is now wrong (memory updated 2026-04-21) — XS

(More than 25 items — kept all the HIGH-severity findings + the most actionable MEDs that unlock multiple HIGHs.)

## Methodology Notes

- **Direct reads** were done on the highest-blast-radius new files: `installer/{cli,commands/*,secrets/*,remote/*,render/engine}`, `auth/oauth.py`, `alerting/{dsl,engine}`, `audit/resource_map.py`, `collector_api/router.py` (selected sections), `ws/router.py`. Plus an alembic chain integrity check.
- **Seven general-purpose agents** swept the full repo by topic in two parallel waves. Each was given the Phase-1 inventory map plus a topic-specific prompt and the deliverable format.
- **Severity calibration** matches #1: I intentionally kept the HIGH list small (~42 items across 7 reports) so the triage list stays useful. A review that labels 100 items as HIGH is no review.
- **Permission-restricted files** (`credentials/crypto.py`) were already audited in `/docs/review/2026-04-19/crypto-review.md` — not re-audited here. AAD binding + ciphertext version prefix remain explicitly deferred.
- **Agent false-positives**: spot-checked S-CEN-016 (`aid_list` SQL string interp) and confirmed UUIDs are constrained to `[0-9a-f-]` — finding kept as drift-risk LOW. No major false positives surfaced.

## Verification

After this report lands, the recommended smoke test is:

1. Pick 3 HIGH findings at random — open the referenced `file:line_range`, confirm the code matches the description.
2. Run `pip-audit` + `npm audit` (already in CI from #136) and reconcile output against `security.md`.
3. Sanity-check `git diff --stat docs/review/2026-04-30/` is files-only — no accidental code edits.

## Not Covered (deferred)

- **Crypto deep-dive** — `credentials/crypto.py` already audited 2026-04-21; AAD/version-prefix work intentionally deferred.
- **Infrastructure configs** (HAProxy, Patroni, Redis Sentinel, etcd) — same as #1, review separately.
- **Load testing** — code-reading only, no production profiling data.
- **F-X-007 phase 2** (stub-collector E2E roundtrip) — explicitly deferred at phase 1 landing; T-X-003 captures the gap.
- **Inventory loader / Pydantic models** in installer — needs its own pass.
- **TLS certificate generation/rotation** in central — not sampled.
- **Patroni switchover endpoint** + `os_install_*` flow internals — admin-only, deferred.

## Memory Cross-References

These memory entries are evergreen and anchor the new findings:

- `feedback_per_row_multiplier_hits_limit` (perf — bucket history endpoints)
- `feedback_pack_first_import_race` (operability — benign on HA first-deploy)
- `feedback_superset_role_composition` (security — Alpha role lacks SQL Lab)
- `feedback_superset_theme_grayscale` (project — primary-only THEME_OVERRIDES)
- `feedback_httpx_cookies_assignment` (security — silent no-op on httpx 0.28+)
- `feedback_check_for_existing_helpers_first` (process — grep before adding)
- `project_no_gossip` (doc — confirmed zero gossip leftovers in README)
- `project_alerting_semantics` (security/correctness — fail-closed on CH errors verified)
- `project_superset_sso` (security — 9 non-obvious SSO quirks)
- `project_rollup_chain_fragility` (M-CEN-016 — flagged as REGRESSED — memory may be stale)
- `feedback_pat_workflow_scope` (D-CLA-005 — CLAUDE.md says lacks scope, memory says has scope as of 2026-04-21)

Memory entries flagged as needing update during this review: `project_rollup_chain_fragility` (verify against current code; if regressed, update + reopen finding) and `project_peer_token_per_host` (memory says per-host but installer ships shared — see M-INST-012).
