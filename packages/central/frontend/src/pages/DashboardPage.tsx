import type { ComponentType } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  Cpu,
  Loader2,
  Monitor,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { useDashboardSummary } from "@/api/hooks.ts";
import { timeAgo } from "@/lib/utils.ts";
import type {
  DashboardTopNEntry,
  DashboardWorstDevice,
  DashboardRecentAlert,
  DashboardStaleCollector,
} from "@/types/api.ts";

// ── Stat Card ────────────────────────────────────────────────────────────────

function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  iconColor,
  to,
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: ComponentType<{ className?: string }>;
  iconColor: string;
  to?: string;
}) {
  const card = (
    <Card className={to ? "hover:border-brand-500/50 transition-colors cursor-pointer" : ""}>
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

  if (to) {
    return <Link to={to}>{card}</Link>;
  }
  return card;
}

// ── Progress bar with color ramp ─────────────────────────────────────────────

function PercentBar({ value }: { value: number }) {
  const color =
    value > 80
      ? "bg-red-500"
      : value > 60
        ? "bg-amber-500"
        : "bg-emerald-500";

  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 rounded-full bg-zinc-800">
        <div
          className={`h-2 rounded-full ${color}`}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
      <span className="w-12 text-right text-xs text-zinc-400">{value}%</span>
    </div>
  );
}

// ── Dashboard Page ───────────────────────────────────────────────────────────

