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
  LayoutDashboard,
  ListChecks,
  Monitor,
  Package,
  Plug,
  ArrowUpCircle,
  Play,
  Search,
  Settings,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils.ts";
import { useUpgradeBadge } from "@/api/hooks.ts";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard", end: true },
  { to: "/system-health", icon: HeartPulse, label: "System Health", end: false },
  { to: "/devices", icon: Monitor, label: "Devices", end: false },
  { to: "/apps", icon: AppWindow, label: "Apps", end: false },
  { to: "/connectors", icon: Plug, label: "Connectors", end: false },
  { to: "/python-modules", icon: Package, label: "Modules", end: false },
  { to: "/assignments", icon: ListChecks, label: "Assignments", end: false },
  { to: "/templates", icon: FileText, label: "Templates", end: false },
  { to: "/packs", icon: Boxes, label: "Packs", end: false },
  { to: "/alerts", icon: Bell, label: "Alerts", end: false },
  { to: "/events", icon: Zap, label: "Events", end: false },
  { to: "/automations", icon: Play, label: "Automations", end: false },
  { to: "/device-types", icon: Search, label: "Device Types", end: false },
  { to: "/analytics/explorer", icon: Terminal, label: "SQL Explorer", end: true },
  { to: "/analytics/dashboards", icon: BarChart3, label: "Dashboards", end: false },
  { to: "/upgrades", icon: ArrowUpCircle, label: "Upgrades", end: false },
  { to: "/settings", icon: Settings, label: "Settings", end: false },
];

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { data: badge } = useUpgradeBadge();
  const osUpdateCount = badge?.os_update_count ?? 0;

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
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-3">
        {navItems.map((item) => (
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
            {item.to === "/upgrades" && osUpdateCount > 0 && !collapsed && (
              <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500/20 px-1.5 text-[10px] font-semibold text-amber-400">
                {osUpdateCount}
              </span>
            )}
            {item.to === "/upgrades" && osUpdateCount > 0 && collapsed && (
              <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-amber-500" />
            )}
          </NavLink>
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
