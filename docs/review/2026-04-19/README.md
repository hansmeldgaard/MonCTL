# MonCTL Code Review — 2026-04-19

Top-to-bottom audit of the codebase for **security, bugs, and performance**. The platform is almost entirely AI-authored (Claude Code), so this review focuses on the classes of issues AI tends to produce: over-broad exception handling, missing boundary checks, unverified assumptions, and copy-paste drift.

## Deliverable

Four per-surface reports + one cross-cutting report + this index. Each finding has a `file:line_range`, severity, and a concrete fix sketch. **No code was changed during this review** — explicit user decision to triage first.

## Reports

| #   | File                                             | Scope                                                            | Findings |
| --- | ------------------------------------------------ | ---------------------------------------------------------------- | -------- |
| 01  | [01-central-backend.md](./01-central-backend.md) | FastAPI / auth / SQL / ClickHouse / alerting / audit / scheduler | 49       |
| 02  | [02-collector.md](./02-collector.md)             | Polling engine / gRPC / WebSocket / credentials / forwarder      | 50       |
| 03  | [03-apps-packs.md](./03-apps-packs.md)           | Built-in BasePoller apps + pack JSON                             | 14       |
| 04  | [04-frontend.md](./04-frontend.md)               | React 19 + TypeScript + React Query                              | 33       |
| 99  | [99-cross-cutting.md](./99-cross-cutting.md)     | Multi-surface initiatives                                        | 11       |

## Severity Counts

| Severity  | Central | Collector | Apps/Packs | Frontend | Cross-cut | **Total** |
| --------- | ------- | --------- | ---------- | -------- | --------- | --------- |
| CRITICAL  | 0       | 0         | 0          | 0        | 0         | **0**     |
| HIGH      | 7       | 11        | 0          | 2        | 1         | **21**    |
| MED       | 26      | 28        | 5          | 14       | 8         | **81**    |
| LOW       | 14      | 11        | 8          | 14       | 2         | **49**    |
| INFO      | 2       | 0         | 1          | 3        | 0         | **6**     |
| **Total** | **49**  | **50**    | **14**     | **33**   | **11**    | **157**   |

Note: no CRITICAL findings, but 21 HIGH items — most are either security (collector trust boundary, cookies, rate-limiting) or perf (ClickHouse async, refetch storms). Effort is skewed small (S = <1h).

## Top 30 to triage first (HIGH + high-value MED)

### Security

1. **F-X-001** — Per-collector API keys (umbrella fix for F-CEN-014/015/016 + F-COL-026) — L
2. **F-CEN-001** — Cookies `secure=False` hardcoded — S
3. **F-CEN-004** — No rate-limit on `/v1/auth/login` — M
4. **F-CEN-014** — Collector can submit results for any job — M
5. **F-CEN-015** — Collector can fetch any credential by name — M
6. **F-CEN-037** — Logs endpoint has no tenant filter — L
7. **F-COL-030** — Pip `__token__` leaks via subprocess env — M
8. **F-COL-031** — Pip requirements not validated (RCE if pack compromised) — M
9. **F-COL-044** — Container logs shipped verbatim (secret leak) — M
10. **F-COL-011** — Path traversal via `app_id` in URL — S
11. **F-WEB-001** — `ConfigDataRenderer` iframe XSS — M
12. **F-CEN-012** — Non-constant-time comparison of shared secret — S

### Reliability / Correctness

13. **F-CEN-024** — `_LockedClient` serialises every ClickHouse call — L
14. **F-CEN-025** — Sync CH calls block event loop — L
15. **F-CEN-044** — WebSocket manager bare-excepts — S
16. **F-CEN-041** — Fire-and-forget tasks swallow exceptions — S
17. **F-COL-022** — No handler timeout on WS commands — S
18. **F-COL-036** — SQLite result buffer grows unbounded — M
19. **F-COL-020** — WS reconnect thundering herd — S
20. **F-COL-047** — Empty `central.url`/`api_key` silently accepted — S
21. **F-APP-001** — `snmp_discovery` calls `snmp.connect()` — S
22. **F-CEN-042** — 30s alert cycle can overlap itself — S

### Performance

23. **F-WEB-010** — `refetchInterval` in background tabs — S
24. **F-CEN-027** — Dashboard runs 4 CH queries sequentially — S
25. **F-WEB-014** — Global `staleTime: 0` refetch storm — S

### Observability / Quality

26. **F-APP-006** — Reference SNMP apps have zero debug traces — S each
27. **F-APP-004** — Hardcoded `error_category="device"` across apps — S each
28. **F-X-003** — Audit gap for background-task mutations — M
29. **F-X-006** — Secret redaction is substring-based and distributed — M
30. **F-X-007** — No E2E integration tests — L

## Methodology Notes

- **Direct reads** were done on the highest-blast-radius files: `dependencies.py`, `auth/router.py`, `audit/db_events.py`, `scheduler/leader.py`, `polling/engine.py`, `api/client.ts`. Agents supplied detail sweeps for the rest.
- **Permission-restricted files** (`credentials/crypto.py`, parts of `credentials/` and `audit/`) are flagged in the relevant reports' "Gaps" sections and need human eyes.
- **Severity calibration**: I intentionally kept the HIGH list small (21 items) to preserve triage value. A review that labels 80 items as HIGH is no review at all.
- **Agent false-positives**: one flagged race condition in the token-refresh code turned out not to exist (see F-WEB-004). I re-verified claims where the mechanism was subtle; treat the remaining HIGH findings as "worth verifying before fixing" rather than "definitely broken."

## Verification

After the report lands, a reasonable smoke test is:

1. Pick any 3 HIGH findings at random.
2. Open the referenced `file:line_range`.
3. Confirm the code matches the report's description.

If any reference is stale, flag that section for re-audit.

## Not Covered (deferred)

- **Infrastructure configs** (HAProxy, Patroni, Redis Sentinel, etcd) — review separately.
- **Third-party CVE scan** — pending (`pip-audit`, `npm audit` — see F-X-008).
- **Load testing** — no production profiling data used; all perf findings are code-reading-only.
- **Crypto review of `credentials/crypto.py`** — permission-restricted from this session.

## Memory Cross-References

This review cites these memory entries as known landmines that remain relevant:

- `feedback_app_timing_placement`
- `feedback_app_debug_logging`
- `feedback_ch_mv_schema_migrations`
- `feedback_per_entity_filtering`
- `feedback_dict_get_none`
- `feedback_no_fallback_patterns`
- `project_rollup_chain_fragility`
- `project_collector_memory`
- `project_snmp_connector_version_key`

Many of these should graduate to `CLAUDE.md` under a "Known pitfalls" section (F-X-011).
