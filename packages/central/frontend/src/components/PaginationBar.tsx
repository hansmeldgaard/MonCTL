import { useEffect, useCallback, type RefObject } from "react";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";

interface PaginationBarProps {
  page: number;
  pageSize: number;
  total: number;
  count: number;
  onPageChange: (page: number) => void;
  scrollMode?: "paginated" | "infinite";
  sentinelRef?: RefObject<HTMLDivElement | null>;
  isFetching?: boolean;
  onLoadMore?: () => void;
}

export function PaginationBar({
  page,
  pageSize,
  total,
  count,
  onPageChange,
  scrollMode = "paginated",
  sentinelRef,
  isFetching = false,
  onLoadMore,
}: PaginationBarProps) {
  const startItem = total === 0 ? 0 : page * pageSize + 1;
  const endItem = Math.min(page * pageSize + count, total);
  const hasNext = endItem < total;
  const hasPrev = page > 0;

  const isInfinite = scrollMode === "infinite";
  const hasMoreInfinite = isInfinite && count < total;

  const handleIntersection = useCallback(() => {
    if (hasMoreInfinite && !isFetching && onLoadMore) {
      onLoadMore();
    }
  }, [hasMoreInfinite, isFetching, onLoadMore]);

  useEffect(() => {
    if (!isInfinite || !sentinelRef?.current) return;
    const observer = new IntersectionObserver(
      (entries) => { if (entries[0].isIntersecting) handleIntersection(); },
      { root: document.querySelector("main"), threshold: 0.1 },
    );
    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [isInfinite, sentinelRef, handleIntersection]);

  if (isInfinite) {
    return (
      <>
        <div ref={sentinelRef} className="flex justify-center py-3">
          {isFetching && <Loader2 className="h-5 w-5 animate-spin text-brand-500" />}
          {!isFetching && hasMoreInfinite && (
            <span className="text-xs text-zinc-600">Scroll for more...</span>
          )}
          {!hasMoreInfinite && count > 0 && (
            <span className="text-xs text-zinc-600">
              Showing all {total} results
            </span>
          )}
        </div>
      </>
    );
  }

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
