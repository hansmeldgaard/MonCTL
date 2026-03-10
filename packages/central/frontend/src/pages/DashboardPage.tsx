import type { ComponentType } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  Cpu,
  Loader2,
  Monitor,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { StatusBadge } from "@/components/StatusBadge.tsx";
import {
  useDevices,
  useCollectors,
  useActiveAlerts,
  useLatestResults,
} from "@/api/hooks.ts";
import { timeAgo } from "@/lib/utils.ts";

function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  iconColor,
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: ComponentType<{ className?: string }>;
  iconColor: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle>{title}</CardTitle>
        <Icon className={`h-4.5 w-4.5 ${iconColor}`} />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold text-zinc-100">{value}</div>
        {subtitle && (
          <p className="mt-1 text-xs text-zinc-500">{subtitle}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function DashboardPage() {
  const { data: devicesResponse, isLoading: devicesLoading } = useDevices();
  const devices = devicesResponse?.data ?? [];
  const { data: collectors, isLoading: collectorsLoading } = useCollectors();
  const { data: alerts, isLoading: alertsLoading } = useActiveAlerts();
  const { data: latestResults } = useLatestResults();

  const isLoading = devicesLoading || collectorsLoading || alertsLoading;

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  const deviceCount = devices?.length ?? 0;
  const collectorCount = collectors?.length ?? 0;
  const alertCount = alerts?.length ?? 0;
  const onlineCollectors =
    collectors?.filter((c) => c.status === "ACTIVE").length ?? 0;

  // Determine up/down device counts from latest results
  const unreachableResults = latestResults?.filter((r) => !r.reachable) ?? [];

  // Unique devices that have at least one unreachable check
  const devicesWithIssues = new Set(unreachableResults.map((r) => r.device_id));
  const devicesUp = deviceCount - devicesWithIssues.size;
  const devicesDown = devicesWithIssues.size;

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Total Devices"
          value={deviceCount}
          subtitle={`${devicesUp} up / ${devicesDown} down`}
          icon={Monitor}
          iconColor="text-brand-400"
        />
        <StatCard
          title="Devices Up"
          value={devicesUp}
          subtitle="Responding to checks"
          icon={CheckCircle2}
          iconColor="text-emerald-400"
        />
        <StatCard
          title="Devices Down"
          value={devicesDown}
          subtitle={devicesDown > 0 ? "Requires attention" : "All systems healthy"}
          icon={devicesDown > 0 ? XCircle : CheckCircle2}
          iconColor={devicesDown > 0 ? "text-red-400" : "text-emerald-400"}
        />
        <StatCard
          title="Active Alerts"
          value={alertCount}
          subtitle={alertCount > 0 ? "Action required" : "No active alerts"}
          icon={alertCount > 0 ? AlertTriangle : Bell}
          iconColor={alertCount > 0 ? "text-amber-400" : "text-zinc-500"}
        />
      </div>

      {/* Two column layout for below */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Active Alerts */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-4 w-4" />
              Active Alerts
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!alerts || alerts.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
                <CheckCircle2 className="mb-2 h-8 w-8 text-emerald-500/50" />
                <p className="text-sm">No active alerts</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>State</TableHead>
                    <TableHead>Rule</TableHead>
                    <TableHead>Started</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {alerts.slice(0, 5).map((alert) => (
                    <TableRow key={alert.id}>
                      <TableCell>
                        <StatusBadge state={alert.state} />
                      </TableCell>
                      <TableCell className="font-medium text-zinc-200">
                        {alert.labels?.rule_name ?? alert.rule_id}
                      </TableCell>
                      <TableCell className="text-zinc-500">
                        {timeAgo(alert.started_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {alerts && alerts.length > 5 && (
              <div className="mt-3 text-center">
                <Link
                  to="/alerts"
                  className="text-sm text-brand-400 hover:text-brand-300"
                >
                  View all {alerts.length} alerts
                </Link>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Collectors Overview */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-4 w-4" />
              Collectors
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!collectors || collectors.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
                <Cpu className="mb-2 h-8 w-8 text-zinc-600" />
                <p className="text-sm">No collectors registered</p>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm text-zinc-400">
                  <Activity className="h-4 w-4" />
                  <span>
                    {onlineCollectors} of {collectorCount} online
                  </span>
                </div>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last Seen</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {collectors.slice(0, 5).map((c) => (
                      <TableRow key={c.id}>
                        <TableCell className="font-medium text-zinc-200">
                          {c.name}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              c.status === "ACTIVE" ? "success" : "destructive"
                            }
                          >
                            {c.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-zinc-500">
                          {timeAgo(c.last_seen_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            {collectors && collectors.length > 5 && (
              <div className="mt-3 text-center">
                <Link
                  to="/collectors"
                  className="text-sm text-brand-400 hover:text-brand-300"
                >
                  View all {collectors.length} collectors
                </Link>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent Check Results */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Recent Check Results
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!latestResults || latestResults.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
              <Activity className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No check results yet</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>State</TableHead>
                  <TableHead>Device</TableHead>
                  <TableHead>Check</TableHead>
                  <TableHead>Output</TableHead>
                  <TableHead>Response Time</TableHead>
                  <TableHead>Executed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {latestResults.slice(0, 10).map((r, idx) => (
                  <TableRow key={`${r.assignment_id}-${idx}`}>
                    <TableCell>
                      <StatusBadge state={r.state_name} />
                    </TableCell>
                    <TableCell>
                      <Link
                        to={`/devices/${r.device_id}`}
                        className="font-medium text-zinc-200 hover:text-brand-400"
                      >
                        {r.device_name ?? r.device_id}
                      </Link>
                    </TableCell>
                    <TableCell className="text-zinc-300">
                      {r.app_name ?? "—"}
                    </TableCell>
                    <TableCell
                      className="max-w-[200px] truncate text-zinc-500"
                      title={r.output}
                    >
                      {r.output || "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400">
                      {r.response_time_ms != null
                        ? `${r.response_time_ms}ms`
                        : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-500">
                      {timeAgo(r.executed_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
