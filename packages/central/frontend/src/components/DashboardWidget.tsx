import { useMemo } from "react";
import { Loader2, AlertCircle, Pencil, Trash2, GripVertical } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiPost } from "@/api/client.ts";
import { QueryResultTable } from "@/components/QueryResultTable.tsx";
import { QueryResultChart } from "@/components/QueryResultChart.tsx";
import type { AnalyticsWidgetConfig, QueryResult } from "@/types/api.ts";

interface Props {
  id: string;
  title: string;
  config: AnalyticsWidgetConfig;
  onEdit?: () => void;
  onDelete?: () => void;
}

export function DashboardWidget({ id, title, config, onEdit, onDelete }: Props) {
  const refetchInterval = config.refresh_seconds && config.refresh_seconds > 0
    ? config.refresh_seconds * 1000
    : undefined;

  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-query", id, config.sql],
    queryFn: () => apiPost<QueryResult>("/analytics/query", { sql: config.sql, limit: 1000 }),
    refetchInterval,
    retry: 1,
  });

  const result = data?.data;

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
          />
        )}
        {result && config.chart_type !== "table" && (
          <QueryResultChart
            columns={result.columns}
            rows={result.rows}
            initialChartType={config.chart_type}
            initialXColumn={config.x_column}
            initialYColumns={config.y_columns}
            hideControls
          />
        )}
      </div>
    </div>
  );
}
