import { useState } from "react";
import { Bell, Clock, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
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
  useAlertRules,
  useResolvedAlertInstances,
  useInvertAlertDefinition,
  useCreateAlertDefinition,
} from "@/api/hooks.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useListState } from "@/hooks/useListState.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { AlertInstance, AppAlertDefinition } from "@/types/api.ts";

type Tab = "active" | "history" | "definitions";

const severityVariant = (severity: string) => {
  switch (severity?.toLowerCase()) {
    case "critical":
    case "emergency":
      return "destructive" as const;
    case "warning":
      return "warning" as const;
    case "recovery":
      return "success" as const;
    case "info":
      return "info" as const;
    default:
      return "default" as const;
  }
};

export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("active");
  const { data: alerts, isLoading: alertsLoading } = useActiveAlerts();
  const defsListState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "severity", label: "Severity" },
      { key: "expression", label: "Expression", sortable: false },
    ],
  });
  const { data: defsResponse, isLoading: defsLoading } = useAlertRules(defsListState.params);
  const definitions = defsResponse?.data ?? [];
  const defsMeta = (defsResponse as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };
  const { data: resolvedData, isLoading: resolvedLoading } = useResolvedAlertInstances();

  const isLoading =
    tab === "active" ? alertsLoading :
    tab === "history" ? resolvedLoading :
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
          variant={tab === "history" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("history")}
        >
          <Clock className="h-3.5 w-3.5" />
          History
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
      ) : tab === "history" ? (
        <HistoryTab
          instances={resolvedData?.data ?? []}
          retentionDays={resolvedData?.meta?.retention_days ?? 7}
        />
      ) : (
        <DefinitionsTab definitions={definitions} listState={defsListState} meta={defsMeta} />
      )}
    </div>
  );
}

function ActiveAlertsTab({ alerts }: { alerts: AlertInstance[] }) {
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
                <TableHead>Severity</TableHead>
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
                    <Badge variant={severityVariant(alert.definition_severity ?? "")}>
                      {alert.definition_severity ?? "unknown"}
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
                    {alert.started_at ? timeAgo(alert.started_at) : "—"}
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

function HistoryTab({
  instances,
  retentionDays,
}: {
  instances: AlertInstance[];
  retentionDays: number;
}) {
  const tz = useTimezone();

  const duration = (start: string | null, end: string | null) => {
    if (!start || !end) return "—";
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
    if (ms < 3_600_000) return `${Math.round(ms / 60_000)} min`;
    return `${(ms / 3_600_000).toFixed(1)}h`;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="h-4 w-4" />
          Resolved Alerts ({instances.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        {instances.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Clock className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No resolved alerts in the last {retentionDays} days</p>
          </div>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Severity</TableHead>
                  <TableHead>Alert Name</TableHead>
                  <TableHead>App</TableHead>
                  <TableHead>Device</TableHead>
                  <TableHead>Entity</TableHead>
                  <TableHead>Peak Value</TableHead>
                  <TableHead>Fired At</TableHead>
                  <TableHead>Resolved At</TableHead>
                  <TableHead>Duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {instances.map((inst) => (
                  <TableRow key={inst.id}>
                    <TableCell>
                      <Badge variant={severityVariant(inst.definition_severity ?? "")}>
                        {inst.definition_severity ?? "unknown"}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-medium text-zinc-100">
                      {inst.definition_name ?? inst.definition_id}
                    </TableCell>
                    <TableCell className="text-zinc-400">
                      {inst.app_name ?? ""}
                    </TableCell>
                    <TableCell className="text-zinc-300">
                      {inst.device_name ?? ""}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-xs font-mono">
                      {inst.entity_labels?.if_name ||
                        inst.entity_labels?.component ||
                        inst.entity_key ||
                        "—"}
                    </TableCell>
                    <TableCell className="text-zinc-300">
                      {inst.current_value != null
                        ? Number(inst.current_value).toFixed(1)
                        : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-xs">
                      {inst.started_at ? formatDate(inst.started_at, tz) : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-xs">
                      {inst.resolved_at ? formatDate(inst.resolved_at, tz) : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400">
                      {duration(inst.started_at, inst.resolved_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="mt-3 text-xs text-zinc-600">
              Showing resolved alerts from the last {retentionDays} days
            </p>
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
  definitions: AppAlertDefinition[];
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
        app_version_id: data.app_version_id,
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
              <FilterableSortHead col="severity" label="Severity" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.severity} onFilterChange={(v) => listState.setFilter("severity", v)} />
              <FilterableSortHead col="enabled" label="Enabled" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
              <TableHead>Instances</TableHead>
              <TableHead>Firing</TableHead>
              <TableHead className="w-12"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {definitions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-zinc-500 py-8">
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
                    <Badge variant={severityVariant(defn.severity)}>
                      {defn.severity}
                    </Badge>
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
