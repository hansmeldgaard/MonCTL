import { useCallback, useEffect, useRef, useState } from "react";
import { useUpdateUiPreferences } from "@/api/hooks.ts";
import {
  mutateUiPreferences,
  readUiPreferences,
  subscribeUiPreferences,
} from "@/hooks/uiPreferencesStore.ts";
import type { UiPreferences } from "@/types/api.ts";

const LOCAL_KEY = "monctl:display-prefs:v1";

export type TimeMode = "relative" | "absolute";

export interface DisplayPrefs {
  compact: boolean;
  timeMode: TimeMode;
}

const DEFAULTS: DisplayPrefs = {
  compact: false,
  timeMode: "relative",
};

function readLocal(): Partial<DisplayPrefs> {
  try {
    const raw = localStorage.getItem(LOCAL_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeLocal(prefs: DisplayPrefs): void {
  try {
    localStorage.setItem(LOCAL_KEY, JSON.stringify(prefs));
  } catch {
    // quota / disabled — server remains source of truth
  }
}

function readServer(uiPrefs: UiPreferences): Partial<DisplayPrefs> {
  return uiPrefs.display ?? {};
}

function merge(current: UiPreferences, next: DisplayPrefs): UiPreferences {
  return {
    ...current,
    display: { ...(current.display ?? {}), ...next },
  };
}

export interface UseDisplayPreferencesReturn extends DisplayPrefs {
  setCompact: (value: boolean) => void;
  setTimeMode: (value: TimeMode) => void;
  toggleCompact: () => void;
}

/** Global per-user display prefs (compact density + abs/rel time mode).
 *  Server-backed via ui_preferences.display; localStorage acts as a
 *  first-paint cache so reloads don't flash default state. Concurrent
 *  writes from useColumnConfig are coordinated through the shared
 *  uiPreferencesStore. */
export function useDisplayPreferences(): UseDisplayPreferencesReturn {
  const update = useUpdateUiPreferences();

  const [prefs, setPrefs] = useState<DisplayPrefs>(() => {
    const server = readServer(readUiPreferences());
    const local = readLocal();
    return { ...DEFAULTS, ...local, ...server };
  });

  // Re-read from the store on every external change (auth refresh or
  // a sibling hook's write).
  const lastSnapshot = useRef<string>("");
  useEffect(() => {
    const sync = () => {
      const server = readServer(readUiPreferences());
      const snapshot = JSON.stringify(server);
      if (snapshot !== lastSnapshot.current) {
        lastSnapshot.current = snapshot;
        const merged = { ...DEFAULTS, ...server };
        setPrefs(merged);
        writeLocal(merged);
      }
    };
    sync();
    return subscribeUiPreferences(sync);
  }, []);

  const persist = useCallback(
    (next: DisplayPrefs) => {
      setPrefs(next);
      writeLocal(next);
      lastSnapshot.current = JSON.stringify(next);
      const merged = mutateUiPreferences((prev) => merge(prev, next));
      update.mutate(merged);
    },
    [update],
  );

  const setCompact = useCallback(
    (value: boolean) => persist({ ...prefs, compact: value }),
    [persist, prefs],
  );

  const setTimeMode = useCallback(
    (value: TimeMode) => persist({ ...prefs, timeMode: value }),
    [persist, prefs],
  );

  const toggleCompact = useCallback(
    () => persist({ ...prefs, compact: !prefs.compact }),
    [persist, prefs],
  );

  return {
    ...prefs,
    setCompact,
    setTimeMode,
    toggleCompact,
  };
}
