// V1 — Faithful refresh of the real MonCTL Devices page.
// Honors actual app.css tokens, real Device columns, real lucide icons,
// real FlexTable patterns (drag handle + label + sort arrow + filter input
// per column), DisplayMenu pattern, PaginationBar. Tightens visual rhythm,
// adds a status filter strip + selection action bar.

(function () {
  const { useState, useMemo, useCallback } = React;
  const { ALL, counts, fmtRel } = window.MONCTL;
  const Icon = window.Icon;

  // ---- Theme tokens (mapped 1:1 from app.css) -----------------------------
  const themeStyles = {
    dark: {
      "--bg":      "oklch(0.13 0.01 260)",   // surface-950 / zinc-950
      "--surf":    "oklch(0.17 0.012 260)",  // surface-900
      "--surf-2":  "oklch(0.19 0.012 260)",  // surface-850
      "--surf-3":  "oklch(0.22 0.012 260)",  // surface-800
      "--border":  "oklch(0.28 0.012 260)",  // surface-700
      "--border-2":"oklch(0.35 0.012 260)",  // surface-600
      "--text":    "oklch(0.96 0.002 260)",
      "--text-2":  "oklch(0.78 0.005 260)",
      "--text-3":  "oklch(0.58 0.006 260)",
      "--text-4":  "oklch(0.42 0.006 260)",
      "--brand":   "oklch(0.58 0.16 250)",
      "--brand-2": "oklch(0.68 0.12 250)",
      "--up":      "oklch(0.72 0.16 152)",   // emerald-500
      "--down":    "oklch(0.65 0.22 25)",    // red-500
      "--warn":    "oklch(0.80 0.17 80)",
    },
    light: {
      "--bg":      "oklch(0.985 0.002 260)",
      "--surf":    "oklch(1 0 0)",
      "--surf-2":  "oklch(0.97 0.005 260)",
      "--surf-3":  "oklch(0.95 0.005 260)",
      "--border":  "oklch(0.91 0.006 260)",
      "--border-2":"oklch(0.84 0.008 260)",
      "--text":    "oklch(0.20 0.008 260)",
      "--text-2":  "oklch(0.36 0.008 260)",
      "--text-3":  "oklch(0.55 0.008 260)",
      "--text-4":  "oklch(0.70 0.008 260)",
      "--brand":   "oklch(0.50 0.16 250)",
      "--brand-2": "oklch(0.42 0.14 250)",
      "--up":      "oklch(0.62 0.18 152)",
      "--down":    "oklch(0.58 0.22 25)",
      "--warn":    "oklch(0.72 0.17 80)",
    },
  };

  // ---- Column definitions, mirroring real DevicesPage ---------------------
  const COLS = [
    { key: "__select", label: "",        w: 40,  noSort: true, noFilter: true, locked: true },
    { key: "__status", label: "Status",  w: 64,  noSort: true, noFilter: true },
    { key: "name",     label: "Name",    w: 230 },
    { key: "address",  label: "Address", w: 130 },
    { key: "device_category",  label: "Category",  w: 160 },
    { key: "device_type_name", label: "Type",      w: 180 },
    { key: "tenant_name",      label: "Tenant",    w: 130 },
    { key: "collector_group_name", label: "Collector Group", w: 150 },
    { key: "__alerts", label: "Alerts",  w: 70,  noFilter: true },
    { key: "__last",   label: "Last poll", w: 100, noFilter: true },
    { key: "updated_at", label: "Updated", w: 150 },
  ];
  const TOTAL_W = COLS.reduce((s, c) => s + c.w, 0);

  function compare(a, b, key, dir) {
    const m = dir === "asc" ? 1 : -1;
    if (key === "__alerts") return (a.alerts - b.alerts) * m;
    if (key === "__last")   return (a.last_poll_sec - b.last_poll_sec) * m;
    if (key === "__status") {
      const r = (d) => !d.is_enabled ? 4 : d.reachable === false ? 0 : d.reachable === null ? 1 : 3;
      return (r(a) - r(b)) * m;
    }
    return String(a[key] ?? "").localeCompare(String(b[key] ?? "")) * m;
  }

  // ---- Atoms ---------------------------------------------------------------
  function StatusDot({ d }) {
    const color = !d.is_enabled ? "var(--text-4)"
                : d.reachable === true ? "var(--up)"
                : d.reachable === false ? "var(--down)"
                : "var(--text-4)";
    const pulse = d.is_enabled && d.reachable === true;
    return (
      <span style={{
        display: "inline-block", width: 8, height: 8, borderRadius: "50%",
        background: color,
        boxShadow: d.reachable === true ? `0 0 0 3px color-mix(in oklch, var(--up) 18%, transparent)` : "none",
        animation: pulse ? "monctlPulse 2s ease-in-out infinite" : undefined,
      }} />
    );
  }

  function CategoryCell({ d }) {
    const map = { router: "router", switch: "switch", server: "server", firewall: "firewall", container: "container", shield: "shield" };
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Icon name={map[d.category_icon] || "monitor"} size={14} style={{ color: "var(--text-3)" }} />
        <span style={{ color: "var(--text-2)", fontSize: 12 }}>{d.device_category}</span>
      </div>
    );
  }

  function Badge({ children, tone = "default" }) {
    const tones = {
      default: { bg: "var(--surf-3)", fg: "var(--text-2)", bd: "var(--border-2)" },
      brand:   { bg: "color-mix(in oklch, var(--brand) 18%, transparent)", fg: "var(--brand-2)", bd: "color-mix(in oklch, var(--brand) 35%, transparent)" },
    };
    const t = tones[tone];
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", height: 18, padding: "0 7px",
        borderRadius: 4, background: t.bg, color: t.fg,
        border: `1px solid ${t.bd}`,
        fontSize: 11, fontFamily: "var(--ui)", whiteSpace: "nowrap",
      }}>{children}</span>
    );
  }

  function ClearableInput({ value, onChange, placeholder, w }) {
    return (
      <div style={{ position: "relative", width: w ?? "100%" }}>
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? "Filter…"}
          style={{
            width: "100%", height: 22,
            background: "var(--surf-3)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            padding: "0 18px 0 6px",
            color: "var(--text)",
            fontFamily: "var(--mono)", fontSize: 11, outline: 0,
          }}
        />
        {value && (
          <button onClick={() => onChange("")} style={{
            position: "absolute", right: 2, top: "50%", transform: "translateY(-50%)",
            background: "transparent", border: 0, padding: 2, cursor: "pointer",
            color: "var(--text-3)", display: "flex", alignItems: "center",
          }}>
            <Icon name="x" size={11} />
          </button>
        )}
      </div>
    );
  }

  // ---- Header --------------------------------------------------------------
  function HeaderCell({ col, sort, setSort, filter, setFilter, allSel, toggleAll }) {
    const sortable = !col.noSort;
    const filterable = !col.noFilter;
    const active = sort.key === col.key;

    return (
      <div style={{
        flex: `0 0 ${col.w}px`, width: col.w,
        padding: "8px 12px",
        borderRight: "1px solid var(--border)",
        background: "var(--surf-2)",
      }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
          {!col.locked && col.label && (
            <span style={{ marginTop: 2, color: "var(--text-4)", cursor: "grab", display: "flex" }}>
              <Icon name="grip" size={11} />
            </span>
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              onClick={sortable ? () => setSort({ key: col.key, dir: active && sort.dir === "asc" ? "desc" : "asc" }) : undefined}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                fontFamily: "var(--ui)", fontSize: 11, fontWeight: 500,
                color: active ? "var(--text)" : "var(--text-3)",
                cursor: sortable ? "pointer" : "default",
                userSelect: "none",
                height: 18,
              }}
            >
              {col.key === "__select" ? (
                <input type="checkbox" checked={allSel} onChange={toggleAll} style={{ width: 13, height: 13, accentColor: "var(--brand)" }} />
              ) : (
                <>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{col.label}</span>
                  {sortable && (
                    <span style={{ color: active ? "var(--brand-2)" : "var(--text-4)", display: "flex" }}>
                      <Icon name={active ? (sort.dir === "asc" ? "arrowUp" : "arrowDown") : "arrowUpDown"} size={11} />
                    </span>
                  )}
                </>
              )}
            </div>
            {filterable && (
              <div style={{ marginTop: 6 }}>
                <ClearableInput value={filter} onChange={setFilter} />
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ---- Row -----------------------------------------------------------------
  function Row({ d, selected, onSelect }) {
    const cell = (extra) => ({
      flex: `0 0 ${extra.w}px`, width: extra.w,
      padding: "0 12px",
      display: "flex", alignItems: "center",
      borderRight: "1px solid var(--border)",
      fontFamily: "var(--ui)", fontSize: 12, color: "var(--text)",
      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      ...extra,
    });
    const dim = !d.is_enabled;

    return (
      <div
        style={{
          display: "flex",
          height: 30,
          background: selected ? "color-mix(in oklch, var(--brand) 12%, transparent)" : "transparent",
          borderBottom: "1px solid var(--border)",
          opacity: dim ? 0.6 : 1,
        }}
        onMouseEnter={(e) => { if (!selected) e.currentTarget.style.background = "var(--surf-2)"; }}
        onMouseLeave={(e) => { if (!selected) e.currentTarget.style.background = "transparent"; }}
      >
        <div style={cell({ w: 40, justifyContent: "center" })}>
          <input type="checkbox" checked={selected} onChange={() => onSelect(d.id)}
            style={{ width: 13, height: 13, accentColor: "var(--brand)" }} />
        </div>
        <div style={cell({ w: 64, justifyContent: "flex-start" })}>
          <StatusDot d={d} />
        </div>
        <div style={cell({ w: 230, color: "var(--text)" })}>
          <span style={{ color: "var(--brand-2)", overflow: "hidden", textOverflow: "ellipsis" }}>{d.name}</span>
        </div>
        <div style={cell({ w: 130, color: "var(--text-2)", fontFamily: "var(--mono)", fontSize: 11 })}>{d.address}</div>
        <div style={cell({ w: 160 })}><CategoryCell d={d} /></div>
        <div style={cell({ w: 180, color: "var(--text-2)", fontSize: 12 })}>
          {d.device_type_name || <span style={{ color: "var(--text-4)" }}>—</span>}
        </div>
        <div style={cell({ w: 130 })}><Badge>{d.tenant_name}</Badge></div>
        <div style={cell({ w: 150 })}><Badge>{d.collector_group_name}</Badge></div>
        <div style={cell({ w: 70, justifyContent: "flex-end" })}>
          {d.alerts > 0 ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3, color: d.alerts > 1 ? "var(--down)" : "var(--warn)", fontFamily: "var(--mono)", fontSize: 11.5, fontWeight: 600 }}>
              <Icon name="bell" size={11} /> {d.alerts}
            </span>
          ) : <span style={{ color: "var(--text-4)" }}>—</span>}
        </div>
        <div style={cell({ w: 100, justifyContent: "flex-end", color: d.reachable === false ? "var(--down)" : "var(--text-2)", fontFamily: "var(--mono)", fontSize: 11 })}>
          {fmtRel(d.last_poll_sec)}
        </div>
        <div style={cell({ w: 150, color: "var(--text-3)", fontFamily: "var(--mono)", fontSize: 11 })}>{d.updated_at}</div>
      </div>
    );
  }

  // ---- Virtualized list ----------------------------------------------------
  function VirtualBody({ items, selected, setSelected }) {
    const ROW_H = 31;
    const VH = 470;
    const [scroll, setScroll] = useState(0);
    const start = Math.max(0, Math.floor(scroll / ROW_H) - 6);
    const end = Math.min(items.length, Math.ceil((scroll + VH) / ROW_H) + 6);
    const slice = items.slice(start, end);
    const onSelect = useCallback((id) => {
      setSelected((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
    }, [setSelected]);
    return (
      <div style={{ height: VH, overflow: "auto", background: "var(--surf)" }} onScroll={(e) => setScroll(e.target.scrollTop)}>
        <div style={{ height: items.length * ROW_H, width: TOTAL_W, position: "relative" }}>
          <div style={{ position: "absolute", top: start * ROW_H, left: 0 }}>
            {slice.map((d) => <Row key={d.id} d={d} selected={selected.has(d.id)} onSelect={onSelect} />)}
          </div>
        </div>
      </div>
    );
  }

  // ---- Top toolbar ---------------------------------------------------------
  function TopBar({ count, total }) {
    const btnGhost = {
      display: "inline-flex", alignItems: "center", gap: 6,
      height: 28, padding: "0 12px", borderRadius: 6,
      background: "transparent", color: "var(--text-2)",
      border: "1px solid var(--border-2)",
      fontFamily: "var(--ui)", fontSize: 12, fontWeight: 500,
      cursor: "pointer",
    };
    const btnSolid = { ...btnGhost, background: "var(--surf-3)", color: "var(--text)" };
    const btnBrand = {
      ...btnGhost, background: "var(--brand)", color: "white",
      border: "1px solid var(--brand)",
    };
    return (
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "12px 16px",
      }}>
        <span style={{ fontFamily: "var(--ui)", fontSize: 13, color: "var(--text-3)" }}>
          <span style={{ color: "var(--text)", fontWeight: 600 }}>{count.toLocaleString()}</span>
          <span> of {total.toLocaleString()} devices</span>
        </span>
        <div style={{ flex: 1 }} />
        <button style={btnGhost}><Icon name="sliders" size={13} /> Display</button>
        <button style={btnSolid}><Icon name="folderIn" size={13} /> Import</button>
        <button style={btnBrand}><Icon name="plus" size={13} /> Add Device</button>
      </div>
    );
  }

  // ---- Status strip --------------------------------------------------------
  function StatusStrip({ all, statusFilter, setStatusFilter, q, setQ }) {
    const c = useMemo(() => counts(all), [all]);
    const seg = (key, label, color, n) => {
      const active = statusFilter === key;
      return (
        <button key={key} onClick={() => setStatusFilter(active ? "all" : key)} style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          height: 26, padding: "0 10px",
          background: active ? "color-mix(in oklch, var(--brand) 14%, transparent)" : "var(--surf-2)",
          border: `1px solid ${active ? "color-mix(in oklch, var(--brand) 40%, transparent)" : "var(--border)"}`,
          borderRadius: 13,
          color: active ? "var(--text)" : "var(--text-2)",
          fontFamily: "var(--ui)", fontSize: 11.5, fontWeight: 500,
          cursor: "pointer",
        }}>
          {color && <span style={{ width: 6, height: 6, borderRadius: "50%", background: color }} />}
          <span>{label}</span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: active ? "var(--text-2)" : "var(--text-3)" }}>{n.toLocaleString()}</span>
        </button>
      );
    };
    return (
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "0 16px 12px",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, height: 28,
          background: "var(--surf-2)", border: "1px solid var(--border)", borderRadius: 6,
          padding: "0 10px",
        }}>
          <Icon name="search" size={13} style={{ color: "var(--text-3)" }} />
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Search devices by name, address, type, tenant…"
            style={{
              flex: 1, height: 26, background: "transparent", border: 0, outline: 0,
              color: "var(--text)", fontFamily: "var(--mono)", fontSize: 12,
            }} />
          <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--text-3)",
            padding: "1px 6px", border: "1px solid var(--border-2)", borderRadius: 3 }}>⌘K</span>
        </div>
        {seg("all", "All", null, all.length)}
        {seg("up", "Up", "var(--up)", c.up)}
        {seg("down", "Down", "var(--down)", c.down)}
        {seg("unknown", "Unknown", "var(--text-4)", c.unknown)}
        {seg("disabled", "Disabled", "var(--text-4)", c.disabled)}
      </div>
    );
  }

  // ---- Card header bar (swaps in selection actions when rows are picked) --
  // Same height as the idle title bar so selecting rows never shifts the
  // table — your row position stays put while you keep selecting.
  function CardHeaderBar({ selectedCount, onClear }) {
    const btn = {
      display: "inline-flex", alignItems: "center", gap: 6,
      height: 24, padding: "0 10px", borderRadius: 4,
      background: "var(--surf-3)", color: "var(--text-2)",
      border: "1px solid var(--border-2)",
      fontFamily: "var(--ui)", fontSize: 11, cursor: "pointer",
    };
    const selecting = selectedCount > 0;
    return (
      <div style={{
        height: 44,
        padding: "0 16px",
        display: "flex", alignItems: "center", gap: 8,
        borderBottom: "1px solid var(--border)",
        background: selecting ? "color-mix(in oklch, var(--brand) 8%, transparent)" : "transparent",
        transition: "background 0.12s",
      }}>
        {selecting ? (
          <>
            <span style={{ fontFamily: "var(--ui)", fontSize: 12, color: "var(--text)" }}>
              <span style={{ color: "var(--brand-2)", fontWeight: 600 }}>{selectedCount}</span> selected
            </span>
            <button onClick={onClear} style={{ ...btn, background: "transparent" }}>Clear</button>
            <span style={{ width: 1, height: 16, background: "var(--border-2)", margin: "0 4px" }} />
            <button style={btn}><Icon name="power" size={11} /> Enable</button>
            <button style={btn}><Icon name="power" size={11} /> Disable</button>
            <button style={btn}><Icon name="folderIn" size={11} /> Move tenant</button>
            <button style={btn}><Icon name="folderIn" size={11} /> Move group</button>
            <button style={btn}><Icon name="tag" size={11} /> Apply template</button>
            <button style={{ ...btn, color: "var(--down)", borderColor: "color-mix(in oklch, var(--down) 35%, transparent)" }}>
              <Icon name="trash" size={11} /> Delete
            </button>
          </>
        ) : (
          <>
            <Icon name="monitor" size={14} style={{ color: "var(--text-3)" }} />
            <span style={{ fontSize: 12, color: "var(--text-3)", fontWeight: 500 }}>Devices</span>
          </>
        )}
      </div>
    );
  }

  // ---- Saved searches strip -----------------------------------------------
  // Mirrors the real app's saved-view contract: a primary view + named
  // user-saved filter sets. Active view is highlighted; "+ Save current"
  // captures the current statusFilter / q / per-column filters.
  const SAVED_VIEWS = [
    { id: "all",        name: "All devices",     primary: true,                  apply: () => ({ statusFilter: "all",      q: "", filters: {} }) },
    { id: "down",       name: "Down right now",  badge: "down",                  apply: () => ({ statusFilter: "down",     q: "", filters: {} }) },
    { id: "alerts",     name: "With active alerts",                              apply: () => ({ statusFilter: "all",      q: "", filters: {} }) },
    { id: "prod-edge",  name: "Prod edge routers",                               apply: () => ({ statusFilter: "all",      q: "", filters: { tenant_name: "prod", device_category: "router" } }) },
    { id: "f5",         name: "F5 BIG-IP fleet",                                  apply: () => ({ statusFilter: "all",      q: "", filters: { device_type_name: "f5" } }) },
    { id: "unknown",    name: "Never polled",     badge: "unknown",               apply: () => ({ statusFilter: "unknown",  q: "", filters: {} }) },
  ];

  function SavedViews({ activeId, onPick, onSave }) {
    return (
      <div style={{
        display: "flex", alignItems: "center", gap: 6, flexWrap: "nowrap",
        padding: "0 16px 10px",
        overflowX: "auto",
      }}>
        <span style={{
          fontFamily: "var(--ui)", fontSize: 10.5, color: "var(--text-4)",
          textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 500,
          marginRight: 4, flexShrink: 0,
        }}>Views</span>
        {SAVED_VIEWS.map((v) => {
          const active = activeId === v.id;
          return (
            <button key={v.id} onClick={() => onPick(v)} style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              height: 24, padding: "0 10px", borderRadius: 4,
              background: active ? "color-mix(in oklch, var(--brand) 16%, transparent)" : "var(--surf-2)",
              border: `1px solid ${active ? "color-mix(in oklch, var(--brand) 45%, transparent)" : "var(--border)"}`,
              color: active ? "var(--text)" : "var(--text-2)",
              fontFamily: "var(--ui)", fontSize: 11.5, fontWeight: active ? 500 : 400,
              cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0,
            }}>
              {v.primary && <Icon name="activity" size={11} style={{ color: active ? "var(--brand-2)" : "var(--text-3)" }} />}
              {v.badge === "down"    && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--down)" }} />}
              {v.badge === "unknown" && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--text-4)" }} />}
              {v.name}
            </button>
          );
        })}
        <span style={{ width: 1, height: 16, background: "var(--border)", margin: "0 2px", flexShrink: 0 }} />
        <button onClick={onSave} style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          height: 24, padding: "0 10px", borderRadius: 4,
          background: "transparent",
          border: "1px dashed var(--border-2)",
          color: "var(--text-3)",
          fontFamily: "var(--ui)", fontSize: 11.5,
          cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0,
        }}>
          <Icon name="plus" size={11} /> Save current
        </button>
      </div>
    );
  }

  // ---- Main ----------------------------------------------------------------
  function MonctlSafe({ theme = "dark" }) {
    const [q, setQ] = useState("");
    const [statusFilter, setStatusFilter] = useState("all");
    const [filters, setFilters] = useState({});
    const [sort, setSort] = useState({ key: "name", dir: "asc" });
    const [selected, setSelected] = useState(new Set());
    const [activeView, setActiveView] = useState("all");

    const pickView = (v) => {
      const s = v.apply();
      setStatusFilter(s.statusFilter);
      setQ(s.q);
      setFilters(s.filters);
      setActiveView(v.id);
    };

    const filtered = useMemo(() => {
      let r = ALL;
      if (statusFilter !== "all") {
        r = r.filter((d) => {
          if (statusFilter === "disabled") return !d.is_enabled;
          if (!d.is_enabled) return false;
          if (statusFilter === "up") return d.reachable === true;
          if (statusFilter === "down") return d.reachable === false;
          if (statusFilter === "unknown") return d.reachable === null;
          return true;
        });
      }
      const ql = q.trim().toLowerCase();
      if (ql) {
        r = r.filter((d) =>
          d.name.toLowerCase().includes(ql) ||
          d.address.includes(ql) ||
          (d.device_type_name || "").toLowerCase().includes(ql) ||
          d.device_category.includes(ql) ||
          d.tenant_name.toLowerCase().includes(ql)
        );
      }
      // per-column filters
      for (const [k, v] of Object.entries(filters)) {
        if (!v) continue;
        const vl = v.toLowerCase();
        r = r.filter((d) => String(d[k] ?? "").toLowerCase().includes(vl));
      }
      return [...r].sort((a, b) => compare(a, b, sort.key, sort.dir));
    }, [q, statusFilter, filters, sort]);

    const allSel = filtered.length > 0 && filtered.slice(0, 200).every((d) => selected.has(d.id));
    const toggleAll = () => {
      if (allSel) setSelected(new Set());
      else setSelected(new Set(filtered.slice(0, 200).map((d) => d.id)));
    };

    const themeVars = themeStyles[theme];

    return (
      <div style={{
        ...themeVars,
        "--ui": "Inter, system-ui, sans-serif",
        "--mono": "'JetBrains Mono', ui-monospace, monospace",
        background: "var(--bg)", color: "var(--text)",
        height: "100%", display: "flex", flexDirection: "column",
        fontFamily: "var(--ui)",
      }}>
        <style>{`@keyframes monctlPulse { 0%,100% { opacity: 1 } 50% { opacity: 0.4 } }`}</style>

        <TopBar count={filtered.length} total={ALL.length} />
        <SavedViews activeId={activeView} onPick={pickView} onSave={() => {}} />
        <StatusStrip all={ALL} statusFilter={statusFilter} setStatusFilter={(k) => { setStatusFilter(k); setActiveView(null); }} q={q} setQ={(v) => { setQ(v); setActiveView(null); }} />

        {/* Card */}
        <div style={{
          margin: "0 16px 16px",
          background: "var(--surf)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          overflow: "hidden",
          display: "flex", flexDirection: "column", flex: 1, minHeight: 0,
        }}>
          {/* Card header — swaps idle title for selection action bar in place,
              same height so the table doesn't shift while you select. */}
          <CardHeaderBar selectedCount={selected.size} onClear={() => setSelected(new Set())} />

          {/* Table */}
          <div style={{ flex: 1, overflowX: "auto", minHeight: 0 }}>
            <div style={{ minWidth: TOTAL_W, display: "flex", flexDirection: "column", height: "100%" }}>
              <div style={{ display: "flex", borderBottom: "1px solid var(--border-2)" }}>
                {COLS.map((c) => (
                  <HeaderCell key={c.key} col={c}
                    sort={sort} setSort={setSort}
                    filter={filters[c.key] ?? ""}
                    setFilter={(v) => setFilters((p) => ({ ...p, [c.key]: v }))}
                    allSel={allSel} toggleAll={toggleAll} />
                ))}
              </div>
              <div style={{ flex: 1, minHeight: 0 }}>
                <VirtualBody items={filtered} selected={selected} setSelected={setSelected} />
              </div>
            </div>
          </div>

          {/* Footer */}
          <div style={{
            display: "flex", alignItems: "center",
            padding: "8px 16px", borderTop: "1px solid var(--border)",
            fontFamily: "var(--ui)", fontSize: 12, color: "var(--text-3)",
          }}>
            <span>{filtered.length === 0 ? "No results" : `1–${Math.min(filtered.length, 100).toLocaleString()} of ${filtered.length.toLocaleString()}`}</span>
            <div style={{ flex: 1 }} />
            <button style={{ background: "transparent", border: 0, padding: 4, color: "var(--text-3)", cursor: "pointer", display: "flex" }}>
              <Icon name="chevronL" size={14} />
            </button>
            <button style={{ background: "transparent", border: 0, padding: 4, color: "var(--text-2)", cursor: "pointer", display: "flex" }}>
              <Icon name="chevronR" size={14} />
            </button>
          </div>
        </div>
      </div>
    );
  }

  window.MonctlSafe = MonctlSafe;
})();
