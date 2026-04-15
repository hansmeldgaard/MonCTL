import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceArea,
} from "recharts";
import { useRef, useState, useCallback } from "react";
import type { ResultRecord } from "@/types/api.ts";
import { formatChartDateTime } from "@/lib/utils.ts";

// Palette for latency lines (one per assignment)
const LINE_COLORS = [
  "#6366f1", // indigo
  "#f59e0b", // amber
  "#06b6d4", // cyan
  "#a855f7", // purple
  "#f97316", // orange
  "#10b981", // emerald
  "#ec4899", // pink
];

interface ChartPoint {
  time: string; // formatted label for X axis
  ts: number; // epoch ms for sorting
  up: number; // 1 = up, 0 = down
  noData?: boolean; // true = monitoring gap (no data at all) — strip gray + latency overlay
  availNoData?: boolean; // true = no availability check in this bucket — strip gray only, latency lines unaffected
  /** Number of availability checks that fired inside this bucket. */
  checksTotal?: number;
  /** Number of those that were `reachable=false`. If > 0, the bucket paints red. */
  checksDown?: number;
  [key: string]: number | string | boolean | undefined; // {appName}_ms values
}

interface AvailabilityChartProps {
  results: ResultRecord[];
  fromTs?: string | null;
  toTs?: string | null;
  timezone?: string;
  onZoom?: (fromMs: number, toMs: number) => void;
}

/**
 * Choose bucket size (ms) based on time span for normalized display.
 */
function chooseBucketMs(spanMs: number): number {
  const DAY = 86400_000;
  const HOUR = 3_600_000;
  if (spanMs >= 7 * DAY) return HOUR; // 1 hour buckets for >= 7 days
  if (spanMs > 1 * DAY) return 15 * 60_000; // 15 min buckets for > 24h
  if (spanMs > 6 * HOUR) return 5 * 60_000; // 5 min buckets for > 6h
  if (spanMs > 1 * HOUR) return 60_000; // 1 min buckets for > 1h
  return 30_000; // 30 sec buckets otherwise
}

/**
 * Format a timestamp for the X axis label based on time span.
 *
 * The label must be unique per bucket — Recharts treats the categorical X-axis
 * `dataKey="time"` as a grouping key, so buckets that share a label collapse
 * into a single point and hover tooltips snap to the coarsest unique category.
 * Since `chooseBucketMs` never returns a bucket larger than 1 hour, any span
 * longer than 1 day must include HH:MM to keep hourly buckets distinct.
 */
function formatAxisLabel(ts: number, spanMs: number, timezone = "UTC"): string {
  const d = new Date(ts);
  const DAY = 86400_000;
  if (spanMs > 1 * DAY) {
    return (
      d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        timeZone: timezone,
      }) +
      " " +
      d.toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: timezone,
      })
    );
  }
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: timezone,
  });
}

/**
 * Build chart data from flat ResultRecord[].
 *
 * Strategy:
 *  - Determine time span from data
 *  - Choose adaptive bucket size
 *  - Group results into buckets by timestamp
 *  - For each bucket: up = 1 if ALL results reachable; latency = avg per app
 *  - Detect gaps: periods > 3× the median inter-sample gap are marked as
 *    "noData" placeholder buckets (rendered gray in the availability strip
 *    and as shaded regions in the latency chart).
 */
