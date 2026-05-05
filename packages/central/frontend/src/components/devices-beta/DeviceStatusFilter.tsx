import { Search, X } from "lucide-react";
import type { DeviceStatusCounts } from "@/types/api.ts";

type StatusKey = "all" | "up" | "down" | "unknown" | "disabled";

interface PillSpec {
  key: StatusKey;
  label: string;
  dotColor?: string; // CSS var name
}

const PILLS: PillSpec[] = [
  { key: "all", label: "All" },
  { key: "up", label: "Up", dotColor: "var(--up)" },
  { key: "down", label: "Down", dotColor: "var(--down)" },
  { key: "unknown", label: "Unknown", dotColor: "var(--text-4)" },
  { key: "disabled", label: "Disabled", dotColor: "var(--text-4)" },
];

interface DeviceStatusFilterProps {
  status: StatusKey;
  onStatusChange: (next: StatusKey) => void;
  query: string;
  onQueryChange: (next: string) => void;
  counts: DeviceStatusCounts;
}

export function DeviceStatusFilter({
  status,
  onStatusChange,
  query,
  onQueryChange,
  counts,
}: DeviceStatusFilterProps) {
  return (
    <div className="flex items-center gap-2 px-4 pb-3">
      <div
        className="flex h-7 min-w-0 flex-1 items-center gap-2 rounded-md border px-2.5"
        style={{
          background: "var(--surf-2)",
          borderColor: "var(--border)",
        }}
      >
        <Search
          className="h-3.5 w-3.5 shrink-0"
          style={{ color: "var(--text-3)" }}
        />
        <input
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search devices by name or address…"
          className="flex-1 bg-transparent border-0 outline-none text-xs"
          style={{
            color: "var(--text)",
            fontFamily:
              "'JetBrains Mono', ui-monospace, SFMono-Regular, monospace",
          }}
        />
        {query && (
          <button
            type="button"
            onClick={() => onQueryChange("")}
            className="cursor-pointer rounded p-0.5 transition-colors hover:bg-white/5"
            style={{ color: "var(--text-3)" }}
            aria-label="Clear search"
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
      {PILLS.map((p) => {
        const active = status === p.key;
        const count = counts[p.key];
        return (
          <button
            key={p.key}
            type="button"
            onClick={() => onStatusChange(active ? "all" : p.key)}
            className="flex h-[26px] cursor-pointer items-center gap-1.5 rounded-[13px] border px-2.5 text-xs transition-colors"
            style={{
              background: active
                ? "color-mix(in oklch, var(--brand) 14%, transparent)"
                : "var(--surf-2)",
              borderColor: active
                ? "color-mix(in oklch, var(--brand) 40%, transparent)"
                : "var(--border)",
              color: active ? "var(--text)" : "var(--text-2)",
            }}
          >
            {p.dotColor && (
              <span
                aria-hidden
                className="block h-1.5 w-1.5 rounded-full"
                style={{ background: p.dotColor }}
              />
            )}
            <span>{p.label}</span>
            <span
              className="text-[10.5px]"
              style={{
                color: active ? "var(--text-3)" : "var(--text-4)",
                fontFamily:
                  "'JetBrains Mono', ui-monospace, SFMono-Regular, monospace",
              }}
            >
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
