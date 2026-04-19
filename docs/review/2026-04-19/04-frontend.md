# 04 — Frontend Review

**Scope**: `packages/central/frontend/src/` — React 19, TypeScript, Vite, Tailwind v4, TanStack Query.
**Date**: 2026-04-19
**Methodology**: direct read of `src/api/client.ts` + Explore agents (architecture overview + detail-level deep dive). Severity calibrated against real-world risk (not nominal).

Unique IDs use prefix `F-WEB-`.

---

## 1. XSS & HTML-Injection Surface

### F-WEB-001: `ConfigDataRenderer` iframe `srcDoc` interpolates raw template CSS + HTML

- **Severity**: HIGH (security)
- **File**: `src/components/ConfigDataRenderer.tsx:53-70`
- **Problem**: User-authored Jinja-like templates embedded in a device's config data are rendered via iframe `srcDoc`. Template CSS and template HTML are interpolated directly; only JSON-placed closing tags (`</`) are partially escaped. An attacker who can write a config-data template (or who controls an upstream config-collection endpoint) can run JS in the iframe.
- **Impact**: Same-origin XSS if the iframe is same-origin; cross-frame via `postMessage` otherwise. Either way, arbitrary JS on a logged-in admin's session.
- **Fix**: Render templates inside a sandboxed iframe with `sandbox="allow-same-origin"` deliberately omitted (use `sandbox="allow-scripts"` only if scripts truly needed — probably not here). Additionally, run templates through a sanitizer (DOMPurify) before injection.
- **Effort**: M

### F-WEB-002: `postMessage` uses wildcard target origin

- **Severity**: MED (security)
- **File**: `src/components/ConfigDataRenderer.tsx:59` (and the iframe-side `window.parent.postMessage(..., '*')`)
- **Problem**: Wildcard origin is broadcast to any listener — including attacker-controlled frames. Content here is cosmetic (height) so the leak is limited, but the habit is wrong.
- **Fix**: `window.parent.postMessage(..., window.location.origin)`. Verify `event.origin` on the listener side as well.
- **Effort**: S

### F-WEB-003: Read-only textarea renders JSON without HTML-escaping `</textarea>`

- **Severity**: LOW (XSS only if future change swaps textarea for dangerouslySetInnerHTML)
- **File**: `src/components/TemplateConfigEditor.tsx:69, 841`
- **Problem**: Today React's JSX escapes content in `<textarea>{value}</textarea>` properly, so this is not exploitable. Flagged because the adjacent patterns (inline JSON preview in tooltips, code editors) easily drift into HTML-injecting territory.
- **Fix**: Keep using React children (not `dangerouslySetInnerHTML`). Add a lint rule against `dangerouslySetInnerHTML` in the whole repo.
- **Effort**: S

---

## 2. Auth & Cookie Flow

### F-WEB-004: Silent refresh deduplication — verified, NOT a race

- **Severity**: INFO (common agent false-positive)
- **File**: `src/api/client.ts:18-47`
- **Note**: A reviewer flagged this as a race condition. Re-verified: JS is single-threaded; the `if (isRefreshing && refreshPromise) return refreshPromise` check and the subsequent `isRefreshing = true` assignment execute atomically with no intervening `await`. Both concurrent callers reliably see the same `refreshPromise`. **No bug.**
- **Action**: None — but keep the pattern in the code review rubric since it looks suspicious at a glance.

### F-WEB-005: 401 redirect to `/login` via `window.location.href` loses SPA state

- **Severity**: LOW (UX, not security)
- **File**: `src/api/client.ts:81-85, 194-198`
- **Problem**: Full page reload on 401 — any in-flight form input, unsaved editor buffer, wizard progress is gone. Also doesn't preserve the current URL as a post-login redirect target.
- **Fix**: Use the router's `navigate("/login?next=" + encodeURIComponent(location.pathname))`. On successful login, redirect back.
- **Effort**: S

### F-WEB-006: Error fallback message stringifies entire response body

