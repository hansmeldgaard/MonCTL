import { NavLink } from "react-router-dom";
import {
  Activity,
  AppWindow,
  Bell,
  ChevronLeft,
  ChevronRight,
  FileText,
  HeartPulse,
  LayoutDashboard,
  ListChecks,
  Monitor,
  Package,
  Plug,
  Settings,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils.ts";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard", end: true },
  { to: "/system-health", icon: HeartPulse, label: "System Health", end: true },
  { to: "/devices", icon: Monitor, label: "Devices", end: false },
  { to: "/apps", icon: AppWindow, label: "Apps", end: false },
  { to: "/connectors", icon: Plug, label: "Connectors", end: false },
  { to: "/python-modules", icon: Package, label: "Modules", end: false },
  { to: "/assignments", icon: ListChecks, label: "Assignments", end: false },
  { to: "/templates", icon: FileText, label: "Templates", end: false },
  { to: "/alerts", icon: Bell, label: "Alerts", end: false },
  { to: "/events", icon: Zap, label: "Events", end: false },
  { to: "/settings", icon: Settings, label: "Settings", end: false },
];

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r border-zinc-800 bg-zinc-900 transition-all duration-200",
        collapsed ? "w-16" : "w-56",
      )}
    >
      {/* Brand */}
      <div className="flex h-14 items-center border-b border-zinc-800 px-4">
        <Activity className="h-6 w-6 shrink-0 text-brand-500" />
        {!collapsed && (
          <span className="ml-2.5 text-base font-semibold tracking-tight text-zinc-100">
            MonCTL
          </span>
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
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-brand-600/15 text-brand-400"
                  : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100",
                collapsed && "justify-center px-0",
              )
            }
          >
            <item.icon className="h-4.5 w-4.5 shrink-0" />
            {!collapsed && <span>{item.label}</span>}
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