function buildChartData(
  results: ResultRecord[],
  fromTs?: string | null,
  toTs?: string | null,
  timezone = "UTC",
): {
  data: ChartPoint[];
  appNames: string[];
} {
  if (!results.length) return { data: [], appNames: [] };

  // Only include results from availability and latency monitoring roles.
  // General assignments (role="" or null) and interface assignments should NOT
  // appear on this chart — they have their own dedicated views.
  results = results.filter(
    (r) => r.role === "availability" || r.role === "latency",
  );
  if (!results.length) return { data: [], appNames: [] };

  // Collect unique app names for series
  const assignmentToApp = new Map<string, string>();
  for (const r of results) {
    if (r.assignment_id && r.app_name) {
      assignmentToApp.set(
        r.assignment_id,
        r.app_name ?? r.assignment_id.slice(0, 8),
      );
    }
  }
  const appNames = [...new Set(assignmentToApp.values())];

  // Determine time span — prefer explicit fromTs/toTs for consistent bucketing
  const timestamps = results.map((r) => new Date(r.executed_at).getTime());
  const dataMin = Math.min(...timestamps);
  const dataMax = Math.max(...timestamps);
  const rangeMin = fromTs ? new Date(fromTs).getTime() : dataMin;
  const rangeMax = toTs ? new Date(toTs).getTime() : Date.now();
  const minTs = Math.min(dataMin, rangeMin);
  const maxTs = Math.max(dataMax, rangeMax);
  const spanMs = Math.max(maxTs - minTs, 60_000); // at least 1 min

  // Auto-detect data granularity per assignment so we never use buckets
  // smaller than the actual polling interval (e.g. hourly rollup data
  // must not be bucketed at 15-minute granularity — most buckets would be empty).
  const byAssignment = new Map<string, number[]>();
  for (const r of results) {
    const ts = new Date(r.executed_at).getTime();
    if (!byAssignment.has(r.assignment_id))
      byAssignment.set(r.assignment_id, []);
    byAssignment.get(r.assignment_id)!.push(ts);
  }
  const perAssignmentMedians: number[] = [];
  for (const ts of byAssignment.values()) {
    if (ts.length < 2) continue;
    ts.sort((a, b) => a - b);
    const gaps: number[] = [];
    for (let i = 1; i < ts.length; i++) {
      const g = ts[i] - ts[i - 1];
      if (g > 0) gaps.push(g);
    }
    if (!gaps.length) continue;
    gaps.sort((a, b) => a - b);
    perAssignmentMedians.push(gaps[Math.floor(gaps.length / 2)]);
  }
  const detectedGranularityMs = perAssignmentMedians.length
    ? Math.min(...perAssignmentMedians)
    : 60_000;

  const bucketMs = Math.max(chooseBucketMs(spanMs), detectedGranularityMs);

  // ── Availability carry-forward ─────────────────────────────────────────────
  // The availability strip is driven exclusively by availability-role checks.
  // We carry-forward the last known state into buckets where only the latency
  // check fired, so the strip is a solid green/red bar — never falsely red
  // due to a failing latency check.
  const availCheckpoints = results
    .filter((r) => r.role === "availability")
    .map((r) => ({
      ts: new Date(r.executed_at).getTime(),
      reachable: r.reachable,
    }))
    .sort((a, b) => a.ts - b.ts);

  // Return the last known reachable state at or before `atTs`; null = no data yet.
  const getAvailStateAt = (atTs: number): boolean | null => {
    let state: boolean | null = null;
    for (const cp of availCheckpoints) {
      if (cp.ts <= atTs) state = cp.reachable;
      else break;
    }
    return state;
  };

  // Group results into buckets: bucket_start → {assignment_id → result[]}
  const byBucket = new Map<number, Map<string, ResultRecord[]>>();
  for (const r of results) {
    const ts = new Date(r.executed_at).getTime();
    const bucketStart = Math.floor(ts / bucketMs) * bucketMs;
    if (!byBucket.has(bucketStart)) byBucket.set(bucketStart, new Map());
    const bucket = byBucket.get(bucketStart)!;
    if (!bucket.has(r.assignment_id)) bucket.set(r.assignment_id, []);
    bucket.get(r.assignment_id)!.push(r);
  }

  // ── Gap detection ──────────────────────────────────────────────────────────
  // Sort actual data timestamps to find the median inter-sample gap.
  // Any period between two data points that exceeds 3× the median (or 3× the
  // bucket size, whichever is greater) is treated as a "no data" gap and filled
  // with gray placeholder buckets.
  const noDataBuckets = new Set<number>();

  if (timestamps.length >= 2) {
    const sortedTs = [...timestamps].sort((a, b) => a - b);

    // Median inter-sample gap
    const interGaps: number[] = [];
    for (let i = 1; i < sortedTs.length; i++) {
      interGaps.push(sortedTs[i] - sortedTs[i - 1]);
    }
    interGaps.sort((a, b) => a - b);
    const medianGap = interGaps[Math.floor(interGaps.length / 2)];
    // Use 6× bucket size so that isolated missing hourly/daily rollup points
    // don't generate gray "no data" overlays — only genuine multi-hour gaps do.
    const gapThreshold = Math.max(3 * medianGap, 6 * bucketMs);

    // Fill [gapStart, gapEnd) with no-data placeholder bucket keys
    const addGapBuckets = (gapStart: number, gapEnd: number) => {
      const firstBucket = (Math.floor(gapStart / bucketMs) + 1) * bucketMs;
      for (let t = firstBucket; t < gapEnd; t += bucketMs) {
        if (!byBucket.has(t)) noDataBuckets.add(t);
      }
    };

    // Gap at the start of the time range
    if (sortedTs[0] - rangeMin > gapThreshold) {
      addGapBuckets(rangeMin, sortedTs[0]);
    }

    // Gaps between consecutive data points
    for (let i = 1; i < sortedTs.length; i++) {
      if (sortedTs[i] - sortedTs[i - 1] > gapThreshold) {
        addGapBuckets(sortedTs[i - 1], sortedTs[i]);
      }
    }

    // Gap at the end of the time range (only if data is clearly stale)
    const lastTs = sortedTs[sortedTs.length - 1];
    if (rangeMax - lastTs > gapThreshold) {
      addGapBuckets(lastTs, rangeMax);
    }
  }

  // ── Build sorted chart points (real buckets + no-data placeholders) ─────────
  const allBucketStarts = new Set([...byBucket.keys(), ...noDataBuckets]);
  const sortedBuckets = [...allBucketStarts].sort((a, b) => a - b);

  const data: ChartPoint[] = sortedBuckets.map((bucketStart) => {
    // No-data placeholder — gray strip, no latency value
    if (noDataBuckets.has(bucketStart)) {
      return {
        time: formatAxisLabel(bucketStart, spanMs, timezone),
        ts: bucketStart,
        up: 0,
        noData: true,
      };
    }

    // Real data bucket
    const bucket = byBucket.get(bucketStart)!;
    const timeLabel = formatAxisLabel(bucketStart, spanMs, timezone);

    // Availability strip: "any-down wins" semantics — if ANY availability
    // check inside this bucket failed, paint the bucket red. This surfaces
    // short outages (<< bucket size) that end-of-bucket carry-forward
    // would otherwise hide. For buckets with no availability checks at all
    // we still carry-forward the last known state.
    const bucketEnd = bucketStart + bucketMs;
    let checksTotal = 0;
    let checksDown = 0;
    for (const cp of availCheckpoints) {
      if (cp.ts < bucketStart) continue;
      if (cp.ts >= bucketEnd) break;
      checksTotal += 1;
      if (!cp.reachable) checksDown += 1;
    }

    let up: 0 | 1 = 0;
    let noAvailData = false;
    if (checksTotal > 0) {
      up = checksDown > 0 ? 0 : 1;
    } else {
      // No checkpoint in this bucket — fall back to carry-forward.
      const availState = getAvailStateAt(bucketEnd - 1);
      if (availState === null) {
        noAvailData = true; // before the first availability check has fired
      } else {
        up = availState ? 1 : 0;
      }
    }

    const point: ChartPoint = {
      time: timeLabel,
      ts: bucketStart,
      up,
      // availNoData makes the strip segment gray but does NOT trigger latency
      // chart gray overlays — only a true monitoring gap (noData) does that.
      ...(noAvailData ? { availNoData: true } : {}),
      ...(checksTotal > 0 ? { checksTotal, checksDown } : {}),
    };

    for (const [assignId, appName] of assignmentToApp) {
      const recs = bucket.get(assignId) ?? [];
      // Only include latency from reachable results — 0ms from a failed check is
      // not real latency data and would draw a misleading flat line at 0.
      // Use || instead of ?? so that rtt_ms=0 falls through to response_time_ms
      // (rollup data sets rtt_avg=0 for port_check, response_time_avg has the value).
      const latencies = recs
        .filter((r) => r.reachable)
        .map((r) => r.rtt_ms || r.response_time_ms || null)
        .filter((v): v is number => v !== null && v > 0);
      if (latencies.length > 0) {
        const avg = latencies.reduce((a, b) => a + b, 0) / latencies.length;
        point[`${appName}_ms`] = Math.round(avg * 100) / 100;
      }
    }

    return point;
  });

  return { data, appNames };
}

