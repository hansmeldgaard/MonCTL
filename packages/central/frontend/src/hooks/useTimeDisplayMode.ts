import { useCallback } from "react";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import type { TimeDisplayMode } from "@/lib/utils.ts";

/** User preference: show timestamps as relative ("3m ago") or absolute
 *  (full date in the user's timezone). Now backed by server-side
 *  ui_preferences.display.timeMode — delegates to useDisplayPreferences.
 *  Kept as a thin wrapper so existing callers (TimeDisplayToggle,
 *  AlertsPage, DeviceDetailPage) don't need to change. */
export function useTimeDisplayMode(): {
  mode: TimeDisplayMode;
  setMode: (m: TimeDisplayMode) => void;
  toggle: () => void;
} {
  const { timeMode, setTimeMode } = useDisplayPreferences();

  const toggle = useCallback(() => {
    setTimeMode(timeMode === "relative" ? "absolute" : "relative");
  }, [timeMode, setTimeMode]);

  return { mode: timeMode, setMode: setTimeMode, toggle };
}
