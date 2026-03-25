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

export function DeviceIcon({
  icon,
  className,
}: {
  icon: string | null | undefined;
  className?: string;
}) {
  const Icon = icon ? DEVICE_ICON_MAP[icon] || Monitor : Monitor;
  return <Icon className={className ?? "h-4 w-4"} />;
}
