import { useLocation, useNavigate } from "react-router-dom";
import { LogOut, User } from "lucide-react";
import { useAuth } from "@/hooks/useAuth.tsx";
import { Button } from "@/components/ui/button.tsx";

const pageTitles: Record<string, string> = {
  "/": "Dashboard",
  "/system-health": "System Health",
  "/devices": "Devices",
  "/apps": "Apps",
  "/connectors": "Connectors",
  "/python-modules": "Modules",
  "/collectors": "Collectors",
  "/assignments": "Assignments",
  "/templates": "Templates",
  "/packs": "Packs",
  "/credentials": "Credentials",
  "/labels": "Labels",
  "/alerts": "Alerts",
  "/events": "Events",
  "/device-types": "Device Types",
  "/automations": "Automations",
  "/analytics/explorer": "SQL Explorer",
  "/analytics/dashboards": "Custom Dashboards",
  "/upgrades": "Upgrades",
  "/settings": "Settings",
};

export function Header() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  // Resolve title — check exact match first, then prefix match for detail pages
  let title = pageTitles[location.pathname];
  if (!title) {
    if (location.pathname.startsWith("/devices/")) title = "Device Detail";
    else if (location.pathname.startsWith("/apps/")) title = "App Detail";
    else if (location.pathname.startsWith("/connectors/")) title = "Connector Detail";
    else if (location.pathname.startsWith("/packs/")) title = "Pack Detail";
    else if (location.pathname.startsWith("/analytics/dashboards/")) title = "Dashboard Editor";
    else if (location.pathname.startsWith("/settings/")) title = "Settings";
    else title = "MonCTL";
  }

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-900/60 px-6 backdrop-blur-sm">
      <h1 className="text-base font-semibold text-zinc-100">{title}</h1>
      <div className="flex items-center gap-3">
        {user && (
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            <User className="h-4 w-4" />
            <span>{user.username}</span>
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-500">
              {user.role}
            </span>
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-500">
              {user.timezone.replace(/_/g, " ")}
            </span>
          </div>
        )}
        <Button variant="ghost" size="sm" onClick={() => void handleLogout()}>
          <LogOut className="h-4 w-4" />
          <span className="hidden sm:inline">Logout</span>
        </Button>
      </div>
    </header>
  );
}
