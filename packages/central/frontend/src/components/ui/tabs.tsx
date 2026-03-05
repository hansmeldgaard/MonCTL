import { cn } from "@/lib/utils.ts";

// ── Tabs context ─────────────────────────────────────────

interface TabsContextValue {
  value: string;
  onChange: (value: string) => void;
}

import { createContext, useContext } from "react";

const TabsContext = createContext<TabsContextValue>({
  value: "",
  onChange: () => {},
});

// ── Tabs root ────────────────────────────────────────────

interface TabsProps {
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
  className?: string;
}

export function Tabs({ value, onChange, children, className }: TabsProps) {
  return (
    <TabsContext.Provider value={{ value, onChange }}>
      <div className={cn("w-full", className)}>{children}</div>
    </TabsContext.Provider>
  );
}

// ── Tabs list (the nav bar) ───────────────────────────────

interface TabsListProps {
  children: React.ReactNode;
  className?: string;
}

export function TabsList({ children, className }: TabsListProps) {
  return (
    <div
      className={cn(
        "flex border-b border-zinc-800",
        className,
      )}
    >
      {children}
    </div>
  );
}

// ── Individual tab trigger ────────────────────────────────

interface TabTriggerProps {
  value: string;
  children: React.ReactNode;
  className?: string;
}

export function TabTrigger({ value, children, className }: TabTriggerProps) {
  const ctx = useContext(TabsContext);
  const isActive = ctx.value === value;
  return (
    <button
      onClick={() => ctx.onChange(value)}
      className={cn(
        "px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px cursor-pointer",
        isActive
          ? "border-brand-500 text-brand-400"
          : "border-transparent text-zinc-500 hover:text-zinc-300 hover:border-zinc-600",
        className,
      )}
    >
      {children}
    </button>
  );
}

// ── Tab content panel ────────────────────────────────────

interface TabsContentProps {
  value: string;
  children: React.ReactNode;
  className?: string;
}

export function TabsContent({ value, children, className }: TabsContentProps) {
  const ctx = useContext(TabsContext);
  if (ctx.value !== value) return null;
  return (
    <div className={cn("mt-4", className)}>{children}</div>
  );
}
