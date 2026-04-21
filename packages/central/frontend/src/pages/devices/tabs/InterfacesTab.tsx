import { useState, useEffect, useMemo, useCallback } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  Tag,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { LabelEditor } from "@/components/LabelEditor.tsx";
import { InterfaceToggleCell } from "@/components/InterfaceToggleCell";
import { InterfaceToggleBulkHead } from "@/components/InterfaceToggleBulkHead";
import {
  TimeRangePicker,
  rangeToTimestamps,
} from "@/components/TimeRangePicker.tsx";
import type {
  TimeRangeValue,
  TimeRangePreset,
} from "@/components/TimeRangePicker.tsx";
import {
  MultiInterfaceChart,
  formatTraffic,
  type DataTier,
} from "@/components/InterfaceTrafficChart.tsx";
import type {
  TrafficUnit,
  ChartMetric,
  ChartMode,
} from "@/components/InterfaceTrafficChart.tsx";
import {
  useAvailabilityHistory,
  useBulkUpdateInterfaceSettings,
  useDeviceInterfaceRules,
  useDeviceMonitoring,
  useEvaluateInterfaceRules,
  useInterfaceLatest,
  useInterfaceMetadata,
  useMultiInterfaceHistory,
  useRefreshInterfaceMetadata,
  useSetDeviceInterfaceRules,
  useUpdateInterfacePreferences,
  useUpdateInterfaceSettings,
} from "@/api/hooks.ts";
import type {
  InterfaceMetadataRecord,
  InterfaceRecord,
  InterfaceRule,
} from "@/types/api.ts";
import { useAuth } from "@/hooks/useAuth.tsx";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { timeAgo } from "@/lib/utils.ts";
import { DEFAULT_RANGE } from "../_shared/constants.ts";

