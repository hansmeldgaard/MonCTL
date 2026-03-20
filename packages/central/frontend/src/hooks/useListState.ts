import { useState, useMemo, useCallback } from "react";
import type { ListParams } from "@/types/api.ts";

interface UseListStateOptions {
  defaultSortBy?: string;
  defaultSortDir?: "asc" | "desc";
  defaultPageSize?: number;
}

export function useListState(options: UseListStateOptions = {}) {
  const {
    defaultSortBy = "name",
    defaultSortDir = "asc",
    defaultPageSize = 50,
  } = options;

  const [search, setSearchRaw] = useState("");
  const [sortBy, setSortBy] = useState(defaultSortBy);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defaultSortDir);
  const [page, setPage] = useState(0);
  const [pageSize] = useState(defaultPageSize);

  const setSearch = useCallback((value: string) => {
    setSearchRaw(value);
    setPage(0);
  }, []);

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

  const params: ListParams = useMemo(() => ({
    search: search || undefined,
    sort_by: sortBy,
    sort_dir: sortDir,
    limit: pageSize,
    offset: page * pageSize,
  }), [search, sortBy, sortDir, page, pageSize]);

  return {
    search,
    setSearch,
    sortBy,
    sortDir,
    handleSort,
    page,
    setPage,
    pageSize,
    params,
  };
}
