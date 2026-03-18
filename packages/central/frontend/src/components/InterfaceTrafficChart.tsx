import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import type { InterfaceRecord } from "@/types/api.ts";

interface Props {
  data: InterfaceRecord[];
  timezone?: string;
}

function formatBpsShort(bps: number): string {
  if (bps >= 1e9) return `${(bps / 1e9).toFixed(1)}G`;
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(1)}M`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(0)}K`;
  return `${bps.toFixed(0)}`;
}

function formatTimeLabel(ts: number, timezone: string): string {
  return new Date(ts).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: timezone,
  });
}

export function InterfaceTrafficChart({ data, timezone = "UTC" }: Props) {
  const reversed = [...data].reverse();

  // Use pre-calculated rates from central — no client-side delta fallback
  const chartData = reversed
    .filter((r) => r.in_rate_bps > 0 || r.out_rate_bps > 0)
    .map((r) => ({
      ts: new Date(r.executed_at).getTime(),
      in_bps: r.in_rate_bps,
      out_bps: r.out_rate_bps,
    }));

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-zinc-600 text-sm">
        Not enough data points for traffic chart yet.
      </div>
    );
  }

  // Compute domain from actual data range
  const minTs = chartData[0].ts;
  const maxTs = chartData[chartData.length - 1].ts;

  return (
    <ResponsiveContainer width="100%" height={250}>
      <AreaChart data={chartData} throttleDelay={0}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis
          dataKey="ts"
          type="number"
          scale="time"
          domain={[minTs, maxTs]}
          tick={{ fill: "#71717a", fontSize: 11 }}
          tickFormatter={(ts) => formatTimeLabel(ts, timezone)}
        />
        <YAxis tick={{ fill: "#71717a", fontSize: 11 }} tickFormatter={formatBpsShort} />
        <Tooltip
          contentStyle={{
            backgroundColor: "#18181b",
            border: "1px solid #3f3f46",
            borderRadius: "0.5rem",
            fontSize: "0.75rem",
          }}
          labelFormatter={(ts) => formatTimeLabel(Number(ts), timezone)}
          formatter={(value, name) => [
            formatBpsShort(Number(value)),
            name === "in_bps" ? "Inbound" : "Outbound",
          ]}
          isAnimationActive={false}
        />
        <Legend />
        <Area
          type="monotone"
          dataKey="in_bps"
          name="Inbound"
          stroke="#06b6d4"
          fill="#06b6d4"
          fillOpacity={0.15}
          strokeWidth={1.5}
          isAnimationActive={false}
          connectNulls={false}
        />
        <Area
          type="monotone"
          dataKey="out_bps"
          name="Outbound"
          stroke="#6366f1"
          fill="#6366f1"
          fillOpacity={0.15}
          strokeWidth={1.5}
          isAnimationActive={false}
          connectNulls={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
