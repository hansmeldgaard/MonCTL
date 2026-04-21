import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, FileText, Filter, Loader2, ShieldCheck } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { useAlertInstances, useAlertLog, useAlertRules } from "@/api/hooks.ts";
import { formatTime } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";
import type {
  AlertEntity,
  AlertDefinition,
  AlertLogEntry,
} from "@/types/api.ts";

type Tab = "active" | "log" | "definitions";

export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("active");
  const { pageSize, scrollMode } = useTablePreferences();

  const activeListState = useListState({
    columns: [
      { key: "definition_name", label: "Alert" },
      { key: "app_name", label: "App" },
      { key: "device_name", label: "Device" },
      { key: "entity_key", label: "Entity" },
      { key: "current_value", label: "Value", filterable: false },
      { key: "fire_count", label: "Fires", filterable: false },
      { key: "current_state_since", label: "Since", filterable: false },
      { key: "last_triggered_at", label: "Last triggered", filterable: false },
    ],
    defaultSortBy: "current_state_since",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: activeResponse,
    isLoading: alertsLoading,
    isFetching: activeFetching,
  } = useAlertInstances({ state: "firing", ...activeListState.params });
  const activeAlerts: AlertEntity[] = activeResponse?.data ?? [];
  const activeMeta = {
    limit: activeResponse?.meta?.limit ?? activeListState.pageSize,
    offset: activeResponse?.meta?.offset ?? 0,
    count: activeResponse?.meta?.count ?? 0,
    total: activeResponse?.meta?.total ?? 0,
  };

  const defsListState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "app_name", label: "App", sortable: false },
      { key: "expression", label: "Expression", sortable: false },
      { key: "enabled", label: "Enabled", filterable: false },
    ],
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: defsResponse,
    isLoading: defsLoading,
    isFetching: defsFetching,
  } = useAlertRules(defsListState.params);
  const definitions = defsResponse?.data ?? [];
  const defsMeta = {
    limit: defsResponse?.meta?.limit ?? 50,
    offset: defsResponse?.meta?.offset ?? 0,
    count: defsResponse?.meta?.count ?? 0,
    total: defsResponse?.meta?.total ?? 0,
  };

  const logListState = useListState({
    columns: [
      { key: "occurred_at", label: "Time", filterable: false },
      { key: "definition_name", label: "Alert" },
      { key: "device_name", label: "Device" },
      { key: "entity_key", label: "Entity" },
      { key: "fire_count", label: "Fires", filterable: false },
      { key: "message", label: "Message", sortable: false },
    ],
    defaultSortBy: "occurred_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: logResponse,
    isLoading: logLoading,
    isFetching: logFetching,
  } = useAlertLog({
    ...logListState.params,
  });
  const logEntries = logResponse?.data ?? [];
  const logMeta = {
    limit: logResponse?.meta?.limit ?? logListState.pageSize,
    offset: logResponse?.meta?.offset ?? 0,
    count: logResponse?.meta?.count ?? 0,
    total: logResponse?.meta?.total ?? 0,
  };

  const isLoading =
    tab === "active" ? alertsLoading : tab === "log" ? logLoading : defsLoading;

  return (
    <div className="space-y-4">
      {/* Tab switcher */}
      <div className="flex items-center gap-1 rounded-lg bg-zinc-900 p-1 w-fit border border-zinc-800">
        <Button
          variant={tab === "active" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("active")}
        >
          <Bell className="h-3.5 w-3.5" />
          Active Alerts
          {activeMeta.total > 0 && (
            <Badge variant="destructive" className="ml-1.5">
              {activeMeta.total}
            </Badge>
          )}
        </Button>
        <Button
          variant={tab === "log" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("log")}
        >
          <FileText className="h-3.5 w-3.5" />
          Alert Log
        </Button>
        <Button
          variant={tab === "definitions" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("definitions")}
        >
          <ShieldCheck className="h-3.5 w-3.5" />
          Alert Definitions
        </Button>
      </div>

      {isLoading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
        </div>
      ) : tab === "active" ? (
        <ActiveAlertsTab
          alerts={activeAlerts}
          listState={activeListState}
          meta={activeMeta}
          isFetching={activeFetching}
        />
      ) : tab === "log" ? (
        <AlertLogTab
          entries={logEntries}
          meta={logMeta}
          listState={logListState}
          isFetching={logFetching}
        />
      ) : (
        <DefinitionsTab
          definitions={definitions}
          listState={defsListState}
          meta={defsMeta}
          isFetching={defsFetching}
        />
      )}
    </div>
  );
}

