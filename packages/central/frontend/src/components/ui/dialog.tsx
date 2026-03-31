import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@/lib/utils.ts";

const SIZE_CLASSES = {
  sm: "max-w-sm",
  md: "max-w-lg",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
  full: "max-w-6xl",
  fullscreen: "max-w-none",
} as const;

type DialogSize = keyof typeof SIZE_CLASSES;

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  className?: string;
  size?: DialogSize;
}

export function Dialog({ open, onClose, title, children, className, size = "md" }: DialogProps) {
  // Close on Escape key
  useEffect(() => {
    if (!open) return;
    const handle = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [open, onClose]);

  // Prevent body scroll when open
  useEffect(() => {
    if (open) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  if (!open) return null;

  const isFullscreen = size === "fullscreen";

  return createPortal(
    <div className={cn(
      "fixed inset-0 z-50 flex",
      isFullscreen ? "" : "items-center justify-center p-4",
    )}>
      {/* Backdrop */}
      {!isFullscreen && (
        <div
          className="absolute inset-0 bg-black/60"
          onClick={onClose}
        />
      )}
      {/* Panel */}
      <div
        className={cn(
          isFullscreen
            ? "relative z-10 w-full h-full flex flex-col bg-zinc-900"
            : `relative z-10 w-full ${SIZE_CLASSES[size]} max-h-[calc(100vh-2rem)] flex flex-col rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl`,
          className,
        )}
      >
        {title && (
          <div className={cn(
            "flex items-center justify-between border-b border-zinc-800 px-6 py-4",
            "shrink-0",
          )}>
            <h2 className="text-base font-semibold text-zinc-100">{title}</h2>
            <button
              onClick={onClose}
              className="rounded-md p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
        <div className={cn(
          "flex-1 overflow-y-auto px-6 py-5",
        )}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}

interface DialogFooterProps {
  children: React.ReactNode;
  className?: string;
}

export function DialogFooter({ children, className }: DialogFooterProps) {
  return (
    <div className={cn("flex items-center justify-end gap-3 pt-4 mt-2 border-t border-zinc-800", className)}>
      {children}
    </div>
  );
}
