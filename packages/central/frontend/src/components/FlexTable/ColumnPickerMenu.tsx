import { useEffect, useRef, useState } from "react";
import { Columns3, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import type { FlexColumnDef } from "./types.ts";
import type { ColumnConfigMap } from "./types.ts";

interface Props<TRow> {
  columns: FlexColumnDef<TRow>[];
  configMap: ColumnConfigMap;
  onToggleHidden: (key: string, hidden: boolean) => void;
  onReset: () => void;
}

export function ColumnPickerMenu<TRow>({
  columns,
  configMap,
  onToggleHidden,
  onReset,
}: Props<TRow>) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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
        <Columns3 className="mr-1.5 h-3.5 w-3.5" />
        Columns
      </Button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-zinc-800 bg-zinc-900 p-1 shadow-lg"
        >
          <div className="max-h-80 overflow-auto py-1">
            {hideable.map((col) => {
              const hidden =
                configMap[col.key]?.hidden ?? col.defaultHidden ?? false;
              return (
                <label
                  key={col.key}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-200 hover:bg-zinc-800"
                >
                  <input
                    type="checkbox"
                    checked={!hidden}
                    onChange={(e) => onToggleHidden(col.key, !e.target.checked)}
                    className="accent-brand-500"
                  />
                  <span className="truncate">
                    {col.pickerLabel ??
                      (typeof col.label === "string" ? col.label : col.key)}
                  </span>
                </label>
              );
            })}
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
              Reset to defaults
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