function formatSpeed(mbps: number): string {
  if (mbps >= 100000) return `${(mbps / 1000).toFixed(0)} Gbps`;
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(1)} Gbps`;
  return `${mbps} Mbps`;
}

type IfaceSortKey =
  | "status"
  | "if_index"
  | "if_name"
  | "if_alias"
  | "speed"
  | "in_traffic"
  | "out_traffic"
  | "in_errors"
  | "out_errors"
  | "last_polled";

const METRIC_TYPES = ["traffic", "errors", "discards", "status"] as const;

function parseMetrics(poll_metrics: string): Set<string> {
  if (poll_metrics === "all") return new Set(METRIC_TYPES);
  return new Set(poll_metrics.split(",").filter(Boolean));
}

function serializeMetrics(set: Set<string>): string {
  if (METRIC_TYPES.every((m) => set.has(m))) return "all";
  if (set.size === 0) return "status";
  return [...set].join(",");
}

function matchesTextFilter(value: string, filter: string): boolean {
  if (!filter) return true;
  const lower = value.toLowerCase();
  const f = filter.toLowerCase();
  if (f.includes("*") || f.startsWith("^") || f.endsWith("$")) {
    try {
      return new RegExp(f.replace(/\*/g, ".*")).test(lower);
    } catch {
      return lower.includes(f);
    }
  }
  return lower.includes(f);
}

const MAX_CHART_INTERFACES = 8;

type IfaceStatusFilter = "all" | "up" | "down" | "monitored";

export function InterfacesTab({ deviceId }: { deviceId: string }) {
  const { user } = useAuth();
  const { data: interfaces, isLoading } = useInterfaceLatest(deviceId);
  const { data: metadata } = useInterfaceMetadata(deviceId);
  const updateSettings = useUpdateInterfaceSettings();
  const bulkUpdate = useBulkUpdateInterfaceSettings();
  const refreshMeta = useRefreshInterfaceMetadata();
  const [refreshQueuedAt, setRefreshQueuedAt] = useState<number | null>(null);
  const [refreshDone, setRefreshDone] = useState(false);
  const [showRulesPanel, setShowRulesPanel] = useState(false);
  const { data: rules } = useDeviceInterfaceRules(deviceId);

  useEffect(() => {
    if (!refreshQueuedAt || !metadata?.length) return;
    const maxUpdated = Math.max(
      ...metadata.map((m) =>
        m.updated_at ? new Date(m.updated_at).getTime() : 0,
      ),
    );
    if (maxUpdated > refreshQueuedAt) {
      setRefreshDone(true);
      setRefreshQueuedAt(null);
    }
  }, [refreshQueuedAt, metadata]);

  useEffect(() => {
    if (!refreshDone) return;
    const t = setTimeout(() => setRefreshDone(false), 3000);
    return () => clearTimeout(t);
  }, [refreshDone]);

  const updateIfacePrefs = useUpdateInterfacePreferences();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [labelEditIface, setLabelEditIface] =
    useState<InterfaceMetadataRecord | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRangeValue>(() => {
    const pref = user?.iface_time_range;
    if (pref && ["1h", "6h", "24h", "7d", "30d"].includes(pref)) {
      return { type: "preset", preset: pref as TimeRangePreset };
    }
    return DEFAULT_RANGE;
  });
  const [sortKey, setSortKey] = useState<IfaceSortKey>("if_index");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [trafficUnit, setTrafficUnit] = useState<TrafficUnit>(
    (user?.iface_traffic_unit as TrafficUnit) ?? "auto",
  );
  const [chartMetric, setChartMetric] = useState<ChartMetric>(
    (user?.iface_chart_metric as ChartMetric) ?? "traffic",
  );
  const [chartMode, setChartMode] = useState<ChartMode>("overlaid");
  const [statusFilter, setStatusFilter] = useState<IfaceStatusFilter>(() => {
    const saved = user?.iface_status_filter;
    if (
      saved === "unmonitored" ||
      !["all", "up", "down", "monitored"].includes(saved ?? "")
    )
      return "all";
    return (saved as IfaceStatusFilter) ?? "all";
  });
  const [filterName, setFilterName] = useState("");
  const [filterAlias, setFilterAlias] = useState("");
  const [filterOperStatus, setFilterOperStatus] = useState<string>("");
  const [filterSpeed, setFilterSpeed] = useState<string>("");
  const [baseRange, setBaseRange] = useState<TimeRangeValue>(timeRange);
  const [isZoomed, setIsZoomed] = useState(false);
  const handleChartZoom = useCallback(
    (fromMs: number, toMs: number) => {
      if (!isZoomed) setBaseRange(timeRange);
      setTimeRange({
        type: "absolute",
        fromTs: new Date(fromMs).toISOString(),
        toTs: new Date(toMs).toISOString(),
      });
      setIsZoomed(true);
    },
    [isZoomed, timeRange],
  );
  const handleResetZoom = useCallback(() => {
    setTimeRange(baseRange);
    setIsZoomed(false);
  }, [baseRange]);
  const tz = useTimezone();
  const { data: monitoring } = useDeviceMonitoring(deviceId);
  const { fromTs, toTs } = useMemo(
    () => rangeToTimestamps(timeRange),
    [timeRange],
  );

  const metaMap = useMemo(() => {
    const m = new Map<string, InterfaceMetadataRecord>();
    for (const meta of metadata ?? []) {
      m.set(meta.id, {
        ...meta,
        poll_metrics: meta.poll_metrics ?? "all",
        labels: meta.labels ?? {},
      });
    }
    return m;
  }, [metadata]);

  const hasInterfacePoller = !!monitoring?.interface?.app_name;

  const isUnmonitored = useCallback(
    (iface: { interface_id: string }) => {
      if (!hasInterfacePoller) return true;
      const meta = metaMap.get(iface.interface_id);
      return !(meta?.polling_enabled ?? true);
    },
    [hasInterfacePoller, metaMap],
  );

  const validInterfaces = useMemo((): InterfaceRecord[] => {
    const chMap = new Map<string, InterfaceRecord>();
    for (const iface of interfaces ?? []) {
      chMap.set(iface.interface_id, iface);
    }
    return (metadata ?? []).map((meta) => {
      const ch = chMap.get(meta.id);
      if (ch) return ch;
      return {
        interface_id: meta.id,
        if_index: meta.current_if_index,
        if_name: meta.if_name,
        if_alias: meta.if_alias || "",
        if_speed_mbps: meta.if_speed_mbps || 0,
        if_admin_status: "",
        if_oper_status: "unknown",
        in_octets: 0,
        out_octets: 0,
        in_errors: 0,
        out_errors: 0,
        in_discards: 0,
        out_discards: 0,
        in_unicast_pkts: 0,
        out_unicast_pkts: 0,
        in_rate_bps: 0,
        out_rate_bps: 0,
        in_utilization_pct: 0,
        out_utilization_pct: 0,
        poll_interval_sec: 0,
        counter_bits: 64,
        state: 3,
        executed_at: "",
        assignment_id: "",
        collector_id: "",
        app_id: "",
        device_id: meta.device_id,
        collector_name: "",
        device_name: "",
        app_name: "",
        tenant_id: "",
      } satisfies InterfaceRecord;
    });
  }, [interfaces, metadata]);

  const availableOperStatuses = useMemo(
    () => [...new Set(validInterfaces.map((i) => i.if_oper_status))].sort(),
    [validInterfaces],
  );
  const availableSpeeds = useMemo(
    () =>
      [...new Set(validInterfaces.map((i) => i.if_speed_mbps))]
        .filter(Boolean)
        .sort((a, b) => a - b),
    [validInterfaces],
  );

  const filtered = useMemo(() => {
    let data = validInterfaces;
    if (statusFilter === "up")
      data = data.filter((i) => i.if_oper_status === "up" && !isUnmonitored(i));
    else if (statusFilter === "down")
      data = data.filter(
        (i) =>
          i.if_oper_status !== "up" &&
          i.if_oper_status !== "unknown" &&
          !isUnmonitored(i),
      );
    else if (statusFilter === "monitored")
      data = data.filter((i) => !isUnmonitored(i));
    if (filterName)
      data = data.filter((i) => matchesTextFilter(i.if_name, filterName));
    if (filterAlias)
      data = data.filter((i) =>
        matchesTextFilter(i.if_alias || "", filterAlias),
      );
    if (filterOperStatus)
      data = data.filter((i) => i.if_oper_status === filterOperStatus);
    if (filterSpeed)
      data = data.filter((i) => i.if_speed_mbps === Number(filterSpeed));
    return data;
  }, [
    validInterfaces,
    statusFilter,
    filterName,
    filterAlias,
    filterOperStatus,
    filterSpeed,
    isUnmonitored,
  ]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      switch (sortKey) {
        case "status":
          return (
            (a.if_oper_status === "up" ? 0 : 1) -
            (b.if_oper_status === "up" ? 0 : 1)
          );
        case "if_index":
          return (a.if_index - b.if_index) * dir;
        case "if_name":
          return a.if_name.localeCompare(b.if_name) * dir;
        case "if_alias":
          return (a.if_alias || "").localeCompare(b.if_alias || "") * dir;
        case "speed":
          return (a.if_speed_mbps - b.if_speed_mbps) * dir;
        case "in_traffic":
          return (a.in_rate_bps - b.in_rate_bps) * dir;
        case "out_traffic":
          return (a.out_rate_bps - b.out_rate_bps) * dir;
        case "in_errors":
          return (a.in_errors - b.in_errors) * dir;
        case "out_errors":
          return (a.out_errors - b.out_errors) * dir;
        case "last_polled":
          return a.executed_at.localeCompare(b.executed_at) * dir;
        default:
          return 0;
      }
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const toggleSort = (key: IfaceSortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const filteredIds = useMemo(
    () => new Set(filtered.map((i) => i.interface_id)),
    [filtered],
  );
  const allFilteredSelected =
    filtered.length > 0 &&
    filtered.every((i) => selectedIds.has(i.interface_id));
  const someFilteredSelected = filtered.some((i) =>
    selectedIds.has(i.interface_id),
  );
  const activeSelectedCount = [...selectedIds].filter((id) =>
    filteredIds.has(id),
  ).length;

  const toggleSelectAll = () => {
    if (allFilteredSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const i of filtered) next.delete(i.interface_id);
        return next;
      });
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const i of filtered) next.add(i.interface_id);
        return next;
      });
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const chartInterfaceIds = useMemo(() => {
    return [...selectedIds]
      .filter((id) => filteredIds.has(id))
      .slice(0, MAX_CHART_INTERFACES);
  }, [selectedIds, filteredIds]);
  const showMultiChart = chartInterfaceIds.length > 0;
  const tooManySelected = activeSelectedCount > MAX_CHART_INTERFACES;

  const { data: multiHistoryResp } = useMultiInterfaceHistory(
    deviceId,
    fromTs,
    toTs,
    showMultiChart ? chartInterfaceIds : [],
  );
  const multiHistory = multiHistoryResp?.perInterface;
  const multiHistoryTier: DataTier =
    (multiHistoryResp?.tier as DataTier | undefined) ?? "raw";

  const { data: deviceAvailability } = useAvailabilityHistory(
    showMultiChart ? deviceId : undefined,
    fromTs,
    toTs,
    5000,
  );

  const bulkToggleMetric = (metric: string, enable: boolean) => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return;
    for (const id of ids) {
      const meta = metaMap.get(id);
      const current = parseMetrics(meta?.poll_metrics ?? "all");
      if (enable) current.add(metric);
      else current.delete(metric);
      updateSettings.mutate({
        deviceId,
        interfaceId: id,
        data: { poll_metrics: serializeMetrics(current) },
      });
    }
  };

  const selectedHaveMetric = (metric: string): boolean | "mixed" => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map((id) =>
      parseMetrics(metaMap.get(id)?.poll_metrics ?? "all").has(metric),
    );
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const selectedHavePolling = (): boolean | "mixed" => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map((id) => metaMap.get(id)?.polling_enabled ?? true);
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const selectedHaveAlerting = (): boolean | "mixed" => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map((id) => metaMap.get(id)?.alerting_enabled ?? true);
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const bulkTogglePolling = (enable: boolean) => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return;
    bulkUpdate.mutate({
      deviceId,
      data: { interface_ids: ids, polling_enabled: enable },
    });
  };

  const bulkToggleAlerting = (enable: boolean) => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return;
    bulkUpdate.mutate({
      deviceId,
      data: { interface_ids: ids, alerting_enabled: enable },
    });
  };

  const SortHead = ({
    col,
    children,
  }: {
    col: IfaceSortKey;
    children: React.ReactNode;
  }) => (
    <TableHead
      className="cursor-pointer select-none"
      onClick={() => toggleSort(col)}
    >
      <span className="flex items-center gap-1">
        {children}
        {sortKey === col ? (
          sortDir === "asc" ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 text-zinc-600" />
        )}
      </span>
    </TableHead>
  );

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!interfaces?.length && !metadata?.length) {
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center justify-center text-zinc-500">
            <Network className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No interface data collected yet.</p>
            <p className="text-xs text-zinc-600 mt-1">
              Assign an interface poller app to this device to start collecting
              data.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const upCount = validInterfaces.filter(
    (i) => i.if_oper_status === "up" && !isUnmonitored(i),
  ).length;
  const downCount = validInterfaces.filter(
    (i) => i.if_oper_status !== "up" && !isUnmonitored(i),
  ).length;
  const monitoredCount = validInterfaces.filter(
    (i) => !isUnmonitored(i),
  ).length;

  const handleStatusFilter = (next: IfaceStatusFilter) => {
    setStatusFilter(next);
    updateIfacePrefs.mutate({ iface_status_filter: next });
  };
  const handleTrafficUnit = (next: TrafficUnit) => {
    setTrafficUnit(next);
    updateIfacePrefs.mutate({ iface_traffic_unit: next });
  };
  const handleChartMetric = (next: ChartMetric) => {
    setChartMetric(next);
    updateIfacePrefs.mutate({ iface_chart_metric: next });
  };
  const handleTimeRange = (next: TimeRangeValue) => {
    setTimeRange(next);
    setBaseRange(next);
    setIsZoomed(false);
    if (
      next.type === "preset" &&
      ["1h", "6h", "24h", "7d", "30d"].includes(next.preset)
    ) {
      updateIfacePrefs.mutate({
        iface_time_range: next.preset as "1h" | "6h" | "24h" | "7d" | "30d",
      });
    }
  };
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2 text-sm flex-wrap">
          <span className="text-zinc-500">Interfaces:</span>
          {[
            {
              value: "all" as const,
              count: validInterfaces.length,
              label: "all",
              cls: "bg-zinc-700 text-zinc-200 border-zinc-600",
            },
            {
              value: "up" as const,
              count: upCount,
              label: "up",
              cls: "bg-green-900/60 text-green-400 border-green-700",
            },
            {
              value: "down" as const,
              count: downCount,
              label: "down",
              cls: "bg-red-900/60 text-red-400 border-red-700",
            },
            {
              value: "monitored" as const,
              count: monitoredCount,
              label: "monitored",
              cls: "bg-brand-900/60 text-brand-400 border-brand-700",
            },
          ].map(({ value, count, label, cls }) => (
            <button
              key={value}
              onClick={() => handleStatusFilter(value)}
              className={[
                "inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium transition-all",
                cls,
                statusFilter === value
                  ? "ring-2 ring-offset-1 ring-offset-zinc-900 ring-brand-500 opacity-100"
                  : "opacity-55 hover:opacity-80",
              ].join(" ")}
            >
              {count} {label}
            </button>
          ))}
          {activeSelectedCount > 0 && (
            <Badge variant="default">{activeSelectedCount} selected</Badge>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs gap-1"
          disabled={refreshMeta.isPending}
          onClick={() => {
            setRefreshQueuedAt(Date.now());
            setRefreshDone(false);
            refreshMeta.mutate(deviceId);
          }}
        >
          {refreshMeta.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <RefreshCw className="h-3 w-3" />
          )}
          Refresh Metadata
        </Button>
        <Button
          variant={showRulesPanel ? "default" : "outline"}
          size="sm"
          className="h-7 text-xs gap-1"
          onClick={() => setShowRulesPanel((p) => !p)}
        >
          <Settings2 className="h-3 w-3" />
          Interface Rules
          {(rules?.length ?? 0) > 0 && (
            <Badge variant="info" className="ml-0.5 text-[10px] px-1 py-0">
              {rules!.length}
            </Badge>
          )}
        </Button>
        {refreshQueuedAt && !refreshDone && (
          <span className="text-xs text-emerald-400">Queued</span>
        )}
        {refreshDone && (
          <span className="text-xs text-emerald-400">Metadata refreshed</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Select
            value={trafficUnit}
            onChange={(e) => handleTrafficUnit(e.target.value as TrafficUnit)}
            className="h-7 text-xs w-24"
          >
            <option value="auto">Auto</option>
            <option value="kbps">Kbps</option>
            <option value="mbps">Mbps</option>
            <option value="gbps">Gbps</option>
            <option value="pct">% util</option>
          </Select>
          <Select
            value={chartMetric}
            onChange={(e) => handleChartMetric(e.target.value as ChartMetric)}
            className="h-7 text-xs w-28"
          >
            <option value="traffic">Traffic</option>
            <option value="errors">Errors</option>
            <option value="discards">Discards</option>
          </Select>
          <TimeRangePicker
            value={timeRange}
            onChange={handleTimeRange}
            timezone={tz}
          />
          {isZoomed && (
            <button
              onClick={handleResetZoom}
              className="text-xs text-brand-400 hover:text-brand-300 cursor-pointer"
            >
              Reset zoom
            </button>
          )}
        </div>
      </div>

      {showRulesPanel && <InterfaceRulesCard deviceId={deviceId} />}

      {showMultiChart && multiHistory ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-zinc-400 flex items-center gap-2 flex-wrap">
              <span>
                {chartMetric === "traffic"
                  ? "Traffic"
                  : chartMetric === "errors"
                    ? "Errors"
                    : "Discards"}
                {" \u2014 "}
                {chartInterfaceIds.length} interface
                {chartInterfaceIds.length > 1 ? "s" : ""}
              </span>
              <div className="ml-auto flex items-center gap-2">
                <div className="flex items-center gap-0.5 border border-zinc-700 rounded px-0.5">
                  <button
                    onClick={() => setChartMode("overlaid")}
                    className={`px-1.5 py-0.5 text-xs rounded ${chartMode === "overlaid" ? "bg-zinc-700 text-zinc-200" : "text-zinc-500"}`}
                  >
                    Overlay
                  </button>
                  <button
                    onClick={() => setChartMode("stacked")}
                    className={`px-1.5 py-0.5 text-xs rounded ${chartMode === "stacked" ? "bg-zinc-700 text-zinc-200" : "text-zinc-500"}`}
                  >
                    Stacked
                  </button>
                </div>
                <button
                  onClick={() => setSelectedIds(new Set())}
                  className="text-zinc-600 hover:text-zinc-300"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MultiInterfaceChart
              interfaceIds={chartInterfaceIds}
              interfaceNames={chartInterfaceIds.map(
                (id) =>
                  interfaces?.find((i) => i.interface_id === id)?.if_name ?? id,
              )}
              historyPerInterface={multiHistory}
              metric={chartMetric}
              unit={trafficUnit}
              mode={chartMode}
              tier={multiHistoryTier}
              deviceAvailability={deviceAvailability}
              timezone={tz}
              onZoom={handleChartZoom}
            />
          </CardContent>
        </Card>
      ) : tooManySelected ? (
        <Card>
          <CardContent className="py-3">
            <p className="text-sm text-zinc-400 text-center">
              Select up to {MAX_CHART_INTERFACES} interfaces to show the chart.
              Currently {activeSelectedCount} selected.
            </p>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardContent className="pt-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead
                  className="w-10"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    checked={allFilteredSelected}
                    ref={(el) => {
                      if (el)
                        el.indeterminate =
                          !allFilteredSelected && someFilteredSelected;
                    }}
                    onChange={toggleSelectAll}
                    className="accent-brand-500 cursor-pointer"
                  />
                </TableHead>
                <SortHead col="status">Status</SortHead>
                <SortHead col="if_index">Index</SortHead>
                <SortHead col="if_name">Name</SortHead>
                <SortHead col="if_alias">Alias</SortHead>
                <SortHead col="speed">Speed</SortHead>
                <SortHead col="in_traffic">In Traffic</SortHead>
                <SortHead col="out_traffic">Out Traffic</SortHead>
                <SortHead col="in_errors">In Err (total)</SortHead>
                <SortHead col="out_errors">Out Err (total)</SortHead>
                <SortHead col="last_polled">Last Polled</SortHead>
                <TableHead>Labels</TableHead>
                <InterfaceToggleBulkHead
                  activeSelectedCount={activeSelectedCount}
                  state={{
                    polling: selectedHavePolling(),
                    alerting: selectedHaveAlerting(),
                    traffic: selectedHaveMetric("traffic"),
                    errors: selectedHaveMetric("errors"),
                    discards: selectedHaveMetric("discards"),
                    status: selectedHaveMetric("status"),
                  }}
                  onTogglePolling={bulkTogglePolling}
                  onToggleAlerting={bulkToggleAlerting}
                  onToggleMetric={(metric, enable) =>
                    bulkToggleMetric(metric, enable)
                  }
                />
              </TableRow>
              <TableRow className="bg-zinc-900/50">
                <TableCell />
                <TableCell>
                  {availableOperStatuses.length > 1 && (
                    <Select
                      value={filterOperStatus}
                      onChange={(e) => setFilterOperStatus(e.target.value)}
                      className="h-6 text-[10px] w-full"
                    >
                      <option value="">All</option>
                      {availableOperStatuses.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </Select>
                  )}
                </TableCell>
                <TableCell />
                <TableCell>
                  <ClearableInput
                    placeholder="Filter..."
                    value={filterName}
                    onChange={(e) => setFilterName(e.target.value)}
                    onClear={() => setFilterName("")}
                    className="h-6 text-[10px]"
                  />
                </TableCell>
                <TableCell>
                  <ClearableInput
                    placeholder="Filter..."
                    value={filterAlias}
                    onChange={(e) => setFilterAlias(e.target.value)}
                    onClear={() => setFilterAlias("")}
                    className="h-6 text-[10px]"
                  />
                </TableCell>
                <TableCell>
                  {availableSpeeds.length > 1 && (
                    <Select
                      value={filterSpeed}
                      onChange={(e) => setFilterSpeed(e.target.value)}
                      className="h-6 text-[10px] w-full"
                    >
                      <option value="">All</option>
                      {availableSpeeds.map((s) => (
                        <option key={s} value={String(s)}>
                          {formatSpeed(s)}
                        </option>
                      ))}
                    </Select>
                  )}
                </TableCell>
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((iface) => {
                const meta = metaMap.get(iface.interface_id);
                const pollingOn = meta?.polling_enabled ?? true;
                const alertingOn = meta?.alerting_enabled ?? true;
                const metrics = parseMetrics(meta?.poll_metrics ?? "all");
                const isSelected = selectedIds.has(iface.interface_id);
                const unmonitored = isUnmonitored(iface);

                const toggleMetric = (metric: string) => {
                  const next = new Set(metrics);
                  if (next.has(metric)) next.delete(metric);
                  else next.add(metric);
                  updateSettings.mutate({
                    deviceId,
                    interfaceId: iface.interface_id,
                    data: { poll_metrics: serializeMetrics(next) },
                  });
                };

                return (
                  <TableRow
                    key={iface.interface_id}
                    className={`cursor-pointer transition-colors ${isSelected ? "bg-zinc-800/70" : "hover:bg-zinc-800/50"} ${unmonitored ? "opacity-40" : ""}`}
                    onClick={() => toggleSelect(iface.interface_id)}
                  >
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(iface.interface_id)}
                        className="accent-brand-500 cursor-pointer"
                      />
                    </TableCell>
                    <TableCell>
                      <div
                        className={`h-2.5 w-2.5 rounded-full ${iface.if_oper_status === "up" ? "bg-emerald-500" : iface.if_oper_status === "down" ? "bg-red-500" : "bg-zinc-600"}`}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-500">
                      {iface.if_index}
                    </TableCell>
                    <TableCell className="font-medium text-zinc-100">
                      <span className="flex items-center gap-1.5">
                        {iface.if_name}
                        {iface.counter_bits === 32 && (
                          <span
                            className="inline-flex items-center rounded px-1 py-0.5 text-[10px] font-medium leading-none bg-amber-500/15 text-amber-400 border border-amber-500/30"
                            title="32-bit SNMP counters — may wrap on high-speed links"
                          >
                            32-bit
                          </span>
                        )}
                      </span>
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {iface.if_alias || "\u2014"}
                    </TableCell>
                    <TableCell className="text-zinc-300 text-sm">
                      {formatSpeed(iface.if_speed_mbps)}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-cyan-400">
                      {iface.in_rate_bps > 0
                        ? formatTraffic(
                            iface.in_rate_bps,
                            trafficUnit,
                            iface.if_speed_mbps,
                          )
                        : "\u2014"}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-indigo-400">
                      {iface.out_rate_bps > 0
                        ? formatTraffic(
                            iface.out_rate_bps,
                            trafficUnit,
                            iface.if_speed_mbps,
                          )
                        : "\u2014"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      <span
                        className={
                          iface.in_errors > 0
                            ? "text-amber-400"
                            : "text-zinc-600"
                        }
                        title="Cumulative error counter since device boot — see Errors chart for rate (err/s)"
                      >
                        {iface.in_errors.toLocaleString()}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      <span
                        className={
                          iface.out_errors > 0
                            ? "text-amber-400"
                            : "text-zinc-600"
                        }
                        title="Cumulative error counter since device boot — see Errors chart for rate (err/s)"
                      >
                        {iface.out_errors.toLocaleString()}
                      </span>
                    </TableCell>
                    <TableCell className="text-zinc-500 text-xs">
                      {iface.executed_at ? timeAgo(iface.executed_at) : "—"}
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <InterfaceLabelsCell
                        labels={meta?.labels ?? {}}
                        onClick={() => meta && setLabelEditIface(meta)}
                        disabled={!meta}
                      />
                    </TableCell>
                    <TableCell
                      className="text-center"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center gap-1 justify-center">
                        <InterfaceToggleCell
                          state={{
                            polling_enabled: pollingOn,
                            alerting_enabled: alertingOn,
                            traffic: metrics.has("traffic"),
                            errors: metrics.has("errors"),
                            discards: metrics.has("discards"),
                            status: metrics.has("status"),
                          }}
                          onTogglePolling={() =>
                            updateSettings.mutate({
                              deviceId,
                              interfaceId: iface.interface_id,
                              data: { polling_enabled: !pollingOn },
                            })
                          }
                          onToggleAlerting={() =>
                            updateSettings.mutate({
                              deviceId,
                              interfaceId: iface.interface_id,
                              data: { alerting_enabled: !alertingOn },
                            })
                          }
                          onToggleMetric={toggleMetric}
                        />
                        {meta?.rules_managed && (
                          <span
                            className="text-[9px] font-bold text-brand-400 leading-none"
                            title="Managed by interface rule"
                          >
                            R
                          </span>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
              {sorted.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={13}
                    className="text-center py-8 text-zinc-500 text-sm"
                  >
                    {statusFilter === "monitored"
                      ? "No monitored interfaces."
                      : statusFilter === "up"
                        ? "No interfaces are currently up."
                        : statusFilter === "down"
                          ? "No interfaces are currently down."
                          : "No interfaces match your filters."}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {labelEditIface && (
        <InterfaceLabelsDialog
          deviceId={deviceId}
          iface={labelEditIface}
          onClose={() => setLabelEditIface(null)}
        />
      )}
    </div>
  );
}

function InterfaceLabelsCell({
  labels,
  onClick,
  disabled,
}: {
  labels: Record<string, string>;
  onClick: () => void;
  disabled: boolean;
}) {
  const entries = Object.entries(labels);
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs transition-colors ${
        disabled
          ? "text-zinc-700 cursor-not-allowed"
          : entries.length > 0
            ? "text-zinc-300 hover:bg-zinc-800"
            : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800"
      }`}
      title={
        entries.length > 0
          ? entries.map(([k, v]) => `${k}=${v}`).join("\n")
          : disabled
            ? "Refresh interface metadata to enable labels"
            : "Add labels"
      }
    >
      <Tag className="h-3 w-3" />
      {entries.length > 0 ? (
        <span className="text-[10px] font-medium">{entries.length}</span>
      ) : (
        <span className="text-[10px]">—</span>
      )}
    </button>
  );
}