- **Severity**: MED (information disclosure in UI / logs)
- **File**: `src/api/client.ts:99-117, 212-230`
- **Problem**: On non-standard error responses the fallback path calls `JSON.stringify(body)` and passes that as the UI message. If the server ever echoes a payload that includes user or tenant data (not uncommon for validation errors), that data is surfaced in toasts / error modals / sent to any frontend error-tracking.
- **Fix**: Cap the stringified body at ~200 chars and redact known-sensitive keys before display.
- **Effort**: S

### F-WEB-007: No cross-tab logout propagation

- **Severity**: MED (security / UX)
- **File**: `src/hooks/useAuth.tsx` (inferred)
- **Problem**: Logging out in tab A leaves tab B in an authenticated state until its next 401. On shared devices, that's a window where someone can glance at open data.
- **Fix**: `BroadcastChannel("auth")` or a storage-event listener on a shared flag. On logout, post a message; other tabs clear their query cache and redirect.
- **Effort**: S

### F-WEB-008: `localStorage` used for UI preferences — integrity-sensitive at least for themes/timezone

- **Severity**: LOW
- **File**: `src/hooks/useDisplayPreferences.ts:26, 37`
- **Problem**: User-visible settings in localStorage is fine. Noted because the same pattern can creep into tokens; enforce a rule.
- **Fix**: Add a code-owners / PR-template reminder: "No auth tokens in storage." Consider moving preferences server-side (already partially there via `user.ui_preferences`).
- **Effort**: S

### F-WEB-009: Fixed 5-minute auto-refresh interval doesn't adapt to idle timeout

- **Severity**: LOW
- **File**: `src/hooks/useAuth.tsx:15, 126-162`
- **Fix**: Refresh at `max(30s, idle_timeout_minutes * 60 * 0.5)` so you refresh roughly halfway through the window.
- **Effort**: S

---

## 3. React Query Hygiene

### F-WEB-010: `refetchInterval` does not pause when tab is hidden

- **Severity**: HIGH (battery, bandwidth, server load)
- **File**: `src/api/hooks.ts` — ~70 occurrences of `refetchInterval: POLL_LIST / POLL_DETAIL`
- **Problem**: Background tabs continue polling every 15-30s. A user with 10 tabs open sustains ~1800 API calls per minute for nothing, and a laptop on battery spins up the network radio continuously.
- **Fix**: Wrap via `refetchInterval: (query) => (document.hidden ? false : POLL_LIST)`. Even simpler: set a sensible `staleTime` (e.g. 10s) and rely on `refetchOnWindowFocus` (which TanStack already handles correctly).
- **Effort**: S (one helper + replace)

### F-WEB-011: Object-literal `queryKey` entries cause unnecessary refetches

- **Severity**: MED (perf)
- **File**: `src/api/hooks.ts:169` (and similar list hooks)
- **Problem**: `queryKey: ["devices", params]` — TanStack compares the key structurally, which is usually fine, but many callers build `params` inline every render. The first few renders before the hook memoises the key cause extra fetches.
- **Fix**: Destructure primitive fields into the key: `["devices", params.name, params.offset, params.limit, params.sort]`. Or `useMemo(params, [params.name, params.offset, ...])` at the call site.
- **Effort**: M

### F-WEB-012: Widget query key includes computed SQL — stale data lingers

- **Severity**: MED
- **File**: `src/components/DashboardWidget.tsx:84, 90`
- **Problem**: `["widget-query", id, resolvedSQL]` changes whenever a variable substitution changes, so the old-key cache entry lingers forever. Memory growth over long sessions.
- **Fix**: Include `variables` (as a stable-order object hash) in the key OR manually `queryClient.removeQueries({queryKey: ["widget-query", id]})` when the widget unmounts.
- **Effort**: S

### F-WEB-013: Mutation side effects use multiple un-bundled invalidations

- **Severity**: MED
- **File**: `src/api/hooks.ts:401-425`
- **Problem**: Threshold mutations call `invalidateQueries(["alert-defs"])` + `invalidateQueries(["alerts"])` + `invalidateQueries(["device", id])` separately. A failure mid-chain can leave one key stale while others refresh.
- **Fix**: Collect invalidations into one helper; wrap in `await queryClient.invalidateQueries({ predicate: (q) => ... })` with a predicate that matches all related keys atomically.
- **Effort**: S

