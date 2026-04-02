import { useState, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowDownToLine,
  ArrowUp,
  ArrowUpDown,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  HardDrive,
  HeartPulse,
  LayoutDashboard,
  Loader2,
  Radio,
  Network,
  RefreshCw,
  Server,
  Shield,
  X,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { useSystemHealth, useDockerOverview, usePatroniSwitchover, useCollectorErrors, useLogs } from "@/api/hooks.ts";
import { timeAgo, formatBytes, formatUptime, formatNumber } from "@/lib/utils.ts";
import type { SubsystemStatus, CollectorHealthDetail, DockerOverviewHost, DockerContainerStats } from "@/types/api.ts";
import { AlertTriangle } from "lucide-react";

// ── Status styling ───────────────────────────────────────────────────────────

const statusColors: Record<SubsystemStatus, string> = {
  healthy: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  degraded: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  critical: "bg-red-500/15 text-red-400 border-red-500/30",
  unknown: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  unconfigured: "bg-zinc-500/15 text-zinc-500 border-zinc-500/30",
};

const statusDotColors: Record<SubsystemStatus, string> = {
  healthy: "bg-emerald-400",
  degraded: "bg-amber-400",
  critical: "bg-red-400",
  unknown: "bg-zinc-400",
  unconfigured: "bg-zinc-500",
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

function UnconfiguredCard({ name, message }: { name: string; message: string }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center py-12 text-center">
        <StatusBadge status="unconfigured" />
        <p className="mt-3 text-sm text-zinc-400">{name} is not configured on this node.</p>
        <p className="mt-1 text-xs text-zinc-500 font-mono">{message}</p>
      </CardContent>
    </Card>
  );
}

function DetailGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-2">
      {children}
    </div>
  );
}

function Tip({ label, tip }: { label: string; tip: string }) {
  return (
    <span className="border-b border-dashed border-zinc-600 cursor-help" title={tip}>
      {label}
    </span>
  );
}

