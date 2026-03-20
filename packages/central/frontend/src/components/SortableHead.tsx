import { ArrowUp, ArrowDown, ArrowUpDown } from "lucide-react";
import { TableHead } from "@/components/ui/table.tsx";

interface SortableHeadProps {
  col: string;
  sortBy: string;
  sortDir: "asc" | "desc";
  onSort: (col: string) => void;
  children: React.ReactNode;
  className?: string;
}

export function SortableHead({ col, sortBy, sortDir, onSort, children, className }: SortableHeadProps) {
  const active = sortBy === col;
  return (
    <TableHead
      className={`cursor-pointer select-none hover:text-zinc-200 transition-colors ${className ?? ""}`}
      onClick={() => onSort(col)}
    >
      <div className="flex items-center gap-1">
        {children}
        {active ? (
          sortDir === "asc" ? (
            <ArrowUp className="h-3 w-3 text-brand-400" />
          ) : (
            <ArrowDown className="h-3 w-3 text-brand-400" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 text-zinc-600" />
        )}
      </div>
    </TableHead>
  );
}
