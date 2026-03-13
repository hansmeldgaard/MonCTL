import {
  Clock,
  Database,
  HardDrive,
  HeartPulse,
  Loader2,
  Radio,
  RefreshCw,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { useSystemHealth } from "@/api/hooks.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import type { ComponentType } from "react";
import type { SubsystemStatus } from "@/types/api.ts";

const statusColors: Record<SubsystemStatus, string> = {
  healthy: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  degraded: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  critical: "bg-red-500/15 text-red-400 border-red-500/30",
  unknown: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
};

const statusDotColors: Record<SubsystemStatus, string> = {
  healthy: "bg-emerald-400",
  degraded: "bg-amber-400",
  critical: "bg-red-400",
  unknown: "bg-zinc-400",
};

const subsystemMeta: Record<string, { label: string; icon: ComponentType<{ className?: string }> }> = {
  postgresql: { label: "PostgreSQL", icon: Database },
  clickhouse: { label: "ClickHouse", icon: HardDrive },
  redis: { label: "Redis", icon: Zap },
  collectors: { label: "Collectors", icon: Radio },
  scheduler: { label: "Scheduler", icon: Clock },
};

function StatusBadge({ status }: { status: SubsystemStatus }) {
  return (
    <Badge className={`${statusColors[status]} uppercase text-xs font-semibold`}>
      <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${statusDotColors[status]}`} />
      {status}
    </Badge>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1 text-sm">
      <span className="text-zinc-500">{label}</span>
      <span className="text-zinc-300 font-mono text-xs">{value ?? "—"}</span>
    </div>
  );
}

function PostgresqlDetails({ details }: { details: Record<string, unknown> }) {
  return (
    <>
      <DetailRow label="Pool size" value={String(details.pool_size)} />
      <DetailRow label="Checked out" value={String(details.checked_out)} />
      <DetailRow label="Overflow" value={String(details.overflow)} />
    </>
  );
}

function ClickHouseDetails({ details }: { details: Record<string, unknown> }) {
  const tables = details.tables as Record<string, { rows: number; latest_received_at: string | null }> | undefined;
  if (!tables) return null;
  return (
    <>
      {Object.entries(tables).map(([name, info]) => (
        <DetailRow
          key={name}
          label={name}
          value={`${(info.rows ?? 0).toLocaleString()} rows`}
        />
      ))}
    </>
  );
}

function RedisDetails({ details }: { details: Record<string, unknown> }) {
  return (
    <>
      <DetailRow label="DB size" value={String(details.db_size)} />
      <DetailRow label="Leader instance" value={String(details.leader_instance ?? "—")} />
    </>
  );
}

function CollectorDetails({ details }: { details: Record<string, unknown> }) {
  const byStatus = details.by_status as Record<string, number> | undefined;
  return (
    <>
      {byStatus && Object.entries(byStatus).map(([s, count]) => (
        <DetailRow key={s} label={s} value={String(count)} />
      ))}
      <DetailRow label="Total jobs" value={String(details.total_jobs)} />
      <DetailRow label="Avg load" value={String(details.avg_load)} />
      <DetailRow label="Avg miss rate" value={String(details.avg_deadline_miss_rate)} />
    </>
  );
}

function SchedulerDetails({ details }: { details: Record<string, unknown> }) {
  return (
    <>
      <DetailRow label="Current leader" value={String(details.current_leader ?? "—")} />
      <DetailRow label="This instance" value={details.is_this_instance ? "Yes" : "No"} />
      <DetailRow label="Leader TTL" value={`${details.leader_key_ttl}s`} />
    </>
  );
}

const detailRenderers: Record<string, (d: Record<string, unknown>) => React.ReactNode> = {
  postgresql: (d) => <PostgresqlDetails details={d} />,
  clickhouse: (d) => <ClickHouseDetails details={d} />,
  redis: (d) => <RedisDetails details={d} />,
  collectors: (d) => <CollectorDetails details={d} />,
  scheduler: (d) => <SchedulerDetails details={d} />,
};

export function SystemHealthPage() {
  const { data, isLoading, refetch, isFetching } = useSystemHealth();
  const tz = useTimezone();

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 text-zinc-500">
        <HeartPulse className="h-10 w-10" />
        <p>Could not load system health</p>
      </div>
    );
  }

  const overallStatus = data.overall_status;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <HeartPulse className="h-6 w-6 text-zinc-400" />
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">System Health</h1>
            <p className="text-sm text-zinc-500">
              Instance {data.instance_id} &middot; v{data.version} &middot; {formatDate(data.checked_at, tz)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={overallStatus} />
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Subsystem cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Object.entries(data.subsystems).map(([name, sub]) => {
          const meta = subsystemMeta[name] ?? { label: name, icon: Database };
          const Icon = meta.icon;
          const renderer = detailRenderers[name];

          return (
            <Card key={name}>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <div className="flex items-center gap-2">
                  <Icon className="h-4.5 w-4.5 text-zinc-400" />
                  <CardTitle>{meta.label}</CardTitle>
                </div>
                <StatusBadge status={sub.status} />
              </CardHeader>
              <CardContent>
                {sub.latency_ms != null && (
                  <DetailRow label="Latency" value={`${sub.latency_ms} ms`} />
                )}
                {typeof sub.details.error === "string" && (
                  <p className="text-sm text-red-400 mt-1">{sub.details.error}</p>
                )}
                {renderer && renderer(sub.details)}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