function DetailRow({ label, value, tip }: { label: string; value: React.ReactNode; tip?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-zinc-500 leading-none">
        {tip ? <Tip label={label} tip={tip} /> : label}
      </span>
      <span className="text-zinc-300 font-mono text-xs leading-snug">{value ?? "\u2014"}</span>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="col-span-full text-xs font-semibold uppercase tracking-wider text-zinc-500 mt-3 mb-1">{children}</div>;
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
  // ClickHouse returns DateTime without timezone suffix — force UTC interpretation
  const ts = isoDate.includes("Z") || isoDate.includes("+") ? isoDate : isoDate + "Z";
  const age = (Date.now() - new Date(ts).getTime()) / 1000;
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

// ── PostgreSQL card ──────────────────────────────────────────────────────────

function PostgreSQLCard({ sub }: { sub: { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> } }) {
  const d = sub.details;
  const conns = d.connections as { active: number; total: number; max: number } | undefined;
  const replication = d.replication as { client_addr: string | null; state: string; replay_lag_ms: number | null; write_lag_ms: number | null; replay_lag_bytes: number | null }[] | undefined;
  const vacuumStats = d.vacuum_stats as { table: string; dead_tuples: number; live_tuples: number; last_autovacuum: string | null }[] | undefined;
  const longQueries = d.long_running_queries as { pid: number; user: string; duration_s: number; query_preview: string }[] | undefined;
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
      <CardContent className="space-y-0">
        <DetailGrid>
          <DetailRow label="Version" value={String(d.version ?? "\u2014")} />
          <DetailRow label="DB size" value={d.db_size_bytes ? formatBytes(Number(d.db_size_bytes)) : "\u2014"} tip="Total size of the PostgreSQL database on disk, including indexes and TOAST data." />
          <DetailRow label="Pool" value={`${d.pool_size} size · ${d.checked_out} out · ${d.overflow} overflow`} tip="SQLAlchemy connection pool. Size = pre-allocated connections, Out = currently in use, Overflow = extra connections beyond pool size." />
          {conns && <DetailRow label="Connections" value={`${conns.active} active · ${conns.total} / ${conns.max} total`} tip="Active = currently executing queries. Total = all connections (active + idle). Max = PostgreSQL max_connections setting." />}
          {!conns && <DetailRow label="Connections" value={String(d.active_connections ?? "\u2014")} tip="Number of active database connections." />}
        </DetailGrid>

        {/* Cache & performance */}
        <SectionTitle>Performance</SectionTitle>
        <DetailGrid>
          <DetailRow label="Cache hit ratio" value={d.cache_hit_pct != null ? `${d.cache_hit_pct}%` : "\u2014"} tip="Percentage of reads served from shared_buffers instead of disk. Should be >99%." />
          <DetailRow label="Index hit ratio" value={d.index_hit_pct != null ? `${d.index_hit_pct}%` : "\u2014"} tip="Percentage of index lookups served from cache. Should be >99%." />
          <DetailRow label="XID age" value={d.xid_age != null ? formatNumber(Number(d.xid_age)) : "\u2014"} tip="Transaction ID age — if approaching 2 billion, VACUUM FREEZE is needed to prevent wraparound shutdown." />
          <DetailRow label="Waiting locks" value={String(d.waiting_locks ?? 0)} tip="Queries currently blocked waiting to acquire a lock." />
          <DetailRow label="Deadlocks (total)" value={formatNumber(Number(d.deadlocks_total ?? 0))} tip="Total deadlocks detected since server start. Frequent deadlocks indicate contention." />
          <DetailRow label="Temp bytes (total)" value={d.temp_bytes_total ? formatBytes(Number(d.temp_bytes_total)) : "0"} tip="Total bytes written to temporary files — high values indicate queries exceeding work_mem." />
        </DetailGrid>

        {/* Replication */}
        {replication && replication.length > 0 && (
          <>
            <SectionTitle>Replication</SectionTitle>
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-xs py-1"><Tip label="Client" tip="IP address of the replication client (standby server)." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="State" tip="Replication state: streaming = actively replicating, catchup = replica is catching up." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Replay lag" tip="Time delay before changes on primary are applied on the replica." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Lag bytes" tip="Bytes of WAL data the replica has not yet applied." /></TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {replication.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs py-1 font-mono">{r.client_addr ?? "\u2014"}</TableCell>
                    <TableCell className="text-xs py-1">{r.state}</TableCell>
                    <TableCell className="text-xs py-1 font-mono">{r.replay_lag_ms != null ? `${r.replay_lag_ms}ms` : "\u2014"}</TableCell>
                    <TableCell className="text-xs py-1 font-mono">{r.replay_lag_bytes != null ? formatBytes(r.replay_lag_bytes) : "\u2014"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}

        {/* Vacuum stats */}
        {vacuumStats && vacuumStats.length > 0 && (
          <>
            <SectionTitle><Tip label="Vacuum (top dead tuples)" tip="VACUUM reclaims storage from dead tuples. Tables with many dead tuples may need autovacuum tuning." /></SectionTitle>
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-xs py-1">Table</TableHead>
                <TableHead className="text-xs py-1"><Tip label="Dead" tip="Rows marked for deletion but not yet reclaimed by VACUUM. High counts may indicate autovacuum is falling behind." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Live" tip="Active, visible rows in the table." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Last vacuum" tip="When PostgreSQL last automatically reclaimed dead tuples from this table." /></TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {vacuumStats.map((v, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs py-1 font-mono">{v.table}</TableCell>
                    <TableCell className="text-xs py-1 font-mono text-amber-400">{formatNumber(v.dead_tuples)}</TableCell>
                    <TableCell className="text-xs py-1 font-mono">{formatNumber(v.live_tuples)}</TableCell>
                    <TableCell className="text-xs py-1">{v.last_autovacuum ? timeAgo(v.last_autovacuum) : "never"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}

        {/* Long-running queries */}
        {longQueries && longQueries.length > 0 && (
          <>
            <SectionTitle>Long-running queries (&gt;5min)</SectionTitle>
            {longQueries.map((q, i) => (
              <div key={i} className="rounded border border-zinc-800 bg-zinc-800/30 p-2 mb-1">
                <div className="flex items-center gap-2 text-xs text-zinc-400">
                  <span>PID {q.pid}</span>
                  <span>·</span>
                  <span>{q.user}</span>
                  <span>·</span>
                  <span className="text-amber-400">{q.duration_s}s</span>
                </div>
                <p className="text-xs font-mono text-zinc-500 mt-1 truncate">{q.query_preview}</p>
              </div>
            ))}
          </>
        )}

        {/* Table counts */}
        {tableCounts && (
          <>
            <SectionTitle>Table counts</SectionTitle>
            <DetailGrid>
              {Object.entries(tableCounts).map(([name, count]) => (
                <DetailRow key={name} label={name} value={count != null ? formatNumber(count) : "\u2014"} />
              ))}
            </DetailGrid>
          </>
        )}
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
          {d.pk_memory_bytes != null && <DetailRow label="PK memory" value={formatBytes(Number(d.pk_memory_bytes))} tip="Memory used by primary key indexes. Kept in RAM for fast lookups." />}
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
              <DetailRow label="Load" value={`${server.load_average[0]} / ${server.load_average[1]} / ${server.load_average[2]}`} tip="System load average (1 / 5 / 15 min). Values above CPU core count indicate saturation." />
              <DetailRow label="Connections" value={String(server.tcp_connections)} tip="Active TCP connections to this ClickHouse node." />
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
            <DetailRow label="Keeper" tip="ZooKeeper/ClickHouse Keeper connectivity — required for replicated tables and distributed DDL." value={
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
                <TableHead className="text-xs py-1"><Tip label="Leader" tip="Whether this node is the replication leader for this table." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Queue" tip="Replication queue — pending operations to sync between replicas. Should be 0 in steady state." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Delay" tip="Replication delay in seconds. 0 means replicas are fully synchronized." /></TableHead>
                <TableHead className="text-xs py-1">Replicas</TableHead>
                <TableHead className="text-xs py-1"><Tip label="R/O" tip="Read-only mode — table cannot accept inserts. Usually indicates a ZooKeeper/Keeper issue." /></TableHead>
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
            <DetailRow label="Merges" tip="Background merge operations combining data parts. Normal ClickHouse housekeeping." value={`${merges.active_count ?? merges.active_merges ?? 0} active${(merges.longest_seconds ?? 0) > 0 ? ` (longest: ${merges.longest_seconds}s)` : ""}`} />
          )}
          {mutations && (
            <DetailRow label="Mutations" tip="ALTER TABLE operations (UPDATE/DELETE). Pending = in-progress, Failed = need attention." value={
              <span className={mutations.failed > 0 ? "text-red-400" : ""}>
                {mutations.pending} pending{mutations.failed > 0 ? ` \u00b7 ${mutations.failed} failed` : ""}
              </span>
            } />
          )}
          {server && <DetailRow label="Max parts/partition" tip="Highest active part count across all partitions. ClickHouse warns at 300 parts." value={String(server.max_parts_per_partition)} />}
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
                <TableHead className="text-xs py-1 text-right"><Tip label="Parts" tip="Number of data parts — ClickHouse merges these in the background. High counts may slow queries." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Fresh" tip="Time since the last data row was received. Green <2min, amber <10min, red >10min." /></TableHead>
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
                          {info.latest_received_at ? timeAgo(info.latest_received_at.includes("Z") || info.latest_received_at.includes("+") ? info.latest_received_at : info.latest_received_at + "Z") : "\u2014"}
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
  const memory = d.memory as { used_memory_human?: string; used_memory_peak_human?: string; mem_fragmentation_ratio?: number } | undefined;
  const replication = d.replication as { role?: string; connected_slaves?: number; replicas?: string[] } | undefined;
  const sentinel = d.sentinel as { master_ip?: string; master_port?: string; num_slaves?: string; num_sentinels?: number; quorum?: string; flags?: string } | undefined;
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
          <DetailRow label="Memory" value={d.used_memory_bytes ? `${formatBytes(Number(d.used_memory_bytes))} / ${formatBytes(Number(d.used_memory_peak_bytes ?? 0))} peak` : (memory?.used_memory_human ? `${memory.used_memory_human} / ${memory.used_memory_peak_human} peak` : "\u2014")} tip="Current Redis memory usage / peak usage since start." />
          <DetailRow label="RSS" value={d.used_memory_rss_bytes ? formatBytes(Number(d.used_memory_rss_bytes)) : "\u2014"} tip="OS-level resident memory — includes fragmentation overhead." />
          {memory?.mem_fragmentation_ratio != null && (
            <DetailRow label="Fragmentation" value={`${memory.mem_fragmentation_ratio.toFixed(2)}x`} tip="RSS / used_memory ratio. Values >1.5 indicate memory fragmentation. <1.0 means swapping." />
          )}
          <DetailRow label="Keys" value={formatNumber(Number(d.db_size ?? 0))} tip="Total number of keys stored in Redis." />
          <DetailRow label="Clients" value={String(d.connected_clients ?? "\u2014")} tip="Number of active client connections to Redis." />
        </DetailGrid>

        {/* Replication */}
        {replication && (
          <>
            <SectionTitle><Tip label="Replication" tip="Redis replication status — primary replicates to one or more read replicas for HA." /></SectionTitle>
            <DetailGrid>
              <DetailRow label="Role" value={String(replication.role ?? "\u2014")} tip="master = primary (accepts writes), slave = replica (read-only)." />
              <DetailRow label="Connected replicas" value={String(replication.connected_slaves ?? 0)} tip="Number of replicas actively connected and replicating." />
            </DetailGrid>
          </>
        )}

        {/* Sentinel */}
        {sentinel && (
          <>
            <SectionTitle><Tip label="Sentinel" tip="Redis Sentinel monitors the primary and triggers automatic failover to a replica if it goes down." /></SectionTitle>
            <DetailGrid>
              <DetailRow label="Master" value={`${sentinel.master_ip}:${sentinel.master_port}`} tip="The Redis instance currently elected as primary by Sentinel." />
              <DetailRow label="Replicas" value={String(sentinel.num_slaves ?? 0)} tip="Number of Redis replicas known to Sentinel." />
              <DetailRow label="Sentinels" value={String(sentinel.num_sentinels ?? 0)} tip="Total Sentinel instances monitoring this master." />
              <DetailRow label="Quorum" value={String(sentinel.quorum ?? "\u2014")} tip="Minimum sentinels that must agree before initiating a failover." />
              {sentinel.flags && sentinel.flags !== "master" && (
                <DetailRow label="Flags" value={sentinel.flags} tip="Sentinel flags — 'master' is normal. 's_down' or 'o_down' indicate problems." />
              )}
            </DetailGrid>
          </>
        )}

        {keyStats && (
          <>
            <SectionTitle><Tip label="Key breakdown" tip="Sample of Redis key prefixes and their counts — shows what is using Redis storage." /></SectionTitle>
            <DetailGrid>
              {Object.entries(keyStats).map(([prefix, count]) => (
                <DetailRow key={prefix} label={prefix} value={formatNumber(count)} />
              ))}
            </DetailGrid>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Scheduler card ───────────────────────────────────────────────────────────

const _TASK_TIPS: Record<string, string> = {
  health_check: "Marks stale collectors as DOWN. Runs every 60s.",
  evaluate_alerts: "Evaluates alert definitions against ClickHouse data. Runs every 30s.",
  hourly_rollup: "Aggregates raw interface data into hourly summaries. Runs every hour.",
  daily_rollup: "Aggregates hourly interface data into daily summaries. Runs daily.",
  retention_cleanup: "Deletes expired data from ClickHouse based on retention settings.",
  rebalance: "Rebalances job distribution across collectors in each group. Runs every 5 min.",
  event_cleanup: "Clears resolved events older than the configured window.",
};

const _TASK_LABELS: Record<string, string> = {
  health_check: "Health check",
  evaluate_alerts: "Alert evaluation",
  hourly_rollup: "Hourly rollup",
  daily_rollup: "Daily rollup",
  retention_cleanup: "Retention cleanup",
  rebalance: "Rebalance",
  event_cleanup: "Event cleanup",
};

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
          <DetailRow label="Leader" value={String(d.current_leader ?? "\u2014")} tip="The central node currently holding the scheduler leader lock. Only the leader runs background tasks." />
          <DetailRow label="This instance" value={d.is_this_instance ? "Yes" : "No"} tip="Whether the central node serving this request is the current scheduler leader." />
          <DetailRow label="Leader TTL" value={`${d.leader_key_ttl ?? 0}s`} tip="Seconds until the leader lock expires. The leader renews this periodically. If it expires, another node takes over." />
          {lastRuns && (
            <>
              <SectionTitle>Last runs</SectionTitle>
              {Object.entries(lastRuns).map(([name, ts]) => (
                <DetailRow key={name} label={_TASK_LABELS[name] ?? name} value={ts ? timeAgo(ts) : "never"} tip={_TASK_TIPS[name]} />
              ))}
            </>
          )}
        </DetailGrid>
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

function CollectorErrorPanel({ collectorName }: { collectorName: string }) {
  const { data: errors, isLoading } = useCollectorErrors(collectorName);
  const [showLogs, setShowLogs] = useState(false);
  const logsQuery = useLogs(
    { collector_name: collectorName, level: "ERROR", page_size: 50, sort_dir: "desc" },
    showLogs,
  );
  const logEntries = logsQuery.data?.data?.data ?? [];

  if (isLoading) return <div className="text-xs text-zinc-500 py-2">Loading error analytics...</div>;
  if (!errors) return null;

  const hasErrors = errors.top_errors.length > 0 || errors.app_errors.some((a) => a.errors > 0);

  const categoryColors: Record<string, string> = {
    device: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    config: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    app: "bg-red-500/20 text-red-400 border-red-500/30",
  };
  const categoryLabel = (cat: string) => cat || "other";

  return (
    <div className="mt-2 space-y-3">
      {/* Error category summary */}
      {errors.category_counts && Object.keys(errors.category_counts).length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {Object.entries(errors.category_counts)
            .sort(([, a], [, b]) => b - a)
            .map(([cat, count]) => (
              <span key={cat || "_empty"} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${categoryColors[cat] || "bg-zinc-500/20 text-zinc-400 border-zinc-500/30"}`}>
                {categoryLabel(cat)}: {count}
              </span>
            ))}
        </div>
      )}
      {/* Per-app error breakdown */}
      {errors.app_errors.length > 0 && (
        <div>
          <SectionTitle>Errors by App (1h)</SectionTitle>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1">
            {errors.app_errors.map((a) => (
              <DetailRow key={a.app} label={a.app} value={
                <span className={a.errors > 0 ? "text-red-400" : "text-zinc-400"}>
                  {a.errors} / {a.total}
                </span>
              } tip={`${a.errors} errors out of ${a.total} total executions`} />
            ))}
          </div>
        </div>
      )}
      {/* Top error messages */}
      {errors.top_errors.length > 0 && (
        <div>
          <SectionTitle>Top Error Messages (1h)</SectionTitle>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {errors.top_errors.map((e, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="text-red-400 font-mono whitespace-nowrap">{e.count}x</span>
                {e.category && (
                  <span className={`inline-flex px-1.5 py-0 rounded text-[10px] font-medium border ${categoryColors[e.category] || "bg-zinc-500/20 text-zinc-400 border-zinc-500/30"}`}>
                    {e.category}
                  </span>
                )}
                <span className="text-zinc-400 font-mono break-all">{e.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {!hasErrors && (
        <div className="text-xs text-emerald-400 py-1">No errors in the last hour.</div>
      )}
      {/* Collector logs toggle */}
      <div>
        <button
          onClick={() => setShowLogs(!showLogs)}
          className="text-xs text-blue-400 hover:text-blue-300 underline cursor-pointer"
        >
          {showLogs ? "Hide recent logs" : "Show recent error logs"}
        </button>
        {showLogs && (
          <div className="mt-2 max-h-64 overflow-y-auto rounded bg-zinc-950 border border-zinc-800 p-2 space-y-0.5">
            {logEntries.length === 0 ? (
              <div className="text-xs text-zinc-500">No error logs found.</div>
            ) : logEntries.map((entry, i) => (
              <div key={i} className="text-[11px] font-mono leading-tight">
                <span className="text-zinc-600">{entry.timestamp.replace("T", " ").slice(0, 19)}</span>
                {" "}
                <span className="text-zinc-500">[{entry.container_name}]</span>
                {" "}
                <span className="text-red-400">{entry.message.slice(0, 300)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
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
          <ClearableInput
            placeholder="Search collectors..."
            value={filterSearch}
            onChange={(e) => setFilterSearch(e.target.value)}
            onClear={() => setFilterSearch("")}
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

        <Table>
            <TableHeader><TableRow>
              <TableHead className="text-xs py-1 w-6"></TableHead>
              <CollectorSortHead label="Name" field="name" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
              <CollectorSortHead label="Status" field="status" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
              <CollectorSortHead label="Last seen" field="last_seen_at" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
              <CollectorSortHead label="Jobs" field="total_jobs" sortBy={sortBy} sortDir={sortDir} onSort={onSort} className="text-right" />
              <CollectorSortHead label="Load" field="effective_load" sortBy={sortBy} sortDir={sortDir} onSort={onSort} className="text-right" />
              <TableHead className="text-xs py-1">Capacity</TableHead>
              <CollectorSortHead label="Group" field="group_name" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
            </TableRow></TableHeader>
            <TableBody>
              {sortedCollectors.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-8 text-zinc-500 text-sm">
                    No collectors match the current filters.
                  </TableCell>
                </TableRow>
              ) : sortedCollectors.map((c) => {
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
                      <TableCell className="py-1.5">
                        {c.capacity_status === "critical" ? (
                          <span className="text-xs font-semibold text-red-400" title={c.capacity_warnings?.join(", ")}>Critical</span>
                        ) : c.capacity_status === "warning" ? (
                          <span className="text-xs font-semibold text-amber-400" title={c.capacity_warnings?.join(", ")}>Warning</span>
                        ) : (
                          <span className="text-xs text-emerald-400">OK</span>
                        )}
                      </TableCell>
                      <TableCell className="py-1.5 text-xs text-zinc-500">{c.group_name ?? "\u2014"}</TableCell>
                    </TableRow>
                    {isExp && (
                      <TableRow key={`${c.id}-detail`}>
                        <TableCell colSpan={8} className="py-2 px-6 bg-zinc-900/50">
                          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1 text-xs">
                            {/* Load metrics */}
                            <DetailRow label="Workers" value={String(c.worker_count)} />
                            <DetailRow label="Load score" value={c.load_score.toFixed(3)} tip="Sum of (avg_execution_time / interval) for all jobs. Represents total CPU-seconds needed per wall-clock second. Values above 1.0 are normal with async I/O." />
                            <DetailRow label="Eff. load" value={c.effective_load.toFixed(3)} tip="Load score divided by worker count. How much work each worker handles." />
                            <DetailRow label="Weight" value={c.weight != null ? c.weight.toFixed(3) : "—"} tip="Hash ring weight from group snapshot. Higher = more jobs assigned." />
                            <DetailRow label="Miss rate" value={
                              <span className={c.deadline_miss_rate > 0.1 ? "text-red-400" : c.deadline_miss_rate > 0.05 ? "text-amber-400" : ""}>
                                {(c.deadline_miss_rate * 100).toFixed(1)}%
                              </span>
                            } tip="Percentage of jobs that miss their scheduled deadline. Warning at 5%, critical at 10%. High miss rate means the collector can't keep up." />

                            {/* System resources */}
                            {c.system_resources ? (() => {
                              const sr = c.system_resources;
                              const cpuPct = sr.cpu_count > 0 && sr.cpu_load.length > 0 ? (sr.cpu_load[0] / sr.cpu_count) * 100 : 0;
                              const memPct = sr.memory_total_mb > 0 ? (sr.memory_used_mb / sr.memory_total_mb) * 100 : 0;
                              const diskPct = sr.disk_total_gb > 0 ? (sr.disk_used_gb / sr.disk_total_gb) * 100 : 0;
                              return (
                                <>
                                  <SectionTitle>System Resources</SectionTitle>
                                  <DetailRow label="CPU" value={
                                    <div className="flex items-center gap-2">
                                      <span className={cpuPct >= 95 ? "text-red-400" : cpuPct >= 80 ? "text-amber-400" : ""}>{cpuPct.toFixed(0)}%</span>
                                      <ProgressBar pct={cpuPct} className="w-20" />
                                      <span className="text-zinc-500">({sr.cpu_load[0]?.toFixed(1)}/{sr.cpu_count} cores)</span>
                                    </div>
                                  } tip="1-minute load average as percentage of available CPU cores. Warning at 80%, critical at 95%." />
                                  <DetailRow label="Memory" value={
                                    <div className="flex items-center gap-2">
                                      <span className={memPct >= 95 ? "text-red-400" : memPct >= 80 ? "text-amber-400" : ""}>{memPct.toFixed(0)}%</span>
                                      <ProgressBar pct={memPct} className="w-20" />
                                      <span className="text-zinc-500">({sr.memory_used_mb}/{sr.memory_total_mb} MB)</span>
                                    </div>
                                  } tip="Memory usage. Warning at 80%, critical at 95%." />
                                  <DetailRow label="Disk" value={
                                    <div className="flex items-center gap-2">
                                      <span className={diskPct >= 90 ? "text-red-400" : diskPct >= 80 ? "text-amber-400" : ""}>{diskPct.toFixed(0)}%</span>
                                      <ProgressBar pct={diskPct} className="w-20" />
                                      <span className="text-zinc-500">({sr.disk_used_gb}/{sr.disk_total_gb} GB)</span>
                                    </div>
                                  } />
                                </>
                              );
                            })() : (
                              <>
                                <SectionTitle>System Resources</SectionTitle>
                                <DetailRow label="System" value="Not reported" tip="System resources will appear after the next heartbeat from this collector." />
                              </>
                            )}

                            {/* Capacity warnings */}
                            {c.capacity_warnings && c.capacity_warnings.length > 0 && (
                              <div className="col-span-full mt-1 p-2 rounded bg-amber-950/30 border border-amber-800/30">
                                <span className={`text-xs font-semibold ${c.capacity_status === "critical" ? "text-red-400" : "text-amber-400"}`}>
                                  {c.capacity_status === "critical" ? "Capacity critical" : "Capacity warning"}:
                                </span>
                                <span className="text-xs text-zinc-300 ml-1">{c.capacity_warnings.join(", ")}</span>
                              </div>
                            )}

                            {/* Containers */}
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
                                <DetailRow label="Pending results" value={String(c.queue_stats.pending_results)} tip="Results waiting to be shipped to central by the forwarder." />
                                <DetailRow label="Overdue" value={
                                  <span className={c.queue_stats.jobs_overdue > 0 ? "text-amber-400" : ""}>{c.queue_stats.jobs_overdue}</span>
                                } tip="Jobs that missed their scheduled execution time. Non-zero indicates the collector is falling behind." />
                                <DetailRow label="Errors (1h)" value={
                                  <span className={c.queue_stats.jobs_errored_last_hour > 5 ? "text-red-400" : ""}>{c.queue_stats.jobs_errored_last_hour}</span>
                                } />
                                <DetailRow label="Avg exec" value={`${c.queue_stats.avg_execution_ms.toFixed(0)}ms`} tip="Average job execution time across all recent jobs." />
                                <DetailRow label="Max exec" value={`${c.queue_stats.max_execution_ms.toFixed(0)}ms`} />
                              </>
                            )}
                          </div>
                          {/* Error analytics & logs */}
                          <CollectorErrorPanel collectorName={c.hostname ?? c.name} />
                        </TableCell>
                      </TableRow>
                    )}
                  </>
                );
              })}
            </TableBody>
          </Table>
      </CardContent>
    </Card>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

// ── Per-node ClickHouse card ────────────────────────────────────────────────

type CHNodeData = {
  host: string;
  reachable: boolean;
  latency_ms: number | null;
  error?: string;
  server?: {
    disks: { name: string; free_bytes: number; total_bytes: number; used_pct: number }[];
    os_memory_total_bytes: number;
    os_memory_free_bytes: number;
    ch_memory_resident_bytes: number;
    cpu_user_pct: number;
    cpu_system_pct: number;
    cpu_iowait_pct: number;
    cpu_idle_pct: number;
    load_average: [number, number, number];
    tcp_connections: number;
    max_parts_per_partition: number;
  };
  replication?: { table: string; queue_size: number; absolute_delay: number; active_replicas: number; total_replicas: number; is_readonly: boolean; is_session_expired: boolean }[];
  merges?: { active_count: number; longest_seconds: number; total_bytes_merging: number };
  mutations?: { total: number; pending: number; failed: number };
  recent_errors?: { name: string; count: number; last_time: string | null; message: string | null }[];
};

function CHNodeCard({ node }: { node: CHNodeData }) {
  const s = node.server;
  if (!node.reachable) {
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-mono">{node.host}</CardTitle>
          <StatusBadge status="critical" />
        </CardHeader>
        <CardContent>
          <p className="text-xs text-red-400">Unreachable: {node.error || "Connection failed"}</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-mono">{node.host}</CardTitle>
        <div className="flex items-center gap-2">
          {node.latency_ms != null && <span className="text-xs text-zinc-500 font-mono">{node.latency_ms}ms</span>}
          <StatusBadge status="healthy" />
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {s && (
          <>
            {s.disks?.map((disk) => (
              <div key={disk.name} className="space-y-0.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-zinc-500">Disk: {disk.name}</span>
                  <span className="text-zinc-400 font-mono">{formatBytes(disk.total_bytes - disk.free_bytes)} / {formatBytes(disk.total_bytes)} ({disk.used_pct}%)</span>
                </div>
                <ProgressBar pct={disk.used_pct} />
              </div>
            ))}
            <DetailGrid>
              <DetailRow label="Memory" value={`OS ${formatBytes(s.os_memory_total_bytes - s.os_memory_free_bytes)} / ${formatBytes(s.os_memory_total_bytes)}`} />
              <DetailRow label="CPU" value={`user ${s.cpu_user_pct}% \u00b7 sys ${s.cpu_system_pct}% \u00b7 idle ${s.cpu_idle_pct}%`} />
              <DetailRow label="Load" value={`${s.load_average[0]} / ${s.load_average[1]} / ${s.load_average[2]}`} />
            </DetailGrid>
          </>
        )}
        <DetailGrid>
          {node.merges && <DetailRow label="Merges" value={`${node.merges.active_count} active${node.merges.longest_seconds > 0 ? ` (${node.merges.longest_seconds}s)` : ""}`} />}
          {node.mutations && (
            <DetailRow label="Mutations" value={
              <span className={node.mutations.failed > 0 ? "text-red-400" : ""}>
                {node.mutations.pending} pending{node.mutations.failed > 0 ? ` \u00b7 ${node.mutations.failed} failed` : ""}
              </span>
            } />
          )}
        </DetailGrid>
        {node.recent_errors && node.recent_errors.length > 0 && (
          <Collapsible title="Errors" badge={<Badge variant="destructive" className="ml-2 text-[10px]">{node.recent_errors.length}</Badge>}>
            {node.recent_errors.map((e, i) => (
              <div key={i} className="text-xs py-0.5">
                <span className="text-red-400 font-mono">{e.name}</span>
                <span className="text-zinc-500"> ({e.count}x)</span>
              </div>
            ))}
          </Collapsible>
        )}
      </CardContent>
    </Card>
  );
}

// ── Patroni card ─────────────────────────────────────────────────────────────

function PatroniCard({ sub }: { sub: { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> } }) {
  const d = sub.details;
  const members = d.members as { name: string; role: string; state: string; host: string; lag: number | null; pending_restart: boolean; timeline: number }[] | undefined;
  const history = d.failover_history as unknown[] | undefined;
  const leaderName = String(d.leader ?? "");
  const replicas = members?.filter((m) => m.role !== "leader") ?? [];

  const [showSwitchover, setShowSwitchover] = useState(false);
  const [switchoverTarget, setSwitchoverTarget] = useState("");
  const switchoverMut = usePatroniSwitchover();

  const handleSwitchover = () => {
    if (!leaderName || !switchoverTarget) return;
    switchoverMut.mutate({ leader: leaderName, candidate: switchoverTarget }, {
      onSuccess: () => setShowSwitchover(false),
    });
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><Shield className="h-4 w-4 text-zinc-400" /><CardTitle>Patroni HA</CardTitle></div>
        <div className="flex items-center gap-2">
          {sub.latency_ms != null && <span className="text-xs text-zinc-500 font-mono">{sub.latency_ms}ms</span>}
          <StatusBadge status={sub.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-0">
        <DetailGrid>
          <DetailRow label="Leader" value={String(d.leader ?? "none")} tip="The primary PostgreSQL node accepting writes. Other members replicate from this node." />
          <DetailRow label="Timeline" value={String(d.timeline ?? "\u2014")} tip="Patroni cluster timeline — increments after each failover event." />
          <DetailRow label="Members" value={`${d.member_count ?? 0} total · ${d.replica_count ?? 0} replicas`} tip="Total Patroni cluster members and how many are replicas." />
        </DetailGrid>

        {members && members.length > 0 && (
          <>
            <SectionTitle>Members</SectionTitle>
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-xs py-1">Name</TableHead>
                <TableHead className="text-xs py-1">Host</TableHead>
                <TableHead className="text-xs py-1"><Tip label="Mode" tip="RW = primary (read-write), RO = replica (read-only)." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Role" tip="leader = primary (accepts writes), replica = read-only standby, sync_standby = synchronous replica." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="State" tip="running = healthy, streaming = actively replicating, stopped = not running." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Lag" tip="Replication lag in bytes — how far behind the replica is from the leader." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="TL" tip="Timeline — increments after failover. All members should share the same timeline." /></TableHead>
                <TableHead className="text-xs py-1"><Tip label="Restart" tip="PostgreSQL parameter changes require a restart to take effect." /></TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {members.map((m) => (
                  <TableRow key={m.name}>
                    <TableCell className="text-xs py-1 font-mono">{m.name}</TableCell>
                    <TableCell className="text-xs py-1 font-mono text-zinc-500">{m.host}</TableCell>
                    <TableCell className="text-xs py-1">
                      {m.role === "leader"
                        ? <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-[10px] font-bold">RW</Badge>
                        : <Badge className="bg-blue-500/15 text-blue-400 border-blue-500/30 text-[10px] font-bold">RO</Badge>}
                    </TableCell>
                    <TableCell className="text-xs py-1">
                      <Badge variant={m.role === "leader" ? "success" : "default"}>{m.role}</Badge>
                    </TableCell>
                    <TableCell className="text-xs py-1">
                      <Badge variant={m.state === "running" || m.state === "streaming" ? "success" : "destructive"}>{m.state}</Badge>
                    </TableCell>
                    <TableCell className="text-xs py-1 font-mono">{m.lag != null ? formatBytes(m.lag) : "\u2014"}</TableCell>
                    <TableCell className="text-xs py-1 font-mono">{m.timeline ?? "\u2014"}</TableCell>
                    <TableCell className="text-xs py-1">{m.pending_restart ? <Badge variant="destructive">yes</Badge> : "no"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}

        {/* Switchover */}
        {leaderName && replicas.length > 0 && (
          <div className="mt-3">
            {!showSwitchover ? (
              <Button variant="outline" size="sm" onClick={() => { setSwitchoverTarget(replicas[0]?.name ?? ""); setShowSwitchover(true); }}>
                Switchover
              </Button>
            ) : (
              <div className="flex items-center gap-2 p-3 rounded-md bg-zinc-900 border border-zinc-700">
                <span className="text-xs text-zinc-400">Switchover fra <span className="font-mono text-zinc-200">{leaderName}</span> til</span>
                <select
                  className="text-xs bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-zinc-200 font-mono"
                  value={switchoverTarget}
                  onChange={(e) => setSwitchoverTarget(e.target.value)}
                >
                  {replicas.map((r) => <option key={r.name} value={r.name}>{r.name} ({r.host})</option>)}
                </select>
                <Button variant="destructive" size="sm" onClick={handleSwitchover} disabled={switchoverMut.isPending}>
                  {switchoverMut.isPending ? "Switching..." : "Confirm"}
                </Button>
                <Button variant="outline" size="sm" onClick={() => setShowSwitchover(false)}>Cancel</Button>
                {switchoverMut.isError && <span className="text-xs text-red-400">{String((switchoverMut.error as Error)?.message ?? "Failed")}</span>}
                {switchoverMut.isSuccess && <span className="text-xs text-emerald-400">Switchover initiated</span>}
              </div>
            )}
          </div>
        )}

        {history && history.length > 0 && (
          <>
            <SectionTitle><Tip label="Failover history (last 5)" tip="Recent automatic or manual failover events in the Patroni cluster." /></SectionTitle>
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-xs py-1">Timeline</TableHead>
                <TableHead className="text-xs py-1">LSN</TableHead>
                <TableHead className="text-xs py-1">Reason / New leader</TableHead>
                <TableHead className="text-xs py-1">Timestamp</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {history.map((h: unknown, i: number) => {
                  const arr = Array.isArray(h) ? h : [];
                  return (
                    <TableRow key={i}>
                      <TableCell className="text-xs py-1 font-mono">{arr[0] ?? "\u2014"}</TableCell>
                      <TableCell className="text-xs py-1 font-mono">{arr[1] ?? "\u2014"}</TableCell>
                      <TableCell className="text-xs py-1 font-mono text-zinc-400">{arr[2] ?? "\u2014"}</TableCell>
                      <TableCell className="text-xs py-1 text-zinc-500">{arr[3] ? timeAgo(String(arr[3])) : "\u2014"}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </>
        )}

        {d.error ? <p className="text-xs text-red-400 mt-2">{String(d.error)}</p> : null}
      </CardContent>
    </Card>
  );
}

// ── etcd card ────────────────────────────────────────────────────────────────

function EtcdCard({ sub }: { sub: { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> } }) {
  const d = sub.details;
  const nodes = d.nodes as { name: string; host: string; healthy: boolean; error?: string }[] | undefined;
  const alarms = d.alarms as { member_id: string; alarm: string }[] | undefined;
  const memberDetails = d.members as { id: string; name: string; peer_urls: string[]; client_urls: string[]; is_leader: boolean }[] | undefined;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-2"><Network className="h-4 w-4 text-zinc-400" /><CardTitle>etcd</CardTitle></div>
        <div className="flex items-center gap-2">
          {sub.latency_ms != null && <span className="text-xs text-zinc-500 font-mono">{sub.latency_ms}ms</span>}
          <StatusBadge status={sub.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-0">
        <DetailGrid>
          <DetailRow label="Healthy" value={`${d.healthy_count ?? 0} / ${d.total_nodes ?? 0}`} tip="Number of etcd nodes responding to health checks." />
          <DetailRow label="Members" value={String(d.member_count ?? "\u2014")} tip="Total etcd cluster members registered in the Raft consensus group." />
          <DetailRow label="Leader" value={d.leader_name ? `${d.leader_name} (${d.leader_id})` : String(d.leader_id ?? "none")} tip="The etcd member currently elected as cluster leader. Manages the Raft consensus log." />
          {d.db_size_bytes != null && <DetailRow label="DB size" value={formatBytes(Number(d.db_size_bytes))} tip="etcd database size on disk. Alert threshold: 2 GB (etcd default max: 8 GB)." />}
          {d.version != null && <DetailRow label="Version" value={String(d.version)} />}
          {d.raft_index != null && <DetailRow label="Raft index" value={formatNumber(Number(d.raft_index))} tip="Current Raft log index — monotonically increasing counter of committed entries." />}
          {d.raft_term != null && <DetailRow label="Raft term" value={String(d.raft_term)} tip="Current Raft election term — increments each time a new leader is elected." />}
        </DetailGrid>

        {/* Alarms */}
        {alarms && alarms.length > 0 ? (
          <>
            <SectionTitle>Alarms</SectionTitle>
            {alarms.map((a, i) => (
              <div key={i} className="flex items-center gap-2 text-xs py-0.5">
                <AlertTriangle className="h-3 w-3 text-red-400" />
                <span className="text-red-400 font-semibold">{a.alarm}</span>
                <span className="text-zinc-500">member {a.member_id}</span>
              </div>
            ))}
          </>
        ) : (
          <p className="text-xs text-emerald-400/60 mt-2">No alarms</p>
        )}

        {nodes && nodes.length > 0 && (
          <>
            <SectionTitle>Nodes</SectionTitle>
            {nodes.map((n) => (
              <div key={n.name} className="flex items-center gap-2 text-xs py-0.5">
                <span className={`h-2 w-2 rounded-full ${n.healthy ? "bg-green-500" : "bg-red-500"}`} />
                <span className="text-zinc-300 font-mono">{n.name}</span>
                <span className="text-zinc-500">{n.host}</span>
                {n.error && <span className="text-red-400 truncate">{String(n.error)}</span>}
              </div>
            ))}
          </>
        )}

        {/* Member details with URLs */}
        {memberDetails && memberDetails.length > 0 && (
          <Collapsible title="Member details">
            <Table>
              <TableHeader><TableRow>
                <TableHead className="text-xs py-1">Name</TableHead>
                <TableHead className="text-xs py-1">Role</TableHead>
                <TableHead className="text-xs py-1">Peer URLs</TableHead>
                <TableHead className="text-xs py-1">Client URLs</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {memberDetails.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="text-xs py-1 font-mono">{m.name || m.id}</TableCell>
                    <TableCell className="text-xs py-1">
                      {m.is_leader ? <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-[10px]">leader</Badge> : <span className="text-zinc-500">follower</span>}
                    </TableCell>
                    <TableCell className="text-xs py-1 font-mono text-zinc-500">{m.peer_urls?.join(", ") || "\u2014"}</TableCell>
                    <TableCell className="text-xs py-1 font-mono text-zinc-500">{m.client_urls?.join(", ") || "\u2014"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Collapsible>
        )}

        {d.error ? <p className="text-xs text-red-400 mt-2">{String(d.error)}</p> : null}
      </CardContent>
    </Card>
  );
}

// ── Overview mini-cards ──────────────────────────────────────────────────────

function OverviewMiniCard({ icon: Icon, title, status, lines, onClick }: {
  icon: React.ElementType;
  title: string;
  status: SubsystemStatus;
  lines: string[];
  onClick?: () => void;
}) {
  return (
    <Card className={`cursor-pointer hover:border-zinc-600 transition-colors ${onClick ? "" : ""}`} onClick={onClick}>
      <CardContent className="py-3 px-4">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-1.5">
            <Icon className="h-3.5 w-3.5 text-zinc-500" />
            <span className="text-xs font-semibold text-zinc-300">{title}</span>
          </div>
          <span className={`inline-block h-2 w-2 rounded-full ${statusDotColors[status]}`} />
        </div>
        {lines.map((line, i) => (
          <p key={i} className="text-[11px] text-zinc-500 font-mono leading-relaxed truncate">{line}</p>
        ))}
      </CardContent>
    </Card>
  );
}

// ── Docker Infrastructure tab ───────────────────────────────────────────────

const dockerStatusMap = (s: string): SubsystemStatus =>
  s === "ok" ? "healthy" : s === "degraded" ? "degraded" : s === "unreachable" || s === "stale" ? "critical" : "unknown";

const dockerStatusOrder: Record<string, number> = { unreachable: 0, stale: 1, degraded: 2, unknown: 3, ok: 4 };

function DockerInfraTab() {
  const { data: dockerResp } = useDockerOverview();
  const hosts = dockerResp?.data?.hosts ?? [];
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (!hosts.length) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-2 text-zinc-500">
        <Server className="h-8 w-8" />
        <p className="text-sm">No Docker hosts available</p>
      </div>
    );
  }

  // Sort: problems first, then alphabetical
  const sorted = [...hosts].sort((a, b) => {
    const sa = dockerStatusOrder[a.status] ?? 3;
    const sb = dockerStatusOrder[b.status] ?? 3;
    if (sa !== sb) return sa - sb;
    return a.label.localeCompare(b.label);
  });

  // Aggregate stats
  const totalContainers = hosts.reduce((s, h) => s + (h.container_count ?? 0), 0);
  const totalUnhealthy = hosts.reduce((s, h) => s + (h.unhealthy_count ?? 0), 0);
  const unreachableCount = hosts.filter((h) => h.status === "unreachable" || h.status === "stale").length;

  function toggleExpand(label: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(label) ? next.delete(label) : next.add(label);
      return next;
    });
  }

  return (
    <div className="space-y-3">
      {/* Summary bar */}
      <div className="flex items-center gap-3 text-xs text-zinc-400">
        <span>{hosts.length} hosts</span>
        <span className="text-zinc-600">&middot;</span>
        <span>{totalContainers} containers</span>
        {totalUnhealthy > 0 && (
          <>
            <span className="text-zinc-600">&middot;</span>
            <span className="text-red-400 font-semibold">{totalUnhealthy} unhealthy</span>
          </>
        )}
        {unreachableCount > 0 && (
          <>
            <span className="text-zinc-600">&middot;</span>
            <span className="text-red-400 font-semibold">{unreachableCount} unreachable</span>
          </>
        )}
      </div>

      {/* Host table */}
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8 py-1" />
              <TableHead className="text-xs py-1">Host</TableHead>
              <TableHead className="text-xs py-1">Status</TableHead>
              <TableHead className="text-xs py-1">Containers</TableHead>
              <TableHead className="text-xs py-1">Load</TableHead>
              <TableHead className="text-xs py-1 w-32">Memory</TableHead>
              <TableHead className="text-xs py-1 w-8" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((h) => {
              const isOpen = expanded.has(h.label);
              const info = h.data;
              const hostMem = info?.host;
              const memPct = hostMem?.mem_total_bytes && hostMem.mem_available_bytes != null
                ? Math.round(((hostMem.mem_total_bytes - hostMem.mem_available_bytes) / hostMem.mem_total_bytes) * 100)
                : null;
              const hasProblems = (h.unhealthy_count ?? 0) > 0 || h.error;
              const mapped = dockerStatusMap(h.status);

              return (
                <DockerHostRows
                  key={h.label}
                  host={h}
                  isOpen={isOpen}
                  mapped={mapped}
                  memPct={memPct}
                  hasProblems={!!hasProblems}
                  onToggle={() => toggleExpand(h.label)}
                />
              );
            })}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

function DockerHostRows({
  host: h, isOpen, mapped, memPct, hasProblems, onToggle,
}: {
  host: DockerOverviewHost; isOpen: boolean; mapped: SubsystemStatus;
  memPct: number | null; hasProblems: boolean; onToggle: () => void;
}) {
  const info = h.data;
  const hostInfo = info?.host;
  // Overview API returns containers as DockerContainerStats[] (not counts object)
  const rawContainers = (info as Record<string, unknown> | null)?.containers;
  const containers = Array.isArray(rawContainers) ? rawContainers as DockerContainerStats[] : undefined;

  // Sort containers: unhealthy/restarting first
  const sortedContainers = useMemo(() => {
    if (!Array.isArray(containers)) return [];
    return [...containers].sort((a, b) => {
      const aBad = a.health === "unhealthy" || a.status === "restarting" ? 0 : 1;
      const bBad = b.health === "unhealthy" || b.status === "restarting" ? 0 : 1;
      if (aBad !== bBad) return aBad - bBad;
      return a.name.localeCompare(b.name);
    });
  }, [containers]);

  return (
    <>
      {/* Summary row */}
      <TableRow className="cursor-pointer hover:bg-zinc-800/50" onClick={onToggle}>
        <TableCell className="py-1.5 px-2">
          {isOpen ? <ChevronDown className="h-3.5 w-3.5 text-zinc-500" /> : <ChevronRight className="h-3.5 w-3.5 text-zinc-500" />}
        </TableCell>
        <TableCell className="py-1.5 font-mono text-xs text-zinc-200">{h.label}</TableCell>
        <TableCell className="py-1.5">
          <StatusBadge status={mapped} />
        </TableCell>
        <TableCell className="py-1.5 text-xs font-mono text-zinc-300">
          {h.container_count ?? "—"} / {h.total_containers ?? "—"}
          {(h.unhealthy_count ?? 0) > 0 && (
            <Badge variant="destructive" className="ml-1.5 text-[10px] px-1 py-0">{h.unhealthy_count}</Badge>
          )}
        </TableCell>
        <TableCell className="py-1.5 text-xs font-mono text-zinc-400">
          {hostInfo?.load_avg ? hostInfo.load_avg["1m"] : "—"}
        </TableCell>
        <TableCell className="py-1.5">
          {memPct != null ? (
            <div className="flex items-center gap-2">
              <ProgressBar pct={memPct} className="w-16" />
              <span className="text-xs font-mono text-zinc-400">{memPct}%</span>
            </div>
          ) : (
            <span className="text-xs text-zinc-500">—</span>
          )}
        </TableCell>
        <TableCell className="py-1.5">
          {hasProblems && <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />}
        </TableCell>
      </TableRow>

      {/* Expanded detail row */}
      {isOpen && (
        <TableRow>
          <TableCell colSpan={7} className="bg-zinc-900/50 px-6 py-4">
            {h.status === "unreachable" || h.status === "stale" ? (
              <div className="space-y-2">
                <p className="text-xs text-red-400">{h.error || `Host is ${h.status}`}</p>
                <a
                  href={`/docker-infrastructure?host=${encodeURIComponent(h.label)}`}
                  className="text-xs text-blue-400 hover:text-blue-300"
                  onClick={(e) => e.stopPropagation()}
                >
                  View logs, events & images →
                </a>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Host resources */}
                <div>
                  <SectionTitle>Host Resources</SectionTitle>
                  <DetailGrid>
                    {info?.docker && <DetailRow label="Docker" value={`${info.docker.version} (API ${info.docker.api_version})`} />}
                    {info?.docker && <DetailRow label="OS" value={`${info.docker.os} · ${info.docker.architecture}`} />}
                    {info?.docker && <DetailRow label="CPU" value={`${info.docker.cpus} cores`} />}
                    {hostInfo?.mem_total_bytes != null && hostInfo.mem_available_bytes != null && (
                      <DetailRow label="Memory" value={
                        <div className="space-y-0.5">
                          <span>{formatBytes(hostInfo.mem_total_bytes - hostInfo.mem_available_bytes)} / {formatBytes(hostInfo.mem_total_bytes)}</span>
                          <ProgressBar pct={Math.round(((hostInfo.mem_total_bytes - hostInfo.mem_available_bytes) / hostInfo.mem_total_bytes) * 100)} />
                        </div>
                      } />
                    )}
                    {hostInfo?.disk_total_bytes != null && hostInfo.disk_used_bytes != null && (
                      <DetailRow label="Disk" value={
                        <div className="space-y-0.5">
                          <span>{formatBytes(hostInfo.disk_used_bytes)} / {formatBytes(hostInfo.disk_total_bytes)}</span>
                          <ProgressBar pct={Math.round((hostInfo.disk_used_bytes / hostInfo.disk_total_bytes) * 100)} />
                        </div>
                      } />
                    )}
                    {hostInfo?.load_avg && (
                      <DetailRow label="Load Avg" value={`${hostInfo.load_avg["1m"]} / ${hostInfo.load_avg["5m"]} / ${hostInfo.load_avg["15m"]}`} />
                    )}
                    {hostInfo?.uptime_seconds != null && <DetailRow label="Uptime" value={formatUptime(hostInfo.uptime_seconds)} />}
                    {hostInfo?.swap_total_bytes != null && hostInfo.swap_free_bytes != null && (
                      <DetailRow label="Swap" value={`${formatBytes(hostInfo.swap_total_bytes - hostInfo.swap_free_bytes)} / ${formatBytes(hostInfo.swap_total_bytes)}`} />
                    )}
                  </DetailGrid>
                </div>

                {/* Containers */}
                {sortedContainers.length > 0 && (
                  <div>
                    <SectionTitle>Containers ({sortedContainers.length})</SectionTitle>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-[11px] py-1">Name</TableHead>
                          <TableHead className="text-[11px] py-1">Status</TableHead>
                          <TableHead className="text-[11px] py-1">CPU</TableHead>
                          <TableHead className="text-[11px] py-1">Memory</TableHead>
                          <TableHead className="text-[11px] py-1">Net I/O</TableHead>
                          <TableHead className="text-[11px] py-1">Restarts</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {sortedContainers.map((c) => {
                          const isUnhealthy = c.health === "unhealthy" || c.status !== "running";
                          return (
                            <TableRow key={c.name}>
                              <TableCell className="py-1 text-xs font-mono text-zinc-200">
                                <div className="flex items-center gap-1.5">
                                  <span className={`inline-block h-1.5 w-1.5 rounded-full ${
                                    c.health === "unhealthy" ? "bg-red-400"
                                    : c.status === "running" ? "bg-emerald-400"
                                    : "bg-zinc-500"
                                  }`} />
                                  {c.name}
                                </div>
                              </TableCell>
                              <TableCell className="py-1 text-xs">
                                <span className={isUnhealthy ? "text-red-400" : "text-zinc-400"}>
                                  {c.status}
                                  {c.health && c.health !== "none" && ` · ${c.health}`}
                                </span>
                              </TableCell>
                              <TableCell className="py-1 text-xs font-mono text-zinc-400">
                                {c.cpu_pct != null ? `${c.cpu_pct.toFixed(1)}%` : "—"}
                              </TableCell>
                              <TableCell className="py-1 text-xs font-mono text-zinc-400">
                                {c.mem_usage_bytes != null && c.mem_limit_bytes
                                  ? `${formatBytes(c.mem_usage_bytes)} / ${formatBytes(c.mem_limit_bytes)}`
                                  : c.mem_pct != null ? `${c.mem_pct.toFixed(1)}%` : "—"}
                              </TableCell>
                              <TableCell className="py-1 text-xs font-mono text-zinc-400">
                                {c.net_rx_bytes != null && c.net_tx_bytes != null
                                  ? `↓${formatBytes(c.net_rx_bytes)} ↑${formatBytes(c.net_tx_bytes)}`
                                  : "—"}
                              </TableCell>
                              <TableCell className={`py-1 text-xs font-mono ${c.restart_count > 0 ? "text-amber-400" : "text-zinc-500"}`}>
                                {c.restart_count}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                )}

                {/* Error details */}
                {h.error && (
                  <div className="text-xs text-red-400 mt-2">
                    <span className="font-semibold">Error:</span> {h.error}
                  </div>
                )}

                {/* Link to full Docker Infrastructure page */}
                <div className="pt-2 border-t border-zinc-800 mt-3">
                  <a
                    href={`/docker-infrastructure?host=${encodeURIComponent(h.label)}`}
                    className="text-xs text-blue-400 hover:text-blue-300"
                    onClick={(e) => e.stopPropagation()}
                  >
                    View logs, events & images →
                  </a>
                </div>
              </div>
            )}
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

// ── Tabs ─────────────────────────────────────────────────────────────────────

const TABS = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "postgresql", label: "PostgreSQL", icon: Database },
  { key: "patroni", label: "Patroni HA", icon: Shield },
  { key: "etcd", label: "etcd", icon: Network },
  { key: "clickhouse", label: "ClickHouse", icon: HardDrive },
  { key: "redis", label: "Redis & Scheduler", icon: Zap },
  { key: "collectors", label: "Collectors", icon: Radio },
  { key: "docker", label: "Docker Infrastructure", icon: Server },
] as const;

type TabKey = typeof TABS[number]["key"];

export function SystemHealthPage() {
  const { data, isLoading, refetch, isFetching } = useSystemHealth();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get("tab") as TabKey) || "overview";
  const setTab = (tab: TabKey) => setSearchParams({ tab }, { replace: true });

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

  // Extract per-node ClickHouse data
  const chDetails = (subs.clickhouse?.details ?? {}) as Record<string, unknown>;
  const chNodes = (chDetails.nodes ?? {}) as Record<string, CHNodeData>;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <HeartPulse className="h-6 w-6 text-zinc-400" />
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">System Health</h1>
            <p className="text-sm text-zinc-500">
              {String((data as unknown as Record<string, unknown>).hostname || data.instance_id)} &middot; v{data.version}
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

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-zinc-800 pb-px overflow-x-auto">
        {TABS.map(({ key, label, icon: Icon }) => {
          const isActive = activeTab === key;
          // Get status for badge dot
          let tabStatus: SubsystemStatus = "unknown";
          if (key === "overview") tabStatus = data.overall_status;
          else if (key === "postgresql") tabStatus = (subs.postgresql?.status as SubsystemStatus) ?? "unknown";
          else if (key === "clickhouse") tabStatus = (subs.clickhouse?.status as SubsystemStatus) ?? "unknown";
          else if (key === "redis") {
            const rs = (subs.redis?.status as SubsystemStatus) ?? "unknown";
            const ss = (subs.scheduler?.status as SubsystemStatus) ?? "unknown";
            tabStatus = rs === "critical" || ss === "critical" ? "critical" : rs === "degraded" || ss === "degraded" ? "degraded" : rs === "healthy" && ss === "healthy" ? "healthy" : "unknown";
          }
          else if (key === "patroni") tabStatus = (subs.patroni?.status as SubsystemStatus) ?? "unknown";
          else if (key === "etcd") tabStatus = (subs.etcd?.status as SubsystemStatus) ?? "unknown";
          else if (key === "collectors") tabStatus = (subs.collectors?.status as SubsystemStatus) ?? "unknown";
          else if (key === "docker") tabStatus = (subs.docker?.status as SubsystemStatus) ?? "unknown";
          return (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t whitespace-nowrap cursor-pointer ${
                isActive
                  ? "bg-zinc-800 text-zinc-100 border-b-2 border-blue-500"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
              {key !== "overview" && tabStatus !== "unknown" && (
                <span className={`ml-1 inline-block h-1.5 w-1.5 rounded-full ${statusDotColors[tabStatus]}`} />
              )}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {activeTab === "overview" && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <OverviewMiniCard icon={Database} title="PostgreSQL" status={(subs.postgresql?.status as SubsystemStatus) ?? "unknown"}
            lines={[
              `${(subs.postgresql?.details as Record<string, unknown>)?.db_size_bytes ? formatBytes(Number((subs.postgresql?.details as Record<string, unknown>).db_size_bytes)) : "—"}`,
              `${((subs.postgresql?.details as Record<string, unknown>)?.connections as { active?: number } | undefined)?.active ?? "?"} connections`,
            ]}
            onClick={() => setTab("postgresql")} />
          <OverviewMiniCard icon={HardDrive} title="ClickHouse" status={(subs.clickhouse?.status as SubsystemStatus) ?? "unknown"}
            lines={[
              `${formatBytes(Number(chDetails.total_bytes ?? 0))} \u00b7 ${formatNumber(Number(chDetails.total_rows ?? 0))} rows`,
              `${Object.values(chNodes).filter(n => n.reachable).length}/${Object.keys(chNodes).length || "?"} nodes`,
            ]}
            onClick={() => setTab("clickhouse")} />
          <OverviewMiniCard icon={Zap} title="Redis" status={(subs.redis?.status as SubsystemStatus) ?? "unknown"}
            lines={[
              `${(subs.redis?.details as Record<string, unknown>)?.db_size ?? "?"} keys`,
              `${(subs.redis?.details as Record<string, unknown>)?.connected_clients ?? "?"} clients`,
            ]}
            onClick={() => setTab("redis")} />
          <OverviewMiniCard icon={ArrowDownToLine} title="Ingestion" status={(subs.ingestion?.status as SubsystemStatus) ?? "unknown"}
            lines={[`${(subs.ingestion?.details as Record<string, unknown>)?.total_rows_per_sec ?? 0} rows/s`]}
            onClick={() => setTab("overview")} />
          <OverviewMiniCard icon={Radio} title="Collectors" status={(subs.collectors?.status as SubsystemStatus) ?? "unknown"}
            lines={[
              `${((subs.collectors?.details as Record<string, unknown>)?.by_status as Record<string, number> | undefined)?.ACTIVE ?? 0} active`,
              `${(subs.collectors?.details as Record<string, unknown>)?.total_jobs ?? 0} jobs`,
            ]}
            onClick={() => setTab("collectors")} />
          <OverviewMiniCard icon={Server} title="Docker" status={(subs.docker?.status as SubsystemStatus) ?? "unknown"}
            lines={(() => {
              const dd = subs.docker?.details as Record<string, unknown> | undefined;
              const dhosts = (dd?.hosts ?? []) as { data?: { containers?: { health?: string }[] } }[];
              const uc = dhosts.reduce((s, dh) => s + (Array.isArray(dh.data?.containers) ? dh.data!.containers.filter(c => c.health === "unhealthy").length : 0), 0);
              return [
                `${dhosts.length} hosts`,
                uc > 0 ? `${uc} unhealthy` : "All healthy",
              ];
            })()}
            onClick={() => setTab("docker")} />
        </div>
      )}

      {activeTab === "postgresql" && subs.postgresql && (
        <PostgreSQLCard sub={subs.postgresql as { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> }} />
      )}

      {activeTab === "patroni" && subs.patroni && (
        subs.patroni.status === "unconfigured"
          ? <UnconfiguredCard name="Patroni" message={String(subs.patroni.details?.message ?? "Not configured")} />
          : <PatroniCard sub={subs.patroni as { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> }} />
      )}

      {activeTab === "etcd" && subs.etcd && (
        subs.etcd.status === "unconfigured"
          ? <UnconfiguredCard name="etcd" message={String(subs.etcd.details?.message ?? "Not configured")} />
          : <EtcdCard sub={subs.etcd as { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> }} />
      )}

      {activeTab === "clickhouse" && subs.clickhouse && (
        <div className="space-y-4">
          {/* Per-node cards */}
          {Object.keys(chNodes).length > 0 && (
            <>
              <SectionTitle>Cluster Nodes</SectionTitle>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {Object.values(chNodes).map((node) => (
                  <CHNodeCard key={node.host} node={node} />
                ))}
              </div>
            </>
          )}

          {/* Shared cluster data (existing ClickHouse card) */}
          <ClickHouseCard sub={subs.clickhouse as { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> }} />
        </div>
      )}

      {activeTab === "redis" && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {subs.redis && <RedisCard sub={subs.redis as { status: SubsystemStatus; latency_ms: number | null; details: Record<string, unknown> }} />}
          {subs.scheduler && <SchedulerCard sub={subs.scheduler as { status: SubsystemStatus; details: Record<string, unknown> }} />}
        </div>
      )}

      {activeTab === "collectors" && subs.collectors && (
        <CollectorsSection sub={subs.collectors as { status: SubsystemStatus; details: Record<string, unknown> }} />
      )}

      {activeTab === "docker" && <DockerInfraTab />}
    </div>
  );
}
