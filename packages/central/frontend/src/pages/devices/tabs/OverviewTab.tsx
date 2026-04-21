import { useState, useMemo, useCallback } from "react";
import { Clock, Loader2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { AvailabilityChart } from "@/components/AvailabilityChart.tsx";
import {
  TimeRangePicker,
  rangeToTimestamps,
} from "@/components/TimeRangePicker.tsx";
import type { TimeRangeValue } from "@/components/TimeRangePicker.tsx";
import { useAvailabilityHistory, useDeviceResults } from "@/api/hooks.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { DEFAULT_RANGE } from "../_shared/constants.ts";

export function OverviewTab({ deviceId }: { deviceId: string }) {
  const tz = useTimezone();
  const [timeRange, setTimeRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const [baseRange, setBaseRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const [isZoomed, setIsZoomed] = useState(false);
  const { fromTs, toTs } = useMemo(
    () => rangeToTimestamps(timeRange),
    [timeRange],
  );
  const { data: deviceResults } = useDeviceResults(deviceId);
  const { data: history, isLoading: histLoading } = useAvailabilityHistory(
    deviceId,
    fromTs,
    toTs,
    5000,
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

  const STALE_THRESHOLD_MS = 15 * 60 * 1000;
  const staleSince = useMemo(() => {
    if (!deviceResults?.checks?.length) return null;
    const monitoringChecks = deviceResults.checks.filter(
      (c) => c.role === "availability" || c.role === "latency",
    );
    if (!monitoringChecks.length) return null;
    const latest = monitoringChecks.reduce((newest: number, check) => {
      const okTs =
        check.last_success_at ||
        (check.error_category ? null : check.executed_at);
      if (!okTs) return newest;
      const ts = new Date(okTs).getTime();
      return ts > newest ? ts : newest;
    }, 0);
    if (latest === 0) return null;
    const ageMs = Date.now() - latest;
    return ageMs > STALE_THRESHOLD_MS ? new Date(latest) : null;
  }, [deviceResults]);

  return (
    <div className="space-y-4">
      {staleSince && (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
          <Clock className="h-4 w-4 flex-shrink-0" />
          <span>
            No data received since{" "}
            <span className="font-medium text-amber-200">
              {formatDate(staleSince.toISOString(), tz)}
            </span>{" "}
            ({timeAgo(staleSince.toISOString())}). Check collector connectivity
            and assignment status.
          </span>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-zinc-400">
            Availability &amp; Latency
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
        <TimeRangePicker
          value={timeRange}
          onChange={handleTimeRangeChange}
          timezone={tz}
        />
      </div>

      <Card>
        <CardContent className="pt-4">
          {histLoading ? (
            <div className="flex h-48 items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            </div>
          ) : (
            <AvailabilityChart
              results={history ?? []}
              fromTs={fromTs}
              toTs={toTs}
              timezone={tz}
              onZoom={handleChartZoom}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-zinc-400 text-sm">
            Incidents &amp; Alerts
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-8 text-zinc-600">
            <p className="text-sm">
              Incident log and alert history coming in a future update.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
