import {
  Box,
  Cloud,
  Cpu,
  Database,
  Globe,
  HardDrive,
  Monitor,
  Network,
  Printer,
  Server,
  Shield,
} from "lucide-react";

const DEVICE_ICON_MAP: Record<string, React.ElementType> = {
  server: Server,
  router: Network,
  switch: Network,
  firewall: Shield,
  printer: Printer,
  cloud: Cloud,
  database: Database,
  container: Box,
  cpu: Cpu,
  globe: Globe,
  "hard-drive": HardDrive,
  monitor: Monitor,
};

/**
 * Renders either a custom uploaded icon (via <img>) or a Lucide icon.
 *
 * @param icon       Lucide icon identifier (e.g. "router", "server")
 * @param customIconUrl  URL to a custom uploaded icon image (takes precedence over Lucide)
 * @param className  CSS classes for sizing (e.g. "h-4 w-4")
 */
export function DeviceIcon({
  icon,
  customIconUrl,
  className,
}: {
  icon: string | null | undefined;
  customIconUrl?: string | null;
  className?: string;
}) {
  if (customIconUrl) {
    return (
      <img
        src={customIconUrl}
        alt=""
        className={className ?? "h-4 w-4"}
        style={{ objectFit: "contain" }}
        draggable={false}
      />
    );
  }
  const Icon = icon ? DEVICE_ICON_MAP[icon] || Monitor : Monitor;
  return <Icon className={className ?? "h-4 w-4"} />;
}

/**
 * Build the custom icon URL for a device category (if it has one).
 */
export function categoryIconUrl(categoryId: string): string {
  return `/v1/device-categories/${categoryId}/icon`;
}
