import { useState, useMemo, useCallback } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  X,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { StatusBadge } from "@/components/StatusBadge.tsx";
import {
  TimeRangePicker,
  rangeToTimestamps,
} from "@/components/TimeRangePicker.tsx";
import type { TimeRangeValue } from "@/components/TimeRangePicker.tsx";
import {
  useDeviceAssignments,
  useDeviceChecksSummary,
  useDeviceHistory,
  useDeviceResults,
} from "@/api/hooks.ts";
import type { CheckResult } from "@/types/api.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

type SortDir = "asc" | "desc";

function SortableHead({
  label,
  field,
  sortBy,
  sortDir,
  onSort,
  title,
}: {
  label: string;
  field: string;
  sortBy: string;
  sortDir: SortDir;
  onSort: (field: string) => void;
  title?: string;
}) {
  const active = sortBy === field;
  return (
    <TableHead
      className="cursor-pointer select-none hover:text-zinc-200"
      onClick={() => onSort(field)}
      title={title}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          sortDir === "asc" ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 text-zinc-600" />
        )}
      </span>
    </TableHead>
  );
}

function useSort(defaultField: string, defaultDir: SortDir = "desc") {
  const [sortBy, setSortBy] = useState(defaultField);
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir);
  const toggle = useCallback(
    (field: string) => {
      if (field === sortBy) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortBy(field);
        setSortDir("desc");
      }
    },
    [sortBy],
  );
  return { sortBy, sortDir, toggle };
}

const STATE_SEVERITY: Record<string, number> = {
  CRITICAL: 4,
  WARNING: 3,
  UNKNOWN: 2,
  OK: 1,
  "": 0,
};

const FALLBACK_FRESH_MS = 120_000;
const FALLBACK_STALE_MS = 600_000;

function freshnessThresholds(intervalSeconds: number | undefined): {
  freshMs: number;
  staleMs: number;
} {
  if (!intervalSeconds || intervalSeconds <= 0) {
    return { freshMs: FALLBACK_FRESH_MS, staleMs: FALLBACK_STALE_MS };
  }
  const ms = intervalSeconds * 1000;
  return { freshMs: ms * 1.5, staleMs: ms * 3 };
}

function freshnessInfo(
  executedAt: string | null | undefined,
  _hasError: boolean,
  intervalSeconds?: number,
): { label: string; color: string; ageMs: number | null; staleMs: number } {
  const { freshMs, staleMs } = freshnessThresholds(intervalSeconds);
  if (!executedAt) {
    return { label: "never", color: "text-zinc-500", ageMs: null, staleMs };
  }
  const age = Date.now() - new Date(executedAt).getTime();
  const hue =
    age < freshMs
      ? "text-green-400"
      : age < staleMs
        ? "text-amber-400"
        : "text-red-400";
  return { label: formatAgeShort(age), color: hue, ageMs: age, staleMs };
}