/**
 * Group consecutive noData buckets into contiguous time ranges for use as
 * ReferenceArea overlays on the latency chart.
 */
function getNoDataRanges(
  data: ChartPoint[],
): Array<{ x1: string; x2: string }> {
  const ranges: Array<{ x1: string; x2: string }> = [];
  let rangeStart: string | null = null;
  let lastTime: string | null = null;

  for (const point of data) {
    if (point.noData) {
      if (rangeStart === null) rangeStart = point.time;
      lastTime = point.time;
    } else if (rangeStart !== null) {
      ranges.push({ x1: rangeStart, x2: lastTime! });
      rangeStart = null;
      lastTime = null;
    }
  }
  if (rangeStart !== null) {
    ranges.push({ x1: rangeStart, x2: lastTime! });
  }
  return ranges;
}

// Custom latency tooltip — shows date + time from the data point's ts field
function LatencyTooltip({
  active,
  payload,
  label,
  timezone,
}: {
  active?: boolean;
  payload?: {
    name: string;
    value: number;
    color: string;
    payload?: { ts?: number };
  }[];
  label?: string;
  timezone?: string;
}) {
  if (!active || !payload?.length) return null;
  const ts = payload[0]?.payload?.ts;
  const timeLabel = ts ? formatChartDateTime(ts, timezone) : label;
  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-xs shadow-xl">
      <p className="mb-1.5 font-medium text-zinc-400">{timeLabel}</p>
      {payload.map((entry) => (
        <div key={entry.name} className="flex items-center gap-2 mt-1">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-zinc-400">{entry.name}:</span>
          <span className="text-zinc-200 font-mono">{entry.value}ms</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Horizontal availability timeline strip.
 * Each bucket is a colored segment: green = UP, red = DOWN, gray = no data.
 * Mouse hover shows a floating tooltip with time + status.
 */
function StatusStrip({
  data,
  timezone,
}: {
  data: ChartPoint[];
  timezone?: string;
}) {
  const stripRef = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState<{
    idx: number;
    x: number;
    y: number;
  } | null>(null);

  const n = data.length;

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = stripRef.current?.getBoundingClientRect();
    if (!rect || n === 0) return;
    const relX = Math.max(0, e.clientX - rect.left);
    const idx = Math.min(n - 1, Math.floor((relX / rect.width) * n));
    setHovered({ idx, x: e.clientX, y: e.clientY });
  };

  const handleMouseLeave = () => setHovered(null);

  // Up to 6 evenly-spaced time labels
  const labelCount = Math.min(6, n);
  const labelIndices =
    labelCount <= 1
      ? [0]
      : Array.from({ length: labelCount }, (_, i) =>
          Math.round((i / (labelCount - 1)) * (n - 1)),
        );

  const hoveredPt = hovered ? data[hovered.idx] : null;

  // Segment color
  const segmentColor = (point: ChartPoint) => {
    if (point.noData || point.availNoData) return "#3f3f46"; // zinc-700 — no data
    return point.up === 1 ? "#22c55e" : "#ef4444"; // green / red
  };

  return (
    <div>
      {/* Colored timeline strip */}
      <div
        ref={stripRef}
        className="flex h-5 w-full overflow-hidden rounded cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {data.map((point, idx) => (
          <div
            key={idx}
            className="flex-1"
            style={{ backgroundColor: segmentColor(point), minWidth: 1 }}
          />
        ))}
      </div>

      {/* Time axis labels */}
      <div className="relative mt-1 h-4 select-none">
        {labelIndices.map((dataIdx) => {
          const pct = n > 1 ? (dataIdx / (n - 1)) * 100 : 0;
          return (
            <span
              key={dataIdx}
              className="absolute text-[10px] text-zinc-500 whitespace-nowrap"
              style={{
                left: `${pct}%`,
                transform:
                  pct < 5
                    ? "none"
                    : pct > 95
                      ? "translateX(-100%)"
                      : "translateX(-50%)",
              }}
            >
              {data[dataIdx].time}
            </span>
          );
        })}
      </div>

      {/* Floating hover tooltip */}
      {hoveredPt && hovered && (
        <div
          className="pointer-events-none fixed z-50 rounded border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-xs shadow-xl"
          style={{ left: hovered.x + 14, top: hovered.y - 10 }}
        >
          <div className="text-zinc-400">
            {hoveredPt.ts
              ? formatChartDateTime(hoveredPt.ts, timezone)
              : hoveredPt.time}
          </div>
          <div
            className="mt-0.5 font-semibold"
            style={{
              color: hoveredPt.noData
                ? "#71717a" // zinc-500
                : hoveredPt.up === 1
                  ? "#22c55e" // green
                  : "#ef4444", // red
            }}
          >
            {hoveredPt.noData ? "No data" : hoveredPt.up === 1 ? "UP" : "DOWN"}
          </div>
          {typeof hoveredPt.checksTotal === "number" &&
            typeof hoveredPt.checksDown === "number" &&
            hoveredPt.checksTotal > 0 && (
              <div className="mt-0.5 text-[10px] text-zinc-500">
                {hoveredPt.checksDown > 0
                  ? `${hoveredPt.checksDown} of ${hoveredPt.checksTotal} checks failed`
                  : `${hoveredPt.checksTotal} check${hoveredPt.checksTotal === 1 ? "" : "s"} ok`}
              </div>
            )}
        </div>
      )}
    </div>
  );
}

