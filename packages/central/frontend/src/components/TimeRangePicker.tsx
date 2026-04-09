import { useEffect, useRef, useState } from "react";
import { Calendar, ChevronDown, Clock } from "lucide-react";
import { cn } from "@/lib/utils.ts";

// ── Types ────────────────────────────────────────────────────────────────────

export type TimeRangePreset =
  | "15m"
  | "30m"
  | "1h"
  | "4h"
  | "12h"
  | "24h"
  | "7d"
  | "30d"
  | "all";

export type TimeRangeValue =
  | { type: "preset"; preset: TimeRangePreset }
  | {
      type: "relative";
      value: number;
      unit: "minutes" | "hours" | "days" | "weeks";
    }
  | { type: "absolute"; fromTs: string; toTs: string | null };

export interface TimeRange {
  fromTs: string | null; // null = no lower bound
  toTs: string | null; // null = now
}

const PRESET_OPTIONS: {
  preset: TimeRangePreset;
  label: string;
  ms: number | null;
}[] = [
  { preset: "15m", label: "Last 15 minutes", ms: 15 * 60 * 1000 },
  { preset: "30m", label: "Last 30 minutes", ms: 30 * 60 * 1000 },
  { preset: "1h", label: "Last 1 hour", ms: 1 * 60 * 60 * 1000 },
  { preset: "4h", label: "Last 4 hours", ms: 4 * 60 * 60 * 1000 },
  { preset: "12h", label: "Last 12 hours", ms: 12 * 60 * 60 * 1000 },
  { preset: "24h", label: "Last 24 hours", ms: 24 * 60 * 60 * 1000 },
  { preset: "7d", label: "Last 7 days", ms: 7 * 24 * 60 * 60 * 1000 },
  { preset: "30d", label: "Last 30 days", ms: 30 * 24 * 60 * 60 * 1000 },
  { preset: "all", label: "All time", ms: null },
];

const UNIT_LABELS = {
  minutes: "Minutes",
  hours: "Hours",
  days: "Days",
  weeks: "Weeks",
};

const UNIT_MS: Record<string, number> = {
  minutes: 60 * 1000,
  hours: 60 * 60 * 1000,
  days: 24 * 60 * 60 * 1000,
  weeks: 7 * 24 * 60 * 60 * 1000,
};

// ── Helpers ──────────────────────────────────────────────────────────────────

export function rangeToTimestamps(r: TimeRangeValue): TimeRange {
  if (r.type === "preset") {
    const opt = PRESET_OPTIONS.find((o) => o.preset === r.preset);
    if (!opt || opt.ms === null) return { fromTs: null, toTs: null };
    // Round to nearest minute so the queryKey is stable within a 60-second window,
    // preventing spurious re-fetches on every React render.
    const nowMin = Math.floor(Date.now() / 60_000) * 60_000;
    return { fromTs: new Date(nowMin - opt.ms).toISOString(), toTs: null };
  }
  if (r.type === "relative") {
    const ms = r.value * UNIT_MS[r.unit];
    const nowMin = Math.floor(Date.now() / 60_000) * 60_000;
    return { fromTs: new Date(nowMin - ms).toISOString(), toTs: null };
  }
  // absolute — user-supplied, already stable
  return { fromTs: r.fromTs, toTs: r.toTs };
}

export function rangeLabel(r: TimeRangeValue, timezone = "UTC"): string {
  if (r.type === "preset") {
    return PRESET_OPTIONS.find((o) => o.preset === r.preset)?.label ?? r.preset;
  }
  if (r.type === "relative") {
    return `Last ${r.value} ${UNIT_LABELS[r.unit].toLowerCase()}`;
  }
  // absolute
  const from = r.fromTs
    ? new Date(r.fromTs).toLocaleString("en-US", { timeZone: timezone })
    : "beginning";
  const to = r.toTs
    ? new Date(r.toTs).toLocaleString("en-US", { timeZone: timezone })
    : "now";
  return `${from} → ${to}`;
}

