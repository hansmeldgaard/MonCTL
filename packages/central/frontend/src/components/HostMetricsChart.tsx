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
import { useHostMetricsHistory } from "@/api/hooks.ts";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Loader2 } from "lucide-react";

type RangeKey = "1h" | "6h" | "24h" | "7d";
type RoleFilter = "all" | "central" | "worker";
type MetricKey = "load_norm" | "mem_pct" | "disk_pct";

const RANGE_SECONDS: Record<RangeKey, number> = {
  "1h": 3600,
  "6h": 6 * 3600,
  "24h": 24 * 3600,
  "7d": 7 * 24 * 3600,
};

const METRIC_LABEL: Record<MetricKey, string> = {
  load_norm: "CPU load (normalised by cores)",
  mem_pct: "Memory used %",
  disk_pct: "Disk used %",
};

// Deterministic colour palette by host label hash so each host keeps
// the same colour across renders without requiring a config table.
function hostColor(label: string): string {
  let h = 0;
  for (let i = 0; i < label.length; i++)
    h = (h * 31 + label.charCodeAt(i)) >>> 0;
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
  ];
  return palette[h % palette.length];
}

/**
 * Per-host CPU load / memory / disk over time. Rows come from the
 * docker-stats sidecar push persisted into host_metrics_history.
 */
export function HostMetricsChart() {
  const [range, setRange] = useState<RangeKey>("24h");
  const [role, setRole] = useState<RoleFilter>("all");
  const [metric, setMetric] = useState<MetricKey>("load_norm");

  const { fromIso, toIso } = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - RANGE_SECONDS[range] * 1000);
    return { fromIso: from.toISOString(), toIso: to.toISOString() };
  }, [range]);

  const q = useHostMetricsHistory({
    from: fromIso,
    to: toIso,
    host_role: role === "all" ? undefined : role,
    limit: 50000,
  });

  const { chartData, hosts } = useMemo(() => {
    if (!q.data) return { chartData: [], hosts: [] as string[] };
    const byTs = new Map<number, Record<string, number>>();
    const hostSet = new Set<string>();
    for (const r of q.data) {
      hostSet.add(r.host_label);
      let value: number;
      if (metric === "load_norm") {
        value = r.cpu_count > 0 ? r.load_1m / r.cpu_count : r.load_1m;
      } else if (metric === "mem_pct") {
        value =
          r.mem_total_bytes > 0
            ? (r.mem_used_bytes / r.mem_total_bytes) * 100
            : 0;
      } else {
        value =
          r.disk_total_bytes > 0
            ? (r.disk_used_bytes / r.disk_total_bytes) * 100
            : 0;
      }
      const ts = new Date(r.timestamp + "Z").getTime();
      const row = byTs.get(ts) ?? ({ ts } as Record<string, number>);
      row[r.host_label] = value;
      byTs.set(ts, row);
    }
    return {
      chartData: [...byTs.values()].sort(
        (a, b) => (a.ts as number) - (b.ts as number),
      ),
      hosts: [...hostSet].sort(),
    };
  }, [q.data, metric]);

  const loading = q.isLoading;
  const empty = !loading && chartData.length === 0;

  const formatValue = (raw: unknown) => {
    const n = Number(Array.isArray(raw) ? raw[0] : (raw ?? 0));
    return metric === "load_norm" ? n.toFixed(2) : `${n.toFixed(0)}%`;
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-zinc-300">
          Host metrics
        </CardTitle>
        <div className="flex items-center gap-2">
          <Select
            value={metric}
            onChange={(e) => setMetric(e.target.value as MetricKey)}
            className="w-56 text-xs"
          >
            <option value="load_norm">{METRIC_LABEL.load_norm}</option>
            <option value="mem_pct">{METRIC_LABEL.mem_pct}</option>
            <option value="disk_pct">{METRIC_LABEL.disk_pct}</option>
          </Select>
          <Select
            value={role}
            onChange={(e) => setRole(e.target.value as RoleFilter)}
            className="w-28 text-xs"
          >
            <option value="all">All hosts</option>
            <option value="central">Central</option>
            <option value="worker">Worker</option>
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
            No host metrics yet for this range. Each docker-stats sidecar push
            writes one row; first data point lands within a minute of startup.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
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
                width={60}
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
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {hosts.map((h) => (
                <Line
                  key={h}
                  type="monotone"
                  dataKey={h}
                  name={h}
                  stroke={hostColor(h)}
                  strokeWidth={2}
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
