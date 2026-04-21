import { useState, useEffect, useMemo, useCallback } from "react";
import { BarChart2, Loader2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Input } from "@/components/ui/input.tsx";
import {
  TimeRangePicker,
  rangeToTimestamps,
} from "@/components/TimeRangePicker.tsx";
import type { TimeRangeValue } from "@/components/TimeRangePicker.tsx";
import { PerformanceChart } from "@/components/PerformanceChart.tsx";
import { usePerformanceHistory, usePerformanceSummary } from "@/api/hooks.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { DEFAULT_RANGE } from "../_shared/constants.ts";

export function PerformanceTab({ deviceId }: { deviceId: string }) {
  const tz = useTimezone();
  const [timeRange, setTimeRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const [baseRange, setBaseRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const [isZoomed, setIsZoomed] = useState(false);
  const { fromTs, toTs } = useMemo(
    () => rangeToTimestamps(timeRange),
    [timeRange],
  );
  const handleChartZoom = useCallback(
    (fromMs: number, toMs: number) => {
      if (!isZoomed) setBaseRange(timeRange);
      setTimeRange({
        type: "absolute",
        fromTs: new Date(fromMs).toISOString(),
        toTs: new Date(toMs).toISOString(),
      });
      setIsZoomed(true);
    },
    [isZoomed, timeRange],
  );
  const handleResetZoom = useCallback(() => {
    setTimeRange(baseRange);
    setIsZoomed(false);
  }, [baseRange]);
  const handleTimeRangeChange = useCallback((v: TimeRangeValue) => {
    setTimeRange(v);
    setBaseRange(v);
    setIsZoomed(false);
  }, []);

  const { data: summary, isLoading: summaryLoading } =
    usePerformanceSummary(deviceId);

  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);
  const [selectedComponentType, setSelectedComponentType] = useState<
    string | null
  >(null);
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null);
  const [selectedComponents, setSelectedComponents] = useState<string[]>([]);
  const [componentFilter, setComponentFilter] = useState("");

  useEffect(() => {
    if (summary?.length && !selectedAppId) {
      const first = summary[0];
      setSelectedAppId(first.app_id);
      const ctKeys = Object.keys(first.component_types).sort();
      if (ctKeys.length) {
        setSelectedComponentType(ctKeys[0]);
        const ct = first.component_types[ctKeys[0]];
        if (ct.metric_names.length) setSelectedMetric(ct.metric_names[0]);
        setSelectedComponents(ct.components.slice(0, 10));
      }
    }
  }, [summary, selectedAppId]);

  const currentApp = summary?.find((a) => a.app_id === selectedAppId);
  const currentCT =
    currentApp && selectedComponentType
      ? currentApp.component_types[selectedComponentType]
      : null;
  const availableComponents = currentCT?.components ?? [];
  const availableMetrics = currentCT?.metric_names ?? [];

  const { data: perfData, isLoading: dataLoading } = usePerformanceHistory(
    deviceId,
    fromTs,
    toTs,
    selectedAppId,
    selectedComponentType,
    selectedComponents.length ? selectedComponents : null,
    5000,
  );

  const filteredComponents = useMemo(() => {
    if (!componentFilter) return availableComponents;
    const q = componentFilter.toLowerCase();
    return availableComponents.filter((c) => c.toLowerCase().includes(q));
  }, [availableComponents, componentFilter]);

  const toggleComponent = (comp: string) => {
    setSelectedComponents((prev) =>
      prev.includes(comp) ? prev.filter((c) => c !== comp) : [...prev, comp],
    );
  };
  const selectAll = () => {
    setSelectedComponents((prev) => {
      const s = new Set(prev);
      filteredComponents.forEach((c) => s.add(c));
      return [...s];
    });
  };
  const selectNone = () => {
    setSelectedComponents((prev) =>
      prev.filter((c) => !filteredComponents.includes(c)),
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-zinc-300">
            Performance Metrics
          </h3>
          {isZoomed && (
            <button
              onClick={handleResetZoom}
              className="text-xs text-brand-400 hover:text-brand-300 cursor-pointer"
            >
              Reset zoom
            </button>
          )}
        </div>
        <TimeRangePicker value={timeRange} onChange={handleTimeRangeChange} />
      </div>

      {summaryLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
        </div>
      ) : !summary?.length ? (
        <Card>
          <CardContent>
            <div className="flex flex-col items-center justify-center py-12 text-zinc-600">
              <BarChart2 className="h-8 w-8 text-zinc-700 mb-2" />
              <p className="text-sm text-zinc-500">
                No performance data collected for this device yet.
              </p>
              <p className="text-xs text-zinc-700 mt-1">
                Assign a performance monitoring app to start collecting metrics.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="flex gap-4">
          <div className="w-64 shrink-0 space-y-3">
            <Card>
              <CardHeader className="py-2 px-3">
                <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">
                  App
                </CardTitle>
              </CardHeader>
              <CardContent className="px-3 pb-3 space-y-1">
                {summary.map((app) => (
                  <button
                    key={app.app_id}
                    onClick={() => {
                      setSelectedAppId(app.app_id);
                      const ctKeys = Object.keys(app.component_types).sort();
                      if (ctKeys.length) {
                        setSelectedComponentType(ctKeys[0]);
                        const ct = app.component_types[ctKeys[0]];
                        setSelectedMetric(ct.metric_names[0] ?? null);
                        setSelectedComponents(ct.components.slice(0, 10));
                        setComponentFilter("");
                      }
                    }}
                    className={`w-full text-left px-2 py-1.5 rounded text-sm transition-colors cursor-pointer ${
                      selectedAppId === app.app_id
                        ? "bg-brand-500/20 text-brand-400"
                        : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
                    }`}
                  >
                    {app.app_name}
                  </button>
                ))}
              </CardContent>
            </Card>

            {currentApp &&
              Object.keys(currentApp.component_types).length > 1 && (
                <Card>
                  <CardHeader className="py-2 px-3">
                    <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">
                      Type
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="px-3 pb-3 space-y-1">
                    {Object.keys(currentApp.component_types)
                      .sort()
                      .map((ct) => (
                        <button
                          key={ct}
                          onClick={() => {
                            setSelectedComponentType(ct);
                            const entry = currentApp.component_types[ct];
                            setSelectedMetric(entry.metric_names[0] ?? null);
                            setSelectedComponents(
                              entry.components.slice(0, 10),
                            );
                            setComponentFilter("");
                          }}
                          className={`w-full text-left px-2 py-1.5 rounded text-sm transition-colors cursor-pointer ${
                            selectedComponentType === ct
                              ? "bg-zinc-700 text-zinc-200"
                              : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800"
                          }`}
                        >
                          {ct}
                        </button>
                      ))}
                  </CardContent>
                </Card>
              )}

            {availableMetrics.length > 1 && (
              <Card>
                <CardHeader className="py-2 px-3">
                  <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">
                    Metric
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-3 pb-3 space-y-1">
                  {availableMetrics.map((m) => (
                    <button
                      key={m}
                      onClick={() => setSelectedMetric(m)}
                      className={`w-full text-left px-2 py-1.5 rounded text-sm font-mono transition-colors cursor-pointer ${
                        selectedMetric === m
                          ? "bg-zinc-700 text-zinc-200"
                          : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800"
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </CardContent>
              </Card>
            )}

            {availableComponents.length > 0 && (
              <Card>
                <CardHeader className="py-2 px-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">
                      Components ({selectedComponents.length}/
                      {availableComponents.length})
                    </CardTitle>
                    <div className="flex gap-1">
                      <button
                        onClick={selectAll}
                        className="text-[10px] text-zinc-500 hover:text-zinc-300 px-1 cursor-pointer"
                      >
                        All
                      </button>
                      <button
                        onClick={selectNone}
                        className="text-[10px] text-zinc-500 hover:text-zinc-300 px-1 cursor-pointer"
                      >
                        None
                      </button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="px-3 pb-3">
                  {availableComponents.length > 15 && (
                    <div className="mb-2">
                      <Input
                        placeholder="Filter components..."
                        value={componentFilter}
                        onChange={(e) => setComponentFilter(e.target.value)}
                        className="h-7 text-xs bg-zinc-800 border-zinc-700"
                      />
                    </div>
                  )}
                  <div className="max-h-64 overflow-y-auto space-y-0.5">
                    {filteredComponents.length === 0 ? (
                      <p className="text-xs text-zinc-600 px-1 py-2">
                        No match
                      </p>
                    ) : (
                      filteredComponents.map((comp) => (
                        <label
                          key={comp}
                          className="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-zinc-800 cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={selectedComponents.includes(comp)}
                            onChange={() => toggleComponent(comp)}
                            className="accent-brand-500 h-3.5 w-3.5"
                          />
                          <span className="text-xs text-zinc-400 font-mono truncate">
                            {comp}
                          </span>
                        </label>
                      ))
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          <div className="flex-1 min-w-0">
            <Card>
              <CardContent className="pt-4">
                {dataLoading ? (
                  <div className="flex items-center justify-center h-72">
                    <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
                  </div>
                ) : selectedMetric && perfData ? (
                  <PerformanceChart
                    data={perfData}
                    selectedComponents={selectedComponents}
                    metricName={selectedMetric}
                    timezone={tz}
                    unit={
                      selectedMetric.includes("pct")
                        ? "%"
                        : selectedMetric.includes("_ms")
                          ? "ms"
                          : selectedMetric.includes("_bytes")
                            ? "B"
                            : ""
                    }
                    title={`${selectedComponentType ?? ""} — ${selectedMetric ?? ""}`}
                    onZoom={handleChartZoom}
                  />
                ) : (
                  <div className="flex items-center justify-center h-72 text-zinc-600 text-sm">
                    Select a metric and components to visualize.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
