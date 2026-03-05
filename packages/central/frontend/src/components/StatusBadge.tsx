import { Badge } from "@/components/ui/badge.tsx";
import type { BadgeVariant } from "@/components/ui/badge.tsx";

interface StatusBadgeProps {
  state: string;
  className?: string;
}

const stateConfig: Record<string, { variant: BadgeVariant; label: string }> = {
  OK: { variant: "success", label: "OK" },
  UP: { variant: "success", label: "UP" },
  WARNING: { variant: "warning", label: "WARNING" },
  CRITICAL: { variant: "destructive", label: "CRITICAL" },
  DOWN: { variant: "destructive", label: "DOWN" },
  UNKNOWN: { variant: "default", label: "UNKNOWN" },
  FIRING: { variant: "destructive", label: "FIRING" },
  PENDING: { variant: "warning", label: "PENDING" },
  RESOLVED: { variant: "success", label: "RESOLVED" },
};

export function StatusBadge({ state, className }: StatusBadgeProps) {
  const upper = state.toUpperCase();
  const config = stateConfig[upper] ?? {
    variant: "default" as BadgeVariant,
    label: upper,
  };

  return (
    <Badge variant={config.variant} className={className}>
      {config.label}
    </Badge>
  );
}
