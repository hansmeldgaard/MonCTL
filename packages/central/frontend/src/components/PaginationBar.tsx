import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";

interface PaginationBarProps {
  page: number;
  pageSize: number;
  total: number;
  count: number;
  onPageChange: (page: number) => void;
}

export function PaginationBar({ page, pageSize, total, count, onPageChange }: PaginationBarProps) {
  const startItem = total === 0 ? 0 : page * pageSize + 1;
  const endItem = Math.min(page * pageSize + count, total);
  const hasNext = endItem < total;
  const hasPrev = page > 0;

  return (
    <div className="flex items-center justify-between text-sm text-zinc-500 pt-2">
      <span>
        {total === 0 ? "No results" : `${startItem}\u2013${endItem} of ${total}`}
      </span>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" disabled={!hasPrev} onClick={() => onPageChange(page - 1)}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" disabled={!hasNext} onClick={() => onPageChange(page + 1)}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
