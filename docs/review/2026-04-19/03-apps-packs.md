# 03 — Built-in Apps & Packs Review

**Scope**: `apps/*.py` (reference BasePoller source) + `packs/*.json` (built-in packs including embedded Python for ping/port/http).
**Date**: 2026-04-19
**Methodology**: agent sweep of all 4 reference apps and 2 pack files (and the 3 embedded pack-only apps), plus direct verification of the one HIGH-ish finding.

Unique IDs use prefix `F-APP-`.

---

## 1. Connector Lifecycle

### F-APP-001: `snmp_discovery` calls `snmp.connect()` itself — engine already does this

- **Severity**: MED (downgraded from the agent's initial "HIGH" after verification — the SNMP connector has an idempotent-connect guard from PR #16 per `project_collector_memory` memory, so this is not a new leak; it _was_ exactly the pattern that caused the memory leak we fixed)
- **Category**: connector lifecycle
- **File**: `apps/snmp_discovery.py:87` — `await snmp.connect(host)`
- **Problem**: Per CLAUDE.md and polling/engine.py:322-323, the engine calls `connector.connect()` before invoking `poller.poll(ctx)`. Apps calling `.connect()` themselves is explicitly prohibited. The SNMP connector now guards against double-connect with an idempotent check, so the immediate risk is low — but the app is still violating the contract and if a future connector type is introduced without the guard, this pattern will re-open the leak.
- **Impact**: None today; regression risk later.
- **Fix**: Delete line 87. The engine has already connected the connector by the time `poll()` runs.
- **Effort**: S (single line + pack version bump)

Grep confirms this is the ONLY occurrence across `apps/` — other apps correctly omit the call.

---

## 2. Timing Hygiene (`feedback_app_timing_placement`)

### F-APP-002: Mixed `time.monotonic()` vs `time.time()` across SNMP apps

- **Severity**: LOW (metric correctness)
- **Files**:
  - `apps/snmp_discovery.py:85, 162` (monotonic for duration, wall-clock for `timestamp`)
  - `apps/snmp_uptime.py:68, 72, 138` (same pattern)
  - `apps/snmp_check.py:49-52` (same pattern)
- **Problem**: These apps use `time.monotonic()` for `execution_time_ms` but `time.time()` for the result `timestamp`. Monotonic is correct for interval measurement (no NTP jumps) but the two are not aligned — on a server right after an NTP step, `timestamp - execution_time_ms/1000` can drift from `started_at` by seconds. Not wrong per se, but inconsistent with the pack-only apps (ping, port, http) which all use `time.time()` exclusively.
- **Fix**: Standardise on `time.time()` for both, matching the pack apps and the `feedback_app_timing_placement` memory (which says `start = time.time()` must be the first line).
- **Effort**: S (per file)

### F-APP-003: `http_check` computes `elapsed_ms` at different points on different branches

- **Severity**: LOW
- **File**: `packs/basic-checks-v1.0.0.json` → embedded `http_check.py:244` (aiohttp path ~line 219 vs urllib path ~line 225)
- **Problem**: On the aiohttp branch `elapsed_ms` is computed _inside_ the `async with`; on the urllib fallback it's computed _after_. Marginal skew only, but the result fields are not directly comparable across branches.
- **Fix**: Move `elapsed_ms = int((time.time() - start) * 1000)` to a single location immediately before the return.
- **Effort**: S

---

## 3. Error Categorization

### F-APP-004: All SNMP apps default every `except Exception` to `error_category="device"`

- **Severity**: MED (observability / alerting correctness)
- **Files**:
  - `apps/snmp_check.py:74-91`
  - `apps/snmp_interface_poller.py:281-293`
  - `apps/snmp_discovery.py:175-192`
  - `apps/snmp_uptime.py:137-151`
- **Problem**: A bare `except Exception` with hardcoded `error_category="device"` conflates (a) genuine device-unreachable errors, (b) connector misconfiguration, (c) bugs inside the app itself. The alerting engine uses `error_category` to route alerts; today all SNMP app crashes look like "device unreachable" in dashboards. Note that polling/engine.py:370-371 also has an "auto-fill device" fallback for error results with no category — so bugs get two layers of misclassification. See also F-COL-003.
- **Fix**: Categorise explicitly:
  - `asyncio.TimeoutError`, `ConnectionError`, PySNMP `NoResponseError` → `"device"`
  - `KeyError`, missing config fields, type errors in `context.parameters` → `"config"`
  - anything else (incl. `AttributeError`, `ValueError` from parsing) → `"app"`
- **Effort**: S per app

### F-APP-005: `http_check` does not distinguish SSL/URL-parsing errors from device errors

- **Severity**: LOW
- **File**: `packs/basic-checks-v1.0.0.json` → `http_check.py:289-309`
- **Fix**: Catch `ssl.SSLError`, `aiohttp.InvalidURL` and map them to `"config"` (caller misconfigured the URL / cert).
- **Effort**: S

---

## 4. Debug Logging Density (`feedback_app_debug_logging`)

### F-APP-006: Reference SNMP apps have **zero** `logger.debug(...)` calls

- **Severity**: MED (debuggability — especially given the Debug Run feature from PR #101)
- **Files**: `apps/snmp_check.py`, `apps/snmp_interface_poller.py`, `apps/snmp_discovery.py`, `apps/snmp_uptime.py` — all four contain no debug traces
- **Problem**: Per `feedback_app_debug_logging` memory, new/modified pollers "must include dense `logger.debug(...)` trace lines; free in prod (no-op), essential for Debug Run." These four are the canonical reference apps — other teams copy them. No debug lines = bad template.
- **Fix** (per app, ~3-5 debug lines):
  - entry: `logger.debug("poll_start", host=..., params=ctx.parameters)`
  - connector resolution + decision points (walk vs get, tiered fallback)
  - result summary: `logger.debug("poll_complete", interfaces=len(rows), rtt_ms=...)`
- **Effort**: S per app, M total

### F-APP-007: Pack-only apps (`ping_check`, `port_check`) also lack debug tracing

- **Severity**: LOW
- **File**: `packs/basic-checks-v1.0.0.json` (embedded sources)
- **Fix**: Same treatment; `ping_check` in particular parses subprocess output with no trace on malformed lines.
- **Effort**: S

---

## 5. `.get(default)` Pitfalls (`feedback_dict_get_none`)

### F-APP-008: Nested `.get()` pattern can return `None` instead of default

- **Severity**: LOW
- **File**: `apps/snmp_interface_poller.py:226-230, 233-238`
- **Problem**: Per `feedback_dict_get_none` memory: when a DB/SNMP key exists with value `None`, `d.get("k", 0)` returns `None`, not `0`. Must use `d.get("k") or 0`. Today this is masked because `_safe_int(None)` returns 0, but the intent is unclear and future refactors can break the assumption.
- **Fix**: Explicit `or 0` on every nullable SNMP value lookup.
- **Effort**: S

---

## 6. Silent Exception Swallowing (Structured)

### F-APP-009: SNMP apps swallow `get_many()` → per-OID fallback exceptions without logging

- **Severity**: LOW
- **Files**:
  - `apps/snmp_interface_poller.py:153-166, 175-178` (multi-OID GET fails → per-OID fallback)
  - `apps/snmp_discovery.py:117-119, 143-152` (optional features)
- **Problem**: The fallback pattern is correct (resilience) but nothing logs _which_ exception triggered the fallback. On a silent regression, debugging requires running `tcpdump`.
- **Fix**: `logger.debug("snmp_get_many_failed, falling back to per-oid", error=str(exc))`.
- **Effort**: S

---

## 7. Status Code Ambiguity

### F-APP-010: `snmp_interface_poller` returns `status="unknown"` when filters exclude all interfaces

- **Severity**: LOW (confuses dashboards)
- **File**: `apps/snmp_interface_poller.py:274` — `status="ok" if interface_rows else "unknown"`
- **Problem**: If `monitored_interfaces` filter excludes every interface on the device, the result is "unknown" — but the poll succeeded. "unknown" should mean "we couldn't determine state," not "we filtered everything out." Dashboards now show unknown for perfectly healthy devices that happen to have no monitored interfaces yet.
- **Fix**: `status="ok"` when the poll succeeded regardless of row count; return `status="unknown"` only when `snmp_error is not None` and zero rows.
- **Effort**: S

---

## 8. Pack Integrity

### F-APP-011: Pack version trails highest embedded app version

- **Severity**: MED (import confusion)
- **Files**:
  - `packs/snmp-core-v1.0.0.json` — pack version `1.3.0`, contains `snmp_discovery:1.4.0` (and others)
  - `packs/basic-checks-v1.0.0.json` — pack version `1.3.0`, contains `ping_check:2.1.0`
- **Problem**: Pack version should be bumped whenever any contained app version is bumped. As-is, an operator inspecting `packs/` sees v1.3.0 but imports pulls in newer app versions. Reverse engineering the delta requires opening each app.
- **Fix**: Bump pack versions on every contained-app change. Add a pre-commit hook: `pack.version = max(app.version for app in pack.apps)`.
- **Effort**: S + M for the pre-commit guard

### F-APP-012: No schema validation for pack JSON at build time

- **Severity**: LOW
- **File**: `packs/*.json`
- **Problem**: A malformed pack (missing `is_latest`, wrong `required_connectors` shape, embedded Python with syntax error) is discovered only at central startup when the seed import runs. Per `feedback_stdlib_logger_no_kwargs` memory, one such bug previously broke pack import silently.
- **Fix**: Add a `scripts/validate_packs.py` that loads every JSON, compiles every embedded source via `compile(src, name, "exec")`, checks that `required_connectors` matches what the Poller's class attribute declares, and runs in CI.
- **Effort**: M

### F-APP-013: No secrets check on packs

- **Severity**: LOW (defence in depth)
- **Fix**: Same CI script: grep the pack JSON for `password|secret|api_key|bearer|token` outside of key names (i.e. reject when found inside `source_code` or `config_schema.default`).
- **Effort**: S

---

## 9. Credential Key Backward Compat

### F-APP-014: SNMP apps do not read `version` or `snmp_version` directly

- **Severity**: INFO (not an issue — delegates correctly)
- **Problem**: Per `project_snmp_connector_version_key` memory, the SNMP **connector** (v1.4.1) handles both `version` and `snmp_version` key names. The apps themselves don't touch the key — they just use the resolved connector. Correct.
- **Action**: None, but worth confirming the connector still carries both keys in any future rewrite.

---

## Summary

| Severity  | Count  |
| --------- | ------ |
| HIGH      | 0      |
| MED       | 5      |
| LOW       | 8      |
| INFO      | 1      |
| **Total** | **14** |

**Priority actions (small, high-value)**:

1. **F-APP-001** — Remove `snmp_discovery.py:87` stray `snmp.connect(host)`. Bump pack. (S)
2. **F-APP-004** — Replace hardcoded `error_category="device"` with typed classification across the 4 SNMP reference apps. (S each)
3. **F-APP-006** — Add `logger.debug(...)` traces to all 4 reference apps; they're the template other teams copy. (S each)
4. **F-APP-011 + F-APP-012** — Pack version bumps + CI validation script. (M)

Everything else is LOW and can wait for the next round.

---

## What We Looked At

- `apps/snmp_check.py`
- `apps/snmp_interface_poller.py`
- `apps/snmp_discovery.py`
- `apps/snmp_uptime.py`
- `packs/snmp-core-v1.0.0.json` (including embedded app sources)
- `packs/basic-checks-v1.0.0.json` (including `ping_check`, `port_check`, `http_check`)

**Cross-referenced memory files**:

- `feedback_app_timing_placement.md`
- `feedback_app_debug_logging.md`
- `feedback_dict_get_none.md`
- `feedback_stdlib_logger_no_kwargs.md`
- `project_collector_memory.md`
- `project_snmp_connector_version_key.md`
