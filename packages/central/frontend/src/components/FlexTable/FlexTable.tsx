import { useState } from "react";
import {
  DndContext,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  closestCenter,
} from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import {
  SortableContext,
  horizontalListSortingStrategy,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import {
  Table,
  TableBody,
  TableCell,
  TableRow,
} from "@/components/ui/table.tsx";
import { FlexTableHead } from "./FlexTableHead.tsx";
import type { FlexColumnDef, ColumnConfigMap } from "./types.ts";
import type { ReactNode } from "react";

export interface FlexTablePresentationProps<TRow> {
  /** Columns already filtered + ordered by useColumnConfig; FlexTable
   *  renders exactly what it's given. */
  orderedVisibleColumns: FlexColumnDef<TRow>[];
  /** Full config map so widths can be looked up. */
  configMap: ColumnConfigMap;
  /** Commit a new visible-column order (dnd). */
  onOrderChange: (orderedKeys: string[]) => void;
  /** Commit a new width for one column. */
  onWidthChange: (key: string, width: number) => void;

  rows: TRow[];
  rowKey: (row: TRow) => string;
  sortBy: string;
  sortDir: "asc" | "desc";
  onSort: (col: string) => void;
  filters: Record<string, string>;
  onFilterChange: (col: string, value: string) => void;
  rowClassName?: (row: TRow) => string | undefined;
  emptyState?: ReactNode;
  tableClassName?: string;
}

/** Pure presentational table. Owns its transient drag/resize preview
 *  state but not the persisted config — that lives in the parent so a
 *  sibling (e.g. ColumnPickerMenu) can share it. */
export function FlexTable<TRow>({
  orderedVisibleColumns,
  configMap,
  onOrderChange,
  onWidthChange,
  rows,
  rowKey,
  sortBy,
  sortDir,
  onSort,
  filters,
  onFilterChange,
  rowClassName,
  emptyState,
  tableClassName,
}: FlexTablePresentationProps<TRow>) {
  // Preview widths while dragging the resize handle; commit on pointerup.
  const [previewWidths, setPreviewWidths] = useState<Record<string, number>>(
    {},
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const handleDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const keys = orderedVisibleColumns.map((c) => c.key);
    const from = keys.indexOf(String(active.id));
    const to = keys.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    const next = [...keys];
    next.splice(to, 0, next.splice(from, 1)[0]);
    onOrderChange(next);
  };

  const widthFor = (key: string): number | undefined => {
    if (previewWidths[key] != null) return previewWidths[key];
    const stored = configMap[key]?.width;
    if (stored != null) return stored;
    return orderedVisibleColumns.find((c) => c.key === key)?.defaultWidth;
  };

  return (
    <div className="w-full overflow-auto">
      <Table className={tableClassName}>
        <colgroup>
          {orderedVisibleColumns.map((col) => {
            const w = widthFor(col.key);
            return (
              <col key={col.key} style={w ? { width: `${w}px` } : undefined} />
            );
          })}
        </colgroup>

        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={orderedVisibleColumns.map((c) => c.key)}
            strategy={horizontalListSortingStrategy}
          >
            <thead className="[&_tr]:border-b [&_tr]:border-zinc-800">
              <tr>
                {orderedVisibleColumns.map((col) => (
                  <FlexTableHead
                    key={col.key}
                    col={col}
                    sortBy={sortBy}
                    sortDir={sortDir}
                    onSort={onSort}
                    filterValue={filters[col.key] ?? ""}
                    onFilterChange={onFilterChange}
                    width={widthFor(col.key)}
                    onResizePreview={(w) =>
                      setPreviewWidths((prev) => ({ ...prev, [col.key]: w }))
                    }
                    onResizeCommit={(w) => {
                      setPreviewWidths((prev) => {
                        const { [col.key]: _, ...rest } = prev;
                        return rest;
                      });
                      onWidthChange(col.key, w);
                    }}
                  />
                ))}
              </tr>
            </thead>
          </SortableContext>
        </DndContext>

        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={orderedVisibleColumns.length}
                className="py-12 text-center text-sm text-zinc-500"
              >
                {emptyState ?? "No rows"}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <TableRow key={rowKey(row)} className={rowClassName?.(row)}>
                {orderedVisibleColumns.map((col) => (
                  <TableCell key={col.key} className={col.cellClassName}>
                    {col.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
