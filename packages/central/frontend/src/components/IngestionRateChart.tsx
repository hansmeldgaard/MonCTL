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
import { useIngestionRateHistory } from "@/api/hooks.ts";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Loader2 } from "lucide-react";

type RangeKey = "24h" | "7d" | "30d";

const RANGE_SECONDS: Record<RangeKey, number> = {
  "24h": 24 * 3600,
  "7d": 7 * 24 * 3600,
  "30d": 30 * 24 * 3600,
};

// Matches SchedulerRunner._INGESTION_TABLES — order drives default legend order.
const TABLES = [
  "availability_latency",
  "performance",
  "interface",
  "config",
  "logs",
  "events",
  "alert_log",
] as const;

const COLORS: Record<string, string> = {
  availability_latency: "#3b82f6",
  performance: "#22c55e",
  interface: "#f59e0b",
  config: "#8b5cf6",
  logs: "#ec4899",
  events: "#06b6d4",
  alert_log: "#ef4444",
};

/**
 * Rows/s per ingestion table over the selected range. Points are 5-min
 * samples from SchedulerRunner._sample_ingestion_rates.
 */
export function IngestionRateChart() {
  const [range, setRange] = useState<RangeKey>("7d");

  const { fromIso, toIso } = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - RANGE_SECONDS[range] * 1000);
    return { fromIso: from.toISOString(), toIso: to.toISOString() };
  }, [range]);

  const q = useIngestionRateHistory({ from: fromIso, to: toIso, limit: 50000 });

  const chartData = useMemo(() => {
    if (!q.data) return [];
    const byTs = new Map<number, Record<string, number>>();
    for (const r of q.data) {
      const ts = new Date(r.timestamp + "Z").getTime();
      const row = byTs.get(ts) ?? ({ ts } as Record<string, number>);
      row[r.table_name] = r.rows_per_second;
      byTs.set(ts, row);
    }
    return [...byTs.values()].sort(
      (a, b) => (a.ts as number) - (b.ts as number),
    );
  }, [q.data]);

  const visibleTables = useMemo(() => {
    if (!chartData.length) return [];
    // Only show tables that actually appeared in the data — keeps the
    // legend clean when some tables have zero activity.
    const seen = new Set<string>();
    for (const row of chartData) {
      for (const k of Object.keys(row)) {
        if (k !== "ts" && row[k] != null) seen.add(k);
      }
    }
    return TABLES.filter((t) => seen.has(t));
  }, [chartData]);

  const loading = q.isLoading;
  const empty = !loading && chartData.length === 0;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-zinc-300">
          Ingestion throughput
        </CardTitle>
        <Select
          value={range}
          onChange={(e) => setRange(e.target.value as RangeKey)}
          className="w-24 text-xs"
        >
          <option value="24h">24 hours</option>
          <option value="7d">7 days</option>
          <option value="30d">30 days</option>
        </Select>
      </CardHeader>
      <CardContent className="pt-2">
        {loading ? (
          <div className="flex h-48 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
          </div>
        ) : empty ? (
          <p className="py-12 text-center text-sm text-zinc-500">
            No samples yet for this range. The scheduler records ingestion rates
            every 5 minutes — first data point lands shortly after startup.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
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
                tickFormatter={(v) => `${Number(v).toFixed(1)}/s`}
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
                formatter={(val) => {
                  const n = Number(Array.isArray(val) ? val[0] : val);
                  return `${n.toFixed(2)} rows/s`;
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {visibleTables.map((t) => (
                <Line
                  key={t}
                  type="monotone"
                  dataKey={t}
                  name={t}
                  stroke={COLORS[t] ?? "#a1a1aa"}
                  strokeWidth={2}
                  dot={false}
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
