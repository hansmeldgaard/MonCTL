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

export function InterfaceTrafficChart({ data, timezone = "UTC" }: Props) {
  const reversed = [...data].reverse();

  // Check if pre-calculated rates exist
  const hasRates = reversed.some((r) => r.in_rate_bps > 0 || r.out_rate_bps > 0);

  // Build chart data — if no pre-calculated rates, compute deltas from counters
  let chartData: { time: string; in_bps: number; out_bps: number }[];

  if (hasRates) {
    chartData = reversed.map((r) => ({
      time: new Date(r.executed_at).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: timezone,
      }),
      in_bps: r.in_rate_bps,
      out_bps: r.out_rate_bps,
    }));
  } else {
    // Delta-based rate calculation from octet counters
    chartData = [];
    for (let i = 1; i < reversed.length; i++) {
      const prev = reversed[i - 1];
      const curr = reversed[i];
      const dtSec =
        (new Date(curr.executed_at).getTime() - new Date(prev.executed_at).getTime()) / 1000;
      if (dtSec <= 0) continue;

      // Handle 32-bit counter wrap (2^32)
      let inDelta = curr.in_octets - prev.in_octets;
      let outDelta = curr.out_octets - prev.out_octets;
      if (inDelta < 0) inDelta += 2 ** 32;
      if (outDelta < 0) outDelta += 2 ** 32;

      chartData.push({
        time: new Date(curr.executed_at).toLocaleTimeString("en-US", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          timeZone: timezone,
        }),
        in_bps: (inDelta * 8) / dtSec,
        out_bps: (outDelta * 8) / dtSec,
      });
    }
  }

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-zinc-600 text-sm">
        Not enough data points for traffic chart yet.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={250}>
      <AreaChart data={chartData} throttleDelay={0}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis dataKey="time" tick={{ fill: "#71717a", fontSize: 11 }} />
        <YAxis tick={{ fill: "#71717a", fontSize: 11 }} tickFormatter={formatBpsShort} />
        <Tooltip
          contentStyle={{
            backgroundColor: "#18181b",
            border: "1px solid #3f3f46",
            borderRadius: "0.5rem",
            fontSize: "0.75rem",
          }}
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
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
