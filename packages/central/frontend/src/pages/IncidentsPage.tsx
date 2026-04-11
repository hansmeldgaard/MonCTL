import { useState } from "react";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { useIncidents } from "@/api/hooks.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import { timeAgo } from "@/lib/utils.ts";
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

  // Build a lookup of primary incidents for the suppression indent. A
  // child incident's `parent_incident_id` may point at a primary that's
  // on a different page — in that case we still render the child but
  // with the raw parent UUID as the label.
  const byId = new Map<string, Incident>();
  for (const inc of incidents) byId.set(inc.id, inc);

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
        </div>
        <p className="text-xs text-zinc-500 mt-1">
          Live output of the IncidentEngine (phase 1 shadow). Suppressed
          children are indented under the parent incident that triggered their
          suppression. Read-only — the engine owns all mutations.
        </p>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <FilterableSortHead
                col="severity"
                label="Severity"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.severity}
                onFilterChange={(v) => listState.setFilter("severity", v)}
              />
              <FilterableSortHead
                col="rule_name"
                label="Rule"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.rule_name}
                onFilterChange={(v) => listState.setFilter("rule_name", v)}
              />
              <FilterableSortHead
                col="device_name"
                label="Device"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.device_name}
                onFilterChange={(v) => listState.setFilter("device_name", v)}
              />
              <TableHead>Fire count</TableHead>
              <FilterableSortHead
                col="opened_at"
                label="Opened"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <TableHead>Last fire</TableHead>
              {state === "cleared" && <TableHead>Cleared reason</TableHead>}
              <TableHead>Suppression</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {incidents.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={state === "cleared" ? 8 : 7}
                  className="text-center text-zinc-500 py-8"
                >
                  {listState.hasActiveFilters
                    ? "No incidents match your filters"
                    : state === "open"
                      ? "No open incidents right now"
                      : "No cleared incidents in the window"}
                </TableCell>
              </TableRow>
            ) : (
              incidents.map((inc) => {
                const isSuppressed = inc.parent_incident_id !== null;
                const parent = isSuppressed
                  ? byId.get(inc.parent_incident_id!)
                  : null;
                const deviceName =
                  (inc.labels as Record<string, string>)?.device_name ??
                  inc.device_id ??
                  "—";
                return (
                  <TableRow
                    key={inc.id}
                    className={isSuppressed ? "bg-zinc-900/30" : ""}
                  >
                    <TableCell>
                      <Badge variant={severityVariant(inc.severity)}>
                        {inc.severity}
                      </Badge>
                    </TableCell>
                    <TableCell>
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
                    </TableCell>
                    <TableCell className="text-zinc-300">
                      {deviceName}
                    </TableCell>
                    <TableCell className="text-zinc-300 font-mono text-xs">
                      {inc.fire_count}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-xs">
                      {timeAgo(inc.opened_at)}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-xs">
                      {timeAgo(inc.last_fired_at)}
                    </TableCell>
                    {state === "cleared" && (
                      <TableCell>
                        {inc.cleared_reason ? (
                          <Badge
                            variant={
                              inc.cleared_reason === "out_of_scope"
                                ? "info"
                                : "default"
                            }
                          >
                            {inc.cleared_reason}
                          </Badge>
                        ) : (
                          <span className="text-xs text-zinc-600">—</span>
                        )}
                      </TableCell>
                    )}
                    <TableCell>
                      {isSuppressed ? (
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
                      ) : (
                        <div className="flex items-center gap-1 text-xs text-zinc-500">
                          <Check className="h-3 w-3 text-emerald-500" />
                          primary
                        </div>
                      )}
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
      </CardContent>
    </Card>
  );
}
