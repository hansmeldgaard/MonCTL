import { useState, useEffect, useMemo, useCallback } from "react";
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
}

export function useListState(options: UseListStateOptions) {
  const {
    columns,
    defaultSortBy = columns[0]?.key ?? "name",
    defaultSortDir = "asc",
    defaultPageSize = 50,
    debounceMs = 300,
  } = options;

  const [sortBy, setSortBy] = useState(defaultSortBy);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defaultSortDir);
  const [page, setPage] = useState(0);
  const [pageSize] = useState(defaultPageSize);

  // Per-column filter values (immediate — drives Input value)
  const filterableKeys = columns.filter((c) => c.filterable !== false).map((c) => c.key);
  const [filters, setFilters] = useState<Record<string, string>>(
    () => Object.fromEntries(filterableKeys.map((k) => [k, ""]))
  );

  // Debounced filter values (sent to API)
  const [debouncedFilters, setDebouncedFilters] = useState<Record<string, string>>(
    () => Object.fromEntries(filterableKeys.map((k) => [k, ""]))
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedFilters(filters);
      setPage(0);
    }, debounceMs);
    return () => clearTimeout(timer);
  }, [filters, debounceMs]);

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

  const params: ListParams = useMemo(() => {
    const p: ListParams = {
      sort_by: sortBy,
      sort_dir: sortDir,
      limit: pageSize,
      offset: page * pageSize,
    };
    for (const [key, val] of Object.entries(debouncedFilters)) {
      if (val) p[key] = val;
    }
    return p;
  }, [sortBy, sortDir, page, pageSize, debouncedFilters]);

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
  };
}
