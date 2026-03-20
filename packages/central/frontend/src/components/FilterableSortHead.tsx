import { ArrowUp, ArrowDown, ArrowUpDown } from "lucide-react";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
import { TableHead } from "@/components/ui/table.tsx";

interface FilterableSortHeadProps {
  col: string;
  label: string;
  sortBy: string;
  sortDir: "asc" | "desc";
  onSort: (col: string) => void;
  filterValue?: string;
  onFilterChange?: (value: string) => void;
  className?: string;
  sortable?: boolean;
  filterable?: boolean;
}

export function FilterableSortHead({
  col, label, sortBy, sortDir, onSort,
  filterValue, onFilterChange,
  className, sortable = true, filterable = true,
}: FilterableSortHeadProps) {
  const active = sortBy === col;

  return (
    <TableHead className={className}>
      <div
        className={`flex items-center gap-1 ${sortable ? "cursor-pointer select-none" : ""}`}
        onClick={sortable ? () => onSort(col) : undefined}
      >
        {label}
        {sortable && (
          active ? (
            sortDir === "asc" ? (
              <ArrowUp className="h-3 w-3 text-brand-400" />
            ) : (
              <ArrowDown className="h-3 w-3 text-brand-400" />
            )
          ) : (
            <ArrowUpDown className="h-3 w-3 text-zinc-600" />
          )
        )}
      </div>
      {filterable && onFilterChange && (
        <ClearableInput
          placeholder="Filter..."
          value={filterValue ?? ""}
          onChange={(e) => onFilterChange(e.target.value)}
          onClear={() => onFilterChange("")}
          className="mt-1 h-6 text-xs"
        />
      )}
    </TableHead>
  );
}