function formatAgeShort(ms: number): string {
  if (ms < 0) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

function ErrorCategoryChip({ category }: { category: string | undefined }) {
  if (!category) return <span className="text-zinc-600 text-xs">—</span>;
  const palette: Record<string, string> = {
    device: "bg-red-900/40 text-red-300 border-red-700/60",
    config: "bg-amber-900/40 text-amber-300 border-amber-700/60",
    app: "bg-purple-900/40 text-purple-300 border-purple-700/60",
  };
  const klass =
    palette[category] || "bg-zinc-800 text-zinc-300 border-zinc-700";
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${klass}`}
    >
      {category}
    </span>
  );
}

function stateBucketColor(worstState: number): string {
  if (worstState === 0) return "#22c55e";
  if (worstState === 1) return "#f59e0b";
  if (worstState === 2) return "#ef4444";
  return "#71717a";
}

function CheckStatusSparkline({
  buckets,
  hours = 24,
}: {
  buckets: { ts_ms: number; worst_state: number }[] | undefined;
  hours?: number;
}) {
  const now = Date.now();
  const hourMs = 3_600_000;
  const currentHour = Math.floor(now / hourMs) * hourMs;
  const slots: { ts: number; color: string; label: string }[] = [];
  const byTs = new Map<number, number>();
  (buckets ?? []).forEach((b) => byTs.set(b.ts_ms, b.worst_state));
  for (let i = hours - 1; i >= 0; i--) {
    const ts = currentHour - i * hourMs;
    const state = byTs.get(ts);
    if (state == null) {
      slots.push({ ts, color: "#27272a", label: "no data" });
    } else {
      slots.push({
        ts,
        color: stateBucketColor(state),
        label: ["OK", "WARNING", "CRITICAL", "UNKNOWN"][state] ?? "UNKNOWN",
      });
    }
  }
  return (
    <div className="flex h-4 gap-[1px]" title={`Last ${hours}h`}>
      {slots.map((s) => {
        const start = new Date(s.ts);
        const end = new Date(s.ts + hourMs);
        const fmt = (d: Date) =>
          d.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          });
        return (
          <div
            key={s.ts}
            className="flex-1 rounded-[1px]"
            style={{ backgroundColor: s.color, minWidth: 2 }}
            title={`${fmt(start)}–${fmt(end)} — ${s.label}`}
          />
        );
      })}
    </div>
  );
}

function LiveChecksFilters({
  checks,
  filterApp,
  setFilterApp,
  filterStatus,
  setFilterStatus,
  filterCollector,
  setFilterCollector,
  filterError,
  setFilterError,
  staleOnly,
  setStaleOnly,
}: {
  checks: CheckResult[];
  filterApp: string;
  setFilterApp: (v: string) => void;
  filterStatus: string;
  setFilterStatus: (v: string) => void;
  filterCollector: string;
  setFilterCollector: (v: string) => void;
  filterError: string;
  setFilterError: (v: string) => void;
  staleOnly: boolean;
  setStaleOnly: (v: boolean) => void;
}) {
  const appNames = [
    ...new Set(checks.map((c) => c.app_name).filter(Boolean)),
  ].sort();
  const statuses = [
    ...new Set(checks.map((c) => c.state_name).filter(Boolean)),
  ].sort();
  const collectors = [
    ...new Set(checks.map((c) => c.collector_name).filter(Boolean)),
  ].sort() as string[];
  const errorCats = [
    ...new Set(
      checks.map((c) => c.error_category || "").filter((c) => c && c !== ""),
    ),
  ].sort();
  const active =
    filterApp || filterStatus || filterCollector || filterError || staleOnly;
  return (
    <div className="flex items-center gap-2 pb-3 flex-wrap">
      <Select
        value={filterStatus}
        onChange={(e) => setFilterStatus(e.target.value)}
        className="w-32 text-xs"
      >
        <option value="">All States</option>
        {statuses.map((s) => (
          <option key={s} value={s!}>
            {s}
          </option>
        ))}
      </Select>
      <Select
        value={filterApp}
        onChange={(e) => setFilterApp(e.target.value)}
        className="w-40 text-xs"
      >
        <option value="">All Apps</option>
        {appNames.map((n) => (
          <option key={n} value={n!}>
            {n}
          </option>
        ))}
      </Select>
      <Select
        value={filterCollector}
        onChange={(e) => setFilterCollector(e.target.value)}
        className="w-40 text-xs"
      >
        <option value="">All Collectors</option>
        {collectors.map((c) => (
          <option key={c} value={c!}>
            {c}
          </option>
        ))}
      </Select>
      <Select
        value={filterError}
        onChange={(e) => setFilterError(e.target.value)}
        className="w-36 text-xs"
      >
        <option value="">All Errors</option>
        <option value="any">Any error</option>
        <option value="none">No error</option>
        {errorCats.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </Select>
      <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={staleOnly}
          onChange={(e) => setStaleOnly(e.target.checked)}
          className="accent-brand-500"
        />
        Stale only
      </label>
      {active && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setFilterApp("");
            setFilterStatus("");
            setFilterCollector("");
            setFilterError("");
            setStaleOnly(false);
          }}
        >
          <X className="h-3 w-3" /> Clear
        </Button>
      )}
    </div>
  );
}

function LiveChecksTable({
  checks,
  checksSummary,
  intervalByAssignment,
  tz,
  sortBy,
  sortDir,
  onSort,
  filterApp,
  filterStatus,
  filterCollector,
  filterError,
  staleOnly,
}: {
  checks: CheckResult[];
  checksSummary:
    | Record<string, { ts_ms: number; worst_state: number; count: number }[]>
    | undefined;
  intervalByAssignment: Map<string, number>;
  tz: string;
  sortBy: string;
  sortDir: "asc" | "desc";
  onSort: (f: string) => void;
  filterApp: string;
  filterStatus: string;
  filterCollector: string;
  filterError: string;
  staleOnly: boolean;
}) {
  const rows = useMemo(() => {
    let data = checks;
    if (filterApp) data = data.filter((c) => c.app_name === filterApp);
    if (filterStatus) data = data.filter((c) => c.state_name === filterStatus);
    if (filterCollector)
      data = data.filter((c) => c.collector_name === filterCollector);
    if (filterError) {
      if (filterError === "any") data = data.filter((c) => !!c.error_category);
      else if (filterError === "none")
        data = data.filter((c) => !c.error_category);
      else data = data.filter((c) => c.error_category === filterError);
    }
    if (staleOnly) {
      data = data.filter((c) => {
        const age = c.executed_at
          ? Date.now() - new Date(c.executed_at).getTime()
          : Infinity;
        const { staleMs } = freshnessThresholds(
          intervalByAssignment.get(c.assignment_id),
        );
        const successAge = c.last_success_at
          ? Date.now() - new Date(c.last_success_at).getTime()
          : Number.POSITIVE_INFINITY;
        const sustainedFailure = !!c.error_category && successAge > staleMs;
        return age > staleMs || sustainedFailure;
      });
    }
    return [...data].sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case "severity":
          cmp =
            (STATE_SEVERITY[b.state_name] ?? 0) -
            (STATE_SEVERITY[a.state_name] ?? 0);
          break;
        case "app":
          cmp = (a.app_name ?? "").localeCompare(b.app_name ?? "");
          break;
        case "fresh": {
          const ageA = a.executed_at
            ? Date.now() - new Date(a.executed_at).getTime()
            : Number.POSITIVE_INFINITY;
          const ageB = b.executed_at
            ? Date.now() - new Date(b.executed_at).getTime()
            : Number.POSITIVE_INFINITY;
          cmp = ageA - ageB;
          break;
        }
        case "runtime":
          cmp = (a.execution_time_ms ?? 0) - (b.execution_time_ms ?? 0);
          break;
        case "collector":
          cmp = (a.collector_name ?? "").localeCompare(b.collector_name ?? "");
          break;
        case "error":
          cmp = (a.error_category ?? "").localeCompare(b.error_category ?? "");
          break;
        case "last_success": {
          const tA = a.last_success_at
            ? new Date(a.last_success_at).getTime()
            : 0;
          const tB = b.last_success_at
            ? new Date(b.last_success_at).getTime()
            : 0;
          cmp = tA - tB;
          break;
        }
      }
      if (sortBy === "severity") return sortDir === "desc" ? cmp : -cmp;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [
    checks,
    filterApp,
    filterStatus,
    filterCollector,
    filterError,
    staleOnly,
    sortBy,
    sortDir,
    intervalByAssignment,
  ]);

  if (rows.length === 0) {
    return (
      <p className="text-sm text-zinc-500 py-8 text-center">
        No checks match the current filters.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <SortableHead
            label="State"
            field="severity"
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={onSort}
          />
          <SortableHead
            label="Freshness"
            field="fresh"
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={onSort}
          />
          <SortableHead
            label="App"
            field="app"
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={onSort}
          />
          <TableHead>Output</TableHead>
          <SortableHead
            label="Error"
            field="error"
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={onSort}
          />
          <SortableHead
            label="Runtime"
            field="runtime"
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={onSort}
          />
          <SortableHead
            label="Last Success"
            field="last_success"
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={onSort}
          />
          <TableHead>24h</TableHead>
          <SortableHead
            label="Collector"
            field="collector"
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={onSort}
            title="Collector that executed the most recent poll. Unpinned assignments dispatch via consistent hashing within the group so this can change between polls."
          />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((check) => {
          const hasError = !!check.error_category;
          const interval = intervalByAssignment.get(check.assignment_id);
          const fresh = freshnessInfo(check.executed_at, hasError, interval);
          const buckets = checksSummary?.[check.assignment_id];
          const successAgeMs = check.last_success_at
            ? Date.now() - new Date(check.last_success_at).getTime()
            : Number.POSITIVE_INFINITY;
          const sustainedFailure = hasError && successAgeMs > fresh.staleMs;
          const overdue = fresh.ageMs != null && fresh.ageMs > fresh.staleMs;
          const transientError = hasError && !sustainedFailure;
          const rowBg = sustainedFailure
            ? "bg-red-950/20"
            : overdue || transientError
              ? "bg-amber-950/20"
              : "";
          return (
            <TableRow key={check.assignment_id} className={rowBg}>
              <TableCell>
                <StatusBadge state={check.state_name} />
              </TableCell>
              <TableCell className="text-xs font-mono">
                <span
                  className={fresh.color}
                  title={
                    check.executed_at
                      ? `Last attempt: ${formatDate(check.executed_at, tz)}`
                      : "No attempt recorded"
                  }
                >
                  {fresh.label}
                </span>
              </TableCell>
              <TableCell className="font-medium text-zinc-200">
                {check.app_name}
              </TableCell>
              <TableCell
                className="max-w-[220px] truncate text-zinc-400 text-sm"
                title={check.output || check.error_message || ""}
              >
                {check.output || check.error_message || "—"}
              </TableCell>
              <TableCell>
                <ErrorCategoryChip category={check.error_category} />
              </TableCell>
              <TableCell className="font-mono text-xs text-zinc-400">
                {check.execution_time_ms != null
                  ? `${Math.round(check.execution_time_ms)}ms`
                  : "—"}
              </TableCell>
              <TableCell className="text-xs text-zinc-500">
                {check.last_success_at ? (
                  <span
                    title={formatDate(check.last_success_at, tz)}
                    className={hasError ? "text-amber-500" : "text-zinc-400"}
                  >
                    {timeAgo(check.last_success_at)}
                  </span>
                ) : (
                  <span className="text-red-400">never</span>
                )}
              </TableCell>
              <TableCell className="w-36">
                <CheckStatusSparkline buckets={buckets} hours={24} />
              </TableCell>
              <TableCell className="text-zinc-400 text-xs">
                {check.collector_name ?? "—"}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function ChecksTab({ deviceId }: { deviceId: string }) {
  const tz = useTimezone();
  const [mode, setMode] = useState<"live" | "history">("live");

  const { data: deviceResults, isLoading: liveLoading } =
    useDeviceResults(deviceId);
  const { data: checksSummary } = useDeviceChecksSummary(deviceId, 24);
  const { data: assignments } = useDeviceAssignments(deviceId);
  const intervalByAssignment = useMemo(() => {
    const m = new Map<string, number>();
    for (const a of assignments ?? []) {
      if (a.schedule_type === "interval") {
        const n = Number(a.schedule_value);
        if (Number.isFinite(n) && n > 0) m.set(a.id, n);
      }
    }
    return m;
  }, [assignments]);

  const [liveFilterApp, setLiveFilterApp] = useState("");
  const [liveFilterStatus, setLiveFilterStatus] = useState("");
  const [liveFilterCollector, setLiveFilterCollector] = useState("");
  const [liveFilterError, setLiveFilterError] = useState("");
  const [liveStaleOnly, setLiveStaleOnly] = useState(false);
  const {
    sortBy: liveSortBy,
    sortDir: liveSortDir,
    toggle: liveOnSort,
  } = useSort("severity");

  const [range, setRange] = useState<TimeRangeValue>({
    type: "preset",
    preset: "24h",
  });
  const { fromTs: from } = useMemo(() => rangeToTimestamps(range), [range]);
  const { data: history, isLoading: histLoading } = useDeviceHistory(
    deviceId,
    from,
    null,
    500,
  );
  const { sortBy, sortDir, toggle: onSort } = useSort("executed_at");
  const [filterApp, setFilterApp] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterCollector, setFilterCollector] = useState("");

  const records = history ?? [];

  const appNames = useMemo(
    () => [...new Set(records.map((r) => r.app_name).filter(Boolean))].sort(),
    [records],
  );
  const statuses = useMemo(
    () => [...new Set(records.map((r) => r.state_name).filter(Boolean))].sort(),
    [records],
  );
  const collectors = useMemo(
    () =>
      [...new Set(records.map((r) => r.collector_name).filter(Boolean))].sort(),
    [records],
  );

  const filtered = useMemo(() => {
    let data = records;
    if (filterApp) data = data.filter((r) => r.app_name === filterApp);
    if (filterStatus) data = data.filter((r) => r.state_name === filterStatus);
    if (filterCollector)
      data = data.filter((r) => r.collector_name === filterCollector);
    return [...data].sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case "app_name":
          cmp = (a.app_name ?? "").localeCompare(b.app_name ?? "");
          break;
        case "started_at":
          cmp = (a.started_at ?? "").localeCompare(b.started_at ?? "");
          break;
        case "executed_at":
          cmp = a.executed_at.localeCompare(b.executed_at);
          break;
        case "duration":
          cmp = (a.execution_time_ms ?? 0) - (b.execution_time_ms ?? 0);
          break;
        case "collector":
          cmp = (a.collector_name ?? "").localeCompare(b.collector_name ?? "");
          break;
        case "status":
          cmp = (a.state_name ?? "").localeCompare(b.state_name ?? "");
          break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [records, filterApp, filterStatus, filterCollector, sortBy, sortDir]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Checks
            {mode === "live" && deviceResults && (
              <Badge variant="default" className="ml-1 text-xs">
                {deviceResults.checks.length}
              </Badge>
            )}
            {mode === "history" && (
              <span className="text-zinc-500 font-normal text-xs ml-1">
                ({filtered.length}
                {filtered.length !== records.length
                  ? ` of ${records.length}`
                  : ""}{" "}
                results)
              </span>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border border-zinc-700 overflow-hidden text-xs">
              <button
                onClick={() => setMode("live")}
                className={`px-3 py-1.5 transition-colors ${mode === "live" ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}
              >
                Live
              </button>
              <button
                onClick={() => setMode("history")}
                className={`px-3 py-1.5 transition-colors ${mode === "history" ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}
              >
                History
              </button>
            </div>
            {mode === "history" && (
              <TimeRangePicker
                value={range}
                onChange={setRange}
                timezone={tz}
              />
            )}
          </div>
        </div>
        {mode === "history" && (
          <div className="flex items-center gap-2 pt-2">
            <Select
              value={filterApp}
              onChange={(e) => setFilterApp(e.target.value)}
              className="w-40 text-xs"
            >
              <option value="">All Apps</option>
              {appNames.map((n) => (
                <option key={n} value={n!}>
                  {n}
                </option>
              ))}
            </Select>
            <Select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="w-36 text-xs"
            >
              <option value="">All Statuses</option>
              {statuses.map((s) => (
                <option key={s} value={s!}>
                  {s}
                </option>
              ))}
            </Select>
            <Select
              value={filterCollector}
              onChange={(e) => setFilterCollector(e.target.value)}
              className="w-40 text-xs"
            >
              <option value="">All Collectors</option>
              {collectors.map((c) => (
                <option key={c} value={c!}>
                  {c}
                </option>
              ))}
            </Select>
            {(filterApp || filterStatus || filterCollector) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setFilterApp("");
                  setFilterStatus("");
                  setFilterCollector("");
                }}
              >
                <X className="h-3 w-3" /> Clear
              </Button>
            )}
          </div>
        )}
      </CardHeader>
      <CardContent>
        {mode === "live" ? (
          liveLoading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
          ) : !deviceResults || deviceResults.checks.length === 0 ? (
            <p className="text-sm text-zinc-500 py-8 text-center">
              No checks configured. Add apps on the Settings tab.
            </p>
          ) : (
            <>
              <LiveChecksFilters
                checks={deviceResults.checks}
                filterApp={liveFilterApp}
                setFilterApp={setLiveFilterApp}
                filterStatus={liveFilterStatus}
                setFilterStatus={setLiveFilterStatus}
                filterCollector={liveFilterCollector}
                setFilterCollector={setLiveFilterCollector}
                filterError={liveFilterError}
                setFilterError={setLiveFilterError}
                staleOnly={liveStaleOnly}
                setStaleOnly={setLiveStaleOnly}
              />
              <LiveChecksTable
                checks={deviceResults.checks}
                checksSummary={checksSummary}
                intervalByAssignment={intervalByAssignment}
                tz={tz}
                sortBy={liveSortBy}
                sortDir={liveSortDir}
                onSort={liveOnSort}
                filterApp={liveFilterApp}
                filterStatus={liveFilterStatus}
                filterCollector={liveFilterCollector}
                filterError={liveFilterError}
                staleOnly={liveStaleOnly}
              />
            </>
          )
        ) : histLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-zinc-500 py-8 text-center">
            No results match the current filters.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <SortableHead
                  label="Status"
                  field="status"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <SortableHead
                  label="App"
                  field="app_name"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <TableHead>Output</TableHead>
                <SortableHead
                  label="Duration"
                  field="duration"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <SortableHead
                  label="Started"
                  field="started_at"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <SortableHead
                  label="Completed"
                  field="executed_at"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <SortableHead
                  label="Collector"
                  field="collector"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((r, i) => {
                const startedAt = r.started_at ? new Date(r.started_at) : null;
                const executedAt = new Date(r.executed_at);
                const durationMs =
                  r.execution_time_ms ??
                  (startedAt
                    ? executedAt.getTime() - startedAt.getTime()
                    : null);
                return (
                  <TableRow key={`${r.assignment_id}-${i}`}>
                    <TableCell>
                      <StatusBadge state={r.state_name} />
                    </TableCell>
                    <TableCell className="font-medium text-zinc-200">
                      {r.app_name ?? "—"}
                    </TableCell>
                    <TableCell
                      className="max-w-[200px] truncate text-zinc-400 text-sm"
                      title={r.output ?? ""}
                    >
                      {r.output || "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-300">
                      {durationMs != null ? `${Math.round(durationMs)}ms` : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-xs">
                      {startedAt
                        ? formatDate(startedAt.toISOString(), tz)
                        : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-xs">
                      {formatDate(r.executed_at, tz)}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {r.collector_name ?? "—"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
