import { useCallback, useRef } from "react";

interface Props {
  /** Starting width of the column in px. If undefined the handle reads
   *  the live header width on pointer-down. */
  currentWidth: number | undefined;
  minWidth: number;
  /** Fired on pointerup with the final width. Committing on release
   *  keeps persistence (localStorage + /users/me/ui-preferences) cheap. */
  onCommit: (width: number) => void;
  /** Optional live callback while dragging — used to paint the header
   *  width in real time without persisting. */
  onPreview?: (width: number) => void;
}

const MAX_WIDTH = 800;

export function ResizeHandle({
  currentWidth,
  minWidth,
  onCommit,
  onPreview,
}: Props) {
  const startX = useRef(0);
  const startWidth = useRef(0);
  const latest = useRef(0);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      const th = (e.currentTarget.parentElement as HTMLElement | null) ?? null;
      startX.current = e.clientX;
      startWidth.current =
        currentWidth ?? th?.getBoundingClientRect().width ?? minWidth;
      latest.current = startWidth.current;
      e.currentTarget.setPointerCapture(e.pointerId);

      const onMove = (ev: PointerEvent) => {
        const delta = ev.clientX - startX.current;
        const next = Math.min(
          MAX_WIDTH,
          Math.max(minWidth, Math.round(startWidth.current + delta)),
        );
        latest.current = next;
        onPreview?.(next);
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        onCommit(latest.current);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [currentWidth, minWidth, onCommit, onPreview],
  );

  return (
    <div
      onPointerDown={handlePointerDown}
      className="absolute right-0 top-0 h-full w-[6px] cursor-col-resize select-none opacity-0 hover:opacity-100"
      style={{ touchAction: "none" }}
      aria-hidden
    >
      <div className="mx-auto h-full w-[2px] bg-brand-500/60" />
    </div>
  );
}