// Format datetime to value for datetime-local input (local time, no timezone)
function toDatetimeLocal(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

// ── Component ────────────────────────────────────────────────────────────────

interface TimeRangePickerProps {
  value: TimeRangeValue;
  onChange: (range: TimeRangeValue) => void;
  className?: string;
  timezone?: string;
}

export function TimeRangePicker({
  value,
  onChange,
  className,
  timezone = "UTC",
}: TimeRangePickerProps) {
  const [open, setOpen] = useState(false);
  const [customTab, setCustomTab] = useState<"relative" | "absolute">(
    "relative",
  );

  // Relative inputs
  const [relValue, setRelValue] = useState(1);
  const [relUnit, setRelUnit] = useState<
    "minutes" | "hours" | "days" | "weeks"
  >("hours");

  // Absolute inputs (defaults to last 1h range)
  const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
  const [absFrom, setAbsFrom] = useState(toDatetimeLocal(oneHourAgo));
  const [absTo, setAbsTo] = useState(""); // empty = now

  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  function selectPreset(preset: TimeRangePreset) {
    onChange({ type: "preset", preset });
    setOpen(false);
  }

  function applyRelative() {
    onChange({ type: "relative", value: relValue, unit: relUnit });
    setOpen(false);
  }

  function applyAbsolute() {
    const from = absFrom ? new Date(absFrom).toISOString() : null;
    const to = absTo ? new Date(absTo).toISOString() : null;
    if (!from) return;
    onChange({ type: "absolute", fromTs: from, toTs: to });
    setOpen(false);
  }

  const label = rangeLabel(value, timezone);

  return (
    <div ref={ref} className={cn("relative", className)}>
      {/* Trigger button */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border transition-colors cursor-pointer",
          open
            ? "bg-brand-600/20 text-brand-400 border-brand-600/40"
            : "text-zinc-400 bg-zinc-800/60 border-zinc-700 hover:border-zinc-600 hover:text-zinc-200",
        )}
      >
        <Clock className="h-3.5 w-3.5" />
        <span>{label}</span>
        <ChevronDown
          className={cn("h-3 w-3 transition-transform", open && "rotate-180")}
        />
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-[520px] rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl overflow-hidden">
          <div className="flex">
            {/* Left: presets */}
            <div className="w-44 border-r border-zinc-800 py-2">
              <p className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                Quick Range
              </p>
              {PRESET_OPTIONS.map((opt) => (
                <button
                  key={opt.preset}
                  onClick={() => selectPreset(opt.preset)}
                  className={cn(
                    "w-full text-left px-3 py-1.5 text-xs transition-colors cursor-pointer",
                    value.type === "preset" && value.preset === opt.preset
                      ? "text-brand-400 bg-brand-600/10"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800",
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {/* Right: custom */}
            <div className="flex-1 p-3 space-y-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                Custom Range
              </p>

              {/* Tab selector */}
              <div className="flex gap-1">
                {(["relative", "absolute"] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setCustomTab(tab)}
                    className={cn(
                      "px-3 py-1 text-xs rounded-md transition-colors cursor-pointer capitalize",
                      customTab === tab
                        ? "bg-zinc-700 text-zinc-100"
                        : "text-zinc-500 hover:text-zinc-300",
                    )}
                  >
                    {tab}
                  </button>
                ))}
              </div>

              {customTab === "relative" && (
                <div className="space-y-3">
                  <p className="text-xs text-zinc-500">
                    Show data from the last:
                  </p>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min={1}
                      value={relValue}
                      onChange={(e) => setRelValue(Number(e.target.value))}
                      className="w-20 rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50"
                    />
                    <select
                      value={relUnit}
                      onChange={(e) =>
                        setRelUnit(e.target.value as typeof relUnit)
                      }
                      className="flex-1 rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50"
                    >
                      {Object.entries(UNIT_LABELS).map(([val, lbl]) => (
                        <option key={val} value={val}>
                          {lbl}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button
                    onClick={applyRelative}
                    className="w-full rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-500 transition-colors cursor-pointer"
                  >
                    Apply
                  </button>
                </div>
              )}

              {customTab === "absolute" && (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <label className="text-xs text-zinc-500 flex items-center gap-1.5">
                      <Calendar className="h-3 w-3" /> From
                    </label>
                    <input
                      type="datetime-local"
                      value={absFrom}
                      onChange={(e) => setAbsFrom(e.target.value)}
                      className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50 [color-scheme:dark]"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs text-zinc-500 flex items-center gap-1.5">
                      <Calendar className="h-3 w-3" /> To (leave empty for now)
                    </label>
                    <input
                      type="datetime-local"
                      value={absTo}
                      onChange={(e) => setAbsTo(e.target.value)}
                      className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50 [color-scheme:dark]"
                    />
                  </div>
                  <button
                    onClick={applyAbsolute}
                    disabled={!absFrom}
                    className="w-full rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-500 transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    Apply
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
