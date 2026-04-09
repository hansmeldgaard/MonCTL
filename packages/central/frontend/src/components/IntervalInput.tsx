import { useState, useEffect, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const UNITS = [
  { value: "s", label: "Seconds", factor: 1 },
  { value: "m", label: "Minutes", factor: 60 },
  { value: "h", label: "Hours", factor: 3600 },
  { value: "d", label: "Days", factor: 86400 },
] as const;

type Unit = (typeof UNITS)[number]["value"];

/** Decompose seconds into the best human-friendly unit + value. */
export function secondsToUnit(totalSeconds: number): {
  value: number;
  unit: Unit;
} {
  if (totalSeconds <= 0) return { value: totalSeconds, unit: "s" };
  for (const { value: u, factor } of [...UNITS].reverse()) {
    if (totalSeconds >= factor && totalSeconds % factor === 0) {
      return { value: totalSeconds / factor, unit: u };
    }
  }
  return { value: totalSeconds, unit: "s" };
}

/** Format seconds to optimal human string: 300 -> "5m", 7200 -> "2h" */
export function formatInterval(seconds: number): string {
  const { value, unit } = secondsToUnit(seconds);
  const labels: Record<Unit, string> = { s: "s", m: "m", h: "h", d: "d" };
  return `${value}${labels[unit]}`;
}

/** Format seconds to a longer label: 300 -> "5 min", 7200 -> "2 hours" */
export function formatIntervalLong(seconds: number): string {
  const { value, unit } = secondsToUnit(seconds);
  const labels: Record<Unit, [string, string]> = {
    s: ["sec", "sec"],
    m: ["min", "min"],
    h: ["hour", "hours"],
    d: ["day", "days"],
  };
  const [singular, plural] = labels[unit];
  return `${value} ${value === 1 ? singular : plural}`;
}

interface IntervalInputProps {
  /** Current value in seconds (as string, matching schedule_value) */
  value: string;
  onChange: (secondsStr: string) => void;
  disabled?: boolean;
  className?: string;
  id?: string;
}

export function IntervalInput({
  value,
  onChange,
  disabled,
  className,
  id,
}: IntervalInputProps) {
  const totalSeconds = Number(value) || 0;
  const decomposed = secondsToUnit(totalSeconds || 60);

  const [numValue, setNumValue] = useState(String(decomposed.value));
  const [unit, setUnit] = useState<Unit>(decomposed.unit);

  // Sync from external value changes (e.g., loading assignment)
  useEffect(() => {
    const secs = Number(value) || 0;
    if (secs > 0) {
      const d = secondsToUnit(secs);
      setNumValue(String(d.value));
      setUnit(d.unit);
    }
  }, [value]);

  const emitChange = useCallback(
    (num: string, u: Unit) => {
      const n = Number(num);
      if (!isNaN(n) && n > 0) {
        const factor = UNITS.find((x) => x.value === u)!.factor;
        onChange(String(n * factor));
      }
    },
    [onChange],
  );

  return (
    <div className={`flex gap-1.5 ${className ?? ""}`}>
      <Input
        id={id}
        type="number"
        min={1}
        value={numValue}
        onChange={(e) => {
          setNumValue(e.target.value);
          emitChange(e.target.value, unit);
        }}
        disabled={disabled}
        className="flex-1"
      />
      <Select
        value={unit}
        onChange={(e) => {
          const newUnit = e.target.value as Unit;
          setUnit(newUnit);
          emitChange(numValue, newUnit);
        }}
        disabled={disabled}
        className="w-24"
      >
        {UNITS.map((u) => (
          <option key={u.value} value={u.value}>
            {u.label}
          </option>
        ))}
      </Select>
    </div>
  );
}
