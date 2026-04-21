import { useState } from "react";
import { CheckCheck, Clock, Loader2, Zap } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
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
import {
  useClearIncidents,
  useDeviceActiveIncidents,
  useDeviceClearedIncidents,
} from "@/api/hooks.ts";
import type { Incident } from "@/types/api.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { timeAgo } from "@/lib/utils.ts";

function SeverityBadge({ severity }: { severity: string }) {
  const variants: Record<string, string> = {
    info: "bg-blue-500/15 text-blue-400 border-blue-500/20",
    warning: "bg-amber-500/15 text-amber-400 border-amber-500/20",
    critical: "bg-red-500/15 text-red-400 border-red-500/20",
    emergency: "bg-purple-500/15 text-purple-400 border-purple-500/20",
    recovery: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  };
  return (
    <span
      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium ${variants[severity] ?? variants.warning}`}
    >
      {severity}
    </span>
  );
}

export function IncidentsTab({ deviceId }: { deviceId: string }) {
  const [subTab, setSubTab] = useState<"active" | "cleared">("active");
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1">
        {(["active", "cleared"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setSubTab(t)}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${subTab === t ? "bg-zinc-700 text-white" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"}`}
          >
            {t === "active" ? "Active" : "Cleared"}
          </button>
        ))}
      </div>
      {subTab === "active" ? (
        <DeviceActiveIncidents deviceId={deviceId} />
      ) : (
        <DeviceClearedIncidents deviceId={deviceId} />
      )}
    </div>
  );
}

function DeviceActiveIncidents({ deviceId }: { deviceId: string }) {
  const { pageSize, scrollMode } = useTablePreferences();
  const listState = useListState({
    columns: [
      { key: "severity", label: "Severity", filterable: false },
      { key: "rule_name", label: "Rule", sortable: false },
      { key: "message", label: "Message", sortable: false, filterable: false },
      { key: "opened_at", label: "Opened", filterable: false },
    ],
    defaultSortBy: "opened_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: response,
    isLoading,
    isFetching,
  } = useDeviceActiveIncidents(deviceId, listState.params);
  const incidents = response?.data ?? [];
  const meta = {
    limit: response?.meta?.limit ?? 50,
    offset: response?.meta?.offset ?? 0,
    count: response?.meta?.count ?? 0,
    total: response?.meta?.total ?? 0,
  };
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const clearMut = useClearIncidents();

  const toggle = (id: string) =>
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const toggleAll = () =>
    selected.size === incidents.length
      ? setSelected(new Set())
      : setSelected(new Set(incidents.map((i: Incident) => i.id)));

  if (isLoading)
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
          </div>
        </CardContent>
      </Card>
    );
  if (incidents.length === 0)
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center justify-center text-zinc-500">
            <Zap className="h-10 w-10 mb-3 text-zinc-600" />
            <p className="text-sm">No active incidents for this device</p>
          </div>
        </CardContent>
      </Card>
    );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-4 w-4" /> Active Incidents ({meta.total})
          </CardTitle>
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={clearMut.isPending}
                onClick={async () => {
                  await clearMut.mutateAsync([...selected]);
                  setSelected(new Set());
                }}
              >
                <CheckCheck className="h-3.5 w-3.5" /> Clear ({selected.size})
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
                  checked={
                    selected.size === incidents.length && incidents.length > 0
                  }
                  onChange={toggleAll}
                  className="accent-brand-500 cursor-pointer"
                />
              </TableHead>
              <FilterableSortHead
                col="severity"
                label="Severity"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="rule_name"
                label="Rule"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.rule_name}
                onFilterChange={(v) => listState.setFilter("rule_name", v)}
                sortable={false}
              />
              <TableHead>Message</TableHead>
              <TableHead>Fires</TableHead>
              <FilterableSortHead
                col="opened_at"
                label="Opened"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
            </TableRow>
          </TableHeader>
          <TableBody>
            {incidents.map((inc: Incident) => (
              <TableRow key={inc.id}>
                <TableCell>
                  <input
                    type="checkbox"
                    checked={selected.has(inc.id)}
                    onChange={() => toggle(inc.id)}
                    className="accent-brand-500 cursor-pointer"
                  />
                </TableCell>
                <TableCell>
                  <SeverityBadge severity={inc.severity} />
                </TableCell>
                <TableCell className="text-xs">{inc.rule_name}</TableCell>
                <TableCell
                  className="text-xs text-zinc-300 max-w-[300px] truncate"
                  title={inc.message}
                >
                  {inc.message}
                </TableCell>
                <TableCell className="text-xs text-zinc-400">
                  {inc.fire_count}
                </TableCell>
                <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                  {timeAgo(inc.opened_at)}
                </TableCell>
              </TableRow>
            ))}
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

function DeviceClearedIncidents({ deviceId }: { deviceId: string }) {
  const { pageSize, scrollMode } = useTablePreferences();
  const listState = useListState({
    columns: [
      { key: "severity", label: "Severity", filterable: false },
      { key: "rule_name", label: "Rule", sortable: false },
      { key: "opened_at", label: "Opened", filterable: false },
    ],
    defaultSortBy: "opened_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: response,
    isLoading,
    isFetching,
  } = useDeviceClearedIncidents(deviceId, listState.params);
  const incidents = response?.data ?? [];
  const meta = {
    limit: response?.meta?.limit ?? 50,
    offset: response?.meta?.offset ?? 0,
    count: response?.meta?.count ?? 0,
    total: response?.meta?.total ?? 0,
  };

  if (isLoading)
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
          </div>
        </CardContent>
      </Card>
    );
  if (incidents.length === 0)
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center justify-center text-zinc-500">
            <Zap className="h-10 w-10 mb-3 text-zinc-600" />
            <p className="text-sm">No cleared incidents for this device</p>
          </div>
        </CardContent>
      </Card>
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="h-4 w-4" /> Cleared Incidents ({meta.total})
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
                filterable={false}
              />
              <FilterableSortHead
                col="rule_name"
                label="Rule"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.rule_name}
                onFilterChange={(v) => listState.setFilter("rule_name", v)}
                sortable={false}
              />
              <TableHead>Message</TableHead>
              <FilterableSortHead
                col="opened_at"
                label="Opened"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <TableHead>Cleared</TableHead>
              <TableHead>Reason</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {incidents.map((inc: Incident) => (
              <TableRow key={inc.id}>
                <TableCell>
                  <SeverityBadge severity={inc.severity} />
                </TableCell>
                <TableCell className="text-xs">{inc.rule_name}</TableCell>
                <TableCell
                  className="text-xs text-zinc-300 max-w-[300px] truncate"
                  title={inc.message}
                >
                  {inc.message}
                </TableCell>
                <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                  {timeAgo(inc.opened_at)}
                </TableCell>
                <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                  {inc.cleared_at ? timeAgo(inc.cleared_at) : "\u2014"}
                </TableCell>
                <TableCell className="text-xs text-zinc-400">
                  {inc.cleared_reason || "\u2014"}
                </TableCell>
              </TableRow>
            ))}
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
