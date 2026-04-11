import { useState } from "react";
import { useLocation, useNavigate, Link } from "react-router-dom";
import { LogOut, Star, User } from "lucide-react";
import { useAuth } from "@/hooks/useAuth.tsx";
import { useSystemHealthStatus, useUpdateMyDefaultPage } from "@/api/hooks.ts";
import { Button } from "@/components/ui/button.tsx";

const pageTitles: Record<string, string> = {
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
  "/incident-rules": "Incident Rules",
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
  const { user, logout, refresh } = useAuth();
  const updateDefaultPage = useUpdateMyDefaultPage();
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Resolve title — check exact match first, then prefix match for detail pages
  let title = pageTitles[location.pathname];
  if (!title) {
    if (location.pathname.startsWith("/devices/")) title = "Device Detail";
    else if (location.pathname.startsWith("/apps/")) title = "App Detail";
    else if (location.pathname.startsWith("/connectors/"))
      title = "Connector Detail";
    else if (location.pathname.startsWith("/packs/")) title = "Pack Detail";
    else if (location.pathname.startsWith("/analytics/dashboards/"))
      title = "Dashboard Editor";
    else if (location.pathname.startsWith("/settings/")) title = "Settings";
    else title = "MonCTL";
  }

  // Determine if the current page can be set as default (must be a top-level page in pageTitles)
  const currentRoute = pageTitles[location.pathname] ? location.pathname : null;
  const isDefault =
    currentRoute !== null &&
    (user?.default_page ?? "/devices") === currentRoute;

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const isAdmin = user?.role === "admin";
  const { data: healthStatus } = useSystemHealthStatus();
  const healthColor =
    !healthStatus?.overall_status || healthStatus.overall_status === "unknown"
      ? "bg-zinc-500"
      : healthStatus.overall_status === "healthy"
        ? "bg-emerald-400"
        : healthStatus.overall_status === "degraded"
          ? "bg-amber-400"
          : "bg-red-400";

  return (
    <>
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-900/60 px-6 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <h1 className="text-base font-semibold text-zinc-100">{title}</h1>
          {currentRoute !== null && (
            <button
              type="button"
              className={`cursor-pointer transition-colors ${isDefault ? "text-amber-400" : "text-zinc-600 hover:text-amber-400"}`}
              onClick={() => {
                if (isDefault) {
                  // Already default — reset to devices if not already devices
                  if (currentRoute !== "/devices") {
                    setConfirmOpen(true);
                  }
                } else {
                  setConfirmOpen(true);
                }
              }}
              title={isDefault ? "Default page" : "Set as default page"}
            >
              <Star
                className="h-4 w-4"
                fill={isDefault ? "currentColor" : "none"}
              />
            </button>
          )}
        </div>
        <div className="flex items-center gap-3">
          {user && (
            <Link
              to="/settings/profile"
              className="flex items-center gap-2 text-sm text-zinc-400 hover:text-zinc-200 transition-colors no-underline"
            >
              <User className="h-4 w-4" />
              <span>{user.username}</span>
              <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-500">
                {user.role}
              </span>
              <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-500">
                {user.timezone.replace(/_/g, " ")}
              </span>
            </Link>
          )}
          {isAdmin && healthStatus && (
            <Link
              to="/system-health"
              className="group flex items-center gap-1.5"
              title={`System: ${healthStatus.overall_status}`}
            >
              <span
                className={`inline-block h-2.5 w-2.5 rounded-full ${healthColor} group-hover:ring-2 group-hover:ring-offset-1 group-hover:ring-offset-zinc-900 group-hover:ring-current transition-shadow`}
              />
            </Link>
          )}
          <Button variant="ghost" size="sm" onClick={() => void handleLogout()}>
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">Logout</span>
          </Button>
        </div>
      </header>
      {confirmOpen && currentRoute !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setConfirmOpen(false)}
          />
          <div className="relative z-10 w-full max-w-sm rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl">
            <div className="px-6 py-5 space-y-4">
              <p className="text-sm text-zinc-200">
                Set <span className="font-semibold text-zinc-100">{title}</span>{" "}
                as your default landing page?
              </p>
              <div className="flex items-center justify-end gap-3">
                <button
                  type="button"
                  className="rounded-md px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer"
                  onClick={() => setConfirmOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-500 transition-colors cursor-pointer"
                  onClick={async () => {
                    const target = isDefault ? "/devices" : currentRoute;
                    await updateDefaultPage.mutateAsync(target);
                    await refresh();
                    setConfirmOpen(false);
                  }}
                >
                  Confirm
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
