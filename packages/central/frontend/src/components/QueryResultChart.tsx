import { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

const COLORS = [
  "#3b82f6",
  "#ef4444",
  "#22c55e",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
  "#06b6d4",
  "#f97316",
  "#14b8a6",
  "#6366f1",
];

type ChartType = "line" | "bar" | "area" | "pie";

interface Column {
  name: string;
  type: string;
}

interface Props {
  columns: Column[];
  rows: unknown[][];
  initialChartType?: ChartType;
  initialXColumn?: string;
  initialYColumns?: string[];
  initialGroupBy?: string;
  hideControls?: boolean;
  onSettingsChange?: (settings: {
    chartType: ChartType;
    xColumn: string;
    yColumns: string[];
    groupBy: string;
  }) => void;
}

function isNumericType(type: string): boolean {
  return /^(U?Int|Float|Decimal)/i.test(type);
}

export function QueryResultChart({
  columns,
  rows,
  initialChartType = "line",
  initialXColumn,
  initialYColumns,
  initialGroupBy,
  hideControls = false,
  onSettingsChange,
}: Props) {
  const numericCols = columns.filter((c) => isNumericType(c.type));
  const nonNumericCols = columns.filter((c) => !isNumericType(c.type));

  const [chartType, setChartType] = useState<ChartType>(initialChartType);
  const [xColumn, setXColumn] = useState(
    initialXColumn || nonNumericCols[0]?.name || columns[0]?.name || "",
  );
  const [yColumns, setYColumns] = useState<string[]>(
    initialYColumns || numericCols.slice(0, 3).map((c) => c.name),
  );
  const [groupBy, setGroupBy] = useState(initialGroupBy || "");

  function updateSettings(
    updates: Partial<{
      chartType: ChartType;
      xColumn: string;
      yColumns: string[];
      groupBy: string;
    }>,
  ) {
    const next = {
      chartType: updates.chartType ?? chartType,
      xColumn: updates.xColumn ?? xColumn,
      yColumns: updates.yColumns ?? yColumns,
      groupBy: updates.groupBy ?? groupBy,
    };
    if (updates.chartType !== undefined) setChartType(updates.chartType);
    if (updates.xColumn !== undefined) setXColumn(updates.xColumn);
    if (updates.yColumns !== undefined) setYColumns(updates.yColumns);
    if (updates.groupBy !== undefined) setGroupBy(updates.groupBy);
    onSettingsChange?.(next);
  }

  // When groupBy is set, pivot data: one series per unique groupBy value
  const { chartData, seriesKeys } = useMemo(() => {
    const xIdx = columns.findIndex((c) => c.name === xColumn);
    if (xIdx === -1) return { chartData: [], seriesKeys: [] as string[] };

    const groupIdx = groupBy
      ? columns.findIndex((c) => c.name === groupBy)
      : -1;

    // No group by — standard mode: each yColumn is a series
    if (groupIdx === -1 || yColumns.length !== 1) {
      const data = rows.map((row) => {
        const point: Record<string, unknown> = { [xColumn]: row[xIdx] };
        for (const yCol of yColumns) {
          const yIdx = columns.findIndex((c) => c.name === yCol);
          if (yIdx !== -1) point[yCol] = row[yIdx];
        }
        return point;
      });
      return { chartData: data, seriesKeys: yColumns };
    }

    // Group by mode: pivot yColumns[0] into one series per groupBy value
    const yIdx = columns.findIndex((c) => c.name === yColumns[0]);
    if (yIdx === -1) return { chartData: [], seriesKeys: [] as string[] };

    // Collect unique group values and build pivoted data
    const groupValues = new Set<string>();
    const xMap = new Map<string, Record<string, unknown>>();

    for (const row of rows) {
      const xVal = String(row[xIdx] ?? "");
      const gVal = String(row[groupIdx] ?? "");
      const yVal = row[yIdx];
      groupValues.add(gVal);

      if (!xMap.has(xVal)) {
        xMap.set(xVal, { [xColumn]: row[xIdx] });
      }
      xMap.get(xVal)![gVal] = yVal;
    }

    const sortedGroups = [...groupValues].sort().slice(0, 20); // cap at 20 series
    const data = [...xMap.values()];
    return { chartData: data, seriesKeys: sortedGroups };
  }, [rows, columns, xColumn, yColumns, groupBy]);

  const tooltipStyle = {
    backgroundColor: "#18181b",
    border: "1px solid #3f3f46",
    borderRadius: "0.5rem",
    fontSize: "0.75rem",
  };

  function toggleYColumn(col: string) {
    const next = yColumns.includes(col)
      ? yColumns.filter((c) => c !== col)
      : [...yColumns, col];
    updateSettings({ yColumns: next });
  }

  // Candidate columns for groupBy: non-numeric, not the xColumn
  const groupByCandidates = nonNumericCols.filter((c) => c.name !== xColumn);

  return (
    <div className="space-y-3">
      {!hideControls && (
        <div className="flex flex-wrap gap-3 items-end text-xs">
          <div className="space-y-1">
            <label className="text-zinc-500 uppercase tracking-wide text-[10px] font-semibold">
              Type
            </label>
            <div className="flex gap-1">
              {(["line", "bar", "area", "pie"] as ChartType[]).map((t) => (
                <button
                  key={t}
                  onClick={() => updateSettings({ chartType: t })}
                  className={`px-2 py-1 rounded capitalize ${
                    chartType === t
                      ? "bg-brand-600/20 text-brand-400 border border-brand-600/40"
                      : "text-zinc-500 hover:text-zinc-300 border border-transparent"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-zinc-500 uppercase tracking-wide text-[10px] font-semibold">
              X Axis
            </label>
            <select
              value={xColumn}
              onChange={(e) => updateSettings({ xColumn: e.target.value })}
              className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-300"
            >
              {columns.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <label className="text-zinc-500 uppercase tracking-wide text-[10px] font-semibold">
              Y Axis
            </label>
            <div className="flex flex-wrap gap-1">
              {numericCols.map((c) => (
                <button
                  key={c.name}
                  onClick={() => toggleYColumn(c.name)}
                  className={`px-2 py-0.5 rounded text-[11px] ${
                    yColumns.includes(c.name)
                      ? "bg-brand-600/20 text-brand-400 border border-brand-600/40"
                      : "text-zinc-500 hover:text-zinc-300 border border-zinc-700"
                  }`}
                >
                  {c.name}
                </button>
              ))}
            </div>
          </div>

          {groupByCandidates.length > 0 && (
            <div className="space-y-1">
              <label className="text-zinc-500 uppercase tracking-wide text-[10px] font-semibold">
                Group By
              </label>
              <select
                value={groupBy}
                onChange={(e) => updateSettings({ groupBy: e.target.value })}
                className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-300"
              >
                <option value="">None</option>
                {groupByCandidates.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}

      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          {chartType === "line" ? (
            <LineChart
              data={chartData}
              margin={{ top: 4, right: 16, bottom: 0, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#27272a"
                vertical={false}
              />
              <XAxis
                dataKey={xColumn}
                stroke="#52525b"
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                stroke="#52525b"
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
              {seriesKeys.map((col, i) => (
                <Line
                  key={col}
                  type="monotone"
                  dataKey={col}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          ) : chartType === "bar" ? (
            <BarChart
              data={chartData}
              margin={{ top: 4, right: 16, bottom: 0, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#27272a"
                vertical={false}
              />
              <XAxis
                dataKey={xColumn}
                stroke="#52525b"
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                stroke="#52525b"
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
              {seriesKeys.map((col, i) => (
                <Bar key={col} dataKey={col} fill={COLORS[i % COLORS.length]} />
              ))}
            </BarChart>
          ) : chartType === "area" ? (
            <AreaChart
              data={chartData}
              margin={{ top: 4, right: 16, bottom: 0, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#27272a"
                vertical={false}
              />
              <XAxis
                dataKey={xColumn}
                stroke="#52525b"
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                stroke="#52525b"
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
              {seriesKeys.map((col, i) => (
                <Area
                  key={col}
                  type="monotone"
                  dataKey={col}
                  stroke={COLORS[i % COLORS.length]}
                  fill={COLORS[i % COLORS.length]}
                  fillOpacity={0.15}
                  isAnimationActive={false}
                />
              ))}
            </AreaChart>
          ) : (
            <PieChart>
              <Pie
                data={chartData}
                dataKey={seriesKeys[0] || ""}
                nameKey={xColumn}
                cx="50%"
                cy="50%"
                outerRadius={100}
                label
              >
                {chartData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
            </PieChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
