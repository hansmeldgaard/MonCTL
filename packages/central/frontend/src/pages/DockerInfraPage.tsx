import { useState, useEffect, useRef, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Box,
  ClipboardCopy,
  HardDrive,
  Loader2,
  RefreshCw,
  ScrollText,
  Server,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import {
  useDockerOverview,
  useDockerHostStats,
  useDockerHostSystem,
  useDockerContainerLogs,
  useDockerEvents,
  useDockerImages,
} from "@/api/hooks.ts";
import { formatBytes, formatUptime, timeAgo } from "@/lib/utils.ts";
import type {
  DockerSystemInfo,
  DockerEvent,
  DockerImageInfo,
  DockerVolumeInfo,
} from "@/types/api.ts";

// ── Types for stats data ────────────────────────────────────────────────────

interface ContainerStats {
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
  block_read_bytes?: number | null;
  block_write_bytes?: number | null;
  pids?: number | null;
}

type Tab = "containers" | "logs" | "events" | "images" | "system";

const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "containers", label: "Containers", icon: Box },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "events", label: "Events", icon: Zap },
  { id: "images", label: "Images & Volumes", icon: HardDrive },
  { id: "system", label: "System", icon: Server },
];

// ── Main page ───────────────────────────────────────────────────────────────

export function DockerInfraPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const overview = useDockerOverview();
  const hosts = overview.data?.data?.hosts ?? [];

  const selectedHost = searchParams.get("host") || hosts[0]?.label || "";
  const activeTab = (searchParams.get("tab") as Tab) || "containers";
  const initialContainer = searchParams.get("container") || "";

  function setHost(label: string) {
    setSearchParams((p) => { p.set("host", label); return p; });
  }
  function setTab(tab: Tab) {
    setSearchParams((p) => { p.set("tab", tab); return p; });
  }

  // Auto-select first host when data loads
  useEffect(() => {
    if (!searchParams.get("host") && hosts.length > 0) {
      setSearchParams((p) => { p.set("host", hosts[0].label); return p; }, { replace: true });
    }
  }, [hosts.length]);

  const currentHost = hosts.find((h) => h.label === selectedHost);

  if (overview.isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
      </div>
    );
  }

  if (!overview.data?.data?.configured) {
    return (
      <div className="p-6">
        <h1 className="text-xl font-semibold text-zinc-100 mb-4">Docker Infrastructure</h1>
        <p className="text-zinc-400">No Docker stats sidecars configured. Set MONCTL_DOCKER_STATS_HOSTS to enable.</p>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Host sidebar */}
      <div className="w-48 shrink-0 border-r border-zinc-800 p-3 space-y-1">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">Hosts</div>
        {hosts.map((h) => (
          <button
            key={h.label}
            onClick={() => setHost(h.label)}
            className={`flex items-center gap-2 w-full text-left px-2 py-1.5 rounded text-sm transition-colors cursor-pointer ${
              h.label === selectedHost ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200"
            }`}
          >
            <span className={`h-2 w-2 rounded-full shrink-0 ${h.status === "ok" ? "bg-emerald-400" : "bg-red-400"}`} />
            <span className="font-mono text-xs">{h.label}</span>
          </button>
        ))}
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-auto p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-zinc-100">Docker Infrastructure</h1>
          <Button variant="default" size="sm" onClick={() => overview.refetch()}>
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${overview.isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {/* Host summary header */}
        {currentHost && currentHost.status === "ok" && currentHost.data && (
          <HostSummaryHeader system={currentHost.data} />
        )}
        {currentHost && currentHost.status !== "ok" && (
          <Card>
            <CardContent className="py-4">
              <p className="text-red-400 text-sm">Host unreachable: {currentHost.error}</p>
            </CardContent>
          </Card>
        )}

        {/* Tabs */}
        <div className="flex gap-1 border-b border-zinc-800 pb-px">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-t transition-colors cursor-pointer ${
                activeTab === t.id
                  ? "bg-zinc-800 text-zinc-100 border-b-2 border-blue-500"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              <t.icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {selectedHost && currentHost?.status === "ok" && (
          <>
            {activeTab === "containers" && <ContainersTab hostLabel={selectedHost} />}
            {activeTab === "logs" && <LogsTab hostLabel={selectedHost} initialContainer={initialContainer} />}
            {activeTab === "events" && <EventsTab hostLabel={selectedHost} />}
            {activeTab === "images" && <ImagesTab hostLabel={selectedHost} />}
            {activeTab === "system" && <SystemTab hostLabel={selectedHost} />}
          </>
        )}
      </div>
    </div>
  );
}

// ── Host summary header ─────────────────────────────────────────────────────

function HostSummaryHeader({ system }: { system: DockerSystemInfo }) {
  const h = system.host;
  const d = system.docker;
  const c = system.containers;
  return (
    <Card>
      <CardContent className="py-3">
        <div className="flex items-center gap-6 text-xs text-zinc-400 flex-wrap">
          <span className="font-mono">Docker {d.version}</span>
          <span>{d.os}</span>
          <span>Kernel {d.kernel}</span>
          <span>CPUs: {d.cpus}</span>
          {h.mem_total_bytes != null && h.mem_available_bytes != null && (
            <span className="font-mono">
              Mem: {formatBytes(h.mem_total_bytes - h.mem_available_bytes)} / {formatBytes(h.mem_total_bytes)}
            </span>
          )}
          {h.load_avg && (
            <span className="font-mono">Load: {h.load_avg["1m"]} / {h.load_avg["5m"]} / {h.load_avg["15m"]}</span>
          )}
          {h.disk_total_bytes != null && h.disk_used_bytes != null && (
            <span className="font-mono">
              Disk: {formatBytes(h.disk_used_bytes)} / {formatBytes(h.disk_total_bytes)}
            </span>
          )}
          {h.uptime_seconds != null && <span>Up: {formatUptime(h.uptime_seconds)}</span>}
          <span className="font-mono">
            <span className="text-emerald-400">{c.running}</span> running
            {c.stopped > 0 && <span className="text-zinc-500"> / {c.stopped} stopped</span>}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Containers tab ──────────────────────────────────────────────────────────

type ContainerSort = "name" | "status" | "cpu_pct" | "mem_pct" | "restart_count";

function ContainersTab({ hostLabel }: { hostLabel: string }) {
  const stats = useDockerHostStats(hostLabel);
  const [sortBy, setSortBy] = useState<ContainerSort>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [selectedContainer, setSelectedContainer] = useState<string | null>(null);

  const containers: ContainerStats[] = useMemo(() => {
    const raw = (stats.data?.data as Record<string, unknown>)?.containers as ContainerStats[] | undefined;
    if (!raw) return [];
    const sorted = [...raw].sort((a, b) => {
      const aVal = a[sortBy] ?? 0;
      const bVal = b[sortBy] ?? 0;
      if (typeof aVal === "string" && typeof bVal === "string") return sortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      return sortDir === "asc" ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number);
    });
    return sorted;
  }, [stats.data, sortBy, sortDir]);

  function toggleSort(field: ContainerSort) {
    if (sortBy === field) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortBy(field); setSortDir(field === "name" ? "asc" : "desc"); }
  }

  function SortHead({ label, field, className }: { label: string; field: ContainerSort; className?: string }) {
    const active = sortBy === field;
    return (
      <TableHead className={`text-xs py-1 cursor-pointer select-none hover:text-zinc-200 ${className ?? ""}`} onClick={() => toggleSort(field)}>
        <span className="inline-flex items-center gap-1">
          {label}
          {active ? (sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ArrowUpDown className="h-3 w-3 text-zinc-600" />}
        </span>
      </TableHead>
    );
  }

  if (stats.isLoading) return <Loader2 className="h-5 w-5 animate-spin text-zinc-500 mx-auto mt-8" />;

  return (
    <div className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <SortHead label="Container" field="name" />
            <SortHead label="Status" field="status" className="w-20" />
            <SortHead label="CPU" field="cpu_pct" className="w-16 text-right" />
            <SortHead label="Memory" field="mem_pct" className="w-28 text-right" />
            <TableHead className="text-xs py-1 w-20 text-right">Net I/O</TableHead>
            <SortHead label="Restarts" field="restart_count" className="w-16 text-right" />
            <TableHead className="text-xs py-1 w-24 text-right">Uptime</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {containers.map((c) => (
            <TableRow
              key={c.name}
              className={`cursor-pointer ${c.health === "unhealthy" ? "bg-red-500/5" : c.status !== "running" ? "bg-zinc-800/30" : ""} ${selectedContainer === c.name ? "bg-blue-500/10" : "hover:bg-zinc-800/50"}`}
              onClick={() => setSelectedContainer(selectedContainer === c.name ? null : c.name)}
            >
              <TableCell className="py-1 text-xs font-mono">{c.name}</TableCell>
              <TableCell className="py-1 text-xs">
                <span className="flex items-center gap-1.5">
                  <span className={`h-2 w-2 rounded-full ${c.status === "running" ? (c.health === "unhealthy" ? "bg-red-400" : "bg-emerald-400") : "bg-zinc-600"}`} />
                  {c.status}
                </span>
              </TableCell>
              <TableCell className="py-1 text-xs font-mono text-right">{c.cpu_pct != null ? `${c.cpu_pct}%` : "\u2014"}</TableCell>
              <TableCell className="py-1 text-xs font-mono text-right">
                {c.mem_usage_bytes != null ? formatBytes(c.mem_usage_bytes) : "\u2014"}
                {c.mem_pct != null && <span className="text-zinc-600 ml-1">({c.mem_pct}%)</span>}
              </TableCell>
              <TableCell className="py-1 text-xs font-mono text-right">
                {c.net_rx_bytes != null ? `${formatBytes(c.net_rx_bytes)}/${formatBytes(c.net_tx_bytes ?? 0)}` : "\u2014"}
              </TableCell>
              <TableCell className="py-1 text-xs font-mono text-right">
                <span className={c.restart_count > 3 ? "text-red-400" : c.restart_count > 0 ? "text-amber-400" : "text-zinc-600"}>
                  {c.restart_count}
                </span>
              </TableCell>
              <TableCell className="py-1 text-xs font-mono text-right">
                {c.started_at ? timeAgo(c.started_at) : "\u2014"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {/* Inline log viewer */}
      {selectedContainer && (
        <InlineLogViewer hostLabel={hostLabel} container={selectedContainer} />
      )}
    </div>
  );
}

// ── Inline log viewer (used in containers tab) ─────────────────────────────

function InlineLogViewer({ hostLabel, container }: { hostLabel: string; container: string }) {
  const logs = useDockerContainerLogs(hostLabel, container, 100);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs.data]);

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-sm">Logs: {container}</CardTitle>
        {logs.isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-500" />}
      </CardHeader>
      <CardContent>
        <div ref={scrollRef} className="bg-zinc-950 rounded p-3 font-mono text-xs text-zinc-300 max-h-64 overflow-auto whitespace-pre-wrap">
          {logs.data?.data?.lines?.length ? (
            logs.data.data.lines.map((line, i) => <div key={i}>{line}</div>)
          ) : (
            <span className="text-zinc-600">No log lines available</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Logs tab ────────────────────────────────────────────────────────────────

function LogsTab({ hostLabel, initialContainer }: { hostLabel: string; initialContainer: string }) {
  const stats = useDockerHostStats(hostLabel);
  const containers: string[] = useMemo(() => {
    const raw = (stats.data?.data as Record<string, unknown>)?.containers as ContainerStats[] | undefined;
    return raw?.filter((c) => c.status === "running").map((c) => c.name).sort() ?? [];
  }, [stats.data]);

  const [container, setContainer] = useState(initialContainer || "");
  const [tail, setTail] = useState(100);
  const logs = useDockerContainerLogs(hostLabel, container, tail);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-select first container
  useEffect(() => {
    if (!container && containers.length > 0) setContainer(containers[0]);
  }, [containers]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs.data]);

  function copyLogs() {
    const text = logs.data?.data?.lines?.join("\n") ?? "";
    navigator.clipboard.writeText(text);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Select value={container} onChange={(e) => setContainer(e.target.value)} className="w-64">
          <option value="">Select container...</option>
          {containers.map((c) => <option key={c} value={c}>{c}</option>)}
        </Select>
        <Select value={String(tail)} onChange={(e) => setTail(Number(e.target.value))} className="w-24">
          {[50, 100, 200, 500].map((n) => <option key={n} value={n}>{n} lines</option>)}
        </Select>
        <Button variant="default" size="sm" onClick={copyLogs}>
          <ClipboardCopy className="h-3.5 w-3.5 mr-1" />
          Copy
        </Button>
        {logs.isFetching && <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />}
      </div>

      <div ref={scrollRef} className="bg-zinc-950 rounded p-3 font-mono text-xs text-zinc-300 max-h-[600px] overflow-auto whitespace-pre-wrap">
        {logs.data?.data?.lines?.length ? (
          logs.data.data.lines.map((line, i) => <div key={i}>{line}</div>)
        ) : container ? (
          <span className="text-zinc-600">No log lines available</span>
        ) : (
          <span className="text-zinc-600">Select a container to view logs</span>
        )}
      </div>
    </div>
  );
}

// ── Events tab ──────────────────────────────────────────────────────────────

const eventActionColors: Record<string, string> = {
  start: "text-emerald-400",
  die: "text-red-400",
  oom: "text-red-400",
  kill: "text-red-400",
  stop: "text-amber-400",
  destroy: "text-red-400",
  create: "text-blue-400",
  pull: "text-blue-400",
};

function EventsTab({ hostLabel }: { hostLabel: string }) {
  const events = useDockerEvents(hostLabel, 0, 200);
  const [typeFilter, setTypeFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");

  const allEvents: DockerEvent[] = events.data?.data?.events ?? [];
  const filtered = useMemo(() => {
    return allEvents
      .filter((e) => !typeFilter || e.type === typeFilter)
      .filter((e) => !actionFilter || e.action === actionFilter)
      .reverse();
  }, [allEvents, typeFilter, actionFilter]);

  const types = useMemo(() => [...new Set(allEvents.map((e) => e.type))].sort(), [allEvents]);
  const actions = useMemo(() => [...new Set(allEvents.map((e) => e.action))].sort(), [allEvents]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="w-40">
          <option value="">All types</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </Select>
        <Select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)} className="w-40">
          <option value="">All actions</option>
          {actions.map((a) => <option key={a} value={a}>{a}</option>)}
        </Select>
        <span className="text-xs text-zinc-500">{filtered.length} events</span>
        {events.isFetching && <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />}
      </div>

      <div className="space-y-0.5 max-h-[600px] overflow-auto">
        {filtered.map((e, i) => (
          <div key={`${e.time}-${i}`} className="flex items-center gap-3 py-1 px-2 rounded hover:bg-zinc-800/50 text-xs">
            <span className="text-zinc-500 font-mono w-16 shrink-0" title={e.time_iso}>
              {timeAgo(e.time_iso)}
            </span>
            <Badge variant="default" className="text-[10px] py-0 px-1.5">{e.type}</Badge>
            <span className={`font-medium ${eventActionColors[e.action] ?? "text-zinc-400"}`}>{e.action}</span>
            <span className="text-zinc-300 font-mono truncate">{e.actor_name || e.actor_id}</span>
            {e.actor_image && <span className="text-zinc-600 truncate">{e.actor_image}</span>}
            {e.exit_code != null && <span className="text-zinc-500">exit={e.exit_code}</span>}
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="text-zinc-500 text-sm py-4 text-center">No events recorded yet</p>
        )}
      </div>
    </div>
  );
}

// ── Images & Volumes tab ────────────────────────────────────────────────────

function ImagesTab({ hostLabel }: { hostLabel: string }) {
  const images = useDockerImages(hostLabel);
  const data = images.data?.data;

  if (images.isLoading) return <Loader2 className="h-5 w-5 animate-spin text-zinc-500 mx-auto mt-8" />;
  if (!data) return <p className="text-zinc-500 text-sm">Failed to load image data</p>;

  return (
    <div className="space-y-6">
      {/* Space summary */}
      {data.space_summary && (
        <Card>
          <CardContent className="py-3">
            <div className="flex items-center gap-6 text-xs text-zinc-400">
              <span>Images: <span className="text-zinc-200 font-mono">{formatBytes(data.space_summary.images_total_bytes)}</span></span>
              <span>Reclaimable: <span className="text-amber-400 font-mono">{formatBytes(data.space_summary.images_reclaimable_bytes)}</span></span>
              <span>Volumes: <span className="text-zinc-200 font-mono">{formatBytes(data.space_summary.volumes_total_bytes)}</span></span>
              <span>Build cache: <span className="text-zinc-200 font-mono">{formatBytes(data.space_summary.build_cache_bytes)}</span></span>
              {data.dangling_count > 0 && (
                <span className="text-amber-400">{data.dangling_count} dangling images</span>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Images table */}
      <div>
        <h3 className="text-sm font-semibold text-zinc-300 mb-2">Images ({data.image_count})</h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs py-1">Tags</TableHead>
              <TableHead className="text-xs py-1 w-20">ID</TableHead>
              <TableHead className="text-xs py-1 w-24 text-right">Size</TableHead>
              <TableHead className="text-xs py-1 w-32">Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.images.map((img: DockerImageInfo) => (
              <TableRow key={img.id} className={img.dangling ? "bg-amber-500/5" : ""}>
                <TableCell className="py-1 text-xs font-mono">
                  {img.tags.length > 0 ? img.tags.join(", ") : <span className="text-amber-400">&lt;dangling&gt;</span>}
                </TableCell>
                <TableCell className="py-1 text-xs font-mono text-zinc-500">{img.id.replace("sha256:", "").slice(0, 12)}</TableCell>
                <TableCell className="py-1 text-xs font-mono text-right">{formatBytes(img.size_bytes)}</TableCell>
                <TableCell className="py-1 text-xs text-zinc-500">{timeAgo(img.created)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Volumes table */}
      <div>
        <h3 className="text-sm font-semibold text-zinc-300 mb-2">Volumes ({data.volume_count})</h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs py-1">Name</TableHead>
              <TableHead className="text-xs py-1 w-20">Driver</TableHead>
              <TableHead className="text-xs py-1 w-32">Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.volumes.map((vol: DockerVolumeInfo) => (
              <TableRow key={vol.name}>
                <TableCell className="py-1 text-xs font-mono">{vol.name}</TableCell>
                <TableCell className="py-1 text-xs text-zinc-500">{vol.driver}</TableCell>
                <TableCell className="py-1 text-xs text-zinc-500">{timeAgo(vol.created)}</TableCell>
              </TableRow>
            ))}
            {data.volumes.length === 0 && (
              <TableRow><TableCell colSpan={3} className="py-4 text-center text-zinc-500 text-xs">No volumes</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// ── System tab ──────────────────────────────────────────────────────────────

function SystemTab({ hostLabel }: { hostLabel: string }) {
  const system = useDockerHostSystem(hostLabel);
  const data = system.data?.data;

  if (system.isLoading) return <Loader2 className="h-5 w-5 animate-spin text-zinc-500 mx-auto mt-8" />;
  if (!data) return <p className="text-zinc-500 text-sm">Failed to load system info</p>;

  const h = data.host;
  const d = data.docker;
  const memUsed = h.mem_total_bytes != null && h.mem_available_bytes != null ? h.mem_total_bytes - h.mem_available_bytes : null;
  const memPct = h.mem_total_bytes && memUsed != null ? (memUsed / h.mem_total_bytes) * 100 : null;
  const diskPct = h.disk_total_bytes && h.disk_used_bytes != null ? (h.disk_used_bytes / h.disk_total_bytes) * 100 : null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Docker engine info */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2"><Box className="h-4 w-4 text-zinc-400" />Docker Engine</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2">
            <InfoRow label="Version" value={d.version} />
            <InfoRow label="API Version" value={d.api_version} />
            <InfoRow label="Storage Driver" value={d.storage_driver} />
            <InfoRow label="OS" value={d.os} />
            <InfoRow label="Kernel" value={d.kernel} />
            <InfoRow label="Architecture" value={d.architecture} />
          </div>
        </CardContent>
      </Card>

      {/* Host resources */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2"><Server className="h-4 w-4 text-zinc-400" />Host Resources</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2">
            <InfoRow label="CPUs" value={String(h.cpu_count)} />
            {h.load_avg && (
              <InfoRow label="Load Average" value={`${h.load_avg["1m"]} / ${h.load_avg["5m"]} / ${h.load_avg["15m"]}`} />
            )}
            {h.uptime_seconds != null && <InfoRow label="Uptime" value={formatUptime(h.uptime_seconds)} />}
            <InfoRow label="Containers" value={`${data.containers.running} running / ${data.containers.total} total`} />
          </div>
        </CardContent>
      </Card>

      {/* Memory */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Memory</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {memPct != null && (
            <div>
              <div className="flex justify-between text-xs text-zinc-400 mb-0.5">
                <span>Used</span>
                <span className="font-mono">{formatBytes(memUsed!)} / {formatBytes(h.mem_total_bytes!)} ({memPct.toFixed(1)}%)</span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-zinc-800">
                <div className={`h-1.5 rounded-full ${memPct > 90 ? "bg-red-500" : memPct > 70 ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${Math.min(memPct, 100)}%` }} />
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
            {h.mem_free_bytes != null && <InfoRow label="Free" value={formatBytes(h.mem_free_bytes)} />}
            {h.mem_buffers_bytes != null && <InfoRow label="Buffers" value={formatBytes(h.mem_buffers_bytes)} />}
            {h.mem_cached_bytes != null && <InfoRow label="Cached" value={formatBytes(h.mem_cached_bytes)} />}
            {h.swap_total_bytes != null && (
              <InfoRow label="Swap" value={`${formatBytes((h.swap_total_bytes ?? 0) - (h.swap_free_bytes ?? 0))} / ${formatBytes(h.swap_total_bytes)}`} />
            )}
          </div>
        </CardContent>
      </Card>

      {/* Disk */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2"><HardDrive className="h-4 w-4 text-zinc-400" />Disk</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {diskPct != null && (
            <div>
              <div className="flex justify-between text-xs text-zinc-400 mb-0.5">
                <span>Used</span>
                <span className="font-mono">{formatBytes(h.disk_used_bytes!)} / {formatBytes(h.disk_total_bytes!)} ({diskPct.toFixed(1)}%)</span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-zinc-800">
                <div className={`h-1.5 rounded-full ${diskPct > 95 ? "bg-red-500" : diskPct > 80 ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${Math.min(diskPct, 100)}%` }} />
              </div>
            </div>
          )}
          {h.disk_free_bytes != null && (
            <div className="text-xs text-zinc-400">Free: <span className="font-mono text-zinc-300">{formatBytes(h.disk_free_bytes)}</span></div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-zinc-500 leading-none">{label}</span>
      <span className="text-zinc-300 font-mono text-xs leading-snug">{value}</span>
    </div>
  );
}
