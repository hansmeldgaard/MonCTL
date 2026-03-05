import { Activity, Loader2, Server, User } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { useAuth } from "@/hooks/useAuth.tsx";
import { useHealth } from "@/api/hooks.ts";

export function SettingsPage() {
  const { user } = useAuth();
  const { data: health, isLoading: healthLoading } = useHealth();

  return (
    <div className="space-y-6 max-w-2xl">
      {/* User Info */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <User className="h-4 w-4" />
            User Information
          </CardTitle>
        </CardHeader>
        <CardContent>
          {user ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Username</span>
                <span className="text-sm font-medium text-zinc-100">
                  {user.username}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">User ID</span>
                <span className="font-mono text-xs text-zinc-300">
                  {user.user_id}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Role</span>
                <Badge variant="info">{user.role}</Badge>
              </div>
            </div>
          ) : (
            <p className="text-sm text-zinc-500">User info not available</p>
          )}
        </CardContent>
      </Card>

      {/* System Health */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-4 w-4" />
            System Health
          </CardTitle>
        </CardHeader>
        <CardContent>
          {healthLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            </div>
          ) : health ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Status</span>
                <Badge
                  variant={
                    health.status === "healthy" || health.status === "ok"
                      ? "success"
                      : "destructive"
                  }
                >
                  {health.status}
                </Badge>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Version</span>
                <span className="font-mono text-xs text-zinc-300">
                  {health.version}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Instance ID</span>
                <span className="font-mono text-xs text-zinc-300">
                  {health.instance_id}
                </span>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
              <Activity className="mb-2 h-6 w-6 text-zinc-600" />
              <p className="text-sm">Unable to fetch system health</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
