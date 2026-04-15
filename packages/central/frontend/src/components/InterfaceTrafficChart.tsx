import React, { useState, useCallback, useRef } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceArea,
} from "recharts";
import type { InterfaceRecord, ResultRecord } from "@/types/api.ts";
import { formatChartDateTime } from "@/lib/utils.ts";

// ── Shared helpers ──────────────────────────────────────────

const CHART_COLOR_PAIRS = [
  { in: "#06b6d4", out: "#6366f1" }, // cyan / indigo
  { in: "#22c55e", out: "#f97316" }, // green / orange
  { in: "#a855f7", out: "#eab308" }, // purple / yellow
  { in: "#ec4899", out: "#14b8a6" }, // pink / teal
  { in: "#ef4444", out: "#3b82f6" }, // red / blue
  { in: "#84cc16", out: "#d946ef" }, // lime / fuchsia
  { in: "#f59e0b", out: "#8b5cf6" }, // amber / violet
  { in: "#10b981", out: "#f43f5e" }, // emerald / rose
];

export type TrafficUnit = "auto" | "kbps" | "mbps" | "gbps" | "pct";
export type ChartMetric = "traffic" | "errors" | "discards";
export type ChartMode = "overlaid" | "stacked";
export type DataTier = "raw" | "hourly" | "daily";

// For rollup tiers, each row value is a per-period total (errors/discards
// accumulated over the bucket). Dividing by the bucket length gives err/s.
const TIER_PERIOD_SEC: Record<DataTier, number> = {
  raw: 0, // raw uses pairwise delta / dt (see calculateDeltas)
  hourly: 3600,
  daily: 86400,
};

function rateSuffix(metric: ChartMetric): string {
  if (metric === "errors") return "err/s";
  if (metric === "discards") return "disc/s";
  return "";
}

// ── Down-span computation (device & interface status overlays) ─────────
//
// Group consecutive "down" samples into {from, to} time spans so the chart
// can render them as ReferenceArea bands. A single isolated down sample
// gets a MIN_SPAN_WIDTH_MS floor so it's visible at typical zoom levels.

export type DownSpan = { from: number; to: number };
const MIN_SPAN_WIDTH_MS = 60_000;

export function computeDownSpans<T>(
  data: T[],
  getTs: (d: T) => number,
  isDown: (d: T) => boolean,
): DownSpan[] {
  const sorted = [...data].sort((a, b) => getTs(a) - getTs(b));
  const spans: DownSpan[] = [];
  let start: number | null = null;
  let last: number | null = null;
  for (const d of sorted) {
    const ts = getTs(d);
    if (isDown(d)) {
      if (start == null) start = ts;
      last = ts;
    } else if (start != null && last != null) {
      spans.push({
        from: start,
        to: Math.max(last, start + MIN_SPAN_WIDTH_MS),
      });
      start = null;
      last = null;
    }
  }
  if (start != null && last != null) {
    spans.push({
      from: start,
      to: Math.max(last, start + MIN_SPAN_WIDTH_MS),
    });
  }
  return spans;
}

