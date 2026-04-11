import { NavLink } from "react-router-dom";
import {
  AppWindow,
  BarChart3,
  Terminal,
  Bell,
  Boxes,
  ChevronLeft,
  ChevronRight,
  FileText,
  HeartPulse,
  KeyRound,
  ListChecks,
  Monitor,
  Package,
  Plug,
  ArrowUpCircle,
  Play,
  Search,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Tags,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils.ts";
import { useUpgradeBadge } from "@/api/hooks.ts";
import { usePermissions } from "@/hooks/usePermissions.ts";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

interface NavItem {
  to: string;
  icon: typeof Monitor;
  label: string;
  end?: boolean;
  resource?: string; // permission resource required to see this item
  adminOnly?: boolean;
}

interface NavGroup {
  label?: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    items: [
      {
        to: "/system-health",
        icon: HeartPulse,
        label: "System Health",
        adminOnly: true,
      },
    ],
  },
  {
    label: "Monitoring",
    items: [
      { to: "/devices", icon: Monitor, label: "Devices", resource: "device" },
      {
        to: "/device-types",
        icon: Search,
        label: "Device Types",
        resource: "device",
      },
      {
        to: "/assignments",
        icon: ListChecks,
        label: "Assignments",
        resource: "assignment",
      },
    ],
  },
  {
    label: "Configuration",
    items: [
      { to: "/apps", icon: AppWindow, label: "Apps", resource: "app" },
      {
        to: "/connectors",
        icon: Plug,
        label: "Connectors",
        resource: "connector",
      },
      {
        to: "/python-modules",
        icon: Package,
        label: "Modules",
        adminOnly: true,
      },
      {
        to: "/templates",
        icon: FileText,
        label: "Templates",
        resource: "template",
      },
      {
        to: "/credentials",
        icon: KeyRound,
        label: "Credentials",
        resource: "credential",
      },
      { to: "/labels", icon: Tags, label: "Labels", resource: "device" },
      { to: "/packs", icon: Boxes, label: "Packs", resource: "app" },
    ],
  },
  {
    label: "Alerting",
    items: [
      { to: "/alerts", icon: Bell, label: "Alerts", resource: "alert" },
      { to: "/events", icon: Zap, label: "Events", resource: "event" },
      {
        to: "/incidents",
        icon: ShieldAlert,
        label: "Incidents",
        resource: "event",
      },
      {
        to: "/incident-rules",
        icon: ShieldCheck,
        label: "Incident Rules",
        resource: "event",
      },
      {
        to: "/automations",
        icon: Play,
        label: "Automations",
        resource: "automation",
      },
    ],
  },
  {
    label: "Analytics",
    items: [
      {
        to: "/analytics/explorer",
        icon: Terminal,
        label: "SQL Explorer",
        end: true,
        resource: "result",
      },
      {
        to: "/analytics/dashboards",
        icon: BarChart3,
        label: "Dashboards",
        resource: "dashboard",
      },
    ],
  },
  {
    label: "System",
    items: [
      {
        to: "/upgrades",
        icon: ArrowUpCircle,
        label: "Upgrades",
        adminOnly: true,
      },
      { to: "/settings", icon: Settings, label: "Settings" },
    ],
  },
];

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { data: badge } = useUpgradeBadge();
  const osUpdateCount = badge?.os_update_count ?? 0;
  const { isAdmin, canView } = usePermissions();

  const visibleGroups = navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => {
        if (item.adminOnly) return isAdmin;
        if (item.resource) return canView(item.resource);
        return true;
      }),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r border-zinc-800 bg-zinc-900 transition-all duration-200",
        collapsed ? "w-16" : "w-56",
      )}
    >
      {/* Brand */}
      <div className="flex h-14 items-center justify-center border-b border-zinc-800 px-4">
        {collapsed ? (
          <img src="/logo-icon.svg" alt="MonCTL" className="h-8 w-8" />
        ) : (
          <img src="/logo.svg" alt="MonCTL" className="h-8" />
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {visibleGroups.map((group, gi) => (
          <div key={gi}>
            {group.label && !collapsed && (
              <div className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                {group.label}
              </div>
            )}
            {group.label && collapsed && (
              <div className="my-1.5 mx-3 border-t border-zinc-800" />
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-brand-600/15 text-brand-400"
                        : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100",
                      collapsed && "justify-center px-0",
                    )
                  }
                >
                  <item.icon className="h-4.5 w-4.5 shrink-0" />
                  {!collapsed && <span>{item.label}</span>}
                  {item.to === "/upgrades" &&
                    osUpdateCount > 0 &&
                    !collapsed && (
                      <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500/20 px-1.5 text-[10px] font-semibold text-amber-400">
                        {osUpdateCount}
                      </span>
                    )}
                  {item.to === "/upgrades" &&
                    osUpdateCount > 0 &&
                    collapsed && (
                      <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-amber-500" />
                    )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Collapse Toggle */}
      <div className="border-t border-zinc-800 p-2">
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-center rounded-md p-2 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300 cursor-pointer"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </button>
      </div>
    </aside>
  );
}