### F-WEB-014: No `staleTime` defaults globally

- **Severity**: MED (perf)
- **File**: `src/api/hooks.ts` (all queries default to `staleTime: 0`)
- **Problem**: Combined with `refetchOnWindowFocus: true` (default), every tab switch refetches every visible query. For list pages with 5+ queries, that's 5+ round-trips per focus event.
- **Fix**: Set a reasonable default `staleTime: 5_000` (5s) at the `QueryClient` level; override per-hook if a query genuinely needs sub-second freshness.
- **Effort**: S

### F-WEB-015: Two concurrent mutations to the same resource lack `mutationKey`

- **Severity**: LOW
- **File**: `src/components/DashboardWidget.tsx:83-92` and others
- **Problem**: Without `mutationKey`, TanStack can run them in parallel; if there's server-side last-writer-wins behaviour, results depend on completion order.
- **Fix**: `mutationKey: ["widget-query", id]` + set a serial cache on the client.
- **Effort**: S

---

## 4. Effect Bugs

### F-WEB-016: `setInterval` inside a `useEffect` with changing deps may layer intervals

- **Severity**: MED
- **File**: `src/pages/DeviceDetailPage.tsx:1531-1541`
- **Problem**: `useEffect` has `[pollRequestedAt, deviceId, qc]`. If `qc` reference changes (it shouldn't but can during React strict-mode double-invocation or HMR), a new interval is spawned and the old one cleared — but the timing of cleanup vs. re-setup can briefly leave two running. User sees duplicate invalidations during hot reload.
- **Fix**: Remove `qc` from the dep list; react-query's `useQueryClient` returns a stable reference.
- **Effort**: S

### F-WEB-017: `addEventListener("message", ...)` without `useCallback`-stabilised handler

- **Severity**: LOW
- **File**: `src/components/ConfigDataRenderer.tsx:72-83`
- **Problem**: Every render creates a new handler; cleanup by ref comparison is correct (React re-runs the effect and the old handler is removed). Still wastes work when the component re-renders a lot.
- **Fix**: `useCallback` the handler with `[setHeight]` deps.
- **Effort**: S

### F-WEB-018: `useEffect` with `[refresh]` dep where `refresh` is a `useCallback`

- **Severity**: INFO (not a bug)
- **File**: `src/hooks/useAuth.tsx:87-89`
- **Note**: `refresh` has a stable identity via `useCallback([])`. Effect runs once. Fine.

---

## 5. Date/Time Correctness

### F-WEB-019: `new Date(timestamp + "Z")` unconditionally appends "Z" — double-appends if API already emits Z

- **Severity**: MED (data correctness — silent wrong times)
- **Files**:
  - `src/components/HostMetricsChart.tsx:103`
  - `src/components/ContainerMetricsChart.tsx:103`
  - `src/components/DbSizeHistoryChart.tsx:63, 72`
- **Problem**: Backend emits timestamps inconsistently across endpoints — some routes include `Z`, others don't (ClickHouse's default output is timezone-naive). Unconditional `+ "Z"` yields `...ZZ` → `new Date(...)` returns `Invalid Date`, and `.getTime()` returns `NaN`. Charts silently drop or misplace those points.
- **Fix**: Helper `ensureUTC(ts: string) => ts.endsWith("Z") ? ts : ts + "Z"`. Or better: normalise on the server — always emit `...Z`. Server-side fix is more robust.
- **Effort**: S (client helper) / M (server standardisation)

### F-WEB-020: `new Date(apiString)` in `src/lib/utils.ts` assumes UTC without checking

- **Severity**: MED
- **File**: `src/lib/utils.ts:14, 30, 74, 106`
- **Fix**: Use the same `ensureUTC` helper before `new Date(...)`.
- **Effort**: S

### F-WEB-021: `TimeRangePicker` silently falls back to browser TZ when `timezone` is falsy