function severityPillClass(sev: string | null | undefined): string {
  switch (sev) {
    case "critical":
      return "bg-red-600 text-white";
    case "warning":
      return "bg-orange-600 text-white";
    case "info":
      return "bg-sky-600 text-white";
    case "healthy":
      return "bg-green-600 text-white";
    default:
      return "bg-zinc-600 text-white";
  }
}

function severityRowClass(sev: string | null | undefined): string {
  switch (sev) {
    case "critical":
      return "bg-red-500/10";
    case "warning":
      return "bg-orange-500/10";
    case "info":
      return "bg-sky-500/10";
    case "healthy":
      return "bg-green-500/10";
    default:
      return "bg-red-500/5";
  }
}

function ActiveAlertsTab({
  alerts,
  listState,
  meta,
  isFetching,
}: {
  alerts: AlertEntity[];
  listState: ReturnType<typeof useListState>;
  meta: { limit: number; offset: number; count: number; total: number };
  isFetching: boolean;
}) {
  const tz = useTimezone();
  const { mode } = useTimeDisplayMode();
  const { compact } = useDisplayPreferences();

  const columns = useMemo<FlexColumnDef<AlertEntity>[]>(
    () => [
      {
        key: "definition_name",
        label: "Alert",
        defaultWidth: 260,
        cell: (a) => (
          <div className="flex items-center gap-2">
            {a.severity && (
              <span
                className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold uppercase ${severityPillClass(a.severity)}`}
              >
                {a.severity}
              </span>
            )}
            <Link
              to={`/alerts/definitions/${a.definition_id}`}
              className="text-brand-400 hover:text-brand-300 hover:underline"
            >
              {a.definition_name ?? a.definition_id}
            </Link>
          </div>
        ),
      },
      {
        key: "app_name",
        label: "App",
        defaultWidth: 160,
        cellClassName: "text-zinc-400",
        cell: (a) => a.app_name ?? "",
      },
      {
        key: "device_name",
        label: "Device",
        defaultWidth: 180,
        cell: (a) =>
          a.device_id ? (
            <Link
              to={`/devices/${a.device_id}`}
              className="text-brand-400 hover:text-brand-300 hover:underline"
            >
              {a.device_name ?? a.device_id}
            </Link>
          ) : (
            (a.device_name ?? "—")
          ),
      },
      {
        key: "entity_key",
        label: "Entity",
        defaultWidth: 160,
        cellClassName: "text-zinc-400 text-xs font-mono",
        cell: (a) =>
          a.entity_labels?.if_name ||
          a.entity_labels?.component ||
          a.entity_key ||
          "—",
      },
      {
        key: "current_value",
        label: "Value",
        filterable: false,
        defaultWidth: 100,
        cellClassName: "text-zinc-300",
        cell: (a) =>
          a.current_value != null ? Number(a.current_value).toFixed(1) : "—",
      },
      {
        key: "fire_count",
        label: "Fires",
        filterable: false,
        defaultWidth: 80,
        cellClassName: "text-zinc-400",
        cell: (a) => a.fire_count,
      },
      {
        key: "current_state_since",
        label: "Since",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 whitespace-nowrap",
        cell: (a) => formatTime(a.current_state_since, mode, tz),
      },
      {
        key: "last_triggered_at",
        label: "Last triggered",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 whitespace-nowrap",
        cell: (a) => formatTime(a.last_triggered_at, mode, tz),
      },
    ],
    [mode, tz],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<AlertEntity>("alerts-active", columns);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bell className="h-4 w-4" />
          Active Alerts
          <Badge
            variant={meta.total > 0 ? "destructive" : "success"}
            className="ml-1.5 text-xs"
          >
            {meta.total} firing
          </Badge>
          <div className="ml-auto">
            <DisplayMenu
              columns={columns}
              configMap={configMap}
              onToggleHidden={setHidden}
              onReset={reset}
            />
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {alerts.length === 0 && !listState.hasActiveFilters ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Bell className="mb-2 h-8 w-8 text-emerald-500/50" />
            <p className="text-sm">No active alerts — all clear</p>
          </div>
        ) : (
          <>
            <div
              className={
                compact
                  ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
                  : ""
              }
            >
              <FlexTable<AlertEntity>
                orderedVisibleColumns={orderedVisibleColumns}
                configMap={configMap}
                onOrderChange={setOrder}
                onWidthChange={setWidth}
                rows={alerts}
                rowKey={(a) => a.id}
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filters={listState.filters}
                onFilterChange={(col, v) => listState.setFilter(col, v)}
                rowClassName={(a) => severityRowClass(a.severity)}
                emptyState="No matches for current filters"
              />
            </div>
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

function AlertLogTab({
  entries,
  meta,
  listState,
  isFetching,
}: {
  entries: AlertLogEntry[];
  meta: { limit: number; offset: number; count: number; total: number };
  listState: ReturnType<typeof useListState>;
  isFetching: boolean;
}) {
  const tz = useTimezone();
  const { mode } = useTimeDisplayMode();
  const { compact } = useDisplayPreferences();

  const columns = useMemo<FlexColumnDef<AlertLogEntry>[]>(
    () => [
      {
        key: "occurred_at",
        label: "Time",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (e) => formatTime(e.occurred_at, mode, tz),
      },
      {
        key: "__action",
        label: "Action",
        pickerLabel: "Action",
        sortable: false,
        filterable: false,
        defaultWidth: 90,
        cell: (e) => (
          <Badge className={severityPillClass(e.severity)}>
            {e.severity || "—"}
          </Badge>
        ),
      },
      {
        key: "definition_name",
        label: "Alert",
        defaultWidth: 220,
        cell: (e) => (
          <Link
            to={`/alerts/definitions/${e.definition_id}`}
            className="font-medium text-brand-400 hover:text-brand-300 hover:underline"
          >
            {e.definition_name}
          </Link>
        ),
      },
      {
        key: "device_name",
        label: "Device",
        defaultWidth: 180,
        cell: (e) => (
          <div className="flex items-center gap-1">
            {e.device_id ? (
              <Link
                to={`/devices/${e.device_id}`}
                className="text-brand-400 hover:text-brand-300 hover:underline"
              >
                {e.device_name || e.device_id}
              </Link>
            ) : (
              <span>{e.device_name || "—"}</span>
            )}
            {e.device_name && (
              <button
                type="button"
                className="rounded p-0.5 text-zinc-600 hover:text-brand-400 hover:bg-brand-500/10 transition-colors cursor-pointer"
                title="Filter by this device"
                onClick={() =>
                  listState.setFilter("device_name", e.device_name)
                }
              >
                <Filter className="h-3 w-3" />
              </button>
            )}
          </div>
        ),
      },
      {
        key: "entity_key",
        label: "Entity",
        defaultWidth: 160,
        cellClassName: "text-zinc-400 text-xs font-mono",
        cell: (e) => {
          const labels =
            typeof e.entity_labels === "string"
              ? JSON.parse(e.entity_labels)
              : e.entity_labels || {};
          return labels.if_name || labels.component || e.entity_key || "—";
        },
      },
      {
        key: "current_value",
        label: "Value",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cellClassName: "text-zinc-300",
        cell: (e) =>
          e.action === "fire" && e.current_value != null
            ? Number(e.current_value).toFixed(1)
            : "—",
      },
      {
        key: "fire_count",
        label: "Fires",
        filterable: false,
        defaultWidth: 80,
        cellClassName: "text-zinc-400",
        cell: (e) => e.fire_count,
      },
      {
        key: "message",
        label: "Message",
        sortable: false,
        defaultWidth: 280,
        cellClassName: "text-zinc-400 text-xs max-w-xs truncate",
        cell: (e) => <span title={e.message}>{e.message}</span>,
      },
    ],
    [mode, tz, listState],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<AlertLogEntry>("alerts-log", columns);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileText className="h-4 w-4" />
          Alert Log ({meta.total})
          <div className="ml-auto">
            <DisplayMenu
              columns={columns}
              configMap={configMap}
              onToggleHidden={setHidden}
              onReset={reset}
            />
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 && !listState.hasActiveFilters ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <FileText className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No alert log entries</p>
          </div>
        ) : (
          <>
            <div
              className={
                compact
                  ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
                  : ""
              }
            >
              <FlexTable<AlertLogEntry>
                orderedVisibleColumns={orderedVisibleColumns}
                configMap={configMap}
                onOrderChange={setOrder}
                onWidthChange={setWidth}
                rows={entries}
                rowKey={(e) =>
                  `${e.id ?? `${e.occurred_at}-${e.definition_id}-${e.entity_key ?? ""}`}`
                }
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filters={listState.filters}
                onFilterChange={(col, v) => listState.setFilter(col, v)}
                rowClassName={(e) => severityRowClass(e.severity)}
                emptyState="No matches for current filters"
              />
            </div>
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

function DefinitionsTab({
  definitions,
  listState,
  meta,
  isFetching,
}: {
  definitions: AlertDefinition[];
  listState: ReturnType<typeof useListState>;
  meta: { limit: number; offset: number; count: number; total: number };
  isFetching: boolean;
}) {
  const { compact } = useDisplayPreferences();

  const columns = useMemo<FlexColumnDef<AlertDefinition>[]>(
    () => [
      {
        key: "name",
        label: "Name",
        defaultWidth: 240,
        cell: (d) => (
          <Link
            to={`/alerts/definitions/${d.id}`}
            className="font-medium text-brand-400 hover:text-brand-300 hover:underline"
          >
            {d.name}
          </Link>
        ),
      },
      {
        key: "app_name",
        label: "App",
        sortable: false,
        defaultWidth: 160,
        cellClassName: "text-zinc-400",
        cell: (d) =>
          d.app_name ? (
            <Link
              to={`/apps/${d.app_id}`}
              className="text-brand-400 hover:text-brand-300 hover:underline"
            >
              {d.app_name}
            </Link>
          ) : (
            "—"
          ),
      },
      {
        key: "expression",
        label: "Expression",
        sortable: false,
        defaultWidth: 320,
        cellClassName: "text-zinc-400 font-mono text-xs max-w-xs",
        cell: (d) => (
          <div className="space-y-0.5 truncate">
            {(d.severity_tiers ?? []).map((t, i) => (
              <div key={i} className="flex items-center gap-1.5">
                <span
                  className={`inline-flex items-center rounded px-1 text-[10px] uppercase font-semibold ${severityPillClass(t.severity)}`}
                >
                  {t.severity}
                </span>
                <span className="truncate">{t.expression}</span>
              </div>
            ))}
          </div>
        ),
      },
      {
        key: "__window",
        label: "Window",
        pickerLabel: "Window",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cellClassName: "text-zinc-400",
        cell: (d) => d.window,
      },
      {
        key: "enabled",
        label: "Enabled",
        filterable: false,
        defaultWidth: 100,
        cell: (d) => (
          <Badge variant={d.enabled ? "success" : "default"}>
            {d.enabled ? "Enabled" : "Disabled"}
          </Badge>
        ),
      },
      {
        key: "__instances",
        label: "Instances",
        pickerLabel: "Instances",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cellClassName: "text-zinc-400",
        cell: (d) => d.instance_count ?? 0,
      },
      {
        key: "__active",
        label: "Active",
        pickerLabel: "Active",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cell: (d) =>
          (d.firing_count ?? 0) > 0 ? (
            <Badge variant="destructive">{d.firing_count}</Badge>
          ) : (
            <span className="text-zinc-500">0</span>
          ),
      },
    ],
    [],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<AlertDefinition>("alerts-definitions", columns);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" />
          Alert Definitions ({meta.total})
          <div className="ml-auto">
            <DisplayMenu
              columns={columns}
              configMap={configMap}
              onToggleHidden={setHidden}
              onReset={reset}
            />
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className={
            compact
              ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
              : ""
          }
        >
          <FlexTable<AlertDefinition>
            orderedVisibleColumns={orderedVisibleColumns}
            configMap={configMap}
            onOrderChange={setOrder}
            onWidthChange={setWidth}
            rows={definitions}
            rowKey={(d) => d.id}
            sortBy={listState.sortBy}
            sortDir={listState.sortDir}
            onSort={listState.handleSort}
            filters={listState.filters}
            onFilterChange={(col, v) => listState.setFilter(col, v)}
            emptyState={
              listState.hasActiveFilters
                ? "No definitions match your filters"
                : "No alert definitions configured"
            }
          />
        </div>
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