export function AvailabilityChart({
  results,
  fromTs,
  toTs,
  timezone = "UTC",
  onZoom,
}: AvailabilityChartProps) {
  const { data, appNames } = buildChartData(results, fromTs, toTs, timezone);

  // Drag-to-zoom for latency chart (index-based for categorical X axis)
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null);
  const [dragStart, setDragStart] = useState<string | null>(null);
  const [dragEnd, setDragEnd] = useState<string | null>(null);
  const isDragging = useRef(false);

  const handleMouseDown = useCallback(
    (e: { activeLabel?: string | number }) => {
      if (e?.activeLabel != null) {
        setDragStart(String(e.activeLabel));
        isDragging.current = true;
      }
    },
    [],
  );
  const handleMouseMove = useCallback(
    (e: { activeLabel?: string | number }) => {
      if (isDragging.current && e?.activeLabel != null)
        setDragEnd(String(e.activeLabel));
    },
    [],
  );
  const handleMouseUp = useCallback(() => {
    if (dragStart && dragEnd && dragStart !== dragEnd) {
      const startIdx = data.findIndex((d) => d.time === dragStart);
      const endIdx = data.findIndex((d) => d.time === dragEnd);
      if (startIdx >= 0 && endIdx >= 0) {
        const [l, r] =
          startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
        if (onZoom && data[l]?.ts && data[r]?.ts) {
          onZoom(data[l].ts, data[r].ts);
        } else {
          setZoomRange([l, r]);
        }
      }
    }
    setDragStart(null);
    setDragEnd(null);
    isDragging.current = false;
  }, [dragStart, dragEnd, data, onZoom]);
  const resetZoom = useCallback(() => setZoomRange(null), []);

  if (!data.length) {
    return (
      <div className="flex h-48 items-center justify-center text-zinc-600 text-sm">
        No data for selected time range
      </div>
    );
  }

  const hasLatency = data.some((pt) =>
    appNames.some((name) => pt[`${name}_ms`] !== undefined),
  );

  // Contiguous no-data ranges for the latency chart overlay
  const visibleData = zoomRange
    ? data.slice(zoomRange[0], zoomRange[1] + 1)
    : data;
  const noDataRanges = getNoDataRanges(visibleData);

  return (
    <div className="space-y-4">
      {/* Availability timeline strip */}
      <div style={{ paddingLeft: 48, paddingRight: 16 }}>
        <div className="mb-1.5 flex items-center gap-3">
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
            Availability
          </p>
          <span className="flex items-center gap-1 text-[10px] text-zinc-600">
            <span className="inline-block h-2 w-2 rounded-sm bg-emerald-500" />
            Up
          </span>
          <span className="flex items-center gap-1 text-[10px] text-zinc-600">
            <span className="inline-block h-2 w-2 rounded-sm bg-red-500" />
            Down
          </span>
          <span className="flex items-center gap-1 text-[10px] text-zinc-600">
            <span className="inline-block h-2 w-2 rounded-sm bg-zinc-600" />
            No data
          </span>
        </div>
        <StatusStrip data={data} timezone={timezone} />
      </div>

      {/* Latency line chart — only shown when latency data is present */}
      {hasLatency && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
              Latency
            </p>
            {!onZoom && zoomRange ? (
              <button
                onClick={resetZoom}
                className="text-[10px] text-brand-400 hover:text-brand-300 cursor-pointer"
              >
                Reset zoom
              </button>
            ) : (
              <span className="text-[10px] text-zinc-600">Drag to zoom</span>
            )}
          </div>
          <div className="h-44 select-none">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={visibleData}
                margin={{ top: 4, right: 16, bottom: 0, left: 0 }}
                throttleDelay={0}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="#27272a"
                  vertical={false}
                />
                <XAxis
                  dataKey="time"
                  stroke="#52525b"
                  fontSize={10}
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  stroke="#52525b"
                  fontSize={10}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v: number) => `${v}ms`}
                  width={48}
                />
                <Tooltip
                  content={<LatencyTooltip timezone={timezone} />}
                  isAnimationActive={false}
                />
                <Legend
                  wrapperStyle={{
                    fontSize: 11,
                    color: "#a1a1aa",
                    paddingTop: 8,
                  }}
                />
                {/* Gray shaded bands for no-data periods */}
                {noDataRanges.map((range, i) => (
                  <ReferenceArea
                    key={i}
                    x1={range.x1}
                    x2={range.x2}
                    fill="#27272a"
                    fillOpacity={0.9}
                  />
                ))}
                {/* Drag selection highlight */}
                {dragStart && dragEnd && (
                  <ReferenceArea
                    x1={dragStart}
                    x2={dragEnd}
                    fill="#3b82f6"
                    fillOpacity={0.15}
                  />
                )}
                {appNames.map((appName, i) => (
                  <Line
                    key={appName}
                    type="monotone"
                    dataKey={`${appName}_ms`}
                    name={`${appName} (ms)`}
                    stroke={LINE_COLORS[i % LINE_COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                    connectNulls={true}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
