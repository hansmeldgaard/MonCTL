import { useState, useMemo } from "react";
import {
  ArrowDown,
  ArrowDownToLine,
  ArrowUp,
  ArrowUpDown,
  Bell,
  Box,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  HardDrive,
  HeartPulse,
  Loader2,
  Radio,
  RefreshCw,
  Server,
  X,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { useSystemHealth } from "@/api/hooks.ts";
import { timeAgo, formatBytes, formatUptime, formatNumber } from "@/lib/utils.ts";
import type { SubsystemStatus, CollectorHealthDetail } from "@/types/api.ts";

// ── Status styling ───────────────────────────────────────────────────────────

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

// ── Shared components ────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: SubsystemStatus }) {
  return (
    <Badge className={`${statusColors[status]} uppercase text-xs font-semibold`}>
      <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${statusDotColors[status]}`} />
      {status}
    </Badge>
  );
}

function DetailGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[max-content_1fr] gap-x-8 gap-y-1 text-sm">
      {children}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <span className="text-zinc-500">{label}</span>
      <span className="text-zinc-300 font-mono text-xs">{value ?? "\u2014"}</span>
    </>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="col-span-2 text-xs font-semibold uppercase tracking-wider text-zinc-500 mt-3 mb-1">{children}</div>;
}

function ProgressBar({ pct, className }: { pct: number; className?: string }) {
  const color = pct > 95 ? "bg-red-500" : pct > 80 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className={`h-1.5 w-full rounded-full bg-zinc-800 ${className ?? ""}`}>
      <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
    </div>
  );
}

function FreshnessDot({ isoDate }: { isoDate: string | null }) {
  if (!isoDate) return <span className="inline-block h-2 w-2 rounded-full bg-zinc-600" />;
  const age = (Date.now() - new Date(isoDate).getTime()) / 1000;
  const color = age < 120 ? "bg-emerald-400" : age < 600 ? "bg-amber-400" : "bg-red-400";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

// ── Collapsible section ──────────────────────────────────────────────────────

function Collapsible({ title, defaultOpen = false, children, badge }: {
  title: string; defaultOpen?: boolean; children: React.ReactNode; badge?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300 cursor-pointer mt-2 mb-1">
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span className="font-semibold uppercase tracking-wider">{title}</span>
        {badge}
      </button>
      {open && children}
    </div>
  );
}

// ── Top row cards ────────────────────────────────────────────────────────────

function CentralCard({ d }: { d: Record<string, unknown> }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><Server className="h-4 w-4 text-zinc-400" /><CardTitle>Central</CardTitle></div>
        <StatusBadge status={(d.status as SubsystemStatus) ?? "unknown"} />
      </CardHeader>
      <CardContent>
        <DetailGrid>
          <DetailRow label="Role" value={String(d.role ?? "\u2014")} />
          <DetailRow label="Uptime" value={formatUptime(Number(d.uptime_seconds ?? 0))} />
          <DetailRow label="RSS" value={`${d.rss_mb} MB`} />
          <DetailRow label="Python" value={String(d.python_version ?? "\u2014")} />
          <DetailRow label="PID" value={String(d.pid ?? "\u2014")} />
        </DetailGrid>
      </CardContent>
    </Card>
  );
}

function AlertsCard({ sub }: { sub: { status: SubsystemStatus; details: Record<string, unknown> } }) {
  const d = sub.details;
  const firing = d.firing_by_severity as Record<string, number> | undefined;
  const totalFiring = Number(d.total_firing ?? 0);
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><Bell className="h-4 w-4 text-zinc-400" /><CardTitle>Alerts</CardTitle></div>
        <StatusBadge status={sub.status} />
      </CardHeader>
      <CardContent>
        <DetailGrid>
          {totalFiring === 0 ? (
            <span className="col-span-2 text-sm text-zinc-500">No alerts firing</span>
          ) : (
            <>
              {firing && Object.entries(firing).map(([sev, count]) => (
                <DetailRow key={sev} label={sev} value={
                  <span className={sev === "critical" ? "text-red-400" : sev === "warning" ? "text-amber-400" : "text-zinc-300"}>
                    {count}
                  </span>
                } />
              ))}
            </>
          )}
          <DetailRow label="Rules" value={`${d.enabled_rules ?? 0} / ${d.total_rules ?? 0} enabled`} />
        </DetailGrid>
      </CardContent>
    </Card>
  );
}

function IngestionCard({ sub }: { sub: { status: SubsystemStatus; details: Record<string, unknown> } }) {
  const d = sub.details;
  const byTable = d.by_table as Record<string, { rows_5m: number; rows_per_sec: number }> | undefined;
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><ArrowDownToLine className="h-4 w-4 text-zinc-400" /><CardTitle>Ingestion</CardTitle></div>
        <StatusBadge status={sub.status} />
      </CardHeader>
      <CardContent>
        <DetailGrid>
          <DetailRow label="Total" value={`${d.total_rows_per_sec ?? 0} rows/s`} />
          {byTable && Object.entries(byTable).map(([table, info]) => (
            <DetailRow key={table} label={table} value={`${info.rows_per_sec}/s`} />
          ))}
        </DetailGrid>
      </CardContent>
    </Card>
  );
}

// ── PostgreSQL card ──────────────────────────────────────────────────────────

function PostgreSQLCard({ sub }: { sub: { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> } }) {
  const d = sub.details;
  const tableCounts = d.table_counts as Record<string, number | null> | undefined;
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><Database className="h-4 w-4 text-zinc-400" /><CardTitle>PostgreSQL</CardTitle></div>
        <div className="flex items-center gap-2">
          {sub.latency_ms != null && <span className="text-xs text-zinc-500 font-mono">{sub.latency_ms}ms</span>}
          <StatusBadge status={sub.status} />
        </div>
      </CardHeader>
      <CardContent>
        <DetailGrid>
          <DetailRow label="Version" value={String(d.version ?? "\u2014")} />
          <DetailRow label="DB size" value={d.db_size_bytes ? formatBytes(Number(d.db_size_bytes)) : "\u2014"} />
          <DetailRow label="Pool" value={`${d.pool_size} size \u00b7 ${d.checked_out} out \u00b7 ${d.overflow} overflow`} />
          <DetailRow label="Connections" value={String(d.active_connections ?? "\u2014")} />
          {tableCounts && (
            <>
              <SectionTitle>Table counts</SectionTitle>
              {Object.entries(tableCounts).map(([name, count]) => (
                <DetailRow key={name} label={name} value={count != null ? formatNumber(count) : "\u2014"} />
              ))}
            </>
          )}
        </DetailGrid>
      </CardContent>
    </Card>
  );
}

// ── ClickHouse card ──────────────────────────────────────────────────────────

function ClickHouseCard({ sub }: { sub: { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> } }) {
  const d = sub.details;
  const tables = d.tables as Record<string, { rows: number; bytes: number; parts: number; latest_received_at: string | null }> | undefined;
  const cluster = d.cluster as { cluster_name: string; shard_count: number; replica_count: number; nodes: { shard: number; replica: number; host: string; address: string; port: number; is_local: boolean }[] } | null;
  const replication = d.replication as { table: string; is_leader: boolean; is_readonly: boolean; queue_size: number; absolute_delay: number; active_replicas: number; total_replicas: number; is_session_expired: boolean; log_lag: number; inserts_in_queue: number; merges_in_queue: number }[] | null;
  const keeper = d.keeper as { reachable: boolean; session_expired: boolean } | null;
  const merges = d.merges as Record<string, number> | null;
  const mutations = d.mutations as { pending: number; failed: number } | null;
  const server = d.server as { disks: { name: string; free_bytes: number; total_bytes: number; used_pct: number }[]; os_memory_total_bytes: number; os_memory_free_bytes: number; ch_memory_resident_bytes: number; cpu_user_pct: number; cpu_system_pct: number; cpu_idle_pct: number; cpu_iowait_pct: number; load_average: [number, number, number]; tcp_connections: number; max_parts_per_partition: number } | null;
  const slowQueries = d.slow_queries as { queries_1h: number; slow_5s: number; avg_duration_ms: number } | null;
  const recentErrors = d.recent_errors as { name: string; count: number; last_time: string | null; message: string | null }[] | null;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><HardDrive className="h-4 w-4 text-zinc-400" /><CardTitle>ClickHouse</CardTitle></div>
        <div className="flex items-center gap-2">
          {sub.latency_ms != null && <span className="text-xs text-zinc-500 font-mono">{sub.latency_ms}ms</span>}
          <StatusBadge status={sub.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-0">
        <DetailGrid>
          <DetailRow label="Version" value={String(d.version ?? "\u2014")} />
          {d.uptime_seconds != null && <DetailRow label="Uptime" value={formatUptime(Number(d.uptime_seconds))} />}
          <DetailRow label="Total size" value={`${formatBytes(Number(d.total_bytes ?? 0))} \u00b7 ${formatNumber(Number(d.total_rows ?? 0))} rows`} />
          {d.pk_memory_bytes != null && <DetailRow label="PK memory" value={formatBytes(Number(d.pk_memory_bytes))} />}
        </DetailGrid>

        {/* Server resources */}
        {server && (
          <>
            <SectionTitle>Server resources</SectionTitle>
            {server.disks?.map((disk) => (
              <div key={disk.name} className="space-y-0.5 mb-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-zinc-500">Disk: {disk.name}</span>
                  <span className="text-zinc-400 font-mono">{formatBytes(disk.total_bytes - disk.free_bytes)} / {formatBytes(disk.total_bytes)} ({disk.used_pct}%)</span>
                </div>
                <ProgressBar pct={disk.used_pct} />
              </div>
            ))}
            <DetailGrid>
              <DetailRow label="Memory" value={`OS ${formatBytes(server.os_memory_total_bytes - server.os_memory_free_bytes)} / ${formatBytes(server.os_memory_total_bytes)} \u00b7 CH ${formatBytes(server.ch_memory_resident_bytes)}`} />
              <DetailRow label="CPU" value={`user ${server.cpu_user_pct}% \u00b7 sys ${server.cpu_system_pct}% \u00b7 io ${server.cpu_iowait_pct}% \u00b7 idle ${server.cpu_idle_pct}%`} />
              <DetailRow label="Load" value={`${server.load_average[0]} / ${server.load_average[1]} / ${server.load_average[2]}`} />
              <DetailRow label="Connections" value={String(server.tcp_connections)} />
            </DetailGrid>
            <p className="text-[10px] text-zinc-600 mt-0.5">Connected node only</p>
          </>
        )}

        {/* Cluster topology */}
        {cluster ? (
          <>
            <SectionTitle>Cluster: {cluster.cluster_name}</SectionTitle>
            <p className="text-xs text-zinc-400 mb-1">{cluster.shard_count} shard(s), {cluster.replica_count} replica(s)</p>
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-xs py-1">Host</TableHead>
                <TableHead className="text-xs py-1">Address</TableHead>
                <TableHead className="text-xs py-1">Port</TableHead>
                <TableHead className="text-xs py-1">Local</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {cluster.nodes.map((n, i) => (
                  <TableRow key={i} className={n.is_local ? "bg-brand-500/5" : ""}>
                    <TableCell className="py-1 text-xs font-mono">{n.host}</TableCell>
                    <TableCell className="py-1 text-xs font-mono">{n.address}</TableCell>
                    <TableCell className="py-1 text-xs font-mono">{n.port}</TableCell>
                    <TableCell className="py-1 text-xs">{n.is_local ? "Yes" : ""}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        ) : (
          <p className="text-xs text-zinc-600 mt-2">Single-node mode (no cluster)</p>
        )}

        {/* Keeper */}
        {keeper && (
          <DetailGrid>
            <DetailRow label="Keeper" value={
              <span className={keeper.reachable && !keeper.session_expired ? "text-emerald-400" : "text-red-400"}>
                {keeper.reachable ? "Reachable" : "Unreachable"}
                {keeper.session_expired && " \u00b7 Session expired"}
              </span>
            } />
          </DetailGrid>
        )}

        {/* Replication */}
        {replication && replication.length > 0 && (
          <Collapsible title="Replication" defaultOpen>
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-xs py-1">Table</TableHead>
                <TableHead className="text-xs py-1">Leader</TableHead>
                <TableHead className="text-xs py-1">Queue</TableHead>
                <TableHead className="text-xs py-1">Lag</TableHead>
                <TableHead className="text-xs py-1">Replicas</TableHead>
                <TableHead className="text-xs py-1">R/O</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {replication.map((r) => (
                  <TableRow key={r.table} className={r.is_readonly ? "bg-red-500/10" : r.queue_size > 0 ? "bg-amber-500/5" : ""}>
                    <TableCell className="py-1 text-xs font-mono">{r.table}</TableCell>
                    <TableCell className="py-1 text-xs">{r.is_leader ? "Yes" : ""}</TableCell>
                    <TableCell className="py-1 text-xs font-mono">{r.queue_size}</TableCell>
                    <TableCell className="py-1 text-xs font-mono">{r.absolute_delay}s</TableCell>
                    <TableCell className="py-1 text-xs font-mono">{r.active_replicas}/{r.total_replicas}</TableCell>
                    <TableCell className="py-1 text-xs">{r.is_readonly ? <span className="text-red-400">Yes</span> : ""}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Collapsible>
        )}

        {/* Merges + Mutations */}
        <DetailGrid>
          {merges && (
            <DetailRow label="Merges" value={`${merges.active_count ?? merges.active_merges ?? 0} active${(merges.longest_seconds ?? 0) > 0 ? ` (longest: ${merges.longest_seconds}s)` : ""}`} />
          )}
          {mutations && (
            <DetailRow label="Mutations" value={
              <span className={mutations.failed > 0 ? "text-red-400" : ""}>
                {mutations.pending} pending{mutations.failed > 0 ? ` \u00b7 ${mutations.failed} failed` : ""}
              </span>
            } />
          )}
          {server && <DetailRow label="Max parts/partition" value={String(server.max_parts_per_partition)} />}
        </DetailGrid>

        {/* Data tables */}
        {tables && (
          <>
            <SectionTitle>Data tables</SectionTitle>
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-xs py-1">Table</TableHead>
                <TableHead className="text-xs py-1 text-right">Rows</TableHead>
                <TableHead className="text-xs py-1 text-right">Size</TableHead>
                <TableHead className="text-xs py-1 text-right">Parts</TableHead>
                <TableHead className="text-xs py-1">Fresh</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {Object.entries(tables).map(([name, info]) => (
                  <TableRow key={name}>
                    <TableCell className="py-1 text-xs font-mono">{name}</TableCell>
                    <TableCell className="py-1 text-xs font-mono text-right">{formatNumber(info.rows ?? 0)}</TableCell>
                    <TableCell className="py-1 text-xs font-mono text-right">{info.bytes != null ? formatBytes(info.bytes) : "\u2014"}</TableCell>
                    <TableCell className="py-1 text-xs font-mono text-right">{info.parts != null ? info.parts : "\u2014"}</TableCell>
                    <TableCell className="py-1 text-xs">
                      {info.rows > 0 ? (
                        <span className="flex items-center gap-1.5">
                          <FreshnessDot isoDate={info.latest_received_at} />
                          {info.latest_received_at ? timeAgo(info.latest_received_at) : "\u2014"}
                        </span>
                      ) : (
                        <span className="text-zinc-600">No data</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}

        {/* Query performance */}
        {slowQueries && (
          <Collapsible title="Query performance (1h)">
            <DetailGrid>
              <DetailRow label="Queries" value={formatNumber(slowQueries.queries_1h)} />
              <DetailRow label="Avg duration" value={`${slowQueries.avg_duration_ms.toFixed(1)}ms`} />
              <DetailRow label="Slow (>5s)" value={String(slowQueries.slow_5s)} />
            </DetailGrid>
          </Collapsible>
        )}

        {/* Recent errors */}
        {recentErrors && recentErrors.length > 0 ? (
          <Collapsible title="Recent errors" badge={<Badge variant="destructive" className="ml-2 text-[10px]">{recentErrors.length}</Badge>}>
            {recentErrors.map((e, i) => (
              <div key={i} className="text-xs py-0.5">
                <span className="text-red-400 font-mono">{e.name}</span>
                <span className="text-zinc-500"> ({e.count}x)</span>
                {e.message && <p className="text-zinc-600 truncate">{e.message}</p>}
              </div>
            ))}
          </Collapsible>
        ) : (
          <p className="text-xs text-zinc-600 mt-1">No errors in last hour</p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Redis card ───────────────────────────────────────────────────────────────

function RedisCard({ sub }: { sub: { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> } }) {
  const d = sub.details;
  const keyStats = d.key_stats as Record<string, number> | undefined;
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><Zap className="h-4 w-4 text-zinc-400" /><CardTitle>Redis</CardTitle></div>
        <div className="flex items-center gap-2">
          {sub.latency_ms != null && <span className="text-xs text-zinc-500 font-mono">{sub.latency_ms}ms</span>}
          <StatusBadge status={sub.status} />
        </div>
      </CardHeader>
      <CardContent>
        <DetailGrid>
          <DetailRow label="Version" value={String(d.version ?? "\u2014")} />
          <DetailRow label="Memory" value={d.used_memory_bytes ? `${formatBytes(Number(d.used_memory_bytes))} / ${formatBytes(Number(d.used_memory_peak_bytes ?? 0))} peak` : "\u2014"} />
          <DetailRow label="RSS" value={d.used_memory_rss_bytes ? formatBytes(Number(d.used_memory_rss_bytes)) : "\u2014"} />
          <DetailRow label="Keys" value={formatNumber(Number(d.db_size ?? 0))} />
          <DetailRow label="Clients" value={String(d.connected_clients ?? "\u2014")} />
          <DetailRow label="Leader" value={String(d.leader_instance ?? "\u2014")} />
          {keyStats && (
            <>
              <SectionTitle>Key breakdown</SectionTitle>
              {Object.entries(keyStats).map(([prefix, count]) => (
                <DetailRow key={prefix} label={prefix} value={formatNumber(count)} />
              ))}
            </>
          )}
        </DetailGrid>
      </CardContent>
    </Card>
  );
}

// ── Scheduler card ───────────────────────────────────────────────────────────

function SchedulerCard({ sub }: { sub: { status: SubsystemStatus; details: Record<string, unknown> } }) {
  const d = sub.details;
  const lastRuns = d.last_runs as Record<string, string | null> | undefined;
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><Clock className="h-4 w-4 text-zinc-400" /><CardTitle>Scheduler</CardTitle></div>
        <StatusBadge status={sub.status} />
      </CardHeader>
      <CardContent>
        <DetailGrid>
          <DetailRow label="Leader" value={String(d.current_leader ?? "\u2014")} />
          <DetailRow label="This instance" value={d.is_this_instance ? "Yes" : "No"} />
          <DetailRow label="Leader TTL" value={`${d.leader_key_ttl ?? 0}s`} />
          {lastRuns && (
            <>
              <SectionTitle>Last runs</SectionTitle>
              {Object.entries(lastRuns).map(([name, ts]) => (
                <DetailRow key={name} label={name.replace("last_", "")} value={ts ? timeAgo(ts) : "never"} />
              ))}
            </>
          )}
        </DetailGrid>
      </CardContent>
    </Card>
  );
}

// ── Docker infrastructure card ───────────────────────────────────────────────

interface DockerHost {
  label: string;
  status: string;
  source: string;
  data: {
    hostname: string;
    container_count: number;
    total_containers: number;
    host: { disk_total_bytes: number | null; disk_used_bytes: number | null; disk_free_bytes: number | null } | null;
    containers: {
      name: string;
      image?: string;
      status: string;
      health: string | null;
      cpu_pct: number | null;
      mem_usage_bytes: number | null;
      mem_limit_bytes: number | null;
      mem_pct: number | null;
      net_rx_bytes: number | null;
      net_tx_bytes: number | null;
      restart_count: number;
      started_at?: string;
    }[];
  } | null;
  error?: string;
}

function ContainerStatusDot({ status, health }: { status: string; health: string | null }) {
  if (status !== "running") return <span className="h-2 w-2 rounded-full bg-zinc-600 inline-block" />;
  if (health === "unhealthy") return <span className="h-2 w-2 rounded-full bg-red-400 inline-block" />;
  if (health === "healthy") return <span className="h-2 w-2 rounded-full bg-emerald-400 inline-block" />;
  return <span className="h-2 w-2 rounded-full bg-emerald-400 inline-block" />;
}

function DockerInfraCard({ sub }: { sub: { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> } }) {
  const d = sub.details;
  if (d.configured === false) return null;

  const hosts = (d.hosts ?? []) as DockerHost[];
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function toggleHost(label: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label); else next.add(label);
      return next;
    });
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><Box className="h-4 w-4 text-zinc-400" /><CardTitle>Docker Infrastructure</CardTitle></div>
        <div className="flex items-center gap-2">
          {sub.latency_ms != null && <span className="text-xs text-zinc-500 font-mono">{sub.latency_ms}ms</span>}
          <StatusBadge status={sub.status} />
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-4 text-sm text-zinc-400 mb-3">
          <span className="font-mono">
            <span className="text-emerald-400">{d.reachable_hosts as number}</span>/{d.total_hosts as number} hosts reachable
          </span>
        </div>

        {hosts.map((host) => {
          const isExp = expanded.has(host.label);
          const containers = host.data?.containers ?? [];
          const running = containers.filter((c) => c.status === "running").length;
          const unhealthy = containers.filter((c) => c.health === "unhealthy").length;

          return (
            <div key={host.label} className="mb-2">
              <button
                onClick={() => toggleHost(host.label)}
                className="flex items-center gap-2 w-full text-left py-1.5 px-2 rounded hover:bg-zinc-800/50 transition-colors cursor-pointer"
              >
                {isExp ? <ChevronDown className="h-3 w-3 text-zinc-500" /> : <ChevronRight className="h-3 w-3 text-zinc-500" />}
                <span className="text-sm font-mono font-medium text-zinc-200">{host.label}</span>
                {host.status === "ok" ? (
                  <span className="text-xs text-zinc-500">
                    {running}/{containers.length} running
                    {unhealthy > 0 && <span className="text-red-400 ml-1">({unhealthy} unhealthy)</span>}
                  </span>
                ) : (
                  <span className="text-xs text-red-400">unreachable</span>
                )}
              </button>

              {isExp && host.data && (
                <div className="ml-5 mt-1">
                  {host.data.host && host.data.host.disk_total_bytes != null && (
                    <div className="mb-2">
                      <div className="flex items-center justify-between text-xs text-zinc-500 mb-0.5">
                        <span>Disk</span>
                        <span className="font-mono">
                          {formatBytes(host.data.host.disk_used_bytes ?? 0)} / {formatBytes(host.data.host.disk_total_bytes)}
                        </span>
                      </div>
                      <ProgressBar pct={host.data.host.disk_total_bytes > 0
                        ? ((host.data.host.disk_used_bytes ?? 0) / host.data.host.disk_total_bytes) * 100
                        : 0
                      } />
                    </div>
                  )}
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs py-1">Container</TableHead>
                        <TableHead className="text-xs py-1 w-16">Status</TableHead>
                        <TableHead className="text-xs py-1 w-16 text-right">CPU</TableHead>
                        <TableHead className="text-xs py-1 w-24 text-right">Memory</TableHead>
                        <TableHead className="text-xs py-1 w-16 text-right">Restarts</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {containers.map((c) => (
                        <TableRow key={c.name} className={c.health === "unhealthy" ? "bg-red-500/5" : c.status !== "running" ? "bg-zinc-800/30" : ""}>
                          <TableCell className="py-1 text-xs font-mono">{c.name}</TableCell>
                          <TableCell className="py-1 text-xs">
                            <span className="flex items-center gap-1.5">
                              <ContainerStatusDot status={c.status} health={c.health} />
                              {c.status}
                            </span>
                          </TableCell>
                          <TableCell className="py-1 text-xs font-mono text-right">
                            {c.cpu_pct != null ? `${c.cpu_pct}%` : "\u2014"}
                          </TableCell>
                          <TableCell className="py-1 text-xs font-mono text-right">
                            {c.mem_usage_bytes != null ? `${formatBytes(c.mem_usage_bytes)}` : "\u2014"}
                            {c.mem_pct != null && <span className="text-zinc-600 ml-1">({c.mem_pct}%)</span>}
                          </TableCell>
                          <TableCell className="py-1 text-xs font-mono text-right">
                            <span className={c.restart_count > 3 ? "text-red-400" : c.restart_count > 0 ? "text-amber-400" : "text-zinc-600"}>
                              {c.restart_count}
                            </span>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// ── Collectors section ───────────────────────────────────────────────────────

type CollectorSortField = "name" | "status" | "last_seen_at" | "total_jobs" | "effective_load" | "group_name";
type SortDir = "asc" | "desc";

function CollectorSortHead({
  label, field, sortBy, sortDir, onSort, className,
}: {
  label: string; field: CollectorSortField; sortBy: CollectorSortField; sortDir: SortDir;
  onSort: (field: CollectorSortField) => void; className?: string;
}) {
  const active = sortBy === field;
  return (
    <TableHead
      className={`text-xs py-1 cursor-pointer select-none hover:text-zinc-200 ${className ?? ""}`}
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
        ) : (
          <ArrowUpDown className="h-3 w-3 text-zinc-600" />
        )}
      </span>
    </TableHead>
  );
}

function CollectorsSection({ sub }: { sub: { status: SubsystemStatus; details: Record<string, unknown> } }) {
  const d = sub.details;
  const byStatus = d.by_status as Record<string, number> | undefined;
  const collectors = (d.collectors ?? []) as CollectorHealthDetail[];
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Sort state
  const [sortBy, setSortBy] = useState<CollectorSortField>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  // Filter state
  const [filterStatus, setFilterStatus] = useState("");
  const [filterSearch, setFilterSearch] = useState("");

  function onSort(field: CollectorSortField) {
    if (field === sortBy) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(field);
      setSortDir(field === "name" || field === "group_name" || field === "status" ? "asc" : "desc");
    }
  }

  const statusOptions = useMemo(() => {
    const statuses = new Set(collectors.map((c) => c.status));
    return Array.from(statuses).sort();
  }, [collectors]);

  const sortedCollectors = useMemo(() => {
    let filtered = collectors;

    if (filterStatus) {
      filtered = filtered.filter((c) => c.status === filterStatus);
    }

    if (filterSearch.trim()) {
      const q = filterSearch.trim().toLowerCase();
      filtered = filtered.filter((c) =>
        (c.name ?? "").toLowerCase().includes(q) ||
        (c.hostname ?? "").toLowerCase().includes(q) ||
        (c.group_name ?? "").toLowerCase().includes(q)
      );
    }

    return [...filtered].sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case "name": cmp = (a.name ?? "").localeCompare(b.name ?? ""); break;
        case "status": cmp = (a.status ?? "").localeCompare(b.status ?? ""); break;
        case "last_seen_at": cmp = (a.last_seen_at ?? "").localeCompare(b.last_seen_at ?? ""); break;
        case "total_jobs": cmp = (a.total_jobs ?? 0) - (b.total_jobs ?? 0); break;
        case "effective_load": cmp = (a.effective_load ?? 0) - (b.effective_load ?? 0); break;
        case "group_name": cmp = (a.group_name ?? "").localeCompare(b.group_name ?? ""); break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [collectors, filterStatus, filterSearch, sortBy, sortDir]);

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><Radio className="h-4 w-4 text-zinc-400" /><CardTitle>Collectors</CardTitle></div>
        <StatusBadge status={sub.status} />
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-4 text-sm text-zinc-400 mb-3">
          {byStatus && Object.entries(byStatus).map(([s, count]) => (
            <span key={s} className="font-mono">
              <span className={s === "ACTIVE" ? "text-emerald-400" : s === "DOWN" ? "text-red-400" : "text-zinc-400"}>{count}</span>
              {" "}{s}
            </span>
          ))}
          <span className="text-zinc-600">&middot;</span>
          <span className="font-mono">{String(d.total_jobs ?? 0)} jobs</span>
          <span className="font-mono">load {Number(d.avg_load ?? 0).toFixed(3)}</span>
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-3 mb-3">
          <Input
            placeholder="Search collectors..."
            value={filterSearch}
            onChange={(e) => setFilterSearch(e.target.value)}
            className="w-56 h-7 text-xs"
          />
          <Select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="w-36 text-xs"
          >
            <option value="">All Statuses</option>
            {statusOptions.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </Select>
          {(filterStatus || filterSearch) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { setFilterStatus(""); setFilterSearch(""); }}
              className="h-7 px-2"
            >
              <X className="h-3 w-3 mr-1" /> Clear
            </Button>
          )}
          <span className="text-xs text-zinc-500 ml-auto">
            {sortedCollectors.length} of {collectors.length} collector{collectors.length !== 1 ? "s" : ""}
          </span>
        </div>

        {sortedCollectors.length === 0 ? (
          <p className="text-sm text-zinc-500 py-8 text-center">
            No collectors match the current filters.
          </p>
        ) : (
          <Table>
            <TableHeader><TableRow>
              <TableHead className="text-xs py-1 w-6"></TableHead>
              <CollectorSortHead label="Name" field="name" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
              <CollectorSortHead label="Status" field="status" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
              <CollectorSortHead label="Last seen" field="last_seen_at" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
              <CollectorSortHead label="Jobs" field="total_jobs" sortBy={sortBy} sortDir={sortDir} onSort={onSort} className="text-right" />
              <CollectorSortHead label="Load" field="effective_load" sortBy={sortBy} sortDir={sortDir} onSort={onSort} className="text-right" />
              <CollectorSortHead label="Group" field="group_name" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            </TableRow></TableHeader>
            <TableBody>
              {sortedCollectors.map((c) => {
                const isExp = expanded.has(c.id);
                return (
                  <>
                    <TableRow key={c.id} className="cursor-pointer hover:bg-zinc-800/50" onClick={() => toggleExpand(c.id)}>
                      <TableCell className="py-1.5 text-zinc-500">
                        {isExp ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                      </TableCell>
                      <TableCell className="py-1.5 text-sm font-mono">{c.name ?? c.hostname}</TableCell>
                      <TableCell className="py-1.5">
                        <span className={`text-xs font-semibold ${c.status === "ACTIVE" ? "text-emerald-400" : c.status === "DOWN" ? "text-red-400" : "text-zinc-400"}`}>
                          {c.status}
                        </span>
                      </TableCell>
                      <TableCell className="py-1.5 text-xs text-zinc-500">{timeAgo(c.last_seen_at)}</TableCell>
                      <TableCell className="py-1.5 text-xs font-mono text-right">{c.total_jobs}</TableCell>
                      <TableCell className="py-1.5 text-xs font-mono text-right">{c.effective_load.toFixed(3)}</TableCell>
                      <TableCell className="py-1.5 text-xs text-zinc-500">{c.group_name ?? "\u2014"}</TableCell>
                    </TableRow>
                    {isExp && (
                      <TableRow key={`${c.id}-detail`}>
                        <TableCell colSpan={7} className="py-2 px-6 bg-zinc-900/50">
                          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1 text-xs">
                            <DetailRow label="Workers" value={String(c.worker_count)} />
                            <DetailRow label="Eff. load" value={c.effective_load.toFixed(3)} />
                            <DetailRow label="Miss rate" value={
                              <span className={c.deadline_miss_rate > 0.1 ? "text-red-400" : c.deadline_miss_rate > 0.05 ? "text-amber-400" : ""}>
                                {c.deadline_miss_rate.toFixed(3)}
                              </span>
                            } />
                            {c.container_states ? (
                              <>
                                <div className="col-span-full mt-1">
                                  <span className="text-zinc-500 text-xs font-semibold">Containers:</span>
                                  {Object.entries(c.container_states).map(([name, state]) => (
                                    <span key={name} className="ml-2 inline-flex items-center gap-1">
                                      <span className={`h-1.5 w-1.5 rounded-full ${state === "running" ? "bg-emerald-400" : "bg-red-400"}`} />
                                      <span className="text-zinc-400">{name}</span>
                                    </span>
                                  ))}
                                </div>
                              </>
                            ) : (
                              <DetailRow label="Containers" value="Not reported" />
                            )}
                            {c.queue_stats && (
                              <>
                                <DetailRow label="Pending results" value={String(c.queue_stats.pending_results)} />
                                <DetailRow label="Overdue" value={
                                  <span className={c.queue_stats.jobs_overdue > 0 ? "text-amber-400" : ""}>{c.queue_stats.jobs_overdue}</span>
                                } />
                                <DetailRow label="Errors (1h)" value={
                                  <span className={c.queue_stats.jobs_errored_last_hour > 5 ? "text-red-400" : ""}>{c.queue_stats.jobs_errored_last_hour}</span>
                                } />
                                <DetailRow label="Avg exec" value={`${c.queue_stats.avg_execution_ms.toFixed(0)}ms`} />
                                <DetailRow label="Max exec" value={`${c.queue_stats.max_execution_ms.toFixed(0)}ms`} />
                              </>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export function SystemHealthPage() {
  const { data, isLoading, refetch, isFetching } = useSystemHealth();

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

  const subs = data.subsystems;
  const central = subs.central;
  const centralDetails = central?.details ?? {};

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <HeartPulse className="h-6 w-6 text-zinc-400" />
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">System Health</h1>
            <p className="text-sm text-zinc-500">
              Instance {data.instance_id} &middot; v{data.version}
              {centralDetails.role ? ` \u00b7 role: ${centralDetails.role}` : ""}
              {" \u00b7 "}{timeAgo(data.checked_at)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={data.overall_status} />
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Top row: Central + Alerts + Ingestion */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {central && <CentralCard d={centralDetails} />}
        {subs.alerts && <AlertsCard sub={subs.alerts as { status: SubsystemStatus; details: Record<string, unknown> }} />}
        {subs.ingestion && <IngestionCard sub={subs.ingestion as { status: SubsystemStatus; details: Record<string, unknown> }} />}
      </div>

      {/* PostgreSQL */}
      {subs.postgresql && <PostgreSQLCard sub={subs.postgresql as { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> }} />}

      {/* ClickHouse */}
      {subs.clickhouse && <ClickHouseCard sub={subs.clickhouse as { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> }} />}

      {/* Redis + Scheduler */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {subs.redis && <RedisCard sub={subs.redis as { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> }} />}
        {subs.scheduler && <SchedulerCard sub={subs.scheduler as { status: SubsystemStatus; details: Record<string, unknown> }} />}
      </div>

      {/* Collectors */}
      {subs.collectors && <CollectorsSection sub={subs.collectors as { status: SubsystemStatus; details: Record<string, unknown> }} />}

      {/* Docker Infrastructure */}
      {subs.docker && <DockerInfraCard sub={subs.docker as { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> }} />}
    </div>
  );
}
