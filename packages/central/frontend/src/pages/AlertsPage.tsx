import { useState } from "react";
import { Bell, FileText, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
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
  useActiveAlerts,
  useAlertLog,
  useAlertRules,
  useInvertAlertDefinition,
  useCreateAlertDefinition,
} from "@/api/hooks.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useListState } from "@/hooks/useListState.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { AlertEntity, AlertDefinition, AlertLogEntry } from "@/types/api.ts";

type Tab = "active" | "log" | "definitions";


export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("active");
  const { data: alerts, isLoading: alertsLoading } = useActiveAlerts();
  const defsListState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "expression", label: "Expression", sortable: false },
    ],
  });
  const { data: defsResponse, isLoading: defsLoading } = useAlertRules(defsListState.params);
  const definitions = defsResponse?.data ?? [];
  const defsMeta = (defsResponse as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };

  // Alert log state
  const [logPage, setLogPage] = useState(0);
  const [logAction, setLogAction] = useState<string>("");
  const LOG_PAGE_SIZE = 50;
  const { data: logResponse, isLoading: logLoading } = useAlertLog({
    action: logAction || undefined,
    limit: LOG_PAGE_SIZE,
    offset: logPage * LOG_PAGE_SIZE,
  });
  const logEntries = logResponse?.data ?? [];
  const logMeta = (logResponse as any)?.meta ?? { limit: LOG_PAGE_SIZE, offset: 0, count: 0, total: 0 };

  const isLoading =
    tab === "active" ? alertsLoading :
    tab === "log" ? logLoading :
    defsLoading;

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
          {alerts && alerts.length > 0 && (
            <Badge variant="destructive" className="ml-1.5">
              {alerts.length}
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
        <ActiveAlertsTab alerts={alerts ?? []} />
      ) : tab === "log" ? (
        <AlertLogTab
          entries={logEntries}
          meta={logMeta}
          page={logPage}
          onPageChange={setLogPage}
          action={logAction}
          onActionChange={(v) => { setLogAction(v); setLogPage(0); }}
        />
      ) : (
        <DefinitionsTab definitions={definitions} listState={defsListState} meta={defsMeta} />
      )}
    </div>
  );
}

function ActiveAlertsTab({ alerts }: { alerts: AlertEntity[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bell className="h-4 w-4" />
          Active Alerts ({alerts.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        {alerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Bell className="mb-2 h-8 w-8 text-emerald-500/50" />
            <p className="text-sm">No active alerts — all clear</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>State</TableHead>
                <TableHead>Alert Name</TableHead>
                <TableHead>App</TableHead>
                <TableHead>Device</TableHead>
                <TableHead>Entity</TableHead>
                <TableHead>Value</TableHead>
                <TableHead>Fire Count</TableHead>
                <TableHead>Firing Since</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {alerts.map((alert) => (
                <TableRow key={alert.id}>
                  <TableCell>
                    <Badge variant={alert.state === "firing" ? "destructive" : "success"}>
                      {alert.state === "firing" ? "ACTIVE" : "CLEARED"}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-medium text-zinc-100">
                    {alert.definition_name ?? alert.definition_id}
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {alert.app_name ?? ""}
                  </TableCell>
                  <TableCell className="text-zinc-300">
                    {alert.device_name ?? ""}
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
                    {alert.started_firing_at ? timeAgo(alert.started_firing_at) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function AlertLogTab({
  entries,
  meta,
  page,
  onPageChange,
  action,
  onActionChange,
}: {
  entries: AlertLogEntry[];
  meta: { limit: number; offset: number; count: number; total: number };
  page: number;
  onPageChange: (p: number) => void;
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
        {entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <FileText className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No alert log entries</p>
          </div>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Alert</TableHead>
                  <TableHead>Device</TableHead>
                  <TableHead>Entity</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead>Fire Count</TableHead>
                  <TableHead>Message</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((entry, i) => {
                  const labels = typeof entry.entity_labels === "string"
                    ? JSON.parse(entry.entity_labels) : entry.entity_labels || {};
                  return (
                    <TableRow key={`${entry.id ?? i}`}>
                      <TableCell className="text-zinc-500 text-xs whitespace-nowrap">
                        {formatDate(entry.occurred_at, tz)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={entry.action === "fire" ? "destructive" : "success"}>
                          {entry.action}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium text-zinc-100">
                        {entry.definition_name}
                      </TableCell>
                      <TableCell className="text-zinc-300">
                        {entry.device_name}
                      </TableCell>
                      <TableCell className="text-zinc-400 text-xs font-mono">
                        {labels.if_name || labels.component || entry.entity_key || "—"}
                      </TableCell>
                      <TableCell className="text-zinc-300">
                        {entry.action === "fire" && entry.current_value != null
                          ? Number(entry.current_value).toFixed(1)
                          : "—"}
                      </TableCell>
                      <TableCell className="text-zinc-400">
                        {entry.fire_count}
                      </TableCell>
                      <TableCell className="text-zinc-400 text-xs max-w-xs truncate">
                        {entry.message}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <PaginationBar
              page={page}
              pageSize={meta.limit}
              total={meta.total}
              count={meta.count}
              onPageChange={onPageChange}
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
}: {
  definitions: AlertDefinition[];
  listState: ReturnType<typeof useListState>;
  meta: { limit: number; offset: number; count: number; total: number };
}) {
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
              <FilterableSortHead col="name" label="Name" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.name} onFilterChange={(v) => listState.setFilter("name", v)} />
              <FilterableSortHead col="expression" label="Expression" sortable={false} sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.expression} onFilterChange={(v) => listState.setFilter("expression", v)} />
              <TableHead>Window</TableHead>
              <FilterableSortHead col="enabled" label="Enabled" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
              <TableHead>Instances</TableHead>
              <TableHead>Active</TableHead>
              <TableHead className="w-12"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {definitions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-zinc-500 py-8">
                  {listState.hasActiveFilters ? "No definitions match your filters" : "No alert definitions configured"}
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
                  <TableCell className="text-zinc-400">
                    {defn.window}
                  </TableCell>
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
                    {!hasChanged(defn.expression) && (
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
        />
      </CardContent>
    </Card>
  );
}