export function DashboardPage() {
  const { data, isLoading } = useDashboardSummary();

  if (isLoading || !data) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  const { alert_summary, device_health, collector_status, performance_top_n } = data;

  return (
    <div className="space-y-6">
      {/* ── Row 1: Stat Cards ─────────────────────────────────────────── */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Active Alerts"
          value={alert_summary.total_firing}
          subtitle={
            alert_summary.total_firing > 0
              ? "Action required"
              : "No active alerts"
          }
          icon={alert_summary.total_firing > 0 ? Bell : CheckCircle2}
          iconColor={alert_summary.total_firing > 0 ? "text-amber-400" : "text-zinc-500"}
          to="/alerts"
        />
        <StatCard
          title="Devices Up"
          value={device_health.up}
          subtitle={`of ${device_health.total}`}
          icon={CheckCircle2}
          iconColor="text-emerald-400"
          to="/devices"
        />
        <StatCard
          title="Devices Down"
          value={device_health.down}
          subtitle={
            device_health.degraded > 0
              ? `+ ${device_health.degraded} degraded`
              : device_health.down > 0
                ? "Requires attention"
                : "All healthy"
          }
          icon={device_health.down > 0 ? XCircle : CheckCircle2}
          iconColor={device_health.down > 0 ? "text-red-400" : "text-emerald-400"}
          to="/devices"
        />
        <StatCard
          title="Collectors Online"
          value={collector_status.online}
          subtitle={`${collector_status.offline} offline, ${collector_status.pending} pending`}
          icon={Cpu}
          iconColor="text-brand-400"
          to="/settings/collectors"
        />
      </div>

      {/* ── Row 2: Active Alerts + Device Health ──────────────────────── */}
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
            {alert_summary.recent.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
                <CheckCircle2 className="mb-2 h-8 w-8 text-emerald-500/50" />
                <p className="text-sm">No active alerts</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Alert</TableHead>
                    <TableHead>Device</TableHead>
                    <TableHead>Entity</TableHead>
                    <TableHead>Value</TableHead>
                    <TableHead>Since</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {alert_summary.recent.map((a: DashboardRecentAlert) => (
                    <TableRow key={a.id}>
                      <TableCell className="font-medium text-zinc-200">
                        {a.definition_name}
                      </TableCell>
                      <TableCell>
                        {a.device_id ? (
                          <Link
                            to={`/devices/${a.device_id}?tab=alerts`}
                            className="text-zinc-300 hover:text-brand-400"
                          >
                            {a.device_name}
                          </Link>
                        ) : (
                          <span className="text-zinc-500">—</span>
                        )}
                      </TableCell>
                      <TableCell className="max-w-[120px] truncate text-zinc-500" title={a.entity_key}>
                        {a.entity_key || "—"}
                      </TableCell>
                      <TableCell className="text-zinc-400">
                        {a.current_value != null ? a.current_value : "—"}
                      </TableCell>
                      <TableCell className="text-zinc-500">
                        {timeAgo(a.started_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {alert_summary.total_firing > 10 && (
              <div className="mt-3 text-center">
                <Link
                  to="/alerts"
                  className="text-sm text-brand-400 hover:text-brand-300"
                >
                  View all {alert_summary.total_firing} alerts
                </Link>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Device Health — Worst Devices */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Monitor className="h-4 w-4" />
              Device Health
            </CardTitle>
          </CardHeader>
          <CardContent>
            {device_health.worst.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
                <CheckCircle2 className="mb-2 h-8 w-8 text-emerald-500/50" />
                <p className="text-sm">All devices healthy</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Device</TableHead>
                    <TableHead>Address</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Alerts</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {device_health.worst.map((d: DashboardWorstDevice) => (
                    <TableRow key={d.device_id}>
                      <TableCell>
                        <Link
                          to={`/devices/${d.device_id}`}
                          className="font-medium text-zinc-200 hover:text-brand-400"
                        >
                          {d.device_name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-zinc-500">{d.device_address}</TableCell>
                      <TableCell>
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                            d.reason === "down"
                              ? "bg-red-500/15 text-red-400"
                              : "bg-amber-500/15 text-amber-400"
                          }`}
                        >
                          {d.reason}
                        </span>
                      </TableCell>
                      <TableCell className="text-zinc-400">
                        {d.firing_alerts > 0 ? (
                          <span className="text-red-400">{d.firing_alerts}</span>
                        ) : (
                          "0"
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            <div className="mt-3 text-center">
              <Link
                to="/devices"
                className="text-sm text-brand-400 hover:text-brand-300"
              >
                View all devices
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Row 3: Performance Top-N ──────────────────────────────────── */}
      {(performance_top_n.cpu.length > 0 ||
        performance_top_n.memory.length > 0 ||
        performance_top_n.bandwidth.length > 0) && (
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Top CPU */}
          <TopNCard
            title="Top CPU"
            entries={performance_top_n.cpu}
            linkTab="performance"
          />

          {/* Top Memory */}
          <TopNCard
            title="Top Memory"
            entries={performance_top_n.memory}
            linkTab="performance"
          />

          {/* Top Bandwidth */}
          <TopNCard
            title="Top Bandwidth"
            entries={performance_top_n.bandwidth}
            linkTab="interfaces"
            showInterface
          />
        </div>
      )}

      {/* ── Row 4: Collector Fleet Status (only when issues) ──────────── */}
      {(collector_status.offline > 0 || collector_status.stale.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-400" />
              Collector Issues
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Collector</TableHead>
                  <TableHead>Last Seen</TableHead>
                  <TableHead>Stale Duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {collector_status.stale.map((c: DashboardStaleCollector) => (
                  <TableRow key={c.collector_id}>
                    <TableCell className="font-medium text-zinc-200">
                      {c.name}
                    </TableCell>
                    <TableCell className="text-zinc-500">
                      {timeAgo(c.last_seen)}
                    </TableCell>
                    <TableCell className="text-amber-400">
                      {c.stale_seconds != null
                        ? formatDuration(c.stale_seconds)
                        : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="mt-3 text-center">
              <Link
                to="/settings/collectors"
                className="text-sm text-brand-400 hover:text-brand-300"
              >
                Manage collectors
              </Link>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Top-N Card Component ─────────────────────────────────────────────────────

function TopNCard({
  title,
  entries,
  linkTab,
  showInterface,
}: {
  title: string;
  entries: DashboardTopNEntry[];
  linkTab: string;
  showInterface?: boolean;
}) {
  if (entries.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="py-4 text-center text-sm text-zinc-500">No data</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {entries.map((e, idx) => (
          <div key={`${e.device_id}-${idx}`}>
            <div className="mb-1 flex items-center justify-between text-xs">
              <Link
                to={`/devices/${e.device_id}?tab=${linkTab}`}
                className="truncate text-zinc-300 hover:text-brand-400"
                title={e.device_name}
              >
                {e.device_name}
                {showInterface && e.interface ? (
                  <span className="ml-1 text-zinc-500">({e.interface})</span>
                ) : null}
              </Link>
            </div>
            <PercentBar value={e.value} />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}
