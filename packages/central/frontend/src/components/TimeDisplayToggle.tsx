import { Button } from "@/components/ui/button.tsx";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";

/** Two-button toggle for switching timestamp columns between relative
 *  ("3m ago") and absolute (user-timezone date/time) display. */
export function TimeDisplayToggle() {
  const { mode, setMode } = useTimeDisplayMode();
  return (
    <div className="ml-auto flex items-center gap-1 text-xs">
      <span className="text-zinc-500 mr-1">Time:</span>
      <Button
        variant={mode === "relative" ? "secondary" : "ghost"}
        size="sm"
        onClick={() => setMode("relative")}
      >
        Relative
      </Button>
      <Button
        variant={mode === "absolute" ? "secondary" : "ghost"}
        size="sm"
        onClick={() => setMode("absolute")}
      >
        Absolute
      </Button>
    </div>
  );
}
