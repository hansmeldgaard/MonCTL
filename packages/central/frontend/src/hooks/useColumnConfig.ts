import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useUpdateUiPreferences } from "@/api/hooks.ts";
import {
  mutateUiPreferences,
  readUiPreferences,
  subscribeUiPreferences,
} from "@/hooks/uiPreferencesStore.ts";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";
import type {
  ColumnConfig,
  ColumnConfigMap,
} from "@/components/FlexTable/types.ts";
import type { UiPreferences } from "@/types/api.ts";

const SCHEMA_VERSION = "v1" as const;
const LOCAL_STORAGE_PREFIX = "monctl:table-columns";

function lsKey(tableId: string): string {
  return `${LOCAL_STORAGE_PREFIX}:${tableId}:${SCHEMA_VERSION}`;
}

function readLocal(tableId: string): ColumnConfigMap {
  try {
    const raw = localStorage.getItem(lsKey(tableId));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeLocal(tableId: string, config: ColumnConfigMap): void {
  try {
    localStorage.setItem(lsKey(tableId), JSON.stringify(config));
  } catch {
    // localStorage full / disabled — server copy is still the source of truth
  }
}

function readServer(
  uiPrefs: UiPreferences | undefined,
  tableId: string,
): ColumnConfigMap {
  const stored = uiPrefs?.tables?.[tableId]?.v1;
  return stored && typeof stored === "object" ? { ...stored } : {};
}

function mergeServerIntoPrefs(
  current: UiPreferences,
  tableId: string,
  config: ColumnConfigMap,
): UiPreferences {
  return {
    ...current,
    tables: {
      ...(current.tables ?? {}),
      [tableId]: {
        ...(current.tables?.[tableId] ?? {}),
        v1: config,
      },
    },
  };
}

/** Clone + strip default-valued entries so the stored config stays lean.
 *  A key with `{}` survives because the user explicitly set something
 *  and then cleared it (e.g. reset width); normalise by dropping the
 *  whole entry. */
function compact(config: ColumnConfigMap): ColumnConfigMap {
  const out: ColumnConfigMap = {};
  for (const [key, entry] of Object.entries(config)) {
    const next: ColumnConfig = {};
    if (entry.width != null) next.width = entry.width;
    if (entry.hidden === true) next.hidden = true;
    if (entry.order != null) next.order = entry.order;
    if (Object.keys(next).length > 0) out[key] = next;
  }
  return out;
}

export interface UseColumnConfigReturn<TRow> {
  /** Columns after applying hidden + order, in display order. */
  orderedVisibleColumns: FlexColumnDef<TRow>[];
  /** Raw config map for the current table (by column key). */
  configMap: ColumnConfigMap;
  /** Toggle the hidden flag on one column. */
  setHidden: (key: string, hidden: boolean) => void;
  /** Commit a resize; pass undefined to revert to auto-width. */
  setWidth: (key: string, width: number | undefined) => void;
  /** Replace the full visible-column order. Missing columns retain their
   *  relative position around the reordered set. */
  setOrder: (orderedKeys: string[]) => void;
  /** Drop every stored override for this table. */
  reset: () => void;
}

export function useColumnConfig<TRow>(
  tableId: string,
  columns: FlexColumnDef<TRow>[],
): UseColumnConfigReturn<TRow> {
  const update = useUpdateUiPreferences();

  // Subscribe to the shared ui_preferences store so sibling hooks'
  // writes (e.g. useDisplayPreferences toggling compact) trigger a
  // re-render here without clobbering our config, and vice versa.
  const [, forceRender] = useState(0);
  useEffect(() => subscribeUiPreferences(() => forceRender((n) => n + 1)), []);

  // Initial read: shared store first (hydrated from auth refresh), fall
  // back to localStorage.
  const [configMap, setConfigMap] = useState<ColumnConfigMap>(() => {
    const fromStore = readServer(readUiPreferences(), tableId);
    if (Object.keys(fromStore).length > 0) return fromStore;
    return readLocal(tableId);
  });

  // Keep local state in sync with the shared store on any external
  // change (auth refresh hydrates it; another tab / device push could too).
  const lastSnapshot = useRef<string>("");
  useEffect(() => {
    const fromStore = readServer(readUiPreferences(), tableId);
    const snapshot = JSON.stringify(fromStore);
    if (snapshot !== lastSnapshot.current) {
      lastSnapshot.current = snapshot;
      setConfigMap(fromStore);
      writeLocal(tableId, fromStore);
    }
  });

  const persist = useCallback(
    (next: ColumnConfigMap) => {
      const compacted = compact(next);
      setConfigMap(compacted);
      writeLocal(tableId, compacted);
      lastSnapshot.current = JSON.stringify(compacted);
      // Atomically merge into the shared store so concurrent writers
      // always base their diff on the latest state.
      const merged = mutateUiPreferences((prev) =>
        mergeServerIntoPrefs(prev, tableId, compacted),
      );
      update.mutate(merged);
    },
    [tableId, update],
  );

  const setHidden = useCallback(
    (key: string, hidden: boolean) => {
      persist({
        ...configMap,
        [key]: { ...(configMap[key] ?? {}), hidden },
      });
    },
    [configMap, persist],
  );

  const setWidth = useCallback(
    (key: string, width: number | undefined) => {
      persist({
        ...configMap,
        [key]: { ...(configMap[key] ?? {}), width },
      });
    },
    [configMap, persist],
  );

  const setOrder = useCallback(
    (orderedKeys: string[]) => {
      const next: ColumnConfigMap = { ...configMap };
      orderedKeys.forEach((k, i) => {
        next[k] = { ...(next[k] ?? {}), order: i };
      });
      persist(next);
    },
    [configMap, persist],
  );

  const reset = useCallback(() => {
    persist({});
  }, [persist]);

  const orderedVisibleColumns = useMemo(() => {
    // Stable sort: alwaysVisible first; then user-configured order; then
    // falls back to the code-defined order so new columns appear at the
    // end of the visible set.
    const withMeta = columns.map((col, codeIndex) => {
      const cfg = configMap[col.key];
      const hidden = cfg?.hidden ?? col.defaultHidden ?? false;
      const order = cfg?.order;
      return { col, codeIndex, hidden, order };
    });

    return withMeta
      .filter((m) => m.col.alwaysVisible || !m.hidden)
      .sort((a, b) => {
        if (a.col.alwaysVisible && !b.col.alwaysVisible) return -1;
        if (!a.col.alwaysVisible && b.col.alwaysVisible) return 1;
        const ao = a.order ?? Number.MAX_SAFE_INTEGER;
        const bo = b.order ?? Number.MAX_SAFE_INTEGER;
        if (ao !== bo) return ao - bo;
        return a.codeIndex - b.codeIndex;
      })
      .map((m) => m.col);
  }, [columns, configMap]);

  return {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  };
}
