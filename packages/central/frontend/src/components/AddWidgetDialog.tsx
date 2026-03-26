import { useState } from "react";
import { Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { SqlEditor } from "@/components/SqlEditor.tsx";
import { QueryResultTable } from "@/components/QueryResultTable.tsx";
import { QueryResultChart } from "@/components/QueryResultChart.tsx";
import { useExecuteQuery } from "@/api/hooks.ts";
import type { AnalyticsWidgetConfig, QueryResult } from "@/types/api.ts";

type ChartType = AnalyticsWidgetConfig["chart_type"];

interface Props {
  open: boolean;
  onClose: () => void;
  onSave: (widget: { title: string; config: AnalyticsWidgetConfig }) => void;
  initial?: { title: string; config: AnalyticsWidgetConfig };
  schema?: Record<string, string[]>;
}

const REFRESH_OPTIONS = [
  { label: "None", value: 0 },
  { label: "15s", value: 15 },
  { label: "30s", value: 30 },
  { label: "1m", value: 60 },
  { label: "5m", value: 300 },
];

export function AddWidgetDialog({ open, onClose, onSave, initial, schema }: Props) {
  const [title, setTitle] = useState(initial?.title || "");
  const [sqlText, setSqlText] = useState(initial?.config.sql || "SELECT 1");
  const [chartType, setChartType] = useState<ChartType>(initial?.config.chart_type || "table");
  const [xColumn, setXColumn] = useState(initial?.config.x_column || "");
  const [yColumns, setYColumns] = useState<string[]>(initial?.config.y_columns || []);
  const [groupByCol, setGroupByCol] = useState(initial?.config.group_by || "");
  const [refreshSeconds, setRefreshSeconds] = useState(initial?.config.refresh_seconds || 0);

  const executeMut = useExecuteQuery();
  const result: QueryResult | undefined = executeMut.data?.data;

  if (!open) return null;

  function handleTest() {
    if (!sqlText.trim()) return;
    executeMut.mutate({ sql: sqlText, limit: 100 });
  }

  function handleSave() {
    onSave({
      title: title.trim() || "Untitled",
      config: {
        sql: sqlText,
        chart_type: chartType,
        x_column: chartType !== "table" ? xColumn : undefined,
        y_columns: chartType !== "table" ? yColumns : undefined,
        group_by: chartType !== "table" && groupByCol ? groupByCol : undefined,
        refresh_seconds: refreshSeconds,
      },
    });
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-zinc-900 border border-zinc-700 rounded-lg w-[900px] max-h-[90vh] overflow-y-auto">
        <div className="p-4 border-b border-zinc-800">
          <h2 className="text-sm font-semibold text-zinc-200">
            {initial ? "Edit Widget" : "Add Widget"}
          </h2>
        </div>

        <div className="p-4 space-y-4">
          {/* Title */}
          <div className="space-y-1">
            <label className="text-xs text-zinc-500">Title</label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Widget title"
            />
          </div>

          {/* SQL */}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label className="text-xs text-zinc-500">SQL Query</label>
              <Button size="sm" variant="outline" onClick={handleTest} disabled={executeMut.isPending} className="gap-1">
                {executeMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                Test
              </Button>
            </div>
            <SqlEditor value={sqlText} onChange={setSqlText} onExecute={handleTest} schema={schema} height="150px" />
          </div>

          {/* Error */}
          {executeMut.isError && (
            <div className="p-2 rounded bg-red-950/50 border border-red-900/50 text-xs text-red-400">
              {(executeMut.error as Error)?.message || "Query failed"}
            </div>
          )}

          {/* Chart config */}
          <div className="flex flex-wrap gap-4 items-end">
            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Visualization</label>
              <div className="flex gap-1">
                {(["table", "line", "bar", "area", "pie"] as ChartType[]).map((t) => (
                  <button
                    key={t}
                    onClick={() => setChartType(t)}
                    className={`px-2 py-1 text-xs rounded capitalize ${
                      chartType === t
                        ? "bg-brand-600/20 text-brand-400 border border-brand-600/40"
                        : "text-zinc-500 hover:text-zinc-300 border border-zinc-700"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>

            {chartType !== "table" && result && (
              <>
                <div className="space-y-1">
                  <label className="text-xs text-zinc-500">X Axis</label>
                  <select
                    value={xColumn}
                    onChange={(e) => setXColumn(e.target.value)}
                    className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-300"
                  >
                    <option value="">Auto</option>
                    {result.columns.map((c) => (
                      <option key={c.name} value={c.name}>{c.name}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-zinc-500">Y Axis</label>
                  <div className="flex flex-wrap gap-1">
                    {result.columns.filter((c) => /^(U?Int|Float|Decimal)/i.test(c.type)).map((c) => (
                      <button
                        key={c.name}
                        onClick={() => setYColumns((prev) =>
                          prev.includes(c.name) ? prev.filter((x) => x !== c.name) : [...prev, c.name]
                        )}
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
                <div className="space-y-1">
                  <label className="text-xs text-zinc-500">Group By</label>
                  <select
                    value={groupByCol}
                    onChange={(e) => setGroupByCol(e.target.value)}
                    className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-300"
                  >
                    <option value="">None</option>
                    {result.columns.filter((c) => !/^(U?Int|Float|Decimal)/i.test(c.type) && c.name !== xColumn).map((c) => (
                      <option key={c.name} value={c.name}>{c.name}</option>
                    ))}
                  </select>
                </div>
              </>
            )}

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Refresh</label>
              <select
                value={refreshSeconds}
                onChange={(e) => setRefreshSeconds(Number(e.target.value))}
                className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-300"
              >
                {REFRESH_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Preview */}
          {result && (
            <div className="border border-zinc-800 rounded-md p-2 max-h-64 overflow-auto">
              {chartType === "table" ? (
                <QueryResultTable
                  columns={result.columns}
                  rows={result.rows}
                  rowCount={result.row_count}
                  truncated={result.truncated}
                  executionTimeMs={result.execution_time_ms}
                />
              ) : (
                <QueryResultChart
                  columns={result.columns}
                  rows={result.rows}
                  initialChartType={chartType}
                  initialXColumn={xColumn || undefined}
                  initialYColumns={yColumns.length > 0 ? yColumns : undefined}
                  initialGroupBy={groupByCol || undefined}
                  hideControls
                />
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 p-4 border-t border-zinc-800">
          <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handleSave} disabled={!sqlText.trim()}>
            {initial ? "Save" : "Add Widget"}
          </Button>
        </div>
      </div>
    </div>
  );
}
