import { useState } from "react";
import {
  Check,
  CheckCheck,
  Clock,
  Loader2,
  Play,
  Plus,
  Settings2,
  Trash2,
  Zap,
} from "lucide-react";
import { useNavigate, Link } from "react-router-dom";
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
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  useActiveEvents,
  useAcknowledgeEvents,
  useAlertRules,
  useClearEvents,
  useClearedEvents,
  useCreateEventPolicy,
  useDeleteEventPolicy,
  useEventPolicies,
} from "@/api/hooks.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { MonitoringEvent, EventPolicy } from "@/types/api.ts";

type Tab = "active" | "cleared" | "policies";

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
        <Button
          variant={tab === "policies" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("policies")}
        >
          <Settings2 className="h-3.5 w-3.5" />
          Policies
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
      ) : tab === "cleared" ? (
        <ClearedEventsTab
          events={clearedEvents}
          listState={clearedListState}
          meta={clearedMeta}
          isFetching={clearedFetching}
        />
      ) : (
        <PoliciesTab />
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

function PoliciesTab() {
  const { canManage } = usePermissions();
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<EventPolicy | null>(null);
  const deleteMut = useDeleteEventPolicy();
  const { pageSize, scrollMode } = useTablePreferences();

  const listState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "definition_name", label: "Alert Definition" },
      { key: "event_severity", label: "Severity" },
    ],
    defaultSortBy: "name",
    defaultSortDir: "asc",
    defaultPageSize: pageSize,
    scrollMode,
  });

  const {
    data: response,
    isLoading,
    isFetching,
  } = useEventPolicies(listState.params);
  const policies = response?.data ?? [];
  const meta = response?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    await deleteMut.mutateAsync(deleteTarget.id);
    setDeleteTarget(null);
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Settings2 className="h-4 w-4" />
              Event Policies ({meta.total})
            </CardTitle>
            {canManage("event") && (
              <Button size="sm" onClick={() => setShowCreate(true)}>
                <Plus className="h-3.5 w-3.5" />
                Create Policy
              </Button>
            )}
          </div>
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
                  col="definition_name"
                  label="Alert Definition"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterValue={listState.filters.definition_name}
                  onFilterChange={(v) =>
                    listState.setFilter("definition_name", v)
                  }
                />
                <FilterableSortHead
                  col="mode"
                  label="Mode"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterable={false}
                />
                <TableHead>Threshold</TableHead>
                <FilterableSortHead
                  col="event_severity"
                  label="Severity"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterValue={listState.filters.event_severity}
                  onFilterChange={(v) =>
                    listState.setFilter("event_severity", v)
                  }
                />
                <TableHead>Auto-clear</TableHead>
                <FilterableSortHead
                  col="enabled"
                  label="Enabled"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterable={false}
                />
                <TableHead className="w-12"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {policies.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={8}
                    className="text-center text-zinc-500 py-8"
                  >
                    {listState.hasActiveFilters
                      ? "No policies match your filters"
                      : "No event policies configured — create a policy to promote alerts to events"}
                  </TableCell>
                </TableRow>
              ) : (
                policies.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium text-zinc-100">
                      {p.name}
                    </TableCell>
                    <TableCell className="text-zinc-400">
                      {p.definition_name || p.definition_id}
                    </TableCell>
                    <TableCell>
                      <Badge variant="default">{p.mode}</Badge>
                    </TableCell>
                    <TableCell className="text-zinc-300">
                      {p.mode === "consecutive"
                        ? `${p.fire_count_threshold} consecutive`
                        : `${p.fire_count_threshold} of ${p.window_size}`}
                    </TableCell>
                    <TableCell>
                      <Badge variant={severityVariant(p.event_severity)}>
                        {p.event_severity}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          p.auto_clear_on_resolve ? "success" : "default"
                        }
                      >
                        {p.auto_clear_on_resolve ? "Yes" : "No"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={p.enabled ? "success" : "default"}>
                        {p.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {canManage("event") && (
                        <button
                          className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                          onClick={() => setDeleteTarget(p)}
                          title="Delete"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
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

      {showCreate && (
        <CreatePolicyDialog onClose={() => setShowCreate(false)} />
      )}

      {/* Delete Confirmation */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Event Policy"
      >
        <p className="text-sm text-zinc-400">
          Are you sure you want to delete the policy{" "}
          <span className="font-medium text-zinc-200">
            {deleteTarget?.name}
          </span>
          ? Active events created by this policy will remain but no new events
          will be promoted.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => void handleDelete()}
            disabled={deleteMut.isPending}
          >
            {deleteMut.isPending && (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

function CreatePolicyDialog({ onClose }: { onClose: () => void }) {
  const { data: definitionsResp } = useAlertRules();
  const definitions = definitionsResp?.data ?? [];
  const createMut = useCreateEventPolicy();

  const [name, setName] = useState("");
  const [definitionId, setDefinitionId] = useState("");
  const [mode, setMode] = useState("consecutive");
  const [threshold, setThreshold] = useState(3);
  const [windowSize, setWindowSize] = useState(5);
  const [severity, setSeverity] = useState("warning");
  const [messageTemplate, setMessageTemplate] = useState("");
  const [autoClear, setAutoClear] = useState(true);

  const handleSubmit = async () => {
    if (!name || !definitionId) return;
    await createMut.mutateAsync({
      name,
      definition_id: definitionId,
      mode,
      fire_count_threshold: threshold,
      window_size: windowSize,
      event_severity: severity,
      message_template: messageTemplate || undefined,
      auto_clear_on_resolve: autoClear,
    });
    onClose();
  };

  return (
    <Dialog open onClose={onClose} title="Create Event Policy">
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label>Name</Label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Interface Util Sustained"
          />
        </div>

        <div className="space-y-1.5">
          <Label>Alert Definition</Label>
          <Select
            value={definitionId}
            onChange={(e) => setDefinitionId(e.target.value)}
          >
            <option value="">Select alert definition</option>
            {(definitions ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Mode</Label>
            <Select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="consecutive">Consecutive</option>
              <option value="cumulative">Cumulative</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Severity</Label>
            <Select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
            >
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Fire Count Threshold</Label>
            <Input
              type="number"
              min={1}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
            />
          </div>
          {mode === "cumulative" && (
            <div className="space-y-1.5">
              <Label>Window Size</Label>
              <Input
                type="number"
                min={1}
                value={windowSize}
                onChange={(e) => setWindowSize(Number(e.target.value))}
              />
            </div>
          )}
        </div>

        <div className="space-y-1.5">
          <Label>Message Template (optional)</Label>
          <Input
            value={messageTemplate}
            onChange={(e) => setMessageTemplate(e.target.value)}
            placeholder="{rule_name}: {value} on {device_name} [{fire_count}x]"
          />
        </div>

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="auto-clear"
            checked={autoClear}
            onChange={(e) => setAutoClear(e.target.checked)}
            className="rounded border-zinc-700"
          />
          <Label htmlFor="auto-clear">Auto-clear on resolve</Label>
        </div>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          onClick={() => void handleSubmit()}
          disabled={!name || !definitionId || createMut.isPending}
        >
          {createMut.isPending && (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          )}
          Create
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
