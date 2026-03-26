import { Loader2, AlertCircle, Pencil, Trash2, GripVertical } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiPost } from "@/api/client.ts";
import { QueryResultTable } from "@/components/QueryResultTable.tsx";
import { QueryResultChart } from "@/components/QueryResultChart.tsx";
import type { AnalyticsWidgetConfig, QueryResult } from "@/types/api.ts";
import type { TimeRange } from "@/components/DashboardTimePicker.tsx";

function toClickHouseDateTime(d: Date): string {
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "");
}

function resolveTimestamp(input: string): string {
  if (input === "now") return toClickHouseDateTime(new Date());
  const match = input.match(/^now-(\d+)([mhd])$/);
  if (match) {
    const ms = { m: 60000, h: 3600000, d: 86400000 }[match[2]]!;
    return toClickHouseDateTime(new Date(Date.now() - Number(match[1]) * ms));
  }
  return input;
}

function resolveSQL(
  sql: string,
  timeRange?: TimeRange,
  variables?: Record<string, string>,
): string {
  let resolved = sql;
  if (timeRange) {
    resolved = resolved
      .replace(/\{time_from\}/g, `'${resolveTimestamp(timeRange.from)}'`)
      .replace(/\{time_to\}/g, `'${resolveTimestamp(timeRange.to)}'`);
  }
  if (variables) {
    for (const [name, value] of Object.entries(variables)) {
      const escaped = value.replace(/'/g, "''");
      resolved = resolved.replace(new RegExp(`\\{var:${name}\\}`, "g"), `'${escaped}'`);
    }
  }
  return resolved;
}

interface Props {
  id: string;
  title: string;
  config: AnalyticsWidgetConfig;
  timeRange?: TimeRange;
  variables?: Record<string, string>;
  onVariableChange?: (name: string, value: string) => void;
  onEdit?: () => void;
  onDelete?: () => void;
}

export function DashboardWidget({
  id, title, config, timeRange, variables, onVariableChange, onEdit, onDelete,
}: Props) {
  const refetchInterval = config.refresh_seconds && config.refresh_seconds > 0
    ? config.refresh_seconds * 1000
    : undefined;

  const resolvedSQL = resolveSQL(config.sql, timeRange, variables);

  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-query", id, resolvedSQL],
    queryFn: () => apiPost<QueryResult>("/analytics/query", { sql: resolvedSQL, limit: 1000 }),
    refetchInterval,
    retry: 1,
  });

  const result = data?.data;

  function handleRowClick(row: unknown[]) {
    if (!config.publishes || !onVariableChange || !result) return;
    const colIdx = result.columns.findIndex((c) => c.name === config.publishes!.column);
    if (colIdx === -1) return;
    const value = row[colIdx];
    if (value != null) {
      onVariableChange(config.publishes!.variable, String(value));
    }
  }

  return (
    <div className="flex flex-col h-full bg-zinc-900 border border-zinc-800 rounded-md overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-zinc-800 bg-zinc-900/80 shrink-0">
        <GripVertical className="h-3.5 w-3.5 text-zinc-600 cursor-grab drag-handle" />
        <span className="text-xs font-medium text-zinc-300 flex-1 truncate">{title}</span>
        {onEdit && (
          <button onClick={onEdit} className="text-zinc-600 hover:text-zinc-300 p-0.5" title="Edit">
            <Pencil className="h-3 w-3" />
          </button>
        )}
        {onDelete && (
          <button onClick={onDelete} className="text-zinc-600 hover:text-red-400 p-0.5" title="Delete">
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-2 min-h-0">
        {isLoading && (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 text-xs text-red-400 p-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="truncate">{(error as Error).message}</span>
          </div>
        )}
        {result && config.chart_type === "table" && (
          <QueryResultTable
            columns={result.columns}
            rows={result.rows}
            rowCount={result.row_count}
            truncated={result.truncated}
            executionTimeMs={result.execution_time_ms}
            onRowClick={config.publishes ? handleRowClick : undefined}
          />
        )}
        {result && config.chart_type !== "table" && (
          <QueryResultChart
            columns={result.columns}
            rows={result.rows}
            initialChartType={config.chart_type}
            initialXColumn={config.x_column}
            initialYColumns={config.y_columns}
            initialGroupBy={config.group_by}
            hideControls
          />
        )}
      </div>
    </div>
  );
}
