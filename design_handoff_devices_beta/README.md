# Handoff: Devices (beta) Page — MonCTL

## Overview

This is the design handoff for **`/devices-beta`**, a new page in MonCTL that ships alongside the existing `/devices` page. It is a refined-faithful redesign of the current Devices list: same FlexTable shape, same column language, same lucide icon vocabulary, same brand token (`oklch(0.58 0.16 250)`), but with three additions:

1. **Saved Views chip row** — primary navigation between filter sets.
2. **Status filter strip** — pill-style quick filters with live counts (Up / Down / Unknown / Disabled), plus a global search box.
3. **In-place selection action bar** — when rows are selected, the card header swaps its idle "Devices" title for selection actions in the **same fixed-height slot**, so the table never reflows and the user's next-row focus is preserved.

The rollout strategy is a **non-destructive beta**: the existing `/devices` page is untouched. A new route, page component, and feature-flagged nav entry are added. When the beta promotes, routes swap and the classic page is removed in a follow-up release.

## About the Design Files

The files in this bundle (`Devices Redesign.html`, `v1-safe.jsx`, `data.jsx`, `icons.jsx`, `design-canvas.jsx`) are **design references created in HTML** — a working prototype showing intended look and behaviour, not production code to copy directly. The HTML uses inline JSX, Babel-standalone, hand-rolled lucide-style icons, and a 2,000-row mock dataset.

The task is to **recreate this design in the MonCTL codebase's existing environment** — React + TypeScript, Tailwind, the existing FlexTable / Badge / Button shadcn components, the real `useDevices()` data hook, and the tokens already defined in `app.css`. Do **not** copy the inline `themeStyles` map from `v1-safe.jsx`; the same tokens already exist in the codebase.

## Fidelity

**High-fidelity.** Final colors, typography, spacing, and interaction patterns are settled. The prototype renders with `Inter` for UI, `JetBrains Mono` for monospace fields (addresses, timestamps, version strings), and oklch tokens that map 1:1 to MonCTL's existing `app.css` surface / text / brand scales. Recreate pixel-perfect using the codebase's existing libraries.

## Screens / Views

There is one page in this handoff: **`DevicesBetaPage`**, mounted at `/devices-beta`.

### Page layout (top → bottom)

All elements sit inside the existing app shell (sidebar, breadcrumbs, etc. unchanged).

#### 1. Top bar — `<DevicesBetaTopBar>`

- **Height**: 52px (12px top/bottom padding + 28px control height)
- **Padding**: `12px 16px`
- **Layout**: flex row, `gap: 8px`, `align-items: center`
- **Left**: count label
  - Text: `"<filtered>" of "<total>" devices` (e.g. *"`248`** of `2,000` devices**"*)
  - Filtered count: `--text` color, `font-weight: 600`
  - Surrounding text: `--text-3` color
  - Font: Inter 13px
- **Right cluster** (3 buttons, all 28px tall, 6px radius, 12px font):
  - **Display** — ghost button, `sliders` icon. Border `--border-2`, transparent bg, `--text-2` text.
  - **Import** — solid ghost, `folderIn` icon. Bg `--surf-3`, `--text` text.
  - **Add Device** — primary, `plus` icon. Bg `--brand`, white text, `--brand` border.

#### 2. Saved Views row — `<SavedViewsBar>`  ⭐ NEW

- **Height**: 34px (24px chips + 10px bottom padding)
- **Padding**: `0 16px 10px`
- **Layout**: flex row, `gap: 6px`, horizontally scrollable on overflow (`overflow-x: auto`, `flex-shrink: 0` on items)
- **Leading label**: `"Views"` — uppercase, 10.5px Inter, `letter-spacing: 0.5px`, `--text-4` color
- **View chips** (24px height, 4px radius, 11.5px Inter):
  - **Inactive**: bg `--surf-2`, border `--border`, `--text-2`
  - **Active**: bg `color-mix(in oklch, var(--brand) 16%, transparent)`, border `color-mix(in oklch, var(--brand) 45%, transparent)`, `--text` color, `font-weight: 500`
  - Optional 11px lucide icon on the left, or a 6×6 colored dot (red for "Down right now", grey for "Never polled", etc.)
