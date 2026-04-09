import { useState, useRef, useCallback } from "react";
import { TableHead } from "@/components/ui/table";

interface BulkToggleState {
  polling: boolean | "mixed";
  alerting: boolean | "mixed";
  traffic: boolean | "mixed";
  errors: boolean | "mixed";
  discards: boolean | "mixed";
  status: boolean | "mixed";
}

interface InterfaceToggleBulkHeadProps {
  activeSelectedCount: number;
  state: BulkToggleState;
  onTogglePolling: (enable: boolean) => void;
  onToggleAlerting: (enable: boolean) => void;
  onToggleMetric: (metric: string, enable: boolean) => void;
}

const ITEMS: {
  label: string;
  field: keyof BulkToggleState;
  group: "monitoring" | "metrics";
}[] = [
  { label: "Poll", field: "polling", group: "monitoring" },
  { label: "Alert", field: "alerting", group: "monitoring" },
  { label: "Traffic", field: "traffic", group: "metrics" },
  { label: "Errors", field: "errors", group: "metrics" },
  { label: "Discards", field: "discards", group: "metrics" },
  { label: "Status", field: "status", group: "metrics" },
];

export function InterfaceToggleBulkHead({
  activeSelectedCount,
  state,
  onTogglePolling,
  onToggleAlerting,
  onToggleMetric,
}: InterfaceToggleBulkHeadProps) {
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

  const handleToggle = (field: keyof BulkToggleState) => {
    const enable = state[field] !== true;
    if (field === "polling") onTogglePolling(enable);
    else if (field === "alerting") onToggleAlerting(enable);
    else onToggleMetric(field, enable);
  };

  const hasSelection = activeSelectedCount > 0;

  return (
    <TableHead className="text-center w-20 relative">
      <div
        className={`text-xs ${hasSelection ? "cursor-pointer hover:text-zinc-200" : ""}`}
        onMouseEnter={() => {
          if (hasSelection) {
            cancelClose();
            setOpen(true);
          }
        }}
        onMouseLeave={scheduleClose}
        onClick={(e) => {
          e.stopPropagation();
          if (hasSelection) setOpen((prev) => !prev);
        }}
      >
        Toggles
        {hasSelection && (
          <span className="ml-1 text-brand-400 text-[10px]">
            ({activeSelectedCount})
          </span>
        )}
      </div>

      {open && hasSelection && (
        <div
          className="absolute right-0 top-full mt-1 z-50 bg-zinc-700 border border-zinc-600 rounded-lg shadow-xl p-2 min-w-[180px] text-left"
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-[10px] text-zinc-400 px-2 pb-1">
            Bulk ({activeSelectedCount} selected)
          </div>
          {ITEMS.map((item, i) => (
            <div key={item.label}>
              {i === 2 && <div className="border-t border-zinc-600 my-1" />}
              <button
                className="flex items-center gap-2 w-full px-2 py-1 rounded text-xs hover:bg-zinc-600 transition-colors cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation();
                  handleToggle(item.field);
                }}
              >
                <input
                  type="checkbox"
                  checked={state[item.field] === true}
                  ref={(el) => {
                    if (el) el.indeterminate = state[item.field] === "mixed";
                  }}
                  readOnly
                  className="accent-brand-500 pointer-events-none h-3 w-3"
                />
                <span className="text-zinc-300">{item.label}</span>
              </button>
            </div>
          ))}
        </div>
      )}
    </TableHead>
  );
}
