import { useCallback, useEffect, useState } from "react";
import type { TimeDisplayMode } from "@/lib/utils.ts";

const STORAGE_KEY = "monctl:timeDisplayMode";
const EVENT = "monctl:timeDisplayMode:change";

function read(): TimeDisplayMode {
  if (typeof window === "undefined") return "relative";
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === "absolute" ? "absolute" : "relative";
}

/** User preference: show timestamps as relative ("3m ago") or absolute
 *  (full date in the user's timezone). Persisted in localStorage and
 *  synchronised across hook instances in the same tab via a custom
 *  window event (native `storage` events only fire across tabs). */
export function useTimeDisplayMode(): {
  mode: TimeDisplayMode;
  setMode: (m: TimeDisplayMode) => void;
  toggle: () => void;
} {
  const [mode, setModeState] = useState<TimeDisplayMode>(read);

  useEffect(() => {
    const resync = () => setModeState(read());
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) resync();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(EVENT, resync);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(EVENT, resync);
    };
  }, []);

  const setMode = useCallback((m: TimeDisplayMode) => {
    window.localStorage.setItem(STORAGE_KEY, m);
    window.dispatchEvent(new Event(EVENT));
  }, []);

  const toggle = useCallback(() => {
    setMode(mode === "relative" ? "absolute" : "relative");
  }, [mode, setMode]);

  return { mode, setMode, toggle };
}
