import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Play, ChevronRight, ChevronDown, Table2, Database, Save } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { SqlEditor } from "@/components/SqlEditor.tsx";
import { QueryResultTable } from "@/components/QueryResultTable.tsx";
import { QueryResultChart } from "@/components/QueryResultChart.tsx";
import {
  useAnalyticsTables, useExecuteQuery,
  useAnalyticsDashboards, useCreateAnalyticsDashboard, useUpdateAnalyticsDashboard,
} from "@/api/hooks.ts";
import type { QueryResult } from "@/types/api.ts";

export function SQLExplorerPage() {
  const navigate = useNavigate();
  const [sqlText, setSqlText] = useState(
    "SELECT device_name, state, rtt_ms, executed_at\nFROM availability_latency_latest FINAL\nWHERE device_name != ''\nORDER BY executed_at DESC\nLIMIT 100"
  );
  const [resultTab, setResultTab] = useState<"table" | "chart">("table");
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());
  const [showSaveMenu, setShowSaveMenu] = useState(false);
  const [chartSettings, setChartSettings] = useState<{ chartType: string; xColumn: string; yColumns: string[]; groupBy: string }>({ chartType: "line", xColumn: "", yColumns: [], groupBy: "" });

  const { data: tables } = useAnalyticsTables();
  const executeMut = useExecuteQuery();
  const { data: dashboards } = useAnalyticsDashboards();
  const createDashMut = useCreateAnalyticsDashboard();
  const updateDashMut = useUpdateAnalyticsDashboard();

  const result: QueryResult | undefined = executeMut.data?.data;

  const schema = useMemo(() => {
    if (!tables) return undefined;
    const s: Record<string, string[]> = {};
    for (const t of tables) {
      s[t.name] = t.columns.map((c) => c.name);
    }
    return s;
  }, [tables]);

  function handleExecute() {
    if (!sqlText.trim()) return;
    executeMut.mutate({ sql: sqlText, limit: 1000 });
  }

  function toggleTable(name: string) {
    setExpandedTables((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function insertTableName(name: string) {
    setSqlText((prev) => {
      const trimmed = prev.trimEnd();
      if (trimmed.endsWith("FROM") || trimmed.endsWith("JOIN") || trimmed.endsWith("from") || trimmed.endsWith("join")) {
        return `${trimmed} ${name}`;
      }
      return prev + name;
    });
  }

  function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] gap-0">
      {/* Schema browser sidebar */}
      <div className="w-64 shrink-0 border-r border-zinc-800 overflow-y-auto bg-zinc-950 p-3">
        <div className="flex items-center gap-2 mb-3">
          <Database className="h-4 w-4 text-zinc-500" />
          <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">Schema</span>
        </div>
        {tables?.map((t) => (
          <div key={t.name} className="mb-1">
            <button
              onClick={() => toggleTable(t.name)}
              className="flex items-center gap-1 w-full text-left text-xs hover:text-zinc-200 text-zinc-400 py-0.5"
            >
              {expandedTables.has(t.name)
                ? <ChevronDown className="h-3 w-3 shrink-0" />
                : <ChevronRight className="h-3 w-3 shrink-0" />
              }
              <Table2 className="h-3 w-3 shrink-0 text-zinc-600" />
              <span
                className="truncate cursor-pointer hover:text-brand-400"
                onClick={(e) => { e.stopPropagation(); insertTableName(t.name); }}
                title={`${t.total_rows?.toLocaleString() || 0} rows, ${formatBytes(t.total_bytes || 0)}`}
              >
                {t.name}
              </span>
            </button>
            {expandedTables.has(t.name) && (
              <div className="ml-5 border-l border-zinc-800 pl-2">
                {t.columns.map((col) => (
                  <div
                    key={col.name}
                    className="flex items-center gap-1 text-[11px] py-0.5 text-zinc-500 hover:text-zinc-300 cursor-pointer"
                    onClick={() => setSqlText((prev) => prev + col.name)}
                    title={col.type}
                  >
                    <span className="truncate">{col.name}</span>
                    <span className="text-zinc-700 text-[9px] ml-auto shrink-0">{col.type}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Main area: editor + results */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* SQL Editor */}
        <div className="p-3 pb-0 shrink-0">
          <div className="flex items-center gap-2 mb-2">
            <Button
              size="sm"
              onClick={handleExecute}
              disabled={executeMut.isPending || !sqlText.trim()}
              className="gap-1.5"
            >
              {executeMut.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              Run
            </Button>
            <span className="text-[10px] text-zinc-600">Ctrl+Enter to execute</span>
            {result && (
              <div className="relative ml-auto">
                <Button size="sm" variant="outline" onClick={() => setShowSaveMenu(!showSaveMenu)} className="gap-1">
                  <Save className="h-3.5 w-3.5" />
                  Save to Dashboard
                </Button>
                {showSaveMenu && (
                  <div className="absolute right-0 top-full mt-1 z-20 bg-zinc-800 border border-zinc-700 rounded-md shadow-lg min-w-48 py-1">
                    {(dashboards || []).map((d) => (
                      <button
                        key={d.id}
                        onClick={async () => {
                          await updateDashMut.mutateAsync({
                            id: d.id,
                            widgets: [...([] as { title: string; config: Record<string, unknown>; layout: Record<string, number> }[]),
                              {
                                title: sqlText.slice(0, 50),
                                config: {
                                  sql: sqlText,
                                  chart_type: resultTab === "chart" ? chartSettings.chartType : "table",
                                  x_column: resultTab === "chart" ? chartSettings.xColumn : undefined,
                                  y_columns: resultTab === "chart" ? chartSettings.yColumns : undefined,
                                  group_by: resultTab === "chart" ? chartSettings.groupBy : undefined,
                                },
                                layout: { x: 0, y: 99, w: 12, h: 6 },
                              },
                            ],
                          });
                          setShowSaveMenu(false);
                          navigate(`/analytics/dashboards/${d.id}`);
                        }}
                        className="w-full text-left px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700"
                      >
                        {d.name}
                      </button>
                    ))}
                    <div className="border-t border-zinc-700 mt-1 pt-1">
                      <button
                        onClick={async () => {
                          const name = prompt("Dashboard name:");
                          if (!name) return;
                          const res = await createDashMut.mutateAsync({ name });
                          const newId = res.data.id;
                          await updateDashMut.mutateAsync({
                            id: newId,
                            widgets: [{
                              title: sqlText.slice(0, 50),
                              config: {
                                sql: sqlText,
                                chart_type: resultTab === "chart" ? chartSettings.chartType : "table",
                                x_column: resultTab === "chart" ? chartSettings.xColumn : undefined,
                                y_columns: resultTab === "chart" ? chartSettings.yColumns : undefined,
                                group_by: resultTab === "chart" ? chartSettings.groupBy : undefined,
                              },
                              layout: { x: 0, y: 0, w: 12, h: 6 },
                            }],
                          });
                          setShowSaveMenu(false);
                          navigate(`/analytics/dashboards/${newId}`);
                        }}
                        className="w-full text-left px-3 py-1.5 text-xs text-brand-400 hover:bg-zinc-700"
                      >
                        + New Dashboard
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
          <SqlEditor
            value={sqlText}
            onChange={setSqlText}
            onExecute={handleExecute}
            schema={schema}
            height="180px"
          />
        </div>

        {/* Error banner */}
        {executeMut.isError && (
          <div className="mx-3 mt-2 p-2 rounded bg-red-950/50 border border-red-900/50 text-xs text-red-400">
            {(executeMut.error as Error)?.message || "Query failed"}
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="flex-1 flex flex-col min-h-0 p-3">
            {/* Tab switcher */}
            <div className="flex gap-1 mb-2">
              {(["table", "chart"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setResultTab(tab)}
                  className={`px-3 py-1 text-xs rounded capitalize ${
                    resultTab === tab
                      ? "bg-zinc-800 text-zinc-200"
                      : "text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-auto">
              {resultTab === "table" ? (
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
                  onSettingsChange={(s) => setChartSettings(s)}
                />
              )}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!result && !executeMut.isPending && !executeMut.isError && (
          <div className="flex-1 flex items-center justify-center text-zinc-600 text-sm">
            Write a SQL query and press Run or Ctrl+Enter
          </div>
        )}

        {/* Loading state */}
        {executeMut.isPending && (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
          </div>
        )}
      </div>
    </div>
  );
}
