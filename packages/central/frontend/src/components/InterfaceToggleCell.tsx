import { useState, useRef, useCallback } from "react";

interface ToggleState {
  polling_enabled: boolean;
  alerting_enabled: boolean;
  traffic: boolean;
  errors: boolean;
  discards: boolean;
  status: boolean;
}

interface InterfaceToggleCellProps {
  state: ToggleState;
  onTogglePolling: () => void;
  onToggleAlerting: () => void;
  onToggleMetric: (metric: string) => void;
}

const DOTS: { key: string; field: keyof ToggleState; color: string }[] = [
  { key: "poll", field: "polling_enabled", color: "bg-brand-500" },
  { key: "alert", field: "alerting_enabled", color: "bg-amber-500" },
  { key: "traffic", field: "traffic", color: "bg-emerald-500" },
  { key: "errors", field: "errors", color: "bg-emerald-500" },
  { key: "discards", field: "discards", color: "bg-emerald-500" },
  { key: "status", field: "status", color: "bg-emerald-500" },
];

export function InterfaceToggleCell({
  state,
  onTogglePolling,
  onToggleAlerting,
  onToggleMetric,
}: InterfaceToggleCellProps) {
  const [open, setOpen] = useState(false);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleClose = useCallback(() => {
    closeTimerRef.current = setTimeout(() => setOpen(false), 150);
  }, []);

  const cancelClose = useCallback(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const toggleItems: { label: string; active: boolean; onToggle: () => void; color: string }[] = [
    { label: "Poll", active: state.polling_enabled, onToggle: onTogglePolling, color: "bg-brand-500" },
    { label: "Alert", active: state.alerting_enabled, onToggle: onToggleAlerting, color: "bg-amber-500" },
    { label: "Traffic", active: state.traffic, onToggle: () => onToggleMetric("traffic"), color: "bg-emerald-500" },
    { label: "Errors", active: state.errors, onToggle: () => onToggleMetric("errors"), color: "bg-emerald-500" },
    { label: "Discards", active: state.discards, onToggle: () => onToggleMetric("discards"), color: "bg-emerald-500" },
    { label: "Status", active: state.status, onToggle: () => onToggleMetric("status"), color: "bg-emerald-500" },
  ];

  return (
    <div
      className="relative"
      onMouseEnter={() => { cancelClose(); setOpen(true); }}
      onMouseLeave={scheduleClose}
      onClick={(e) => { e.stopPropagation(); setOpen((prev) => !prev); }}
    >
      {/* Collapsed: dot strip */}
      <div className="flex items-center gap-1 cursor-pointer px-1 py-0.5 rounded hover:bg-zinc-800 transition-colors">
        {DOTS.map((d) => (
          <div
            key={d.key}
            className={`h-2 w-2 rounded-full transition-colors ${
              state[d.field] ? d.color : "bg-zinc-700"
            }`}
            title={`${d.key}: ${state[d.field] ? "on" : "off"}`}
          />
        ))}
      </div>

      {/* Expanded: popover */}
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50 bg-zinc-700 border border-zinc-600 rounded-lg shadow-xl p-2 min-w-[140px]"
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
          onClick={(e) => e.stopPropagation()}
        >
          {toggleItems.map((item, i) => (
            <div key={item.label}>
              {i === 2 && <div className="border-t border-zinc-600 my-1" />}
              <button
                className="flex items-center gap-2 w-full px-2 py-1 rounded text-xs hover:bg-zinc-600 transition-colors cursor-pointer"
                onClick={(e) => { e.stopPropagation(); item.onToggle(); }}
              >
                <div
                  className={`h-3 w-3 rounded border transition-colors ${
                    item.active
                      ? `${item.color} border-transparent`
                      : "bg-transparent border-zinc-400"
                  }`}
                />
                <span className={item.active ? "text-zinc-100" : "text-zinc-300"}>
                  {item.label}
                </span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
