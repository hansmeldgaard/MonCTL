import { useState } from "react";
import { Link } from "react-router-dom";
import { Bell, FileText, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import {
  useAlertInstances,
  useAlertLog,
  useAlertRules,
  useInvertAlertDefinition,
  useCreateAlertDefinition,
} from "@/api/hooks.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type {
  AlertEntity,
  AlertDefinition,
  AlertLogEntry,
} from "@/types/api.ts";

type Tab = "active" | "log" | "definitions";

export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("active");
  const { pageSize, scrollMode } = useTablePreferences();

  // Active alerts (global, firing-only)
  const activeListState = useListState({
    columns: [
      { key: "definition_name", label: "Alert" },
      { key: "app_name", label: "App" },
      { key: "device_name", label: "Device" },
      { key: "entity_key", label: "Entity" },
      { key: "current_value", label: "Value", filterable: false },
      { key: "fire_count", label: "Fires", filterable: false },
      { key: "started_firing_at", label: "Since", filterable: false },
    ],
    defaultSortBy: "started_firing_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: activeResponse,
    isLoading: alertsLoading,
    isFetching: activeFetching,
  } = useAlertInstances({ state: "firing", ...activeListState.params });
  const activeAlerts: AlertEntity[] = (activeResponse as any)?.data ?? [];
  const activeMeta = (activeResponse as any)?.meta ?? {
    limit: activeListState.pageSize,
    offset: 0,
    count: 0,
    total: 0,
  };

  const defsListState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "expression", label: "Expression", sortable: false },
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
  const defsMeta = (defsResponse as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };

  // Alert log state
  const [logAction, setLogAction] = useState<string>("");
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
    action: logAction || undefined,
  });
  const logEntries = logResponse?.data ?? [];
  const logMeta = (logResponse as any)?.meta ?? {
    limit: logListState.pageSize,
    offset: 0,
    count: 0,
    total: 0,
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
          action={logAction}
          onActionChange={(v) => {
            setLogAction(v);
            logListState.setPage(0);
          }}
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
            <Table>
              <TableHeader>
                <TableRow>
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
                    col="device_name"
                    label="Device"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterValue={listState.filters.device_name}
                    onFilterChange={(v) =>
                      listState.setFilter("device_name", v)
                    }
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
                    col="started_firing_at"
                    label="Since"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterable={false}
                  />
                </TableRow>
              </TableHeader>
              <TableBody>
                {alerts.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={7}
                      className="text-center text-sm text-zinc-500 py-8"
                    >
                      No matches for current filters
                    </TableCell>
                  </TableRow>
                ) : (
                  alerts.map((alert) => (
                    <TableRow key={alert.id} className="bg-red-500/5">
                      <TableCell className="font-medium text-zinc-100">
                        {alert.definition_name ?? alert.definition_id}
                      </TableCell>
                      <TableCell className="text-zinc-400">
                        {alert.app_name ?? ""}
                      </TableCell>
                      <TableCell className="text-zinc-300">
                        {alert.device_id ? (
                          <Link
                            to={`/devices/${alert.device_id}`}
                            className="text-brand-400 hover:text-brand-300 hover:underline"
                          >
                            {alert.device_name ?? alert.device_id}
                          </Link>
                        ) : (
                          (alert.device_name ?? "—")
                        )}
                      </TableCell>
                      <TableCell className="text-zinc-400 text-xs font-mono">
                        {alert.entity_labels?.if_name ||
                          alert.entity_labels?.component ||
                          alert.entity_key ||
                          "—"}
                      </TableCell>
                      <TableCell className="text-zinc-300">
                        {alert.current_value != null
                          ? Number(alert.current_value).toFixed(1)
                          : "—"}
                      </TableCell>
                      <TableCell className="text-zinc-400">
                        {alert.fire_count}
                      </TableCell>
                      <TableCell className="text-zinc-500">
                        {alert.started_firing_at
                          ? timeAgo(alert.started_firing_at)
                          : "—"}
                      </TableCell>
                    </TableRow>
                  ))
                )}
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

