import { ArrowDown, ArrowUp, ArrowUpDown, GripVertical } from "lucide-react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
import { ResizeHandle } from "./ResizeHandle.tsx";
import type { FlexColumnDef } from "./types.ts";

interface Props<TRow> {
  col: FlexColumnDef<TRow>;
  sortBy: string;
  sortDir: "asc" | "desc";
  onSort: (col: string) => void;
  filterValue: string;
  onFilterChange: (col: string, value: string) => void;
  width: number | undefined;
  onResizePreview: (width: number) => void;
  onResizeCommit: (width: number) => void;
}

export function FlexTableHead<TRow>({
  col,
  sortBy,
  sortDir,
  onSort,
  filterValue,
  onFilterChange,
  width,
  onResizePreview,
  onResizeCommit,
}: Props<TRow>) {
  const sortable = col.sortable !== false;
  const filterable = col.filterable !== false;
  const isActive = sortBy === col.key;

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: col.key, disabled: col.alwaysVisible });

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    width: width ?? undefined,
  };

  return (
    <th
      ref={setNodeRef}
      style={style}
      className={`relative h-10 px-4 text-left align-middle text-xs font-medium text-zinc-400 ${col.headerClassName ?? ""}`}
    >
      <div className="flex items-start gap-1">
        {/* Drag handle — separate from label so clicks on the label still sort. */}
        {!col.alwaysVisible && (
          <button
            {...attributes}
            {...listeners}
            type="button"
            aria-label={`Drag to reorder ${col.pickerLabel ?? col.key}`}
            className="mt-0.5 cursor-grab text-zinc-600 hover:text-zinc-300 active:cursor-grabbing"
          >
            <GripVertical className="h-3 w-3" />
          </button>
        )}

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div
            className={`flex items-center gap-1 ${sortable ? "cursor-pointer select-none" : ""}`}
            onClick={sortable ? () => onSort(col.key) : undefined}
          >
            <span className="truncate">{col.label}</span>
            {sortable &&
              (isActive ? (
                sortDir === "asc" ? (
                  <ArrowUp className="h-3 w-3 shrink-0 text-brand-400" />
                ) : (
                  <ArrowDown className="h-3 w-3 shrink-0 text-brand-400" />
                )
              ) : (
                <ArrowUpDown className="h-3 w-3 shrink-0 text-zinc-600" />
              ))}
          </div>
          {filterable && (
            <ClearableInput
              placeholder="Filter..."
              value={filterValue}
              onChange={(e) => onFilterChange(col.key, e.target.value)}
              onClear={() => onFilterChange(col.key, "")}
              className="h-6 text-xs"
            />
          )}
        </div>
      </div>

      <ResizeHandle
        currentWidth={width}
        minWidth={col.minWidth ?? 60}
        onPreview={onResizePreview}
        onCommit={onResizeCommit}
      />
    </th>
  );
}
