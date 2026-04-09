import { useState, useRef, useEffect } from "react";
import { Clock } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";

export interface TimeRange {
  from: string;
  to: string;
}

const PRESETS: { label: string; from: string; to: string }[] = [
  { label: "Last 15m", from: "now-15m", to: "now" },
  { label: "Last 1h", from: "now-1h", to: "now" },
  { label: "Last 6h", from: "now-6h", to: "now" },
  { label: "Last 24h", from: "now-24h", to: "now" },
  { label: "Last 7d", from: "now-7d", to: "now" },
  { label: "Last 30d", from: "now-30d", to: "now" },
];

function formatLabel(range: TimeRange): string {
  const preset = PRESETS.find(
    (p) => p.from === range.from && p.to === range.to,
  );
  if (preset) return preset.label;
  return "Custom";
}

interface Props {
  value: TimeRange;
  onChange: (range: TimeRange) => void;
}

export function DashboardTimePicker({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function applyCustom() {
    if (!customFrom || !customTo) return;
    onChange({ from: customFrom, to: customTo });
    setOpen(false);
  }

  return (
    <div className="relative" ref={ref}>
      <Button
        size="sm"
        variant="outline"
        onClick={() => setOpen(!open)}
        className="gap-1 text-xs"
      >
        <Clock className="h-3 w-3" />
        {formatLabel(value)}
      </Button>
      {open && (
        <div className="absolute left-0 top-full mt-1 z-30 bg-zinc-800 border border-zinc-700 rounded-md shadow-lg min-w-52 py-1">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => {
                onChange({ from: p.from, to: p.to });
                setOpen(false);
              }}
              className={`w-full text-left px-3 py-1.5 text-xs hover:bg-zinc-700 ${
                value.from === p.from && value.to === p.to
                  ? "text-brand-400"
                  : "text-zinc-300"
              }`}
            >
              {p.label}
            </button>
          ))}
          <div className="border-t border-zinc-700 mt-1 pt-2 px-3 pb-2 space-y-2">
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide">
              Custom Range
            </span>
            <Input
              type="datetime-local"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
              className="text-xs h-7"
            />
            <Input
              type="datetime-local"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
              className="text-xs h-7"
            />
            <Button
              size="sm"
              className="w-full text-xs h-7"
              onClick={applyCustom}
            >
              Apply
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