- **Severity**: LOW
- **File**: `src/components/TimeRangePicker.tsx:91, 94`
- **Fix**: Pass a default of `"UTC"` and require the caller to opt out explicitly.
- **Effort**: S

---

## 6. Form & Input Hygiene

### F-WEB-022: Number inputs flip controlled ↔ uncontrolled

- **Severity**: MED (React warning + lost edits)
- **File**: `src/components/SchemaConfigFields.tsx:194-198`
- **Problem**: `value={String(currentVal)}` + `onChange` that sets state to `undefined` when empty. React logs "A component is changing a controlled input to be uncontrolled." Lost edits can occur if the state reset races a submit.
- **Fix**: Keep the state as `string | number` throughout; convert at submit time only.
- **Effort**: S

### F-WEB-023: `parseInt(x, 10) || 0` treats empty-string as 0

- **Severity**: LOW
- **Files**: `src/pages/DeviceDetailPage.tsx:4128, 4177`, `src/components/LadderEditor.tsx:231`
- **Problem**: User clearing a field to replace it means the intermediate state is 0, which can be submitted if they tab away before typing a new value.
- **Fix**: `const v = e.target.value === "" ? null : parseInt(e.target.value, 10); if (v === null) return;`.
- **Effort**: S

---

## 7. Permission UI Consistency

### F-WEB-024: Many action buttons submit without a client-side `usePermissions()` guard

- **Severity**: LOW (server enforces — UX only)
- **Files**: `src/pages/DeviceDetailPage.tsx` (many places), `src/pages/DevicesPage.tsx:789, 798`
- **Problem**: Buttons are visible to users without permission; click → fetch → 403 → toast. Works, but noisy.
- **Fix**: Wrap actionable UI in `<CanDo resource="device" action="edit">...</CanDo>` that reads from `usePermissions()`. Hide or disable + tooltip.
- **Effort**: M (cross-cutting touch)

---

## 8. Bundle, Complexity, and Lazy Loading

### F-WEB-025: Zero `React.lazy` — all 8K-line detail pages load on initial nav

- **Severity**: MED (perf)
- **Files**: routing entry (likely `src/App.tsx` or `src/main.tsx`)
- **Problem**: `DeviceDetailPage.tsx` (8025 lines), `SystemHealthPage.tsx` (3488), `AppDetailPage.tsx` (3306), `TemplateConfigEditor.tsx` (1348), `InterfaceTrafficChart.tsx` (991), `AvailabilityChart.tsx` (725) — all bundled eagerly. First-load bundle likely > 2 MB.
- **Fix**: `const DeviceDetailPage = React.lazy(() => import("./pages/DeviceDetailPage"))`; wrap route in `<Suspense>`.
- **Effort**: M

### F-WEB-026: Oversized components (>500 lines) hurt render and reviewability

- **Severity**: MED (maintainability)
- **File**: Top offenders:
  - `DeviceDetailPage.tsx` (8025) — split by tab into separate routed sub-pages (`/devices/:id/overview`, `/alerts`, `/interfaces`, etc.)
  - `SystemHealthPage.tsx` (3488) — extract a dashboard-widget-like layer for each subsystem
  - `AppDetailPage.tsx` (3306) — config editor is 240+ lines, deserves its own page
  - `TemplateConfigEditor.tsx` (1348), `InterfaceTrafficChart.tsx` (991), `AvailabilityChart.tsx` (725)
- **Fix**: Break by tab / concern. Start with DeviceDetailPage — the most copied template.
- **Effort**: L

### F-WEB-027: 106 `any` + 29 `as any` across the codebase

- **Severity**: MED (type safety)
- **File**: concentrated in `DeviceDetailPage.tsx` (19), `SettingsPage.tsx` (6), `AlertsPage.tsx` (4)
- **Fix**: Add typed response interfaces per API hook; remove casts. Lint with `@typescript-eslint/no-explicit-any` warn.
- **Effort**: L

---

## 9. Accessibility

### F-WEB-028: Icon-only buttons lack `aria-label`

