import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import type { ListParams } from "@/types/api.ts";

export interface ColumnDef {
  key: string;
  label: string;
  sortable?: boolean;
  filterable?: boolean;
}

interface UseListStateOptions {
  columns: ColumnDef[];
  defaultSortBy?: string;
  defaultSortDir?: "asc" | "desc";
  defaultPageSize?: number;
  debounceMs?: number;
  scrollMode?: "paginated" | "infinite";
}

export function useListState(options: UseListStateOptions) {
  const {
    columns,
    defaultSortBy = columns[0]?.key ?? "name",
    defaultSortDir = "asc",
    defaultPageSize = 50,
    debounceMs = 300,
    scrollMode = "paginated",
  } = options;

  const [sortBy, setSortBy] = useState(defaultSortBy);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defaultSortDir);
  const [page, setPage] = useState(0);
  const [pageSize] = useState(defaultPageSize);

  // Infinite scroll: how many batches loaded
  const [infinitePages, setInfinitePages] = useState(1);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Per-column filter values (immediate — drives Input value)
  const filterableKeys = columns
    .filter((c) => c.filterable !== false)
    .map((c) => c.key);
  const [filters, setFilters] = useState<Record<string, string>>(() =>
    Object.fromEntries(filterableKeys.map((k) => [k, ""])),
  );

  // Debounced filter values (sent to API)
  const [debouncedFilters, setDebouncedFilters] = useState<
    Record<string, string>
  >(() => Object.fromEntries(filterableKeys.map((k) => [k, ""])));

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedFilters(filters);
      setPage(0);
      setInfinitePages(1);
    }, debounceMs);
    return () => clearTimeout(timer);
  }, [filters, debounceMs]);

  // Reset infinite pages on sort change
  useEffect(() => {
    setInfinitePages(1);
  }, [sortBy, sortDir]);

  const setFilter = useCallback((key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  const clearFilters = useCallback(() => {
    const empty = Object.fromEntries(filterableKeys.map((k) => [k, ""]));
    setFilters(empty);
  }, [filterableKeys.join(",")]);

  const hasActiveFilters = Object.values(filters).some((v) => v !== "");

  const handleSort = useCallback((col: string) => {
    setSortBy((prev) => {
      if (prev === col) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
        return prev;
      }
      setSortDir("asc");
      return col;
    });
    setPage(0);
  }, []);

  const isInfinite = scrollMode === "infinite";

  const params: ListParams = useMemo(() => {
    const p: ListParams = {
      sort_by: sortBy,
      sort_dir: sortDir,
      limit: isInfinite ? pageSize * infinitePages : pageSize,
      offset: isInfinite ? 0 : page * pageSize,
    };
    for (const [key, val] of Object.entries(debouncedFilters)) {
      if (val) p[key] = val;
    }
    return p;
  }, [
    sortBy,
    sortDir,
    page,
    pageSize,
    debouncedFilters,
    isInfinite,
    infinitePages,
  ]);

  const loadMore = useCallback(() => {
    setInfinitePages((p) => p + 1);
  }, []);

  return {
    columns,
    filters,
    setFilter,
    clearFilters,
    hasActiveFilters,
    sortBy,
    sortDir,
    handleSort,
    page,
    setPage,
    pageSize,
    params,
    // Infinite scroll support
    scrollMode,
    sentinelRef,
    loadMore,
  };
}