export function formatRateShort(v: number, suffix: string): string {
  const abs = Math.abs(v);
  if (abs === 0) return `0 ${suffix}`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K ${suffix}`;
  if (abs >= 10) return `${v.toFixed(1)} ${suffix}`;
  if (abs >= 1) return `${v.toFixed(2)} ${suffix}`;
  return `${v.toFixed(3)} ${suffix}`;
}

export function formatBpsShort(bps: number): string {
  if (bps >= 1e9) return `${(bps / 1e9).toFixed(1)} Gbps`;
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(1)} Mbps`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(0)} Kbps`;
  return `${bps.toFixed(0)} bps`;
}

export function convertBpsToUnit(
  bps: number,
  unit: TrafficUnit,
  speedMbps: number,
): number {
  switch (unit) {
    case "kbps":
      return bps / 1e3;
    case "mbps":
      return bps / 1e6;
    case "gbps":
      return bps / 1e9;
    case "pct":
      return speedMbps > 0 ? (bps / (speedMbps * 1e6)) * 100 : 0;
    default:
      return bps;
  }
}

export function formatTraffic(
  bps: number,
  unit: TrafficUnit,
  speedMbps: number,
): string {
  switch (unit) {
    case "kbps":
      return `${(bps / 1e3).toFixed(1)} Kbps`;
    case "mbps":
      return `${(bps / 1e6).toFixed(2)} Mbps`;
    case "gbps":
      return `${(bps / 1e9).toFixed(3)} Gbps`;
    case "pct": {
      if (speedMbps <= 0) return "\u2014";
      return `${((bps / (speedMbps * 1e6)) * 100).toFixed(1)}%`;
    }
    default:
      return formatBpsShort(bps);
  }
}

export function unitLabel(unit: TrafficUnit): string {
  switch (unit) {
    case "kbps":
      return "Kbps";
    case "mbps":
      return "Mbps";
    case "gbps":
      return "Gbps";
    case "pct":
      return "%";
    default:
      return "bps";
  }
}

function formatTimeLabel(ts: number, timezone: string): string {
  return new Date(ts).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: timezone,
  });
}

function formatUnitShort(val: number, unit: TrafficUnit): string {
  if (unit === "pct") return `${val.toFixed(1)}%`;
  if (unit === "auto") return formatBpsShort(val);
  if (val >= 1e3) return `${(val / 1e3).toFixed(1)}K`;
  return val.toFixed(1);
}

function formatTooltipValue(val: number, unit: TrafficUnit): string {
  if (unit === "pct") return `${val.toFixed(2)}%`;
  if (unit === "auto") return formatBpsShort(val);
  return `${val.toFixed(2)} ${unitLabel(unit)}`;
}

// ── Drag-to-zoom hook ──────────────────────────────────────

function useChartZoom(onZoom?: (fromMs: number, toMs: number) => void) {
  const [zoomDomain, setZoomDomain] = useState<[number, number] | null>(null);
  const [refAreaLeft, setRefAreaLeft] = useState<number | null>(null);
  const [refAreaRight, setRefAreaRight] = useState<number | null>(null);
  const isDragging = useRef(false);

  const handleMouseDown = useCallback(
    (e: { activeLabel?: string | number }) => {
      if (e?.activeLabel != null) {
        setRefAreaLeft(Number(e.activeLabel));
        isDragging.current = true;
      }
    },
    [],
  );
  const handleMouseMove = useCallback(
    (e: { activeLabel?: string | number }) => {
      if (isDragging.current && e?.activeLabel != null)
        setRefAreaRight(Number(e.activeLabel));
    },
    [],
  );
  const handleMouseUp = useCallback(() => {
    if (
      refAreaLeft != null &&
      refAreaRight != null &&
      refAreaLeft !== refAreaRight
    ) {
      const [l, r] =
        refAreaLeft < refAreaRight
          ? [refAreaLeft, refAreaRight]
          : [refAreaRight, refAreaLeft];
      if (onZoom) {
        onZoom(l, r);
      } else {
        setZoomDomain([l, r]);
      }
    }
    setRefAreaLeft(null);
    setRefAreaRight(null);
    isDragging.current = false;
  }, [refAreaLeft, refAreaRight, onZoom]);
  const resetZoom = useCallback(() => setZoomDomain(null), []);

  return {
    zoomDomain,
    refAreaLeft,
    refAreaRight,
    handleMouseDown,
    handleMouseMove,
    handleMouseUp,
    resetZoom,
    hasExternalZoom: !!onZoom,
  };
}

function ZoomHint({
  zoomDomain,
  resetZoom,
  external,
}: {
  zoomDomain: [number, number] | null;
  resetZoom: () => void;
  external?: boolean;
}) {
  if (!external && zoomDomain)
    return (
      <div className="flex justify-end mb-1">
        <button
          onClick={resetZoom}
          className="text-[10px] text-brand-400 hover:text-brand-300 cursor-pointer"
        >
          Reset zoom
        </button>
      </div>
    );
  return (
    <div className="flex justify-end mb-1">
      <span className="text-[10px] text-zinc-600">Drag to zoom</span>
    </div>
  );
}

// ── Single-interface chart ──────────────────────────────────

interface Props {
  data: InterfaceRecord[];
  timezone?: string;
  onZoom?: (fromMs: number, toMs: number) => void;
}

export function InterfaceTrafficChart({
  data,
  timezone = "UTC",
  onZoom,
}: Props) {
  const sorted = [...data].sort(
    (a, b) =>
      new Date(a.executed_at).getTime() - new Date(b.executed_at).getTime(),
  );

  const rateData = sorted
    .filter((r) => r.in_rate_bps > 0 || r.out_rate_bps > 0)
    .map((r) => ({
      ts: new Date(r.executed_at).getTime(),
      in_bps: r.in_rate_bps,
      out_bps: r.out_rate_bps,
    }));

  let chartData = rateData;
  let isFallback = false;

  if (rateData.length < 2 && sorted.length >= 2) {
    const deltaData: { ts: number; in_bps: number; out_bps: number }[] = [];
    for (let i = 1; i < sorted.length; i++) {
      const prev = sorted[i - 1];
      const curr = sorted[i];
      const dtSec =
        (new Date(curr.executed_at).getTime() -
          new Date(prev.executed_at).getTime()) /
        1000;
      if (dtSec <= 0) continue;
      const inDelta = curr.in_octets - prev.in_octets;
      const outDelta = curr.out_octets - prev.out_octets;
      if (inDelta < 0 || outDelta < 0) continue;
      deltaData.push({
        ts: new Date(curr.executed_at).getTime(),
        in_bps: (inDelta * 8) / dtSec,
        out_bps: (outDelta * 8) / dtSec,
      });
    }
    if (deltaData.length >= 1) {
      chartData = deltaData;
      isFallback = true;
    }
  }

  const zoom = useChartZoom(onZoom);

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-zinc-600 text-sm">
        Not enough data points for traffic chart yet.
      </div>
    );
  }

  const domainPadding = chartData.length === 1 ? 60_000 : 0;
  const fullDomain: [number, number] = [
    chartData[0].ts - domainPadding,
    chartData[chartData.length - 1].ts + domainPadding,
  ];
  const domain = zoom.zoomDomain ?? fullDomain;

  return (
    <div>
      {isFallback && (
        <div className="text-xs text-amber-500/70 mb-1">
          Showing estimated rates from counter deltas — central rate calculation
          warming up
        </div>
      )}
      <ZoomHint
        zoomDomain={zoom.zoomDomain}
        resetZoom={zoom.resetZoom}
        external={zoom.hasExternalZoom}
      />
      <div className="select-none">
        <ResponsiveContainer width="100%" height={250}>
          <AreaChart
            data={chartData}
            throttleDelay={0}
            onMouseDown={zoom.handleMouseDown}
            onMouseMove={zoom.handleMouseMove}
            onMouseUp={zoom.handleMouseUp}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={domain}
              allowDataOverflow={!!zoom.zoomDomain}
              tick={{ fill: "#71717a", fontSize: 11 }}
              tickFormatter={(ts) => formatTimeLabel(ts, timezone)}
            />
            <YAxis
              tick={{ fill: "#71717a", fontSize: 11 }}
              tickFormatter={formatBpsShort}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#18181b",
                border: "1px solid #3f3f46",
                borderRadius: "0.5rem",
                fontSize: "0.75rem",
              }}
              labelFormatter={(ts) => formatChartDateTime(Number(ts), timezone)}
              formatter={(value, name) => [
                formatBpsShort(Number(value)),
                name === "in_bps" ? "Inbound" : "Outbound",
              ]}
              isAnimationActive={false}
            />
            <Legend />
            {zoom.refAreaLeft != null && zoom.refAreaRight != null && (
              <ReferenceArea
                x1={zoom.refAreaLeft}
                x2={zoom.refAreaRight}
                fill="#3b82f6"
                fillOpacity={0.15}
              />
            )}
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
      </div>
    </div>
  );
}

// ── Multi-interface chart ───────────────────────────────────

interface MultiProps {
  interfaceIds: string[];
  interfaceNames: string[];
  historyPerInterface: InterfaceRecord[][];
  metric: ChartMetric;
  unit: TrafficUnit;
  mode: ChartMode;
  timezone: string;
  tier?: DataTier;
  /** Device availability history — used to render gray "device down" bands. */
  deviceAvailability?: ResultRecord[];
  onZoom?: (fromMs: number, toMs: number) => void;
}

// Styling for status overlay bands.
const DEVICE_DOWN_FILL = "#6b7280"; // gray
const DEVICE_DOWN_OPACITY = 0.25;
const IFACE_DOWN_FILL = "#ef4444"; // red
const IFACE_DOWN_OPACITY = 0.15;

function deviceDownSpans(avail: ResultRecord[] | undefined): DownSpan[] {
  if (!avail?.length) return [];
  return computeDownSpans(
    avail,
    (r) => new Date(r.executed_at).getTime(),
    // A ping/availability row is "down" when not reachable.
    (r) => !r.reachable,
  );
}

function interfaceDownSpans(data: InterfaceRecord[]): DownSpan[] {
  return computeDownSpans(
    data,
    (r) => new Date(r.executed_at).getTime(),
    (r) =>
      r.if_oper_status === "down" ||
      r.if_oper_status === "notPresent" ||
      r.if_oper_status === "lowerLayerDown",
  );
}

function StatusBands({
  deviceDown,
  ifaceDown,
}: {
  deviceDown: DownSpan[];
  ifaceDown?: DownSpan[];
}) {
  return (
    <>
      {/* Interface-down first so device-down (higher opacity) paints on top. */}
      {ifaceDown?.map((s, i) => (
        <ReferenceArea
          key={`if-${i}`}
          x1={s.from}
          x2={s.to}
          fill={IFACE_DOWN_FILL}
          fillOpacity={IFACE_DOWN_OPACITY}
          ifOverflow="hidden"
        />
      ))}
      {deviceDown.map((s, i) => (
        <ReferenceArea
          key={`dev-${i}`}
          x1={s.from}
          x2={s.to}
          fill={DEVICE_DOWN_FILL}
          fillOpacity={DEVICE_DOWN_OPACITY}
          ifOverflow="hidden"
        />
      ))}
    </>
  );
}

function getMetricFields(metric: ChartMetric): [string, string] {
  switch (metric) {
    case "traffic":
      return ["in_rate_bps", "out_rate_bps"];
    case "errors":
      return ["in_errors", "out_errors"];
    case "discards":
      return ["in_discards", "out_discards"];
  }
}

function calculateRate(
  data: InterfaceRecord[],
  inField: string,
  outField: string,
  tier: DataTier,
): { ts: number; in_val: number; out_val: number }[] {
  const sorted = [...data].sort((a, b) =>
    a.executed_at.localeCompare(b.executed_at),
  );

  // Rollup tiers: each row value is already a per-period total (errors or
  // discards accumulated over the hour/day bucket). Divide by the bucket
  // length to get per-second rate. No pairwise subtraction needed.
  if (tier !== "raw") {
    const period = TIER_PERIOD_SEC[tier];
    return sorted.map((r) => ({
      ts: new Date(r.executed_at).getTime(),
      in_val: ((r[inField as keyof InterfaceRecord] as number) || 0) / period,
      out_val: ((r[outField as keyof InterfaceRecord] as number) || 0) / period,
    }));
  }

  // Raw tier: values are cumulative SNMP counters. Compute per-second rate
  // from pairwise delta / dt. Skip counter wraps (delta < 0) and zero-dt.
  const result: { ts: number; in_val: number; out_val: number }[] = [];
  for (let i = 1; i < sorted.length; i++) {
    const prev = sorted[i - 1];
    const curr = sorted[i];
    const dtSec =
      (new Date(curr.executed_at).getTime() -
        new Date(prev.executed_at).getTime()) /
      1000;
    if (dtSec <= 0) continue;
    const inDelta =
      (curr[inField as keyof InterfaceRecord] as number) -
      (prev[inField as keyof InterfaceRecord] as number);
    const outDelta =
      (curr[outField as keyof InterfaceRecord] as number) -
      (prev[outField as keyof InterfaceRecord] as number);
    if (inDelta < 0 || outDelta < 0) continue;
    result.push({
      ts: new Date(curr.executed_at).getTime(),
      in_val: inDelta / dtSec,
      out_val: outDelta / dtSec,
    });
  }
  return result;
}

function mergeTimeSeries(
  interfaceIds: string[],
  historyPerInterface: InterfaceRecord[][],
  metric: ChartMetric,
  unit: TrafficUnit,
  tier: DataTier,
): Record<string, number>[] {
  const tsMap = new Map<number, Record<string, number>>();
  const [inField, outField] = getMetricFields(metric);

  interfaceIds.forEach((id, idx) => {
    const data = historyPerInterface[idx] ?? [];
    const points =
      metric === "traffic"
        ? data.map((r) => ({
            ts: new Date(r.executed_at).getTime(),
            in_val: r[inField as keyof InterfaceRecord] as number,
            out_val: r[outField as keyof InterfaceRecord] as number,
            speed: r.if_speed_mbps,
          }))
        : calculateRate(data, inField, outField, tier).map((p) => ({
            ...p,
            speed: 0,
          }));

    for (const pt of points) {
      if (!tsMap.has(pt.ts)) tsMap.set(pt.ts, { ts: pt.ts });
      const row = tsMap.get(pt.ts)!;
      const inVal =
        metric === "traffic"
          ? convertBpsToUnit(pt.in_val, unit, pt.speed)
          : pt.in_val;
      const outVal =
        metric === "traffic"
          ? convertBpsToUnit(pt.out_val, unit, pt.speed)
          : pt.out_val;
      row[`${id}_in`] = inVal;
      row[`${id}_out`] = outVal;
    }
  });

  return [...tsMap.values()].sort((a, b) => a.ts - b.ts);
}

export function MultiInterfaceChart({
  interfaceIds,
  interfaceNames,
  historyPerInterface,
  metric,
  unit,
  mode,
  timezone,
  tier = "raw",
  deviceAvailability,
  onZoom,
}: MultiProps) {
  const deviceDown = deviceDownSpans(deviceAvailability);
  if (!historyPerInterface?.length) {
    return (
      <div className="flex items-center justify-center h-48 text-zinc-600 text-sm">
        Loading chart data...
      </div>
    );
  }

  const rateUnit = rateSuffix(metric);
  const yFormatter = (v: number) =>
    metric === "traffic"
      ? formatUnitShort(v, unit)
      : formatRateShort(v, rateUnit);

  if (mode === "stacked") {
    const [inField, outField] = getMetricFields(metric);
    return (
      <div className="space-y-2">
        {interfaceIds.map((id, idx) => {
          const rawData = historyPerInterface[idx] ?? [];
          const points =
            metric === "traffic"
              ? [...rawData]
                  .sort((a, b) => a.executed_at.localeCompare(b.executed_at))
                  .filter(
                    (r) =>
                      (r[inField as keyof InterfaceRecord] as number) > 0 ||
                      (r[outField as keyof InterfaceRecord] as number) > 0,
                  )
                  .map((r) => ({
                    ts: new Date(r.executed_at).getTime(),
                    in_val: convertBpsToUnit(
                      r[inField as keyof InterfaceRecord] as number,
                      unit,
                      r.if_speed_mbps,
                    ),
                    out_val: convertBpsToUnit(
                      r[outField as keyof InterfaceRecord] as number,
                      unit,
                      r.if_speed_mbps,
                    ),
                  }))
              : calculateRate(rawData, inField, outField, tier).map((p) => ({
                  ...p,
                }));

          if (points.length === 0) return null;
          const ifaceDown = interfaceDownSpans(rawData);
          return (
            <StackedInterfaceChart
              key={id}
              points={points}
              idx={idx}
              name={interfaceNames[idx]}
              yFormatter={yFormatter}
              unit={unit}
              metric={metric}
              timezone={timezone}
              deviceDown={deviceDown}
              ifaceDown={ifaceDown}
              onZoom={onZoom}
            />
          );
        })}
      </div>
    );
  }

  // Overlaid mode
  return (
    <OverlaidInterfaceChart
      interfaceIds={interfaceIds}
      interfaceNames={interfaceNames}
      historyPerInterface={historyPerInterface}
      metric={metric}
      unit={unit}
      tier={tier}
      timezone={timezone}
      yFormatter={yFormatter}
      deviceDown={deviceDown}
      onZoom={onZoom}
    />
  );
}

// Stacked sub-chart (one per interface) with drag-to-zoom
function StackedInterfaceChart({
  points,
  idx,
  name,
  yFormatter,
  unit,
  metric,
  timezone,
  deviceDown,
  ifaceDown,
  onZoom,
}: {
  points: { ts: number; in_val: number; out_val: number }[];
  idx: number;
  name: string;
  yFormatter: (v: number) => string;
  unit: TrafficUnit;
  metric: ChartMetric;
  timezone: string;
  deviceDown: DownSpan[];
  ifaceDown: DownSpan[];
  onZoom?: (fromMs: number, toMs: number) => void;
}) {
  const zoom = useChartZoom(onZoom);
  const sPad = points.length <= 2 ? 60_000 : 0;
  // Extend the domain past the last data point to cover device-down spans —
  // otherwise the gray band sits in the no-render region outside the axis.
  const allSpans = [...deviceDown, ...ifaceDown];
  const rightEdge = Math.max(
    points[points.length - 1].ts + sPad,
    ...allSpans.map((s) => s.to),
  );
  const leftEdge = Math.min(
    points[0].ts - sPad,
    ...allSpans.map((s) => s.from),
  );
  const fullDomain: [number, number] = [leftEdge, rightEdge];
  const domain = zoom.zoomDomain ?? fullDomain;

  return (
    <div>
      <div className="text-xs text-zinc-400 mb-1 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div
            className="w-3 h-3 rounded-sm"
            style={{
              backgroundColor:
                CHART_COLOR_PAIRS[idx % CHART_COLOR_PAIRS.length].in,
            }}
          />
          {name}
        </div>
        {!zoom.hasExternalZoom && zoom.zoomDomain ? (
          <button
            onClick={zoom.resetZoom}
            className="text-[10px] text-brand-400 hover:text-brand-300 cursor-pointer"
          >
            Reset
          </button>
        ) : null}
      </div>
      <div className="select-none">
        <ResponsiveContainer width="100%" height={120}>
          <AreaChart
            data={points}
            throttleDelay={0}
            onMouseDown={zoom.handleMouseDown}
            onMouseMove={zoom.handleMouseMove}
            onMouseUp={zoom.handleMouseUp}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={domain}
              allowDataOverflow={!!zoom.zoomDomain}
              tick={{ fill: "#71717a", fontSize: 10 }}
              tickFormatter={(ts) => formatTimeLabel(ts, timezone)}
            />
            <YAxis
              tick={{ fill: "#71717a", fontSize: 10 }}
              tickFormatter={yFormatter}
              width={50}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#18181b",
                border: "1px solid #3f3f46",
                borderRadius: "0.5rem",
                fontSize: "0.7rem",
              }}
              labelFormatter={(ts) => formatChartDateTime(Number(ts), timezone)}
              formatter={(value) => {
                const v =
                  typeof value === "number" ? value : Number(value) || 0;
                return [
                  metric === "traffic"
                    ? formatTooltipValue(v, unit)
                    : formatRateShort(v, rateSuffix(metric)),
                ];
              }}
              isAnimationActive={false}
            />
            <StatusBands deviceDown={deviceDown} ifaceDown={ifaceDown} />
            {zoom.refAreaLeft != null && zoom.refAreaRight != null && (
              <ReferenceArea
                x1={zoom.refAreaLeft}
                x2={zoom.refAreaRight}
                fill="#3b82f6"
                fillOpacity={0.15}
              />
            )}
            <Area
              type="monotone"
              dataKey="in_val"
              name="In"
              stroke={CHART_COLOR_PAIRS[idx % CHART_COLOR_PAIRS.length].in}
              fill={CHART_COLOR_PAIRS[idx % CHART_COLOR_PAIRS.length].in}
              fillOpacity={0.15}
              strokeWidth={1.5}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="out_val"
              name="Out"
              stroke={CHART_COLOR_PAIRS[idx % CHART_COLOR_PAIRS.length].out}
              fill={CHART_COLOR_PAIRS[idx % CHART_COLOR_PAIRS.length].out}
              fillOpacity={0.1}
              strokeWidth={1.5}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// Overlaid multi-interface chart with drag-to-zoom
function OverlaidInterfaceChart({
  interfaceIds,
  interfaceNames,
  historyPerInterface,
  metric,
  unit,
  tier,
  timezone,
  yFormatter,
  deviceDown,
  onZoom,
}: {
  interfaceIds: string[];
  interfaceNames: string[];
  historyPerInterface: InterfaceRecord[][];
  metric: ChartMetric;
  unit: TrafficUnit;
  tier: DataTier;
  timezone: string;
  yFormatter: (v: number) => string;
  deviceDown: DownSpan[];
  onZoom?: (fromMs: number, toMs: number) => void;
}) {
  const zoom = useChartZoom(onZoom);
  const merged = mergeTimeSeries(
    interfaceIds,
    historyPerInterface,
    metric,
    unit,
    tier,
  );
  if (merged.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-zinc-600 text-sm">
        Not enough data points.
      </div>
    );
  }

  const domainPad = merged.length <= 2 ? 60_000 : 0;
  const rightEdge = Math.max(
    merged[merged.length - 1].ts + domainPad,
    ...deviceDown.map((s) => s.to),
  );
  const leftEdge = Math.min(
    merged[0].ts - domainPad,
    ...deviceDown.map((s) => s.from),
  );
  const fullDomain: [number, number] = [leftEdge, rightEdge];
  const domain = zoom.zoomDomain ?? fullDomain;

  return (
    <div>
      <ZoomHint
        zoomDomain={zoom.zoomDomain}
        resetZoom={zoom.resetZoom}
        external={zoom.hasExternalZoom}
      />
      <div className="select-none">
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart
            data={merged}
            throttleDelay={0}
            onMouseDown={zoom.handleMouseDown}
            onMouseMove={zoom.handleMouseMove}
            onMouseUp={zoom.handleMouseUp}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={domain}
              allowDataOverflow={!!zoom.zoomDomain}
              tick={{ fill: "#71717a", fontSize: 11 }}
              tickFormatter={(ts) => formatTimeLabel(ts, timezone)}
            />
            <YAxis
              tick={{ fill: "#71717a", fontSize: 11 }}
              tickFormatter={yFormatter}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#18181b",
                border: "1px solid #3f3f46",
                borderRadius: "0.5rem",
                fontSize: "0.75rem",
              }}
              labelFormatter={(ts) => formatChartDateTime(Number(ts), timezone)}
              formatter={(value) => {
                const v =
                  typeof value === "number" ? value : Number(value) || 0;
                return [
                  metric === "traffic"
                    ? formatTooltipValue(v, unit)
                    : formatRateShort(v, rateSuffix(metric)),
                ];
              }}
              isAnimationActive={false}
            />
            <Legend />
            <StatusBands deviceDown={deviceDown} />
            {zoom.refAreaLeft != null && zoom.refAreaRight != null && (
              <ReferenceArea
                x1={zoom.refAreaLeft}
                x2={zoom.refAreaRight}
                fill="#3b82f6"
                fillOpacity={0.15}
              />
            )}
            {interfaceIds.map((id, idx) => {
              const pair = CHART_COLOR_PAIRS[idx % CHART_COLOR_PAIRS.length];
              return (
                <React.Fragment key={id}>
                  <Area
                    type="monotone"
                    dataKey={`${id}_in`}
                    name={`${interfaceNames[idx]} In`}
                    stroke={pair.in}
                    fill={pair.in}
                    fillOpacity={0.1}
                    strokeWidth={1.5}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                  <Area
                    type="monotone"
                    dataKey={`${id}_out`}
                    name={`${interfaceNames[idx]} Out`}
                    stroke={pair.out}
                    fill={pair.out}
                    fillOpacity={0.1}
                    strokeWidth={1.5}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                </React.Fragment>
              );
            })}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
