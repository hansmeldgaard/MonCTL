import { useState } from "react";
import { Link } from "react-router-dom";
import { Bell, Clock, Loader2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import { TimeDisplayToggle } from "@/components/TimeDisplayToggle.tsx";
import {
  useAlertInstances,
  useDeviceAlertLog,
  useUpdateAlertInstance,
} from "@/api/hooks.ts";
import type { AlertLogEntry } from "@/types/api.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { formatTime } from "@/lib/utils.ts";

export function AlertsTab({ deviceId }: { deviceId: string }) {
  const [subTab, setSubTab] = useState<"active" | "history">("active");
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1">
        {(["active", "history"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setSubTab(t)}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${subTab === t ? "bg-zinc-700 text-white" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"}`}
          >
            {t === "active" ? "Active" : "History"}
          </button>
        ))}
      </div>
      {subTab === "active" ? (
        <DeviceActiveAlerts deviceId={deviceId} />
      ) : (
        <DeviceAlertHistory deviceId={deviceId} />
      )}
    </div>
  );
}

function DeviceActiveAlerts({ deviceId }: { deviceId: string }) {
  const { pageSize, scrollMode } = useTablePreferences();
  const tz = useTimezone();
  const { mode: timeMode } = useTimeDisplayMode();
  const listState = useListState({
    columns: [
      { key: "state", label: "State", filterable: false },
      { key: "definition_name", label: "Alert" },
      { key: "app_name", label: "App" },
      { key: "entity_key", label: "Entity" },
      { key: "current_value", label: "Value", filterable: false },
      { key: "fire_count", label: "Fires", filterable: false },
      { key: "current_state_since", label: "Since", filterable: false },
      { key: "last_triggered_at", label: "Last triggered", filterable: false },
    ],
    defaultSortBy: "state",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: response,
    isLoading,
    isFetching,
  } = useAlertInstances({
    device_id: deviceId,
    state: "firing",
    ...listState.params,
  });
  const instances = response?.data ?? [];
  const meta = {
    limit: response?.meta?.limit ?? 50,
    offset: response?.meta?.offset ?? 0,
    count: response?.meta?.count ?? instances.length,
    total: response?.meta?.total ?? instances.length,
  };
  const updateInstance = useUpdateAlertInstance();

  if (isLoading)
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );

  if (!instances || instances.length === 0) {
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center justify-center text-zinc-500">
            <Bell className="h-10 w-10 mb-3 text-emerald-500/50" />
            <p className="text-sm">No active alerts — all clear</p>
            <p className="text-xs text-zinc-600 mt-1">
              Switch to History to see past firings, or Thresholds to inspect
              alert definitions for this device
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-4 w-4" /> Active Alerts
            <Badge variant="destructive" className="ml-1.5 text-xs">
              {meta.total} firing
            </Badge>
            <TimeDisplayToggle />
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <FilterableSortHead
                col="state"
                label="State"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="definition_name"
                label="Alert"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.definition_name}
                onFilterChange={(v) =>
                  listState.setFilter("definition_name", v)
                }
              />
              <FilterableSortHead
                col="app_name"
                label="App"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.app_name}
                onFilterChange={(v) => listState.setFilter("app_name", v)}
              />
              <FilterableSortHead
                col="entity_key"
                label="Entity"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.entity_key}
                onFilterChange={(v) => listState.setFilter("entity_key", v)}
              />
              <FilterableSortHead
                col="current_value"
                label="Value"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="fire_count"
                label="Fires"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="current_state_since"
                label="Since"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="last_triggered_at"
                label="Last triggered"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <TableHead className="w-16">Enabled</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {instances.map((inst) => {
              const sev: string | null = inst.severity ?? null;
              const rowClass =
                sev === "critical"
                  ? "bg-red-500/10"
                  : sev === "warning"
                    ? "bg-orange-500/10"
                    : sev === "info"
                      ? "bg-sky-500/10"
                      : inst.state === "firing"
                        ? "bg-red-500/5"
                        : "";
              const pillClass =
                sev === "critical"
                  ? "bg-red-600 text-white"
                  : sev === "warning"
                    ? "bg-orange-600 text-white"
                    : sev === "info"
                      ? "bg-sky-600 text-white"
                      : "bg-zinc-700 text-zinc-200";
              return (
                <TableRow key={inst.id} className={rowClass}>
                  <TableCell>
                    {inst.state === "firing" ? (
                      <span
                        className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${pillClass}`}
                      >
                        {sev ?? "firing"}
                      </span>
                    ) : (
                      <Badge
                        variant={
                          inst.state === "resolved" ? "warning" : "success"
                        }
                      >
                        {inst.state === "resolved"
                          ? "CLEARED"
                          : inst.state.toUpperCase()}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="font-medium">
                    <Link
                      to={`/alerts/definitions/${inst.definition_id}`}
                      className="text-brand-400 hover:text-brand-300 hover:underline"
                    >
                      {inst.definition_name ?? "\u2014"}
                    </Link>
                    {inst.entity_labels?.if_name && (
                      <span className="ml-1.5 text-xs text-zinc-500">
                        ({inst.entity_labels.if_name})
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-zinc-400 text-sm">
                    {inst.app_name ?? "\u2014"}
                  </TableCell>
                  <TableCell className="text-zinc-400 text-xs font-mono">
                    {inst.entity_labels?.if_name ||
                      inst.entity_labels?.component ||
                      inst.entity_key ||
                      "\u2014"}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {inst.current_value != null
                      ? Number(inst.current_value).toFixed(2)
                      : "\u2014"}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {inst.fire_count ?? 0}
                  </TableCell>
                  <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                    {formatTime(inst.current_state_since, timeMode, tz)}
                  </TableCell>
                  <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                    {formatTime(inst.last_triggered_at, timeMode, tz)}
                  </TableCell>
                  <TableCell className="text-center">
                    <button
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${inst.enabled ? "bg-brand-500" : "bg-zinc-600"}`}
                      onClick={() =>
                        updateInstance.mutate({
                          id: inst.id,
                          enabled: !inst.enabled,
                        })
                      }
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${inst.enabled ? "translate-x-4.5" : "translate-x-0.5"}`}
                      />
                    </button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        <PaginationBar
          page={listState.page}
          pageSize={listState.pageSize}
          total={meta.total}
          count={meta.count}
          onPageChange={listState.setPage}
          scrollMode={listState.scrollMode}
          sentinelRef={listState.sentinelRef}
          isFetching={isFetching}
          onLoadMore={listState.loadMore}
        />
      </CardContent>
    </Card>
  );
}

function DeviceAlertHistory({ deviceId }: { deviceId: string }) {
  const { pageSize, scrollMode } = useTablePreferences();
  const tz = useTimezone();
  const { mode: timeMode } = useTimeDisplayMode();
  const listState = useListState({
    columns: [
      { key: "definition_name", label: "Alert" },
      { key: "message", label: "Message" },
      { key: "occurred_at", label: "Time", filterable: false },
    ],
    defaultSortBy: "occurred_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });

  const {
    data: response,
    isLoading,
    isFetching,
  } = useDeviceAlertLog(deviceId, listState.params, {});
  const logEntries = response?.data ?? [];
  const meta = {
    limit: response?.meta?.limit ?? 50,
    offset: response?.meta?.offset ?? 0,
    count: response?.meta?.count ?? 0,
    total: response?.meta?.total ?? 0,
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-4 w-4" /> Alert History
            <Badge variant="default" className="ml-1.5 text-xs">
              {meta.total}
            </Badge>
            <TimeDisplayToggle />
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-brand-500" />
          </div>
        ) : logEntries.length === 0 ? (
          <p className="text-sm text-zinc-500 text-center py-8">
            No alert history for this device
          </p>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">Action</TableHead>
                  <FilterableSortHead
                    col="definition_name"
                    label="Alert"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterValue={listState.filters.definition_name}
                    onFilterChange={(v) =>
                      listState.setFilter("definition_name", v)
                    }
                  />
                  <TableHead>Entity</TableHead>
                  <TableHead>Value</TableHead>
                  <FilterableSortHead
                    col="message"
                    label="Message"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterValue={listState.filters.message}
                    onFilterChange={(v) => listState.setFilter("message", v)}
                    sortable={false}
                  />
                  <FilterableSortHead
                    col="occurred_at"
                    label="Time"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterable={false}
                  />
                </TableRow>
              </TableHeader>
              <TableBody>
                {logEntries.map((entry: AlertLogEntry, idx: number) => {
                  const sev = entry.severity;
                  const rowClass =
                    sev === "critical"
                      ? "bg-red-500/10"
                      : sev === "warning"
                        ? "bg-orange-500/10"
                        : sev === "info"
                          ? "bg-sky-500/10"
                          : sev === "healthy"
                            ? "bg-green-500/10"
                            : "bg-zinc-800/20";
                  const pillClass =
                    sev === "critical"
                      ? "bg-red-600 text-white"
                      : sev === "warning"
                        ? "bg-orange-600 text-white"
                        : sev === "info"
                          ? "bg-sky-600 text-white"
                          : sev === "healthy"
                            ? "bg-green-600 text-white"
                            : "bg-zinc-600 text-white";
                  return (
                    <TableRow
                      key={`${entry.definition_id}-${entry.occurred_at}-${idx}`}
                      className={rowClass}
                    >
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Badge className={pillClass}>{sev || "—"}</Badge>
                          <span className="text-[10px] uppercase text-zinc-500">
                            {entry.action}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="font-medium">
                        <Link
                          to={`/alerts/definitions/${entry.definition_id}`}
                          className="text-brand-400 hover:text-brand-300 hover:underline"
                        >
                          {entry.definition_name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-zinc-400 text-xs font-mono">
                        {entry.entity_key || "\u2014"}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {entry.current_value != null
                          ? Number(entry.current_value).toFixed(2)
                          : "\u2014"}
                      </TableCell>
                      <TableCell
                        className="text-xs text-zinc-400 max-w-[200px] truncate"
                        title={entry.message}
                      >
                        {entry.message || "\u2014"}
                      </TableCell>
                      <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                        {formatTime(entry.occurred_at, timeMode, tz)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <PaginationBar
              page={listState.page}
              pageSize={listState.pageSize}
              total={meta.total}
              count={meta.count}
              onPageChange={listState.setPage}
              scrollMode={listState.scrollMode}
              sentinelRef={listState.sentinelRef}
              isFetching={isFetching}
              onLoadMore={listState.loadMore}
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}
