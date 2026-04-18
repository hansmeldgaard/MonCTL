import { useEffect, useRef, useState } from "react";
import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import type { FlexColumnDef, ColumnConfigMap } from "./types.ts";

interface Props<TRow> {
  /** Columns available for this table — drives the Columns checklist. */
  columns: FlexColumnDef<TRow>[];
  /** Current column config (hidden/width/order). */
  configMap: ColumnConfigMap;
  /** Toggle a column's hidden flag. */
  onToggleHidden: (key: string, hidden: boolean) => void;
  /** Clear all column config for this table. Does NOT reset the global
   *  display prefs (compact / time mode) — those are cross-table. */
  onReset: () => void;
}

/** Unified view-settings dropdown. Holds global display prefs (Compact
 *  density + Time display mode) and the per-table Columns checklist.
 *  One button in the toolbar, one menu for everything view-shaping. */
export function DisplayMenu<TRow>({
  columns,
  configMap,
  onToggleHidden,
  onReset,
}: Props<TRow>) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const { compact, timeMode, setCompact, setTimeMode } =
    useDisplayPreferences();

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const hideable = columns.filter((c) => !c.alwaysVisible);

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <SlidersHorizontal className="mr-1.5 h-3.5 w-3.5" />
        Display
      </Button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-64 rounded-md border border-zinc-800 bg-zinc-900 p-1 shadow-lg"
        >
          {/* Compact toggle */}
          <label className="flex cursor-pointer items-center justify-between gap-2 rounded px-2 py-1.5 text-sm text-zinc-200 hover:bg-zinc-800">
            <span>Compact rows</span>
            <input
              type="checkbox"
              checked={compact}
              onChange={(e) => setCompact(e.target.checked)}
              className="accent-brand-500"
            />
          </label>

          {/* Time mode */}
          <div className="mt-1 border-t border-zinc-800 pt-1">
            <div className="flex items-center gap-2 px-2 py-1.5 text-sm text-zinc-200">
              <span className="flex-1">Time</span>
              <div className="inline-flex rounded-md border border-zinc-700 p-0.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => setTimeMode("relative")}
                  className={`rounded px-2 py-0.5 ${
                    timeMode === "relative"
                      ? "bg-zinc-700 text-zinc-100"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Relative
                </button>
                <button
                  type="button"
                  onClick={() => setTimeMode("absolute")}
                  className={`rounded px-2 py-0.5 ${
                    timeMode === "absolute"
                      ? "bg-zinc-700 text-zinc-100"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Absolute
                </button>
              </div>
            </div>
          </div>

          {/* Columns checklist */}
          <div className="mt-1 border-t border-zinc-800 pt-1">
            <div className="px-2 pb-0.5 pt-1 text-[10px] uppercase tracking-wide text-zinc-500">
              Columns
            </div>
            <div className="max-h-64 overflow-auto">
              {hideable.map((col) => {
                const hidden =
                  configMap[col.key]?.hidden ?? col.defaultHidden ?? false;
                const label =
                  col.pickerLabel ??
                  (typeof col.label === "string" ? col.label : col.key);
                return (
                  <label
                    key={col.key}
                    className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-200 hover:bg-zinc-800"
                  >
                    <input
                      type="checkbox"
                      checked={!hidden}
                      onChange={(e) =>
                        onToggleHidden(col.key, !e.target.checked)
                      }
                      className="accent-brand-500"
                    />
                    <span className="truncate">{label}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="mt-1 border-t border-zinc-800 pt-1">
            <button
              type="button"
              onClick={() => {
                onReset();
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset columns
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
