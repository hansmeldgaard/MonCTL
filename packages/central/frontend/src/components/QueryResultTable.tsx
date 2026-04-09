import { useState, useMemo } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { cn } from "@/lib/utils.ts";

interface Column {
  name: string;
  type: string;
}

interface Props {
  columns: Column[];
  rows: unknown[][];
  rowCount: number;
  truncated: boolean;
  executionTimeMs: number;
  onRowClick?: (row: unknown[]) => void;
}

function formatValue(val: unknown, type: string): string {
  if (val === null || val === undefined) return "NULL";
  if (Array.isArray(val)) return `[${val.join(", ")}]`;
  if (typeof val === "number") {
    if (type.includes("Float")) return val.toFixed(2);
    return val.toLocaleString();
  }
  return String(val);
}

function isNumericType(type: string): boolean {
  return /^(U?Int|Float|Decimal)/i.test(type);
}

export function QueryResultTable({
  columns,
  rows,
  rowCount,
  truncated,
  executionTimeMs,
  onRowClick,
}: Props) {
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sortedRows = useMemo(() => {
    if (sortCol === null) return rows;
    return [...rows].sort((a, b) => {
      const va = a[sortCol] ?? "";
      const vb = b[sortCol] ?? "";
      if (typeof va === "number" && typeof vb === "number") {
        return sortDir === "asc" ? va - vb : vb - va;
      }
      return sortDir === "asc"
        ? String(va).localeCompare(String(vb))
        : String(vb).localeCompare(String(va));
    });
  }, [rows, sortCol, sortDir]);

  function toggleSort(colIdx: number) {
    if (sortCol === colIdx) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(colIdx);
      setSortDir("asc");
    }
  }

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto max-h-[600px] overflow-y-auto border border-zinc-800 rounded-md">
        <Table>
          <TableHeader className="sticky top-0 bg-zinc-900 z-10">
            <TableRow>
              {columns.map((col, i) => (
                <TableHead
                  key={i}
                  onClick={() => toggleSort(i)}
                  className={cn(
                    "cursor-pointer select-none hover:text-zinc-200 whitespace-nowrap",
                    isNumericType(col.type) && "text-right",
                  )}
                >
                  {col.name}
                  {sortCol === i && (
                    <span className="ml-1 text-brand-400">
                      {sortDir === "asc" ? "\u2191" : "\u2193"}
                    </span>
                  )}
                  <span className="ml-1 text-[10px] text-zinc-600">
                    {col.type}
                  </span>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedRows.map((row, ri) => (
              <TableRow
                key={ri}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={
                  onRowClick ? "cursor-pointer hover:bg-zinc-800/60" : ""
                }
              >
                {row.map((val, ci) => (
                  <TableCell
                    key={ci}
                    className={cn(
                      "whitespace-nowrap font-mono text-xs",
                      isNumericType(columns[ci]?.type || "") && "text-right",
                    )}
                  >
                    {formatValue(val, columns[ci]?.type || "")}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between text-xs text-zinc-500 px-1">
        <span>
          {rowCount.toLocaleString()} row{rowCount !== 1 ? "s" : ""}
          {truncated && " (truncated)"}
        </span>
        <span>{executionTimeMs}ms</span>
      </div>
    </div>
  );
}
