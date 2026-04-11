import { useState } from "react";
import { Check, CheckCheck, Clock, Loader2, Play, Zap } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import {
  useActiveEvents,
  useAcknowledgeEvents,
  useClearEvents,
  useClearedEvents,
} from "@/api/hooks.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import type { MonitoringEvent } from "@/types/api.ts";

// EventsPage now only serves the historical CH events Active/Cleared
// read surface. EventPolicy CRUD + the legacy "Policies" tab were
// retired as part of the event policy rework's phase deprecation —
// operators manage rules via /incident-rules and observe incident
// lifecycle via /incidents. See docs/event-policy-rework.md.

type Tab = "active" | "cleared";

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

export function EventsPage() {
  const [tab, setTab] = useState<Tab>("active");
  const { pageSize, scrollMode } = useTablePreferences();
  const activeListState = useListState({
    columns: [
      { key: "severity", label: "Severity" },
      { key: "source", label: "Source" },
      { key: "policy_name", label: "Policy" },
      { key: "message", label: "Message" },
      { key: "device_name", label: "Device" },
      { key: "occurred_at", label: "Occurred", filterable: false },
    ],
    defaultSortBy: "occurred_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });
  const clearedListState = useListState({
    columns: [
      { key: "severity", label: "Severity" },
      { key: "source", label: "Source" },
      { key: "policy_name", label: "Policy" },
      { key: "message", label: "Message" },
      { key: "device_name", label: "Device" },
      { key: "occurred_at", label: "Occurred", filterable: false },
    ],
    defaultSortBy: "occurred_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: activeResponse,
    isLoading: activeLoading,
    isFetching: activeFetching,
  } = useActiveEvents(activeListState.params);
  const activeEvents = activeResponse?.data ?? [];
  const activeMeta = (activeResponse as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };
  const {
    data: clearedResponse,
    isLoading: clearedLoading,
    isFetching: clearedFetching,
  } = useClearedEvents(clearedListState.params);
  const clearedEvents = clearedResponse?.data ?? [];
  const clearedMeta = (clearedResponse as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };
  const isLoading =
    tab === "active"
      ? activeLoading
      : tab === "cleared"
        ? clearedLoading
        : false;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1 rounded-lg bg-zinc-900 p-1 w-fit border border-zinc-800">
        <Button
          variant={tab === "active" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("active")}
        >
          <Zap className="h-3.5 w-3.5" />
          Active Events
          {activeMeta.total > 0 && (
            <Badge variant="destructive" className="ml-1.5">
              {activeMeta.total}
            </Badge>
          )}
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

      {isLoading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
        </div>
      ) : tab === "active" ? (
        <ActiveEventsTab
          events={activeEvents}
          listState={activeListState}
          meta={activeMeta}
          isFetching={activeFetching}
        />
      ) : (
        <ClearedEventsTab
          events={clearedEvents}
          listState={clearedListState}
          meta={clearedMeta}
          isFetching={clearedFetching}
        />
      )}
    </div>
  );
}

function ActiveEventsTab({
  events,
  listState,
  meta,
  isFetching,
}: {
  events: MonitoringEvent[];
  listState: ReturnType<typeof useListState>;
  meta: { limit: number; offset: number; count: number; total: number };
  isFetching: boolean;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const navigate = useNavigate();
  const ackMut = useAcknowledgeEvents();
  const clearMut = useClearEvents();

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === events.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(events.map((e) => e.id)));
    }
  };

  const handleAck = async () => {
    await ackMut.mutateAsync([...selected]);
    setSelected(new Set());
  };

  const handleClear = async () => {
    await clearMut.mutateAsync([...selected]);
    setSelected(new Set());
  };

  const handleCreateAutomation = () => {
    // Collect unique severities and device IDs from selected events
    const selectedEvents = events.filter((e) => selected.has(e.id));
    const severities = [
      ...new Set(selectedEvents.map((e) => e.severity).filter(Boolean)),
    ];
    const deviceIds = [
      ...new Set(selectedEvents.map((e) => e.device_id).filter(Boolean)),
    ];
    const severity = severities.length === 1 ? severities[0] : "";

    // Navigate to automations page with prefilled state
    navigate("/automations", {
      state: {
        prefill: {
          trigger_type: "event",
          event_severity_filter: severity,
          device_ids: deviceIds,
        },
      },
    });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-4 w-4" />
            Active Events ({meta.total})
          </CardTitle>
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleAck()}
                disabled={ackMut.isPending}
              >
                <Check className="h-3.5 w-3.5" />
                Acknowledge ({selected.size})
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleClear()}
                disabled={clearMut.isPending}
              >
                <CheckCheck className="h-3.5 w-3.5" />
                Clear ({selected.size})
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleCreateAutomation}
              >
                <Play className="h-3.5 w-3.5" />
                Create Automation
              </Button>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <input
                  type="checkbox"
                  checked={selected.size === events.length && events.length > 0}
                  onChange={toggleAll}
                  className="rounded border-zinc-700"
                />
              </TableHead>
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
                col="source"
                label="Source"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.source}
                onFilterChange={(v) => listState.setFilter("source", v)}
              />
              <FilterableSortHead
                col="policy_name"
                label="Policy"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.policy_name}
                onFilterChange={(v) => listState.setFilter("policy_name", v)}
              />
              <FilterableSortHead
                col="message"
                label="Message"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.message}
                onFilterChange={(v) => listState.setFilter("message", v)}
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
              <FilterableSortHead
                col="occurred_at"
                label="Occurred"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="text-center text-zinc-500 py-8"
                >
                  {listState.hasActiveFilters
                    ? "No events match your filters"
                    : "No active events"}
                </TableCell>
              </TableRow>
            ) : (
              events.map((evt) => (
                <TableRow key={evt.id}>
                  <TableCell>
                    <input
                      type="checkbox"
                      checked={selected.has(evt.id)}
                      onChange={() => toggle(evt.id)}
                      className="rounded border-zinc-700"
                    />
                  </TableCell>
                  <TableCell>
                    <Badge variant={severityVariant(evt.severity)}>
                      {evt.severity}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-zinc-400 text-xs">
                    {evt.source}
                  </TableCell>
                  <TableCell className="text-zinc-300 text-sm">
                    {evt.policy_name || evt.definition_name}
                  </TableCell>
                  <TableCell className="text-zinc-300 text-sm max-w-sm truncate">
                    {evt.message}
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {evt.device_id ? (
                      <Link
                        to={`/devices/${evt.device_id}`}
                        className="text-brand-400 hover:text-brand-300 hover:underline"
                      >
                        {evt.device_name || evt.device_id}
                      </Link>
                    ) : (
                      evt.device_name || "—"
                    )}
                  </TableCell>
                  <TableCell className="text-zinc-500">
                    {evt.occurred_at ? timeAgo(evt.occurred_at) : "—"}
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

function ClearedEventsTab({
  events,
  listState,
  meta,
  isFetching,
}: {
  events: MonitoringEvent[];
  listState: ReturnType<typeof useListState>;
  meta: { limit: number; offset: number; count: number; total: number };
  isFetching: boolean;
}) {
  const tz = useTimezone();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="h-4 w-4" />
          Cleared Events ({meta.total})
        </CardTitle>
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
                col="source"
                label="Source"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.source}
                onFilterChange={(v) => listState.setFilter("source", v)}
              />
              <FilterableSortHead
                col="policy_name"
                label="Policy"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.policy_name}
                onFilterChange={(v) => listState.setFilter("policy_name", v)}
              />
              <FilterableSortHead
                col="message"
                label="Message"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.message}
                onFilterChange={(v) => listState.setFilter("message", v)}
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
              <FilterableSortHead
                col="occurred_at"
                label="Occurred"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <TableHead>Cleared At</TableHead>
              <TableHead>Cleared By</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={8}
                  className="text-center text-zinc-500 py-8"
                >
                  {listState.hasActiveFilters
                    ? "No events match your filters"
                    : "No cleared events"}
                </TableCell>
              </TableRow>
            ) : (
              events.map((evt) => (
                <TableRow key={evt.id}>
                  <TableCell>
                    <Badge variant={severityVariant(evt.severity)}>
                      {evt.severity}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-zinc-400 text-xs">
                    {evt.source}
                  </TableCell>
                  <TableCell className="text-zinc-300 text-sm">
                    {evt.policy_name || evt.definition_name || "—"}
                  </TableCell>
                  <TableCell className="text-zinc-300 text-sm max-w-sm truncate">
                    {evt.message}
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {evt.device_id ? (
                      <Link
                        to={`/devices/${evt.device_id}`}
                        className="text-brand-400 hover:text-brand-300 hover:underline"
                      >
                        {evt.device_name || evt.device_id}
                      </Link>
                    ) : (
                      evt.device_name || "—"
                    )}
                  </TableCell>
                  <TableCell className="text-zinc-500 text-xs">
                    {evt.occurred_at ? formatDate(evt.occurred_at, tz) : "—"}
                  </TableCell>
                  <TableCell className="text-zinc-500 text-xs">
                    {evt.cleared_at ? formatDate(evt.cleared_at, tz) : "—"}
                  </TableCell>
                  <TableCell className="text-zinc-400 text-xs">
                    {evt.cleared_by || "—"}
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

// `PoliciesTab` and `PolicyDialog` were removed in the event policy
// rework's phase deprecation (see docs/event-policy-rework.md). Rule
// configuration lives at /incident-rules now. The Active and Cleared
// event tabs above still query the append-only CH events table for
// historical observation.
