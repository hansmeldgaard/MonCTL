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
import { useDbSizeHistory } from "@/api/hooks.ts";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Loader2 } from "lucide-react";
import { formatBytes } from "@/lib/utils.ts";

type RangeKey = "24h" | "7d" | "30d";

const RANGE_SECONDS: Record<RangeKey, number> = {
  "24h": 24 * 3600,
  "7d": 7 * 24 * 3600,
  "30d": 30 * 24 * 3600,
};

/**
 * Stacks PG total + CH total bytes over the selected range. Data is
 * produced by the scheduler's db_size_history sampler (~1 row per 15 min),
 * so the sparkline can look empty in the first 30 min after deploy.
 */
export function DbSizeHistoryChart() {
  const [range, setRange] = useState<RangeKey>("7d");

  const { fromIso, toIso } = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - RANGE_SECONDS[range] * 1000);
    return { fromIso: from.toISOString(), toIso: to.toISOString() };
  }, [range]);

  // PG total: one row per sample. CH total: sum per-sample across tables.
  const pgQuery = useDbSizeHistory({
    source: "postgres",
    scope: "database",
    from: fromIso,
    to: toIso,
  });
  const chQuery = useDbSizeHistory({
    source: "clickhouse",
    scope: "table",
    from: fromIso,
    to: toIso,
  });

  const chartData = useMemo(() => {
    const byTs = new Map<number, { ts: number; pg?: number; ch?: number }>();

    for (const r of pgQuery.data ?? []) {
      const ts = new Date(r.timestamp + "Z").getTime();
      const row = byTs.get(ts) ?? { ts };
      row.pg = r.bytes;
      byTs.set(ts, row);
    }

    // CH: sum across tables per-timestamp (one sampler pass → one ts, many rows)
    const chTotals = new Map<number, number>();
    for (const r of chQuery.data ?? []) {
      const ts = new Date(r.timestamp + "Z").getTime();
      chTotals.set(ts, (chTotals.get(ts) ?? 0) + r.bytes);
    }
    for (const [ts, total] of chTotals) {
      const row = byTs.get(ts) ?? { ts };
      row.ch = total;
      byTs.set(ts, row);
    }

    return [...byTs.values()].sort((a, b) => a.ts - b.ts);
  }, [pgQuery.data, chQuery.data]);

  const loading = pgQuery.isLoading || chQuery.isLoading;
  const empty = !loading && chartData.length === 0;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-zinc-300">
          Database growth
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
            No samples yet for this range. The scheduler captures sizes every 15
            minutes — first data point lands shortly after startup.
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
                tickFormatter={(v) => formatBytes(Number(v))}
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
                formatter={(val: number | string) => formatBytes(Number(val))}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="pg"
                name="PostgreSQL"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="ch"
                name="ClickHouse"
                stroke="#22c55e"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