- **Save current** button — dashed-border 1×1.5 px button, `plus` icon + label, `--text-3` color
- **Vertical 1px divider** (`--border`) between view chips and "Save current"
- **Seed views** to ship with (real data, hard-coded names; filter contents come from the user's current selection at save time):
  - "All devices" — primary view, `activity` icon
  - "Down right now" — red dot, applies `statusFilter: 'down'`
  - "With active alerts" — applies `alerts > 0` filter
  - "Prod edge routers" — column filters: `tenant_name: 'prod'`, `device_category: 'router'`
  - "F5 BIG-IP fleet" — column filter: `device_type_name: 'f5'`
  - "Never polled" — grey dot, applies `statusFilter: 'unknown'`

When a saved view is picked, all four pieces of filter state (`statusFilter`, `q`, `columnFilters`, `sort`) are replaced atomically. When the user manually changes any filter, `activeView` is cleared to `null` (no view chip is highlighted) — this signals "modified".

#### 3. Status filter strip — `<DeviceStatusFilter>`  ⭐ NEW

- **Padding**: `0 16px 12px`
- **Layout**: flex row, `gap: 8px`, `align-items: center`
- **Left**: search box (flex: 1, 28px tall)
  - Bg `--surf-2`, border `--border`, 6px radius, `0 10px` padding
  - 13px `search` lucide icon (`--text-3`)
  - Input: transparent bg, no border, `JetBrains Mono` 12px, `--text` color
  - Trailing `⌘K` kbd hint: 10.5px mono, `--text-3`, 1px border, 3px radius
  - Placeholder: *"Search devices by name, address, type, tenant…"*
- **Status pills** (one per status, 26px height, 13px border-radius — pill-shaped):
  - Inactive: bg `--surf-2`, border `--border`, `--text-2`
  - Active: bg `color-mix(in oklch, var(--brand) 14%, transparent)`, border `color-mix(in oklch, var(--brand) 40%, transparent)`, `--text`
  - Layout: 6×6 colored dot + label + count (mono, smaller, dimmer)
  - Pills:
    - **All** — no dot, `all.length` count
    - **Up** — `--up` (green) dot
    - **Down** — `--down` (red) dot
    - **Unknown** — `--text-4` (grey) dot
    - **Disabled** — `--text-4` (grey) dot
- Clicking the active pill toggles back to "all".

#### 4. Card — the table container

- **Margins**: `0 16px 16px`
- **Bg**: `--surf`, border `--border`, 8px radius, `overflow: hidden`
- **Layout**: vertical flex, fills remaining height

##### 4a. Card header — `<CardHeaderBar>` ⭐ CRITICAL FIXED-HEIGHT BEHAVIOUR

This is the **most important** behavioural change. The card header is a single fixed-height slot that swaps content based on selection. **The slot height MUST stay constant** so the table never reflows when the user clicks a row checkbox.

- **Height**: exactly `44px` — fixed, do not let it grow or shrink
- **Padding**: `0 16px`
- **Bottom border**: 1px `--border`
- **Layout**: flex row, `gap: 8px`, `align-items: center`
- **Idle state** (no selection):
  - Bg: transparent
  - Content: 14px `monitor` lucide icon (`--text-3`) + label *"Devices"* (12px Inter 500, `--text-3`)
- **Selecting state** (`selected.size > 0`):
  - Bg: `color-mix(in oklch, var(--brand) 8%, transparent)` (transitions in over 120ms)
  - Content (left → right):
    1. *"<n> selected"* — 12px, `<n>` is `--brand-2` weight 600
    2. **Clear** button (transparent ghost, 24px tall)
    3. 1px vertical divider, 16px tall, `--border-2`, 4px horizontal margin
    4. Action buttons (24px tall, 4px radius, 11px Inter, bg `--surf-3`, border `--border-2`, `--text-2`):
       - **Enable** — `power` icon
       - **Disable** — `power` icon
       - **Move tenant** — `folderIn` icon
       - **Move group** — `folderIn` icon
       - **Apply template** — `tag` icon
    5. **Delete** — same shape as above but `--down` text and `color-mix(in oklch, var(--down) 35%, transparent)` border

> **Implementation note**: do **not** render the action bar as a separate row beneath the card title (that's what the current Devices page does and the user explicitly does not want it — the row shift breaks their visual focus on the next-row checkbox). One slot, two states.

##### 4b. Table — virtualized FlexTable

Same column set, sort, and filter inputs as the existing Devices page. Columns (left → right, fixed widths sum to 1374px):

| Key | Label | Width | Sortable | Filterable | Notes |
|---|---|---|---|---|---|
| `__select` | (checkbox) | 40 | no | no | Header has select-all checkbox |
| `__status` | Status | 64 | yes | no | 8px colored dot (`--up` w/ pulse / `--down` / `--text-4`) |
| `name` | Name | 230 | yes | yes | Brand-coloured (`--brand-2`), elliptical overflow |
| `address` | Address | 130 | yes | yes | Mono 11px, `--text-2` |
| `device_category` | Category | 160 | yes | yes | Lucide icon by category + label |
| `device_type_name` | Type | 180 | yes | yes | `--text-2` 12px |
| `tenant_name` | Tenant | 130 | yes | yes | Badge |
| `collector_group_name` | Collector Group | 150 | yes | yes | Badge |
| `__alerts` | Alerts | 70 | yes | no | `bell` icon + count, `--down` if >1, `--warn` if 1, em-dash if 0 |
| `__last` | Last poll | 100 | yes | no | Mono 11px relative time |
| `updated_at` | Updated | 150 | yes | yes | Mono 11px timestamp |

- **Header cell**: 8px 12px padding, bg `--surf-2`, right border `--border`
  - Top row: 11px drag-grip (`--text-4`) + label + sort arrow (active = `--brand-2`, idle = `--text-4`)
  - Bottom row: 22px filter input (bg `--surf-3`, mono 11px, with x-clear button)
  - Filter input is hidden for `noFilter: true` columns
- **Body row**: 30px height, 1px bottom border `--border`
  - Hover bg: `--surf-2`
  - Selected bg: `color-mix(in oklch, var(--brand) 12%, transparent)`
  - Disabled (`!is_enabled`): `opacity: 0.6`
- **Virtualization**: `@tanstack/react-virtual` recommended. Body height in prototype is 470px.

##### 4c. Pagination footer

- 8px 16px padding, top border `--border`, 12px Inter `--text-3`
- Left: *"1–<min(filtered, 100)> of <filtered>"*
- Right: chevron-left + chevron-right buttons (transparent, 14px icons)

## Interactions & Behavior

- **Sort**: click a column header label → cycle asc/desc on that column. Active column header is `--text` (vs `--text-3`); arrow becomes `--brand-2`.
- **Filter**: each filterable column has a per-column input below the header label. Filtering is `String(value).toLowerCase().includes(needle)` for string fields. The drag-grip and filter-input layout match the existing FlexTable pattern.
- **Select**:
  - Row checkbox toggles single row.
  - Header checkbox toggles up to first 200 visible rows (matches current behaviour; safety cap on bulk).
  - Selection state is preserved across filter changes (rows you can no longer see stay selected).
- **Card header swap**: pure CSS transition on `background` (120ms). The content swap is conditional render but must keep `height: 44px` constant.
- **Saved view picked**: replaces all filter state atomically. Sets `activeView = view.id`.
- **Manual filter change**: clears `activeView = null`, no chip highlighted.
- **Pulse animation** (status dot for "up" devices): `@keyframes monctlPulse { 0%,100% { opacity: 1 } 50% { opacity: 0.4 } }`, 2s ease-in-out infinite.

## State Management

```ts
type DevicesBetaPageState = {
  q: string;                                 // global search
  statusFilter: 'all' | 'up' | 'down' | 'unknown' | 'disabled';
  columnFilters: Record<ColumnKey, string>;  // per-column filter inputs
  sort: { key: ColumnKey; dir: 'asc' | 'desc' };
  selected: Set<DeviceId>;
  activeView: SavedViewId | null;            // null = "modified" (no chip lit)
};
```

- **Source of truth for device list**: existing `useDevices()` hook (or whatever is canonical). Don't re-implement.
- **Saved views**: new `useSavedViews('devices-beta')` hook backed by a new `saved_views` table:
  ```sql
  CREATE TABLE saved_views (
    id          uuid primary key,
    user_id     uuid not null references users(id),
    page        text not null,    -- 'devices-beta' for now
    name        text not null,
    filter_json jsonb not null,   -- { statusFilter, q, columnFilters, sort }
    position    int not null,
    is_pinned   bool default false,
    created_at  timestamptz default now(),
    updated_at  timestamptz default now()
  );
  CREATE INDEX ON saved_views (user_id, page, position);
  ```
  - Endpoints: `GET /saved-views?page=devices-beta`, `POST`, `PATCH /:id`, `DELETE /:id`, `POST /:id/reorder`.
  - Seed the six "starter" views server-side on first page-load if user has none, so the UX out of the box matches the prototype.
- **URL state**: serialize `{ statusFilter, q, columnFilters, sort }` into the query string so views are bookmarkable and shareable. "Apply view" = navigate to a URL.

## Design Tokens

All tokens already exist in `app.css` as oklch values. Use the named CSS custom properties; do **not** hard-code the oklch values from the prototype.

### Color tokens used (dark theme reference values; light theme values are in `app.css`)

| Token | Dark | Role |
|---|---|---|
| `--bg` | `oklch(0.13 0.01 260)` | Page background |
| `--surf` | `oklch(0.17 0.012 260)` | Card / table surface |
| `--surf-2` | `oklch(0.19 0.012 260)` | Header bg, hover row, chip bg |
| `--surf-3` | `oklch(0.22 0.012 260)` | Input bg, button bg |
| `--border` | `oklch(0.28 0.012 260)` | All 1px borders |
| `--border-2` | `oklch(0.35 0.012 260)` | Stronger borders, dividers |
| `--text` | `oklch(0.96 0.002 260)` | Primary text |
| `--text-2` | `oklch(0.78 0.005 260)` | Secondary text, badge fg |
| `--text-3` | `oklch(0.58 0.006 260)` | Tertiary, label, count text |
| `--text-4` | `oklch(0.42 0.006 260)` | Quaternary, dot grey, em-dash |
| `--brand` | `oklch(0.58 0.16 250)` | Primary CTAs, focus, accent |
| `--brand-2` | `oklch(0.68 0.12 250)` | Brand text (name column, badge fg, "selected" count) |
| `--up` | `oklch(0.72 0.16 152)` | Reachable / on / OK |
| `--down` | `oklch(0.65 0.22 25)` | Down / error / destructive |
| `--warn` | `oklch(0.80 0.17 80)` | Single alert |

### Typography

- **UI font**: Inter (already loaded). Sizes used: 10.5 / 11 / 11.5 / 12 / 13 / 14 / 18 px. Weights: 400, 500, 600.
- **Mono font**: JetBrains Mono. Used for: addresses, timestamps, last-poll relative times, count-in-pill labels, ⌘K kbd hint, alert counts. Sizes: 10 / 10.5 / 11 / 11.5 / 12 px.

### Spacing

Page-level: 16px gutter (left/right of all sections), 12px between vertical sections except the saved-views row which is 10px below.

Inside the card: 16px horizontal padding for header rows, 12px horizontal padding for cells, 8px gap between row elements.

Control heights: 22 (filter input), 24 (chip / action button), 26 (status pill), 28 (top-bar button), 30 (table row), 32 (status-strip search box), 44 (card header — fixed).

### Border radii

- 3px — inline kbd hint, count badges
- 4px — chips, action buttons, filter inputs, table cells
- 6px — top-bar buttons, search box
- 8px — card
- 13px — status pills (half of height = pill shape)

## Assets

- **Icons**: lucide-react. The prototype hand-rolls SVGs in `icons.jsx` to mirror lucide. Use the real `lucide-react` package in the codebase. Names used: `monitor`, `router`, `switch`, `server`, `firewall`, `container`, `shield`, `plus`, `folderIn` (= `folder-input`), `sliders`, `search`, `grip` (= `grip-vertical`), `arrowUp` (= `arrow-up`), `arrowDown` (= `arrow-down`), `arrowUpDown` (= `arrow-up-down`), `chevronL` (= `chevron-left`), `chevronR` (= `chevron-right`), `x`, `trash` (= `trash-2`), `tag`, `power`, `bell`, `activity`, `terminal`, `filter`.
- **Fonts**: Inter and JetBrains Mono — both are already loaded in MonCTL. No new font assets needed.
- **No images**.

## PR Sequence (recommended)

1. **Empty `/devices-beta` route + nav entry behind feature flag** (`devices_beta_enabled`). Renders a placeholder. Lands in 30 minutes; proves plumbing.
2. **Copy `DevicesPage.tsx` → `DevicesBetaPage.tsx`**, hook up the existing `useDevices()` query, no UI changes yet. Verifies data wiring works at the new route.
3. **Card-header swap**: replace the floating selection toast with the in-place 44px slot.
4. **`<DeviceStatusFilter>` strip** with Up/Down/Unknown/Disabled pills + global search.
5. **Saved views**: SQL migration → endpoints → `useSavedViews()` hook → `<SavedViewsBar>` component → seed defaults on first load.
6. **Telemetry**: emit `devices_beta.viewed`, `devices_beta.view_picked`, `devices_beta.view_saved`, `devices_beta.bulk_action`, `devices_beta.switched_to_classic`.
7. **Cross-link both pages**: small "← Switch to classic" / "Try the new view →" link in the top-right of each page header.
8. **Friendly-tenant rollout** via flag, gather telemetry, decide promotion.

## Promotion Criteria

When ≥70% of weekly Devices users who have opted into beta have **not** clicked "Switch back to classic" in the past 7 days, swap routes: `/devices` renders the new page, `/devices-classic` keeps the old one for one release. Then delete classic in the following release.

## Files in This Bundle

- `Devices Redesign.html` — the design canvas, presents V1 (this design) and V2 (a rejected NOC-console direction; ignore for this handoff). Open in a browser to see the live prototype.
- `v1-safe.jsx` — the V1 component. **This is the design reference.** Read this end-to-end; every visual detail in this README maps to specific code in this file.
- `data.jsx` — mock dataset (2,000 generated devices). Replace with real `useDevices()` in production.
- `icons.jsx` — hand-rolled lucide SVGs. Replace with `lucide-react` in production.
- `design-canvas.jsx` — the side-by-side presentation harness. Not part of the page; ignore for production.

## Out of Scope for This Handoff

- The V2 "NOC console" direction shown in `Devices Redesign.html` is **rejected**. Implement V1 only.
- The Categories and Assignments redesigns are separate handoffs.
- The light-theme tokens are defined but not the focus; MonCTL's default is dark. Light support comes for free since all colors are CSS custom properties.

## Open Questions for the Implementing Team

1. Does the existing `FlexTable` already support per-column filter inputs? If yes, re-skin its header to add the drag-grip + sort row above the input rather than forking. If not, add this capability to FlexTable rather than building it inside `DevicesBetaPage` only.
2. Is there an existing pattern for cross-page filter persistence (URL or local storage)? Prefer URL so saved views are bookmarks.
3. Does the existing nav system support a "beta" pill on items? If not, ship as a separate "Devices (beta)" item for now.
