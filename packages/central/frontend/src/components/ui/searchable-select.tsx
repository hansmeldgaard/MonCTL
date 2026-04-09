import { useState, useRef, useEffect, useCallback } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils.ts";

export interface SearchableSelectOption {
  value: string;
  label: string;
}

interface SearchableSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: SearchableSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  id?: string;
}

export function SearchableSelect({
  value,
  onChange,
  options,
  placeholder = "Select...",
  disabled,
  className,
  id,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [highlightIndex, setHighlightIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const selectedLabel = options.find((o) => o.value === value)?.label;

  const filtered = search
    ? options.filter((o) =>
        o.label.toLowerCase().includes(search.toLowerCase()),
      )
    : options;

  const openDropdown = useCallback(() => {
    if (disabled) return;
    setOpen(true);
    setSearch("");
    setHighlightIndex(0);
  }, [disabled]);

  const closeDropdown = useCallback(() => {
    setOpen(false);
    setSearch("");
  }, []);

  const selectOption = useCallback(
    (val: string) => {
      onChange(val);
      closeDropdown();
    },
    [onChange, closeDropdown],
  );

  // Click outside to close
  useEffect(() => {
    if (!open) return;
    const handle = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        closeDropdown();
      }
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open, closeDropdown]);

  // Auto-focus input when opened
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Scroll highlighted item into view
  useEffect(() => {
    if (!open || !listRef.current) return;
    const item = listRef.current.children[highlightIndex] as
      | HTMLElement
      | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [highlightIndex, open]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
        e.preventDefault();
        openDropdown();
      }
      return;
    }

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightIndex((i) => Math.min(i + 1, filtered.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightIndex((i) => Math.max(i - 1, 0));
        break;
      case "Enter":
        e.preventDefault();
        if (filtered[highlightIndex]) {
          selectOption(filtered[highlightIndex].value);
        }
        break;
      case "Escape":
        e.preventDefault();
        closeDropdown();
        break;
      case "Tab":
        closeDropdown();
        break;
    }
  };

  return (
    <div
      ref={containerRef}
      className={cn("relative", className)}
      onKeyDown={handleKeyDown}
    >
      {/* Trigger button */}
      <button
        type="button"
        id={id}
        disabled={disabled}
        onClick={() => (open ? closeDropdown() : openDropdown())}
        className={cn(
          "flex h-9 w-full items-center justify-between rounded-md border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm text-left",
          "focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500",
          "disabled:cursor-not-allowed disabled:opacity-50",
          selectedLabel ? "text-zinc-100" : "text-zinc-500",
        )}
      >
        <span className="truncate">{selectedLabel || placeholder}</span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-zinc-500 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 z-50 rounded-md border border-zinc-700 bg-zinc-800 shadow-lg">
          {/* Search input */}
          <div className="p-1.5">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setHighlightIndex(0);
              }}
              placeholder="Søg..."
              className="w-full rounded border border-zinc-600 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-brand-500/50"
            />
          </div>

          {/* Options list */}
          <div ref={listRef} className="max-h-48 overflow-y-auto px-1 pb-1">
            {filtered.length === 0 ? (
              <div className="px-2.5 py-2 text-sm text-zinc-500">
                Ingen resultater
              </div>
            ) : (
              filtered.map((option, idx) => (
                <div
                  key={option.value}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    selectOption(option.value);
                  }}
                  onMouseEnter={() => setHighlightIndex(idx)}
                  className={cn(
                    "cursor-pointer rounded px-2.5 py-1.5 text-sm",
                    idx === highlightIndex
                      ? "bg-zinc-700 text-zinc-100"
                      : "text-zinc-300 hover:bg-zinc-700/50",
                    option.value === value && "font-medium text-brand-400",
                  )}
                >
                  {option.label}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