- **Severity**: LOW (a11y)
- **Problem**: Zero `aria-label` on Lucide icons used as clickable elements.
- **Fix**: Wrap the pattern in a small `<IconButton aria-label=...>`; enforce via ESLint rule `jsx-a11y/accessible-emoji`/`jsx-a11y/no-noninteractive-element-interactions`.
- **Effort**: M

### F-WEB-029: Many form inputs missing `<label htmlFor>` associations

- **Severity**: LOW
- **Fix**: Standardise on a `<Field label="…">` wrapper that auto-generates `id` + `htmlFor`.
- **Effort**: M

---

## 10. Testing

### F-WEB-030: Zero frontend tests on 111 K lines of component code

- **Severity**: MED (regression risk)
- **File**: `packages/central/frontend/` — no `.test.tsx` / `.spec.ts`
- **Problem**: All UI verification is manual (via Playwright MCP). No regression safety net on `FlexTable`, `useListState`, `FilterableSortHead`, or any API-hook code path.
- **Fix**: Add Vitest + React Testing Library. Start with shared primitives (`FlexTable`, `useListState`, API client's retry logic). Aim for 30% coverage within a quarter.
- **Effort**: L (but pays back fast)

---

## 11. Smaller But Worth Fixing

### F-WEB-031: Duplicate retry logic in `request()` and `apiPostFormData()`

- **Severity**: LOW (maintenance)
- **File**: `src/api/client.ts:51-125` vs `170-233`
- **Fix**: Extract a `fetchWithAutoRefresh(url, init)` that both call.
- **Effort**: S

### F-WEB-032: `apiPost` and siblings skip body when `body` is falsy — drops legit `0`, `""`, `false`

- **Severity**: LOW (edge case)
- **File**: `src/api/client.ts:137, 147, 157`
- **Problem**: `body ? JSON.stringify(body) : undefined` — sending `apiPost("/x", 0)` sends no body.
- **Fix**: `body !== undefined ? JSON.stringify(body) : undefined` — only undefined means "no body".
- **Effort**: S

### F-WEB-033: `setTimeout` without cleanup in transient-feedback components

- **Severity**: LOW (memory, React warnings)
- **File**: `src/components/DebugRunDialog.tsx:382`, `src/pages/CollectorsPage.tsx:1151, 1423, 1428`
- **Fix**: Track timer in a `useRef` and clear on unmount.
- **Effort**: S (per site)

---

## Summary

| Severity  | Count  |
| --------- | ------ |
| HIGH      | 2      |
| MED       | 14     |
| LOW       | 14     |
| INFO      | 3      |
| **Total** | **33** |

**Top 5 to fix first**:

1. **F-WEB-001** — `ConfigDataRenderer` iframe srcDoc XSS (HIGH security, M)
2. **F-WEB-010** — `refetchInterval` in background tabs (HIGH perf, S)
3. **F-WEB-019** — Date+"Z" double-append silently corrupts chart data (MED correctness, S)
4. **F-WEB-006** — Error-body stringification can leak data to UI/tracking (MED info disclosure, S)
5. **F-WEB-014** — Global `staleTime: 0` causes refetch storm on focus (MED perf, S)

---

## What We Looked At

**Direct reads**:

- `src/api/client.ts` (234 lines, full)

**Agent sweeps**:

- Frontend architecture & complexity (component sizes, type safety, bundle, a11y, tests)
- Frontend detail deep-dive (XSS, React Query bugs, effect bugs, form hygiene, date correctness)

**Key files referenced**:

- `src/components/ConfigDataRenderer.tsx`
- `src/components/DashboardWidget.tsx`
- `src/components/{HostMetrics,ContainerMetrics,DbSizeHistory}Chart.tsx`
- `src/components/TemplateConfigEditor.tsx`, `SchemaConfigFields.tsx`, `LadderEditor.tsx`
- `src/hooks/useAuth.tsx`, `useDisplayPreferences.ts`, `useColumnConfig.ts`
- `src/api/hooks.ts` (ubiquitous), `src/lib/utils.ts`
- `src/pages/DeviceDetailPage.tsx`, `DevicesPage.tsx`, `SystemHealthPage.tsx`, `AppDetailPage.tsx`
