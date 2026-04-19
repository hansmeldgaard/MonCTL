import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useContainerMetricsHistory } from "@/api/hooks.ts";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Loader2 } from "lucide-react";
import { formatBytes } from "@/lib/utils.ts";

type RangeKey = "1h" | "6h" | "24h" | "7d";
type MetricKey = "mem_usage_bytes" | "cpu_pct" | "mem_pct";

const RANGE_SECONDS: Record<RangeKey, number> = {
  "1h": 3600,
  "6h": 6 * 3600,
  "24h": 24 * 3600,
  "7d": 7 * 24 * 3600,
};

const METRIC_LABEL: Record<MetricKey, string> = {
  mem_usage_bytes: "Memory RSS",
  cpu_pct: "CPU %",
  mem_pct: "Memory %",
};

function containerColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  const palette = [
    "#3b82f6",
    "#22c55e",
    "#f59e0b",
    "#8b5cf6",
    "#ec4899",
    "#06b6d4",
    "#ef4444",
    "#14b8a6",
    "#f97316",
    "#a855f7",
    "#84cc16",
    "#0ea5e9",
    "#e11d48",
    "#d946ef",
    "#10b981",
    "#f43f5e",
  ];
  return palette[h % palette.length];
}

/**
 * Per-container time-series. Host selector drives the filter; the top-N
 * containers by peak value are graphed so the legend stays readable on a
 * host running 20+ containers. Designed primarily for leak hunts
 * (memory RSS view) but also useful for CPU spikes.
 */
export function ContainerMetricsChart({ hosts }: { hosts: string[] }) {
  const [host, setHost] = useState<string>(hosts[0] ?? "");
  const [metric, setMetric] = useState<MetricKey>("mem_usage_bytes");
  const [range, setRange] = useState<RangeKey>("24h");

  // If the host list changes (e.g. after first paint), default to the first
  const effectiveHost = host || hosts[0] || "";

  const { fromIso, toIso } = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - RANGE_SECONDS[range] * 1000);
    return { fromIso: from.toISOString(), toIso: to.toISOString() };
  }, [range]);

  const q = useContainerMetricsHistory({
    host_label: effectiveHost,
    from: fromIso,
    to: toIso,
    enabled: !!effectiveHost,
  });

  const { chartData, containers } = useMemo(() => {
    if (!q.data || !q.data.length) return { chartData: [], containers: [] };

    // Bucket by timestamp and container name
    const byTs = new Map<number, Record<string, number>>();
    const peakByContainer = new Map<string, number>();

    for (const r of q.data) {
      const value = Number(r[metric] ?? 0);
      peakByContainer.set(
        r.container_name,
        Math.max(peakByContainer.get(r.container_name) ?? 0, value),
      );
      const ts = new Date(r.timestamp + "Z").getTime();
      const row = byTs.get(ts) ?? ({ ts } as Record<string, number>);
      row[r.container_name] = value;
      byTs.set(ts, row);
    }

    // Pick top 12 containers by peak value — keeps the legend tractable
    const topContainers = [...peakByContainer.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12)
      .map(([c]) => c);

    return {
      chartData: [...byTs.values()].sort(
        (a, b) => (a.ts as number) - (b.ts as number),
      ),
      containers: topContainers,
    };
  }, [q.data, metric]);

  const loading = q.isLoading;
  const empty = !loading && chartData.length === 0;

  const formatValue = (raw: unknown): string => {
    const n = Number(Array.isArray(raw) ? raw[0] : (raw ?? 0));
    if (metric === "mem_usage_bytes") return formatBytes(n);
    return `${n.toFixed(1)}%`;
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-zinc-300">
          Container metrics
        </CardTitle>
        <div className="flex items-center gap-2">
          <Select
            value={effectiveHost}
            onChange={(e) => setHost(e.target.value)}
            className="w-36 text-xs"
            disabled={hosts.length === 0}
          >
            {hosts.length === 0 ? (
              <option>No hosts</option>
            ) : (
              hosts.map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))
            )}
          </Select>
          <Select
            value={metric}
            onChange={(e) => setMetric(e.target.value as MetricKey)}
            className="w-36 text-xs"
          >
            <option value="mem_usage_bytes">
              {METRIC_LABEL.mem_usage_bytes}
            </option>
            <option value="cpu_pct">{METRIC_LABEL.cpu_pct}</option>
            <option value="mem_pct">{METRIC_LABEL.mem_pct}</option>
          </Select>
          <Select
            value={range}
            onChange={(e) => setRange(e.target.value as RangeKey)}
            className="w-24 text-xs"
          >
            <option value="1h">1 hour</option>
            <option value="6h">6 hours</option>
            <option value="24h">24 hours</option>
            <option value="7d">7 days</option>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="pt-2">
        {loading ? (
          <div className="flex h-48 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
          </div>
        ) : empty ? (
          <p className="py-12 text-center text-sm text-zinc-500">
            No container metrics yet for {effectiveHost || "this host"}. Each
            docker-stats sidecar push writes one row per running container —
            data starts landing within a minute.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart
              data={chartData}
              margin={{ top: 5, right: 12, left: 0, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis
                dataKey="ts"
                type="number"
                domain={["dataMin", "dataMax"]}
                scale="time"
                tick={{ fontSize: 10, fill: "#a1a1aa" }}
                tickFormatter={(ts) =>
                  new Date(ts).toLocaleString("en-US", {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                  })
                }
              />
              <YAxis
                tick={{ fontSize: 10, fill: "#a1a1aa" }}
                tickFormatter={(v) => formatValue(v)}
                width={70}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#18181b",
                  border: "1px solid #3f3f46",
                  borderRadius: 4,
                  fontSize: 12,
                }}
                labelFormatter={(ts) => new Date(Number(ts)).toLocaleString()}
                formatter={(v) => formatValue(v)}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {containers.map((c) => (
                <Line
                  key={c}
                  type="monotone"
                  dataKey={c}
                  name={c}
                  stroke={containerColor(c)}
                  strokeWidth={1.5}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
