import { cn } from "@/lib/utils.ts";

export type TimeRange = "1h" | "6h" | "24h" | "7d";

const RANGES: { label: TimeRange; ms: number }[] = [
  { label: "1h",  ms: 1 * 60 * 60 * 1000 },
  { label: "6h",  ms: 6 * 60 * 60 * 1000 },
  { label: "24h", ms: 24 * 60 * 60 * 1000 },
  { label: "7d",  ms: 7 * 24 * 60 * 60 * 1000 },
];

/** Returns the ISO string for now minus the selected range's ms */
export function rangeToFromTs(range: TimeRange): string {
  const r = RANGES.find((r) => r.label === range)!;
  return new Date(Date.now() - r.ms).toISOString();
}

interface TimePickerProps {
  value: TimeRange;
  onChange: (range: TimeRange) => void;
  className?: string;
}

export function TimePicker({ value, onChange, className }: TimePickerProps) {
  return (
    <div className={cn("flex items-center gap-1", className)}>
      {RANGES.map((r) => (
        <button
          key={r.label}
          onClick={() => onChange(r.label)}
          className={cn(
            "px-3 py-1 text-xs font-medium rounded-md transition-colors cursor-pointer",
            value === r.label
              ? "bg-brand-600/20 text-brand-400 border border-brand-600/40"
              : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 border border-transparent",
          )}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}