function AlertLogTab({
  entries,
  meta,
  listState,
  isFetching,
  action,
  onActionChange,
}: {
  entries: AlertLogEntry[];
  meta: { limit: number; offset: number; count: number; total: number };
  listState: ReturnType<typeof useListState>;
  isFetching: boolean;
  action: string;
  onActionChange: (v: string) => void;
}) {
  const tz = useTimezone();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileText className="h-4 w-4" />
          Alert Log ({meta.total})
          <div className="ml-auto flex items-center gap-1">
            {["", "fire", "clear"].map((v) => (
              <Button
                key={v}
                variant={action === v ? "secondary" : "ghost"}
                size="sm"
                onClick={() => onActionChange(v)}
              >
                {v === "" ? "All" : v === "fire" ? "Fire" : "Clear"}
              </Button>
            ))}
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
            <Table>
              <TableHeader>
                <TableRow>
                  <FilterableSortHead
                    col="occurred_at"
                    label="Time"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterable={false}
                  />
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
                  <FilterableSortHead
                    col="device_name"
                    label="Device"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterValue={listState.filters.device_name}
                    onFilterChange={(v) =>
                      listState.setFilter("device_name", v)
                    }
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
                  <TableHead className="w-24">Value</TableHead>
                  <FilterableSortHead
                    col="fire_count"
                    label="Fires"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterable={false}
                  />
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
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={8}
                      className="text-center text-sm text-zinc-500 py-8"
                    >
                      No matches for current filters
                    </TableCell>
                  </TableRow>
                ) : (
                  entries.map((entry, i) => {
                    const labels =
                      typeof entry.entity_labels === "string"
                        ? JSON.parse(entry.entity_labels)
                        : entry.entity_labels || {};
                    return (
                      <TableRow
                        key={`${entry.id ?? i}`}
                        className={
                          entry.action === "fire"
                            ? "bg-red-500/5"
                            : "bg-green-500/5"
                        }
                      >
                        <TableCell className="text-zinc-500 text-xs whitespace-nowrap">
                          {formatDate(entry.occurred_at, tz)}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              entry.action === "fire"
                                ? "destructive"
                                : "success"
                            }
                          >
                            {entry.action}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-medium text-zinc-100">
                          {entry.definition_name}
                        </TableCell>
                        <TableCell className="text-zinc-300">
                          {entry.device_id ? (
                            <Link
                              to={`/devices/${entry.device_id}`}
                              className="text-brand-400 hover:text-brand-300 hover:underline"
                            >
                              {entry.device_name || entry.device_id}
                            </Link>
                          ) : (
                            entry.device_name || "—"
                          )}
                        </TableCell>
                        <TableCell className="text-zinc-400 text-xs font-mono">
                          {labels.if_name ||
                            labels.component ||
                            entry.entity_key ||
                            "—"}
                        </TableCell>
                        <TableCell className="text-zinc-300">
                          {entry.action === "fire" &&
                          entry.current_value != null
                            ? Number(entry.current_value).toFixed(1)
                            : "—"}
                        </TableCell>
                        <TableCell className="text-zinc-400">
                          {entry.fire_count}
                        </TableCell>
                        <TableCell
                          className="text-zinc-400 text-xs max-w-xs truncate"
                          title={entry.message}
                        >
                          {entry.message}
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
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
  const { canCreate } = usePermissions();
  const invertDef = useInvertAlertDefinition();
  const createDef = useCreateAlertDefinition();
  const [invertingId, setInvertingId] = useState<string | null>(null);

  const handleCreateRecovery = async (defnId: string) => {
    setInvertingId(defnId);
    try {
      const res = await invertDef.mutateAsync(defnId);
      const data = res.data;
      await createDef.mutateAsync({
        app_id: data.app_id,
        name: data.suggested_name,
        expression: data.inverted_expression,
        window: data.window,
        severity: data.severity,
      });
    } catch {
      // silently fail — user sees the button stop spinning
    } finally {
      setInvertingId(null);
    }
  };

  const hasChanged = (expr: string) =>
    /\bCHANGED\b/.test(expr) && !/[><=!]/.test(expr);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" />
          Alert Definitions ({meta.total})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <FilterableSortHead
                col="name"
                label="Name"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.name}
                onFilterChange={(v) => listState.setFilter("name", v)}
              />
              <FilterableSortHead
                col="expression"
                label="Expression"
                sortable={false}
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.expression}
                onFilterChange={(v) => listState.setFilter("expression", v)}
              />
              <TableHead>Window</TableHead>
              <FilterableSortHead
                col="enabled"
                label="Enabled"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <TableHead>Instances</TableHead>
              <TableHead>Active</TableHead>
              <TableHead className="w-12"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {definitions.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="text-center text-zinc-500 py-8"
                >
                  {listState.hasActiveFilters
                    ? "No definitions match your filters"
                    : "No alert definitions configured"}
                </TableCell>
              </TableRow>
            ) : (
              definitions.map((defn) => (
                <TableRow key={defn.id}>
                  <TableCell className="font-medium text-zinc-100">
                    {defn.name}
                  </TableCell>
                  <TableCell className="text-zinc-400 font-mono text-xs max-w-xs truncate">
                    {defn.expression}
                  </TableCell>
                  <TableCell className="text-zinc-400">{defn.window}</TableCell>
                  <TableCell>
                    <Badge variant={defn.enabled ? "success" : "default"}>
                      {defn.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {defn.instance_count ?? 0}
                  </TableCell>
                  <TableCell>
                    {(defn.firing_count ?? 0) > 0 ? (
                      <Badge variant="destructive">{defn.firing_count}</Badge>
                    ) : (
                      <span className="text-zinc-500">0</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {canCreate("alert") && !hasChanged(defn.expression) && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-zinc-500 hover:text-brand-400"
                        title="Create Recovery Alert"
                        disabled={invertingId === defn.id}
                        onClick={() => handleCreateRecovery(defn.id)}
                      >
                        {invertingId === defn.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <RefreshCw className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
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
