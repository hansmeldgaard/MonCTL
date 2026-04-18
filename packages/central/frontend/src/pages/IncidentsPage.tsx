import { useMemo, useState } from "react";
import {
  Activity,
  Check,
  ChevronRight,
  Clock,
  Loader2,
  ShieldAlert,
  ShieldOff,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { useIncidents } from "@/api/hooks.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import { formatTime } from "@/lib/utils.ts";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";
import type { Incident } from "@/types/api.ts";

type Tab = "open" | "cleared";

const severityVariant = (severity: string) => {
  switch (severity?.toLowerCase()) {
    case "critical":
    case "emergency":
      return "destructive" as const;
    case "warning":
      return "warning" as const;
    case "info":
      return "info" as const;
    default:
      return "default" as const;
  }
};

export function IncidentsPage() {
  const [tab, setTab] = useState<Tab>("open");
  const { pageSize, scrollMode } = useTablePreferences();

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1 rounded-lg bg-zinc-900 p-1 w-fit border border-zinc-800">
        <Button
          variant={tab === "open" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("open")}
        >
          <Activity className="h-3.5 w-3.5" />
          Open
        </Button>
        <Button
          variant={tab === "cleared" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("cleared")}
        >
          <Clock className="h-3.5 w-3.5" />
          Cleared
        </Button>
      </div>

      <IncidentsTable
        key={tab}
        state={tab}
        pageSize={pageSize}
        scrollMode={scrollMode}
      />
    </div>
  );
}

function IncidentsTable({
  state,
  pageSize,
  scrollMode,
}: {
  state: Tab;
  pageSize: number;
  scrollMode: ReturnType<typeof useTablePreferences>["scrollMode"];
}) {
  const tz = useTimezone();
  const { mode } = useTimeDisplayMode();
  const { compact } = useDisplayPreferences();

  const listState = useListState({
    columns: [
      { key: "severity", label: "Severity" },
      { key: "rule_name", label: "Rule" },
      { key: "device_name", label: "Device" },
      { key: "opened_at", label: "Opened", filterable: false },
    ],
    defaultSortBy: "opened_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });

  const params = { ...listState.params, state };
  const { data: response, isLoading, isFetching } = useIncidents(params);
  const incidents = response?.data ?? [];
  const meta = response?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };

  // Parent lookup for suppression indent. A child's parent may be on
  // another page — fall back to the raw UUID suffix in that case.
  const byId = new Map<string, Incident>();
  for (const inc of incidents) byId.set(inc.id, inc);

  const columns = useMemo<FlexColumnDef<Incident>[]>(() => {
    const base: FlexColumnDef<Incident>[] = [
      {
        key: "severity",
        label: "Severity",
        defaultWidth: 110,
        cell: (inc) => (
          <Badge variant={severityVariant(inc.severity)}>{inc.severity}</Badge>
        ),
      },
      {
        key: "rule_name",
        label: "Rule",
        defaultWidth: 280,
        cell: (inc) => {
          const isSuppressed = inc.parent_incident_id !== null;
          return (
            <div
              className={
                isSuppressed
                  ? "flex items-center gap-1 pl-4 text-zinc-400"
                  : "font-medium text-zinc-100"
              }
            >
              {isSuppressed && (
                <ChevronRight className="h-3 w-3 text-zinc-600" />
              )}
              <Link
                to={`/incident-rules?rule_id=${inc.rule_id}`}
                className="hover:text-brand-400 transition-colors"
              >
                {inc.rule_name ?? inc.rule_id}
              </Link>
            </div>
          );
        },
      },
      {
        key: "device_name",
        label: "Device",
        defaultWidth: 180,
        cellClassName: "text-zinc-300",
        cell: (inc) => {
          const deviceName =
            (inc.labels as Record<string, string>)?.device_name ??
            inc.device_id ??
            "—";
          return deviceName;
        },
      },
      {
        key: "__fire_count",
        label: "Fire count",
        pickerLabel: "Fire count",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cellClassName: "text-zinc-300 font-mono text-xs",
        cell: (inc) => inc.fire_count,
      },
      {
        key: "opened_at",
        label: "Opened",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-400 text-xs whitespace-nowrap",
        cell: (inc) => formatTime(inc.opened_at, mode, tz),
      },
      {
        key: "__last_fire",
        label: "Last fire",
        pickerLabel: "Last fire",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-400 text-xs whitespace-nowrap",
        cell: (inc) => formatTime(inc.last_fired_at, mode, tz),
      },
    ];
    if (state === "cleared") {
      base.push({
        key: "__cleared_reason",
        label: "Cleared reason",
        pickerLabel: "Cleared reason",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cell: (inc) =>
          inc.cleared_reason ? (
            <Badge
              variant={
                inc.cleared_reason === "out_of_scope" ? "info" : "default"
              }
            >
              {inc.cleared_reason}
            </Badge>
          ) : (
            <span className="text-xs text-zinc-600">—</span>
          ),
      });
    }
    base.push({
      key: "__suppression",
      label: "Suppression",
      pickerLabel: "Suppression",
      sortable: false,
      filterable: false,
      defaultWidth: 180,
      cell: (inc) => {
        const isSuppressed = inc.parent_incident_id !== null;
        const parent = isSuppressed ? byId.get(inc.parent_incident_id!) : null;
        if (!isSuppressed) {
          return (
            <div className="flex items-center gap-1 text-xs text-zinc-500">
              <Check className="h-3 w-3 text-emerald-500" />
              primary
            </div>
          );
        }
        return (
          <div className="flex items-center gap-1 text-xs text-zinc-500">
            <ShieldOff className="h-3 w-3" />
            <span>
              under{" "}
              {parent ? (
                <span className="text-zinc-300">
                  {parent.rule_name ?? "parent"}
                </span>
              ) : (
                <span className="font-mono text-[10px]">
                  {inc.parent_incident_id!.slice(0, 8)}…
                </span>
              )}
            </span>
          </div>
        );
      },
    });
    return base;
  }, [state, mode, tz, byId]);

  const tableId = state === "open" ? "incidents-open" : "incidents-cleared";
  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<Incident>(tableId, columns);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            {state === "open" ? (
              <ShieldAlert className="h-4 w-4" />
            ) : (
              <ShieldOff className="h-4 w-4" />
            )}
            {state === "open" ? "Open incidents" : "Cleared incidents"} (
            {meta.total})
          </CardTitle>
          <DisplayMenu
            columns={columns}
            configMap={configMap}
            onToggleHidden={setHidden}
            onReset={reset}
          />
        </div>
        <p className="text-xs text-zinc-500 mt-1">
          Live output of the IncidentEngine (phase 1 shadow). Suppressed
          children are indented under the parent incident that triggered their
          suppression. Read-only — the engine owns all mutations.
        </p>
      </CardHeader>
      <CardContent>
        <div
          className={
            compact
              ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
              : ""
          }
        >
          <FlexTable<Incident>
            orderedVisibleColumns={orderedVisibleColumns}
            configMap={configMap}
            onOrderChange={setOrder}
            onWidthChange={setWidth}
            rows={incidents}
            rowKey={(inc) => inc.id}
            sortBy={listState.sortBy}
            sortDir={listState.sortDir}
            onSort={listState.handleSort}
            filters={listState.filters}
            onFilterChange={(col, v) => listState.setFilter(col, v)}
            rowClassName={(inc) =>
              inc.parent_incident_id !== null ? "bg-zinc-900/30" : undefined
            }
            emptyState={
              listState.hasActiveFilters
                ? "No incidents match your filters"
                : state === "open"
                  ? "No open incidents right now"
                  : "No cleared incidents in the window"
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
