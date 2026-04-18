import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, Plug, Plus, Trash2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  useConnectors,
  useCreateConnector,
  useDeleteConnector,
} from "@/api/hooks.ts";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import { formatTime } from "@/lib/utils.ts";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";
import type { ConnectorSummary } from "@/types/api.ts";

export function ConnectorsPage() {
  const { canCreate, canDelete } = usePermissions();
  const { pageSize, scrollMode } = useTablePreferences();
  const tz = useTimezone();
  const { mode } = useTimeDisplayMode();
  const { compact } = useDisplayPreferences();

  const listState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "connector_type", label: "Type" },
      { key: "description", label: "Description", sortable: false },
      { key: "created_at", label: "Created", filterable: false },
      { key: "updated_at", label: "Updated", filterable: false },
    ],
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: response,
    isLoading,
    isFetching,
  } = useConnectors(listState.params);
  const connectors = response?.data ?? [];
  const meta = (response as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };
  const createConnector = useCreateConnector();
  const deleteConnector = useDeleteConnector();
  const navigate = useNavigate();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addType, setAddType] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<ConnectorSummary | null>(
    null,
  );
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) {
      setAddError("Name is required.");
      return;
    }
    if (!addType.trim()) {
      setAddError("Type is required.");
      return;
    }
    try {
      const result = await createConnector.mutateAsync({
        name: addName.trim(),
        description: addDesc.trim() || undefined,
        connector_type: addType.trim(),
      });
      setAddName("");
      setAddDesc("");
      setAddType("");
      setAddOpen(false);
      if (result.data?.id) navigate(`/connectors/${result.data.id}`);
    } catch (err) {
      setAddError(
        err instanceof Error ? err.message : "Failed to create connector",
      );
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteConnector.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete connector",
      );
    }
  }

  const columns = useMemo<FlexColumnDef<ConnectorSummary>[]>(() => {
    const cols: FlexColumnDef<ConnectorSummary>[] = [
      {
        key: "name",
        label: "Name",
        defaultWidth: 220,
        cell: (c) => (
          <Link
            to={`/connectors/${c.id}`}
            className="font-medium text-brand-400 hover:text-brand-300 transition-colors"
          >
            {c.name}
          </Link>
        ),
      },
      {
        key: "connector_type",
        label: "Type",
        defaultWidth: 120,
        cell: (c) => <Badge variant="info">{c.connector_type}</Badge>,
      },
      {
        key: "description",
        label: "Description",
        sortable: false,
        defaultWidth: 300,
        cellClassName: "text-zinc-400 text-sm max-w-[400px] truncate",
        cell: (c) =>
          c.description ?? <span className="text-zinc-600 italic">—</span>,
      },
      {
        key: "__version_count",
        label: "Versions",
        pickerLabel: "Versions",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cellClassName: "text-zinc-400 text-sm",
        cell: (c) => c.version_count,
      },
      {
        key: "__latest_version",
        label: "Latest Version",
        pickerLabel: "Latest Version",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cell: (c) =>
          c.latest_version ? (
            <Badge variant="default" className="font-mono text-xs">
              {c.latest_version}
            </Badge>
          ) : (
            <span className="text-zinc-600 italic text-sm">—</span>
          ),
      },
      {
        key: "__builtin",
        label: "Built-in",
        pickerLabel: "Built-in",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cell: (c) =>
          c.is_builtin ? <Badge variant="success">built-in</Badge> : null,
      },
      {
        key: "created_at",
        label: "Created",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (c) => (c.created_at ? formatTime(c.created_at, mode, tz) : "—"),
      },
      {
        key: "updated_at",
        label: "Updated",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (c) => (c.updated_at ? formatTime(c.updated_at, mode, tz) : "—"),
      },
    ];
    if (canDelete("connector")) {
      cols.push({
        key: "__actions",
        label: "",
        pickerLabel: "Actions",
        sortable: false,
        filterable: false,
        defaultWidth: 60,
        cell: (c) => (
          <button
            onClick={() => setDeleteTarget(c)}
            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        ),
      });
    }
    return cols;
  }, [canDelete, mode, tz]);

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<ConnectorSummary>("connectors", columns);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Connectors</h1>
          <p className="text-sm text-zinc-500">
            Manage connectors and their versions.
          </p>
        </div>
        {canCreate("connector") && (
          <Button
            size="sm"
            onClick={() => {
              setAddName("");
              setAddDesc("");
              setAddType("");
              setAddError(null);
              setAddOpen(true);
            }}
            className="gap-1.5"
          >
            <Plus className="h-4 w-4" />
            New Connector
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plug className="h-4 w-4" />
            Connectors
            <Badge variant="default" className="ml-2">
              {meta.total}
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
          {connectors.length === 0 && !listState.hasActiveFilters ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Plug className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No connectors registered</p>
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
                <FlexTable<ConnectorSummary>
                  orderedVisibleColumns={orderedVisibleColumns}
                  configMap={configMap}
                  onOrderChange={setOrder}
                  onWidthChange={setWidth}
                  rows={connectors}
                  rowKey={(c) => c.id}
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filters={listState.filters}
                  onFilterChange={(col, v) => listState.setFilter(col, v)}
                  emptyState="No connectors match your filters"
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

      <Dialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="New Connector"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="conn-name">Name</Label>
            <Input
              id="conn-name"
              placeholder="e.g. snmp_connector"
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="conn-type">Connector Type</Label>
            <Input
              id="conn-type"
              placeholder="e.g. snmp, http, sql"
              value={addType}
              onChange={(e) => setAddType(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="conn-desc">
              Description{" "}
              <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="conn-desc"
              value={addDesc}
              onChange={(e) => setAddDesc(e.target.value)}
            />
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createConnector.isPending}>
              {createConnector.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      <Dialog
        open={!!deleteTarget}
        onClose={() => {
          setDeleteTarget(null);
          setDeleteError(null);
        }}
        title="Delete Connector"
      >
        <p className="text-sm text-zinc-400">
          Delete connector{" "}
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.name}
          </span>{" "}
          and all its versions?
        </p>
        {deleteError && (
          <p className="text-sm text-red-400 mt-2">{deleteError}</p>
        )}
        <DialogFooter>
          <Button
            variant="secondary"
            onClick={() => {
              setDeleteTarget(null);
              setDeleteError(null);
            }}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteConnector.isPending}
          >
            {deleteConnector.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