function InterfaceLabelsDialog({
  deviceId,
  iface,
  onClose,
}: {
  deviceId: string;
  iface: InterfaceMetadataRecord;
  onClose: () => void;
}) {
  const [labels, setLabels] = useState<Record<string, string>>(iface.labels);
  const update = useUpdateInterfaceSettings();

  async function handleSave() {
    await update.mutateAsync({
      deviceId,
      interfaceId: iface.id,
      data: { labels },
    });
    onClose();
  }

  return (
    <Dialog open onClose={onClose} title={`Labels — ${iface.if_name}`}>
      <div className="space-y-3">
        <div className="text-xs text-zinc-500">
          Tag this interface with key/value labels. Same format as device labels
          — keys auto-register for reuse.
        </div>
        <LabelEditor
          labels={labels}
          onChange={setLabels}
          disabled={update.isPending}
        />
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={update.isPending}>
          Cancel
        </Button>
        <Button onClick={handleSave} disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

const MATCH_TYPE_OPTIONS = [
  { value: "glob", label: "Glob" },
  { value: "regex", label: "Regex" },
  { value: "exact", label: "Exact" },
];
const NUMERIC_OP_OPTIONS = [
  { value: "eq", label: "=" },
  { value: "gt", label: ">" },
  { value: "lt", label: "<" },
  { value: "gte", label: "≥" },
  { value: "lte", label: "≤" },
];
const METRICS_OPTIONS = [
  { value: "all", label: "All metrics" },
  { value: "none", label: "None" },
  { value: "traffic,status", label: "Traffic + Status" },
  { value: "traffic", label: "Traffic only" },
  { value: "traffic,errors", label: "Traffic + Errors" },
  { value: "traffic,errors,discards,status", label: "All (explicit)" },
];

function emptyRule(): InterfaceRule {
  return {
    name: "",
    match: { if_alias: { pattern: "*", type: "glob" } },
    settings: {
      polling_enabled: true,
      alerting_enabled: true,
      poll_metrics: "all",
    },
    priority: 10,
  };
}

function InterfaceRulesCard({ deviceId }: { deviceId: string }) {
  const { data: rules } = useDeviceInterfaceRules(deviceId);
  const setRules = useSetDeviceInterfaceRules();
  const evaluate = useEvaluateInterfaceRules();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<InterfaceRule[]>([]);
  const [evalResult, setEvalResult] = useState<{
    matched: number;
    changed: number;
    total: number;
  } | null>(null);

  const startEdit = () => {
    const base: InterfaceRule[] =
      rules && rules.length > 0
        ? JSON.parse(JSON.stringify(rules))
        : [emptyRule()];
    const normalized = base.map((r) => ({
      ...r,
      settings: {
        polling_enabled: r.settings.polling_enabled ?? true,
        alerting_enabled: r.settings.alerting_enabled ?? true,
        poll_metrics: r.settings.poll_metrics ?? "all",
      },
    }));
    setDraft(normalized);
    setEditing(true);
    setEvalResult(null);
  };
  const cancel = () => {
    setEditing(false);
    setEvalResult(null);
  };

  const save = () => {
    setRules.mutate(
      { deviceId, data: { interface_rules: draft, apply_now: false } },
      {
        onSuccess: () => setEditing(false),
      },
    );
  };

  const runEvaluate = (force: boolean) => {
    evaluate.mutate(
      { deviceId, force },
      {
        onSuccess: (res) => {
          const d = (
            res as { data: { matched: number; changed: number; total: number } }
          ).data;
          setEvalResult(d);
        },
      },
    );
  };

  const addRule = () => setDraft([...draft, emptyRule()]);
  const removeRule = (i: number) =>
    setDraft(draft.filter((_, idx) => idx !== i));
  const updateRule = (i: number, rule: InterfaceRule) => {
    const next = [...draft];
    next[i] = rule;
    setDraft(next);
  };

  const hasRules = (rules?.length ?? 0) > 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-zinc-400 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Interface Rules
            {hasRules && !editing && (
              <Badge variant="info">
                {rules!.length} rule{rules!.length !== 1 ? "s" : ""}
              </Badge>
            )}
          </span>
          <div className="flex items-center gap-2">
            {!editing && hasRules && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs gap-1"
                  disabled={evaluate.isPending}
                  onClick={() => runEvaluate(false)}
                >
                  {evaluate.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Zap className="h-3 w-3" />
                  )}
                  Evaluate
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs gap-1"
                  disabled={evaluate.isPending}
                  onClick={() => runEvaluate(true)}
                >
                  Force
                </Button>
              </>
            )}
            <Button
              variant={editing ? "secondary" : "outline"}
              size="sm"
              className="h-7 text-xs gap-1"
              onClick={editing ? cancel : startEdit}
            >
              {editing ? (
                <>
                  <X className="h-3 w-3" /> Cancel
                </>
              ) : (
                <>
                  <Pencil className="h-3 w-3" />{" "}
                  {hasRules ? "Edit" : "Add Rules"}
                </>
              )}
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {evalResult && (
          <div className="mb-3 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            Evaluated {evalResult.total} interfaces — {evalResult.matched}{" "}
            matched, {evalResult.changed} changed.
          </div>
        )}

        {!editing && !hasRules && (
          <p className="text-sm text-zinc-500">
            No interface rules configured. Rules auto-configure interface
            monitoring based on name, alias, or speed.
          </p>
        )}

        {!editing && hasRules && (
          <div className="space-y-1.5">
            {rules!.map((rule, i) => (
              <div
                key={i}
                className="flex items-center gap-3 rounded-md border border-zinc-800 px-3 py-2"
              >
                <span className="text-xs font-medium text-zinc-200 min-w-0 truncate">
                  {rule.name}
                </span>
                <span className="ml-auto text-[10px] text-zinc-500 shrink-0">
                  prio {rule.priority}
                </span>
                <div className="flex items-center gap-1.5">
                  {Object.entries(rule.match).map(([field, spec]) => (
                    <Badge
                      key={field}
                      variant="default"
                      className="text-[10px]"
                    >
                      {field}:{" "}
                      {(
                        spec as {
                          pattern?: string;
                          op?: string;
                          value?: number;
                        }
                      ).pattern ??
                        `${(spec as { op: string }).op} ${(spec as { value: number }).value}`}
                    </Badge>
                  ))}
                </div>
                <div className="flex items-center gap-1">
                  {rule.settings.polling_enabled != null && (
                    <span
                      className={`h-2 w-2 rounded-full ${rule.settings.polling_enabled ? "bg-brand-500" : "bg-zinc-700"}`}
                      title={`Poll: ${rule.settings.polling_enabled ? "on" : "off"}`}
                    />
                  )}
                  {rule.settings.alerting_enabled != null && (
                    <span
                      className={`h-2 w-2 rounded-full ${rule.settings.alerting_enabled ? "bg-amber-500" : "bg-zinc-700"}`}
                      title={`Alert: ${rule.settings.alerting_enabled ? "on" : "off"}`}
                    />
                  )}
                  {rule.settings.poll_metrics && (
                    <span className="text-[10px] text-zinc-500">
                      {rule.settings.poll_metrics}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {editing && (
          <div className="space-y-3">
            {draft.map((rule, i) => (
              <InterfaceRuleEditor
                key={i}
                rule={rule}
                onChange={(r) => updateRule(i, r)}
                onRemove={() => removeRule(i)}
              />
            ))}
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="gap-1"
                onClick={addRule}
              >
                <Plus className="h-3.5 w-3.5" /> Add Rule
              </Button>
              <Button
                type="button"
                size="sm"
                className="gap-1"
                onClick={save}
                disabled={setRules.isPending}
              >
                {setRules.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                Save Rules
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function InterfaceRuleEditor({
  rule,
  onChange,
  onRemove,
}: {
  rule: InterfaceRule;
  onChange: (r: InterfaceRule) => void;
  onRemove: () => void;
}) {
  const matchFields = Object.keys(rule.match);
  const hasSpeed = "if_speed_mbps" in rule.match;

  const updateMatch = (field: string, spec: Record<string, unknown>) => {
    onChange({ ...rule, match: { ...rule.match, [field]: spec } });
  };

  const removeMatchField = (field: string) => {
    const next = { ...rule.match };
    delete (next as Record<string, unknown>)[field];
    onChange({ ...rule, match: next });
  };

  const addMatchField = (field: string) => {
    if (field === "if_speed_mbps") {
      onChange({
        ...rule,
        match: { ...rule.match, if_speed_mbps: { op: "gte", value: 1000 } },
      });
    } else {
      onChange({
        ...rule,
        match: { ...rule.match, [field]: { pattern: "*", type: "glob" } },
      });
    }
  };

  return (
    <div className="rounded-md border border-zinc-700 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Input
          value={rule.name}
          onChange={(e) => onChange({ ...rule, name: e.target.value })}
          placeholder="Rule name"
          className="h-7 text-xs flex-1"
        />
        <div className="flex items-center gap-1">
          <label className="text-[10px] text-zinc-500">Priority</label>
          <Input
            type="number"
            value={rule.priority}
            onChange={(e) =>
              onChange({ ...rule, priority: parseInt(e.target.value, 10) || 0 })
            }
            className="h-7 text-xs w-16"
            min={0}
          />
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="space-y-1.5">
        <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
          Match (all must match)
        </span>
        {matchFields.map((field) => {
          const spec = (rule.match as Record<string, Record<string, unknown>>)[
            field
          ];
          if (field === "if_speed_mbps") {
            return (
              <div key={field} className="flex items-center gap-1.5">
                <span className="text-xs text-zinc-400 w-24 shrink-0">
                  {field}
                </span>
                <Select
                  value={String(spec.op ?? "gte")}
                  onChange={(e) =>
                    updateMatch(field, { ...spec, op: e.target.value })
                  }
                  className="h-7 text-xs w-16"
                >
                  {NUMERIC_OP_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
                <Input
                  type="number"
                  value={(spec.value as number) ?? 0}
                  onChange={(e) =>
                    updateMatch(field, {
                      ...spec,
                      value: parseInt(e.target.value, 10) || 0,
                    })
                  }
                  className="h-7 text-xs w-24"
                />
                <span className="text-[10px] text-zinc-600">Mbps</span>
                <button
                  type="button"
                  onClick={() => removeMatchField(field)}
                  className="text-zinc-600 hover:text-red-400 cursor-pointer"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            );
          }
          return (
            <div key={field} className="flex items-center gap-1.5">
              <span className="text-xs text-zinc-400 w-24 shrink-0">
                {field}
              </span>
              <Select
                value={String(spec.type ?? "glob")}
                onChange={(e) =>
                  updateMatch(field, { ...spec, type: e.target.value })
                }
                className="h-7 text-xs w-20"
              >
                {MATCH_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
              <Input
                value={String(spec.pattern ?? "")}
                onChange={(e) =>
                  updateMatch(field, { ...spec, pattern: e.target.value })
                }
                placeholder="Pattern..."
                className="h-7 text-xs flex-1"
              />
              <button
                type="button"
                onClick={() => removeMatchField(field)}
                className="text-zinc-600 hover:text-red-400 cursor-pointer"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          );
        })}
        <div className="flex items-center gap-1">
          {["if_alias", "if_name", "if_descr"]
            .filter((f) => !(f in rule.match))
            .map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => addMatchField(f)}
                className="text-[10px] text-zinc-600 hover:text-brand-400 border border-zinc-800 hover:border-brand-500/30 rounded px-1.5 py-0.5 cursor-pointer transition-colors"
              >
                + {f}
              </button>
            ))}
          {!hasSpeed && (
            <button
              type="button"
              onClick={() => addMatchField("if_speed_mbps")}
              className="text-[10px] text-zinc-600 hover:text-brand-400 border border-zinc-800 hover:border-brand-500/30 rounded px-1.5 py-0.5 cursor-pointer transition-colors"
            >
              + if_speed_mbps
            </button>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
          Settings
        </span>
        <div className="flex items-center gap-4 flex-wrap">
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={rule.settings.polling_enabled ?? true}
              onChange={(e) =>
                onChange({
                  ...rule,
                  settings: {
                    ...rule.settings,
                    polling_enabled: e.target.checked,
                  },
                })
              }
              className="accent-brand-500"
            />
            <span className="text-zinc-300">Polling</span>
          </label>
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={rule.settings.alerting_enabled ?? true}
              onChange={(e) =>
                onChange({
                  ...rule,
                  settings: {
                    ...rule.settings,
                    alerting_enabled: e.target.checked,
                  },
                })
              }
              className="accent-amber-500"
            />
            <span className="text-zinc-300">Alerting</span>
          </label>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-zinc-400">Metrics:</span>
            <Select
              value={rule.settings.poll_metrics ?? "all"}
              onChange={(e) =>
                onChange({
                  ...rule,
                  settings: { ...rule.settings, poll_metrics: e.target.value },
                })
              }
              className="h-7 text-xs w-44"
            >
              {METRICS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </div>
    </div>
  );
}
