import { useState, useEffect, useRef, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  Clock,
  FileText,
  Loader2,
  RefreshCw,
  Wrench,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { ConfigDataRenderer } from "@/components/ConfigDataRenderer.tsx";
import { formatInterval } from "@/components/IntervalInput";
import {
  useConfigChangelog,
  useConfigChangeTimestamps,
  useConfigCompare,
  useConfigDiff,
  useDeviceAssignments,
  useDeviceConfigData,
  useDeviceConfigTemplates,
  usePollConfigNow,
} from "@/api/hooks.ts";
import type { ConfigDiffEntry } from "@/types/api.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

export function ConfigurationTab({ deviceId }: { deviceId: string }) {
  const tz = useTimezone();
  const { data: configTemplates } = useDeviceConfigTemplates(deviceId);
  const { data: assignments } = useDeviceAssignments(deviceId);
  const [configView, setConfigView] = useState<
    "current" | "changes" | "compare"
  >("current");
  const [selectedConfigApp, setSelectedConfigApp] = useState<string | null>(
    null,
  );
  const pollNow = usePollConfigNow();
  const qc = useQueryClient();

  const [pollStatus, setPollStatus] = useState<
    "idle" | "polling" | "done" | "error"
  >("idle");
  const [pollRequestedAt, setPollRequestedAt] = useState<number | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const latestExecutedAtBefore = useRef<string | null>(null);
  const { data: configRows, isLoading } = useDeviceConfigData(deviceId);

  useEffect(() => {
    if (!pollRequestedAt) return;
    let tries = 0;
    const iv = setInterval(() => {
      tries++;
      qc.invalidateQueries({ queryKey: ["device-config-data", deviceId] });
      if (tries >= 15) {
        clearInterval(iv);
        setPollRequestedAt(null);
        setPollStatus("idle");
      }
    }, 2000);
    return () => clearInterval(iv);
  }, [pollRequestedAt, deviceId, qc]);

  useEffect(() => {
    if (!pollRequestedAt || !configRows?.length) return;
    const latestNow = configRows.reduce(
      (max: string, r: Record<string, unknown>) => {
        const ea = String(r.executed_at ?? "");
        return ea > max ? ea : max;
      },
      "",
    );
    if (latestNow && latestNow !== latestExecutedAtBefore.current) {
      setPollRequestedAt(null);
      setPollStatus("done");
      setTimeout(() => setPollStatus("idle"), 2500);
    }
  }, [configRows, pollRequestedAt]);

  const [changelogPage, setChangelogPage] = useState(0);
  const [filterKey, setFilterKey] = useState("");
  const [filterComponent, setFilterComponent] = useState("");
  const [filterValue, setFilterValue] = useState("");
  const [changeSortCol, setChangeSortCol] = useState<
    "time" | "component" | "key" | "value"
  >("time");
  const [changeSortDir, setChangeSortDir] = useState<"asc" | "desc">("desc");
  const PAGE_SIZE = 50;
  const { data: changelogResp } = useConfigChangelog(deviceId, {
    app_id: selectedConfigApp ?? undefined,
    config_key: filterKey || undefined,
    component: filterComponent || undefined,
    value: filterValue || undefined,
    limit: PAGE_SIZE,
    offset: changelogPage * PAGE_SIZE,
  });
  const changelog = changelogResp?.data ?? [];
  const changelogMeta = (changelogResp as unknown as Record<string, unknown>)
    ?.meta as { total?: number; count?: number } | undefined;

  const [diffKey, setDiffKey] = useState<string | null>(null);
  const { data: diffResp } = useConfigDiff(
    deviceId,
    diffKey ?? "",
    selectedConfigApp ?? undefined,
    20,
  );
  const diffRows = diffResp?.data ?? [];

  const { data: timestamps } = useConfigChangeTimestamps(deviceId, {
    app_id: selectedConfigApp ?? undefined,
  });
  const tsData = timestamps?.data ?? [];
  const [compareTimeA, setCompareTimeA] = useState<string | null>(null);
  const [compareTimeB, setCompareTimeB] = useState<string | null>(null);
  const { data: compareResult } = useConfigCompare(
    deviceId,
    compareTimeA,
    compareTimeB,
    selectedConfigApp ?? undefined,
  );

  useEffect(() => {
    if (tsData.length >= 2 && !compareTimeA && !compareTimeB) {
      setCompareTimeA(tsData[1].change_time);
      setCompareTimeB(tsData[0].change_time);
    }
  }, [tsData, compareTimeA, compareTimeB]);

  const configApps = useMemo(() => {
    const apps = new Map<
      string,
      {
        appName: string;
        data: Record<string, string>;
        lastCollected: string | null;
        intervalSeconds: number | null;
        scheduleHuman: string | null;
      }
    >();
    const scheduleByAppId = new Map<
      string,
      { intervalSeconds: number | null; scheduleHuman: string }
    >();
    for (const a of assignments ?? []) {
      scheduleByAppId.set(a.app.id, {
        intervalSeconds:
          a.schedule_type === "interval" ? Number(a.schedule_value) : null,
        scheduleHuman:
          a.schedule_human ??
          (a.schedule_type === "interval"
            ? `every ${formatInterval(Number(a.schedule_value))}`
            : a.schedule_value),
      });
    }
    for (const row of configRows ?? []) {
      const appId = String(row.app_id ?? "unknown");
      const key = String(row.config_key ?? "");
      const value = String(row.config_value ?? "");
      const appName = String(row.app_name ?? appId);
      const executedAt = String(row.executed_at ?? "");
      if (!apps.has(appId)) {
        const sched = scheduleByAppId.get(appId);
        apps.set(appId, {
          appName,
          data: {},
          lastCollected: null,
          intervalSeconds: sched?.intervalSeconds ?? null,
          scheduleHuman: sched?.scheduleHuman ?? null,
        });
      }
      const entry = apps.get(appId)!;
      if (!(key in entry.data)) {
        entry.data[key] = value;
      }
      if (
        executedAt &&
        (!entry.lastCollected || executedAt > entry.lastCollected)
      ) {
        entry.lastCollected = executedAt;
      }
    }
    return apps;
  }, [configRows, assignments]);

  useEffect(() => {
    if (!selectedConfigApp && configApps.size > 0) {
      const firstByDisplayOrder = [...configApps.entries()].sort(
        ([, a], [, b]) =>
          a.appName.toLowerCase().localeCompare(b.appName.toLowerCase()),
      )[0][0];
      setSelectedConfigApp(firstByDisplayOrder);
    }
  }, [configApps, selectedConfigApp]);

  useEffect(() => {
    setChangelogPage(0);
    setFilterKey("");
    setFilterComponent("");
    setFilterValue("");
  }, [selectedConfigApp]);

  useEffect(() => {
    setChangelogPage(0);
  }, [filterKey, filterComponent, filterValue]);

  function handleChangeSort(col: string) {
    if (changeSortCol === col)
      setChangeSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setChangeSortCol(col as typeof changeSortCol);
      setChangeSortDir("asc");
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  if (configApps.size === 0) {
    return (
      <Card>
        <CardContent className="py-12 flex flex-col items-center gap-3 text-zinc-600">
          <Wrench className="h-8 w-8 text-zinc-700" />
          <p className="text-sm text-zinc-500">No configuration data yet.</p>
          <p className="text-xs text-zinc-700 text-center max-w-sm">
            Config apps will populate structured data here once they have been
            assigned and executed.
          </p>
        </CardContent>
      </Card>
    );
  }

  const selectedAppData = selectedConfigApp
    ? configApps.get(selectedConfigApp)
    : null;

  return (
    <div className="flex gap-4">
      <div className="w-48 shrink-0">
        <Card>
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-xs text-zinc-500 uppercase tracking-wide">
              Apps
            </CardTitle>
          </CardHeader>
          <CardContent className="p-1.5 space-y-0.5">
            {[...configApps.entries()]
              .sort(([, a], [, b]) =>
                a.appName.toLowerCase().localeCompare(b.appName.toLowerCase()),
              )
              .map(([appId, { appName }]) => (
                <button
                  key={appId}
                  onClick={() => setSelectedConfigApp(appId)}
                  className={`w-full text-left rounded-md px-2.5 py-1.5 text-xs transition-colors cursor-pointer truncate ${
                    selectedConfigApp === appId
                      ? "bg-brand-500/15 text-brand-400 font-medium"
                      : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                  }`}
                >
                  {appName}
                </button>
              ))}
          </CardContent>
        </Card>
      </div>

      <div className="flex-1 min-w-0 space-y-4">
        <div className="flex items-center gap-2">
          <Button
            variant={configView === "current" ? "default" : "outline"}
            size="sm"
            onClick={() => setConfigView("current")}
          >
            <Wrench className="h-3.5 w-3.5 mr-1" />
            Current
          </Button>
          <Button
            variant={configView === "changes" ? "default" : "outline"}
            size="sm"
            onClick={() => setConfigView("changes")}
          >
            <Clock className="h-3.5 w-3.5 mr-1" />
            Changes
          </Button>
          <Button
            variant={configView === "compare" ? "default" : "outline"}
            size="sm"
            onClick={() => setConfigView("compare")}
          >
            <FileText className="h-3.5 w-3.5 mr-1" />
            Compare
          </Button>
        </div>

        {configView === "current" && selectedAppData && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <Wrench className="h-4 w-4" />
                {selectedAppData.appName}
                {selectedAppData.lastCollected &&
                  (() => {
                    const ageSec =
                      (Date.now() -
                        new Date(selectedAppData.lastCollected).getTime()) /
                      1000;
                    const interval = selectedAppData.intervalSeconds;
                    const missedPolls = interval ? ageSec / interval : 0;
                    const statusColor = !interval
                      ? "bg-zinc-700 text-zinc-300"
                      : missedPolls <= 1.5
                        ? "bg-emerald-900/60 text-emerald-400 border border-emerald-700/50"
                        : missedPolls <= 2.5
                          ? "bg-amber-900/60 text-amber-400 border border-amber-700/50"
                          : "bg-red-900/60 text-red-400 border border-red-700/50";
                    return (
                      <span className="ml-auto flex items-center gap-2">
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded ${statusColor}`}
                          title={`Last polled: ${formatDate(selectedAppData.lastCollected, tz)}`}
                        >
                          {timeAgo(selectedAppData.lastCollected)}
                        </span>
                        {selectedAppData.scheduleHuman && (
                          <span className="text-xs text-zinc-500 font-normal">
                            ↻ {selectedAppData.scheduleHuman}
                          </span>
                        )}
                        {(() => {
                          const selectedAssignment = (assignments ?? []).find(
                            (a) => a.app.id === selectedConfigApp,
                          );
                          if (!selectedAssignment) return null;
                          const isPolling = pollStatus === "polling";
                          const isDone = pollStatus === "done";
                          const isError = pollStatus === "error";
                          return (
                            <button
                              onClick={() => {
                                if (isPolling) return;
                                setPollError(null);
                                latestExecutedAtBefore.current =
                                  configRows?.reduce(
                                    (
                                      max: string,
                                      r: Record<string, unknown>,
                                    ) => {
                                      const ea = String(r.executed_at ?? "");
                                      return ea > max ? ea : max;
                                    },
                                    "",
                                  ) ?? null;
                                setPollRequestedAt(Date.now());
                                setPollStatus("polling");
                                pollNow.mutate(
                                  {
                                    deviceId,
                                    assignmentId: selectedAssignment.id,
                                  },
                                  {
                                    onSuccess: (res) => {
                                      if (!res?.data?.poll_triggered) {
                                        setPollStatus("error");
                                        setPollRequestedAt(null);
                                        setPollError(
                                          "No collector could trigger the poll",
                                        );
                                        setTimeout(() => {
                                          setPollStatus("idle");
                                          setPollError(null);
                                        }, 4000);
                                      }
                                    },
                                    onError: () => {
                                      setPollStatus("idle");
                                      setPollRequestedAt(null);
                                    },
                                  },
                                );
                              }}
                              disabled={isPolling}
                              title={
                                isError
                                  ? (pollError ?? "Failed")
                                  : isPolling
                                    ? "Polling..."
                                    : isDone
                                      ? "Done!"
                                      : "Poll now"
                              }
                              className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded transition-colors disabled:opacity-60 ${
                                isError
                                  ? "text-red-400 bg-red-900/30"
                                  : isDone
                                    ? "text-emerald-400 bg-emerald-900/30"
                                    : isPolling
                                      ? "text-brand-400 bg-brand-900/30"
                                      : "text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700/50"
                              }`}
                            >
                              {isError ? (
                                <>
                                  <AlertTriangle className="h-3 w-3" /> Failed
                                </>
                              ) : isDone ? (
                                <>
                                  <Check className="h-3 w-3" /> Done
                                </>
                              ) : isPolling ? (
                                <>
                                  <RefreshCw className="h-3 w-3 animate-spin" />{" "}
                                  Polling...
                                </>
                              ) : (
                                <RefreshCw className="h-3.5 w-3.5" />
                              )}
                            </button>
                          );
                        })()}
                      </span>
                    );
                  })()}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ConfigDataRenderer
                template={
                  selectedConfigApp &&
                  configTemplates?.[selectedConfigApp]?.display_template?.html
                    ? {
                        html: configTemplates[selectedConfigApp]
                          .display_template!.html,
                        css:
                          configTemplates[selectedConfigApp].display_template!
                            .css ?? undefined,
                        key_mappings:
                          configTemplates[selectedConfigApp].display_template!
                            .key_mappings ?? [],
                      }
                    : null
                }
                data={selectedAppData.data}
              />
            </CardContent>
          </Card>
        )}

        {configView === "changes" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                Config Change History
                {changelogMeta?.total ? (
                  <Badge variant="default" className="text-[10px] px-1.5 py-0">
                    {changelogMeta.total}
                  </Badge>
                ) : null}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {changelog.length === 0 ? (
                <div className="py-8 text-center">
                  <Clock className="h-6 w-6 text-zinc-700 mx-auto mb-2" />
                  <p className="text-sm text-zinc-500">
                    No configuration changes detected.
                  </p>
                  <p className="text-xs text-zinc-600 mt-1 max-w-sm mx-auto">
                    Changes will appear here automatically when config values on
                    this device change between poll cycles.
                  </p>
                </div>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <FilterableSortHead
                          col="time"
                          label="Time"
                          sortBy={changeSortCol}
                          sortDir={changeSortDir}
                          onSort={handleChangeSort}
                          filterable={false}
                        />
                        <FilterableSortHead
                          col="component"
                          label="Component"
                          sortBy={changeSortCol}
                          sortDir={changeSortDir}
                          onSort={handleChangeSort}
                          filterValue={filterComponent}
                          onFilterChange={setFilterComponent}
                          filterable={true}
                        />
                        <FilterableSortHead
                          col="key"
                          label="Key"
                          sortBy={changeSortCol}
                          sortDir={changeSortDir}
                          onSort={handleChangeSort}
                          filterValue={filterKey}
                          onFilterChange={setFilterKey}
                          filterable={true}
                        />
                        <FilterableSortHead
                          col="value"
                          label="Value"
                          sortBy={changeSortCol}
                          sortDir={changeSortDir}
                          onSort={handleChangeSort}
                          filterValue={filterValue}
                          onFilterChange={setFilterValue}
                          filterable={true}
                        />
                        <TableHead className="w-16">Diff</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {changelog.map((row, i) => (
                        <TableRow
                          key={`${row.executed_at}-${row.config_key}-${i}`}
                        >
                          <TableCell
                            className="text-xs text-zinc-400 whitespace-nowrap"
                            title={formatDate(row.executed_at, tz)}
                          >
                            {timeAgo(row.executed_at)}
                          </TableCell>
                          <TableCell className="text-xs font-mono text-zinc-500">
                            {row.component
                              ? `${row.component_type}/${row.component}`
                              : "—"}
                          </TableCell>
                          <TableCell className="text-xs font-mono">
                            {row.config_key}
                          </TableCell>
                          <TableCell
                            className="text-xs font-mono max-w-[250px] truncate"
                            title={row.config_value}
                          >
                            {row.config_value}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-xs"
                              onClick={() => setDiffKey(row.config_key)}
                            >
                              <FileText className="h-3 w-3" />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {(changelogMeta?.total ?? 0) > PAGE_SIZE && (
                    <div className="flex items-center justify-between mt-3 text-xs text-zinc-400">
                      <span>
                        {changelogPage * PAGE_SIZE + 1}–
                        {Math.min(
                          (changelogPage + 1) * PAGE_SIZE,
                          changelogMeta?.total ?? 0,
                        )}{" "}
                        of {changelogMeta?.total}
                      </span>
                      <div className="flex gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-2 text-xs"
                          disabled={changelogPage === 0}
                          onClick={() => setChangelogPage((p) => p - 1)}
                        >
                          Prev
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-2 text-xs"
                          disabled={
                            (changelogPage + 1) * PAGE_SIZE >=
                            (changelogMeta?.total ?? 0)
                          }
                          onClick={() => setChangelogPage((p) => p + 1)}
                        >
                          Next
                        </Button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        )}

        {configView === "compare" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Compare Snapshots</CardTitle>
            </CardHeader>
            <CardContent>
              {tsData.length < 2 ? (
                <div className="py-8 text-center">
                  <FileText className="h-6 w-6 text-zinc-700 mx-auto mb-2" />
                  <p className="text-sm text-zinc-500">
                    No changes to compare yet.
                  </p>
                  <p className="text-xs text-zinc-600 mt-1 max-w-sm mx-auto">
                    The comparison view requires at least two different
                    configuration snapshots. Changes will become available once
                    config values on this device change between poll cycles.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center gap-3 flex-wrap">
                    {(() => {
                      const groups = new Map<string, typeof tsData>();
                      for (const ts of tsData) {
                        const label = new Intl.DateTimeFormat("en-GB", {
                          timeZone: tz || undefined,
                          weekday: "short",
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        }).format(new Date(ts.change_time));
                        if (!groups.has(label)) groups.set(label, []);
                        groups.get(label)!.push(ts);
                      }
                      const renderOption = (ts: (typeof tsData)[0]) => (
                        <option key={ts.change_time} value={ts.change_time}>
                          {new Date(ts.change_time).toLocaleTimeString(
                            "en-GB",
                            {
                              timeZone: tz || undefined,
                              hour: "2-digit",
                              minute: "2-digit",
                            },
                          )}{" "}
                          ({ts.change_count} keys)
                        </option>
                      );
                      const renderSelect = (
                        value: string,
                        onChange: (v: string) => void,
                      ) => (
                        <select
                          value={value}
                          onChange={(e) => onChange(e.target.value)}
                          className="bg-zinc-900 border border-zinc-700 rounded-md text-xs text-zinc-200 px-2 py-1 min-w-[220px] focus:outline-none focus:ring-1 focus:ring-brand-500"
                        >
                          {[...groups.entries()].map(([date, group]) => (
                            <optgroup key={date} label={date}>
                              {group.map(renderOption)}
                            </optgroup>
                          ))}
                        </select>
                      );
                      return (
                        <>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-zinc-500">
                              Before:
                            </span>
                            {renderSelect(compareTimeA ?? "", setCompareTimeA)}
                          </div>
                          <span className="text-zinc-600">vs</span>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-zinc-500">
                              After:
                            </span>
                            {renderSelect(compareTimeB ?? "", setCompareTimeB)}
                          </div>
                        </>
                      );
                    })()}
                  </div>

                  {compareResult &&
                    (() => {
                      const added = compareResult.changes.filter(
                        (d) => d.change_type === "added",
                      );
                      const removed = compareResult.changes.filter(
                        (d) => d.change_type === "removed",
                      );
                      const modified = compareResult.changes.filter(
                        (d) => d.change_type === "modified",
                      );
                      const unchangedList = compareResult.unchanged ?? [];

                      const renderDiffRow = (d: ConfigDiffEntry, i: number) => {
                        const rowBg =
                          d.change_type === "added"
                            ? "bg-emerald-950/20"
                            : d.change_type === "removed"
                              ? "bg-red-950/20"
                              : d.change_type === "modified"
                                ? "bg-amber-950/20"
                                : "";
                        const statusIcon =
                          d.change_type === "added"
                            ? "+"
                            : d.change_type === "removed"
                              ? "\u2212"
                              : d.change_type === "modified"
                                ? "~"
                                : "=";
                        const statusColor =
                          d.change_type === "added"
                            ? "text-emerald-400"
                            : d.change_type === "removed"
                              ? "text-red-400"
                              : d.change_type === "modified"
                                ? "text-amber-400"
                                : "text-zinc-600";

                        return (
                          <TableRow
                            key={`${d.component_type}-${d.component}-${d.config_key}-${i}`}
                            className={rowBg}
                          >
                            <TableCell
                              className={`text-sm font-bold w-8 text-center ${statusColor}`}
                            >
                              {statusIcon}
                            </TableCell>
                            <TableCell className="text-xs font-mono">
                              {d.config_key}
                            </TableCell>
                            <TableCell
                              className="text-xs font-mono max-w-[250px] truncate"
                              title={d.value_a ?? ""}
                            >
                              {d.change_type === "added" ? (
                                <span className="text-zinc-600">&mdash;</span>
                              ) : (
                                <span
                                  className={
                                    d.change_type === "removed" ||
                                    d.change_type === "modified"
                                      ? "text-red-400"
                                      : "text-zinc-400"
                                  }
                                >
                                  {d.value_a}
                                </span>
                              )}
                            </TableCell>
                            <TableCell
                              className="text-xs font-mono max-w-[250px] truncate"
                              title={d.value_b ?? ""}
                            >
                              {d.change_type === "removed" ? (
                                <span className="text-zinc-600">&mdash;</span>
                              ) : (
                                <span
                                  className={
                                    d.change_type === "added" ||
                                    d.change_type === "modified"
                                      ? "text-emerald-400"
                                      : "text-zinc-400"
                                  }
                                >
                                  {d.value_b}
                                </span>
                              )}
                            </TableCell>
                          </TableRow>
                        );
                      };

                      return (
                        <>
                          <div className="flex items-center gap-2 flex-wrap">
                            {added.length > 0 && (
                              <Badge variant="success" className="text-[10px]">
                                +{added.length} added
                              </Badge>
                            )}
                            {removed.length > 0 && (
                              <Badge
                                variant="destructive"
                                className="text-[10px]"
                              >
                                &minus;{removed.length} removed
                              </Badge>
                            )}
                            {modified.length > 0 && (
                              <Badge variant="warning" className="text-[10px]">
                                ~{modified.length} changed
                              </Badge>
                            )}
                            {unchangedList.length > 0 && (
                              <Badge variant="default" className="text-[10px]">
                                {unchangedList.length} unchanged
                              </Badge>
                            )}
                          </div>

                          {compareResult.changes.length === 0 &&
                          unchangedList.length === 0 ? (
                            <p className="text-sm text-zinc-500 py-4 text-center">
                              No configuration data found for the selected
                              timestamps.
                            </p>
                          ) : compareResult.changes.length === 0 ? (
                            <p className="text-sm text-zinc-500 py-4 text-center">
                              No differences between these two snapshots.
                            </p>
                          ) : (
                            <Table>
                              <TableHeader>
                                <TableRow>
                                  <TableHead className="w-8"></TableHead>
                                  <TableHead>Key</TableHead>
                                  <TableHead>Before</TableHead>
                                  <TableHead>After</TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {compareResult.changes.map(renderDiffRow)}
                              </TableBody>
                            </Table>
                          )}

                          {unchangedList.length > 0 && (
                            <details className="mt-2">
                              <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-300 select-none">
                                {unchangedList.length} unchanged key
                                {unchangedList.length !== 1 ? "s" : ""}
                              </summary>
                              <div className="mt-2">
                                <Table>
                                  <TableHeader>
                                    <TableRow>
                                      <TableHead className="w-8"></TableHead>
                                      <TableHead>Key</TableHead>
                                      <TableHead>Before</TableHead>
                                      <TableHead>After</TableHead>
                                    </TableRow>
                                  </TableHeader>
                                  <TableBody>
                                    {unchangedList.map(renderDiffRow)}
                                  </TableBody>
                                </Table>
                              </div>
                            </details>
                          )}
                        </>
                      );
                    })()}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {diffKey && (
          <Dialog
            open
            onClose={() => setDiffKey(null)}
            title={`History: ${diffKey}`}
          >
            <div className="max-h-[60vh] overflow-auto">
              {diffRows.length === 0 ? (
                <p className="text-sm text-zinc-500 p-4">No history found.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Time</TableHead>
                      <TableHead>Value</TableHead>
                      <TableHead className="w-20">Hash</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {diffRows.map((row, i) => {
                      const prevRow = diffRows[i + 1];
                      const changed =
                        !prevRow || prevRow.config_hash !== row.config_hash;
                      return (
                        <TableRow
                          key={`${row.executed_at}-${i}`}
                          className={changed ? "bg-amber-500/10" : ""}
                        >
                          <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                            {formatDate(row.executed_at, tz)}
                          </TableCell>
                          <TableCell className="text-xs font-mono max-w-[400px] whitespace-pre-wrap break-all">
                            {row.config_value}
                          </TableCell>
                          <TableCell className="text-xs font-mono text-zinc-500">
                            {row.config_hash.slice(0, 8)}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setDiffKey(null)}
              >
                Close
              </Button>
            </DialogFooter>
          </Dialog>
        )}
      </div>
    </div>
  );
}
