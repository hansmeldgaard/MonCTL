import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useListState } from "./useListState.ts";

const columns = [
  { key: "name", label: "Name" },
  { key: "type", label: "Type", filterable: false },
  { key: "address", label: "Address" },
];

describe("useListState", () => {
  it("initialises with defaults derived from column definitions", () => {
    const { result } = renderHook(() => useListState({ columns }));
    expect(result.current.sortBy).toBe("name");
    expect(result.current.sortDir).toBe("asc");
    expect(result.current.page).toBe(0);
    expect(result.current.pageSize).toBe(50);
    expect(Object.keys(result.current.filters).sort()).toEqual([
      "address",
      "name",
    ]);
  });

  it("handleSort toggles direction on the same column and resets page", () => {
    const { result } = renderHook(() =>
      useListState({ columns, defaultPageSize: 25 }),
    );
    act(() => result.current.setPage(3));
    expect(result.current.page).toBe(3);

    act(() => result.current.handleSort("name"));
    expect(result.current.sortBy).toBe("name");
    expect(result.current.sortDir).toBe("desc");
    expect(result.current.page).toBe(0);

    act(() => result.current.handleSort("name"));
    expect(result.current.sortDir).toBe("asc");
  });

  it("handleSort on a different column resets to asc", () => {
    const { result } = renderHook(() =>
      useListState({ columns, defaultSortDir: "desc" }),
    );
    act(() => result.current.handleSort("address"));
    expect(result.current.sortBy).toBe("address");
    expect(result.current.sortDir).toBe("asc");
  });

  it("debounces filter values into `params`", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() =>
        useListState({ columns, debounceMs: 300 }),
      );
      act(() => result.current.setFilter("name", "ros"));
      // Immediate filter is set; debounced params have not caught up yet
      expect(result.current.filters.name).toBe("ros");
      expect(result.current.params.name).toBeUndefined();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(350);
      });

      expect(result.current.params.name).toBe("ros");
    } finally {
      vi.useRealTimers();
    }
  });

  it("computes limit from infinitePages in infinite scroll mode", () => {
    const { result } = renderHook(() =>
      useListState({ columns, scrollMode: "infinite", defaultPageSize: 20 }),
    );
    expect(result.current.params.limit).toBe(20);
    expect(result.current.params.offset).toBe(0);

    act(() => result.current.loadMore());
    expect(result.current.params.limit).toBe(40);
    expect(result.current.params.offset).toBe(0);
  });
});
