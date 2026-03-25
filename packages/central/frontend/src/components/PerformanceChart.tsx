import { useMemo } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import type { PerformanceRecord } from "@/types/api.ts";

const COLORS = [
  "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1",
  "#a855f7", "#84cc16", "#e11d48", "#0ea5e9", "#d946ef",
  "#10b981", "#f43f5e", "#7c3aed", "#eab308", "#2dd4bf",
];

interface Props {
  data: PerformanceRecord[];
  selectedComponents: string[];
  metricName: string;
  timezone?: string;
  unit?: string;
  title?: string;
}

function formatTimeLabel(ts: number, timezone: string): string {
  return new Date(ts).toLocaleTimeString("en-US", {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone: timezone,
  });
}

export function PerformanceChart({ data, selectedComponents, metricName, timezone = "UTC", unit = "", title }: Props) {
  const { chartData, domain } = useMemo(() => {
    const filtered = data.filter((r) => selectedComponents.includes(r.component));

    const byTime = new Map<number, Record<string, number | string>>();

    for (const r of filtered) {
      const ts = new Date(r.executed_at).getTime();
      if (!byTime.has(ts)) {
        byTime.set(ts, { ts } as Record<string, number | string>);
      }
      const entry = byTime.get(ts)!;
      const val = r.metrics[metricName];
      if (val !== undefined) {
        entry[r.component] = val;
      }
    }

    const sorted = [...byTime.values()].sort((a, b) => (a.ts as number) - (b.ts as number));
    const timestamps = sorted.map((d) => d.ts as number);
    const pad = timestamps.length > 1 ? (timestamps[timestamps.length - 1] - timestamps[0]) * 0.02 : 60_000;
    const domain: [number, number] = timestamps.length > 0
      ? [timestamps[0] - pad, timestamps[timestamps.length - 1] + pad]
      : [Date.now() - 3600_000, Date.now()];

    return { chartData: sorted, domain };
  }, [data, selectedComponents, metricName]);

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-zinc-600 text-sm">
        No performance data available for selection.
      </div>
    );
  }

  return (
    <div>
      {title && (
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">{title}</p>
      )}
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={domain}
              stroke="#52525b"
              fontSize={10}
              tickLine={false}
              axisLine={false}
              tickFormatter={(ts: number) => formatTimeLabel(ts, timezone)}
            />
            <YAxis
              stroke="#52525b"
              fontSize={10}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => unit ? `${v}${unit}` : String(v)}
              width={56}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#18181b",
                border: "1px solid #3f3f46",
                borderRadius: "0.5rem",
                fontSize: "0.75rem",
              }}
              labelFormatter={(ts) => formatTimeLabel(Number(ts), timezone)}
              formatter={(value: unknown, name: unknown) => [
                unit ? `${Number(value).toFixed(1)}${unit}` : Number(value).toFixed(2),
                String(name),
              ]}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa", paddingTop: 8 }} />
            {selectedComponents.map((comp, i) => (
              <Line
                key={comp}
                type="linear"
                dataKey={comp}
                name={comp}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={1.5}
                dot={false}
                activeDot={{ r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
