import { useState } from "react";
import {
  Loader2,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import {
  useDeviceTypes,
  useCreateDeviceType,
  useUpdateDeviceType,
  useDeleteDeviceType,
  useDeviceCategories,
} from "@/api/hooks.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import type { DeviceType } from "@/types/api.ts";

export function DeviceTypesPage() {
  const { pageSize, scrollMode } = useTablePreferences();
  const listState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "vendor", label: "Vendor" },
      { key: "sys_object_id_pattern", label: "OID Pattern" },
    ],
    defaultSortBy: "name",
    defaultSortDir: "asc",
    defaultPageSize: pageSize,
    scrollMode,
  });

  const { data: response, isLoading, isFetching } = useDeviceTypes(listState.params);
  const rules = response?.data ?? [];
  const meta = response?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };

  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<DeviceType | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeviceType | null>(null);

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
        <p className="text-sm text-zinc-500">
          Map SNMP sysObjectID patterns to device categories for automatic device classification.
        </p>
        <Button size="sm" onClick={() => setShowCreate(true)} className="gap-1.5">
          <Plus className="h-4 w-4" />
          Add Device Type
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            Device Types ({meta.total})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <FilterableSortHead col="name" label="Name" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.name} onFilterChange={(v) => listState.setFilter("name", v)} />
                <FilterableSortHead col="sys_object_id_pattern" label="sysObjectID Pattern" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.sys_object_id_pattern} onFilterChange={(v) => listState.setFilter("sys_object_id_pattern", v)} />
                <TableHead>Category</TableHead>
                <FilterableSortHead col="vendor" label="Vendor" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.vendor} onFilterChange={(v) => listState.setFilter("vendor", v)} />
                <TableHead>Model</TableHead>
                <TableHead>OS Family</TableHead>
                <FilterableSortHead col="priority" label="Priority" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-zinc-500 py-8">
                    {listState.hasActiveFilters
                      ? "No device types match your filters"
                      : "No device types defined — add types to enable SNMP device auto-classification"}
                  </TableCell>
                </TableRow>
              ) : (
                rules.map((rule) => (
                  <TableRow key={rule.id}>
                    <TableCell className="font-medium text-zinc-100">
                      {rule.name}
                      {rule.pack_id && (
                        <Badge variant="default" className="ml-2 text-xs text-zinc-500">pack</Badge>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-400">
                      {rule.sys_object_id_pattern}
                    </TableCell>
                    <TableCell>
                      <Badge variant="info" className="text-xs">
                        {rule.device_category_name || "—"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-zinc-300">
                      {rule.vendor || "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {rule.model || "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {rule.os_family || "—"}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm tabular-nums">
                      {rule.priority}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {rule.pack_id ? (
                          <span className="text-xs text-zinc-600 italic">pack-managed</span>
                        ) : (
                          <>
                            <button
                              onClick={() => setEditTarget(rule)}
                              className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => setDeleteTarget(rule)}
                              className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </>
                        )}
                      </div>
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
        <RuleFormDialog onClose={() => setShowCreate(false)} />
      )}

      {editTarget && (
        <RuleFormDialog rule={editTarget} onClose={() => setEditTarget(null)} />
      )}

      <DeleteRuleDialog rule={deleteTarget} onClose={() => setDeleteTarget(null)} />
    </div>
  );
}

/* ── Rule form dialog (create + edit) ────────────────────── */

function RuleFormDialog({
  rule,
  onClose,
}: {
  rule?: DeviceType;
  onClose: () => void;
}) {
  const { data: deviceCategories } = useDeviceCategories();
  const createMut = useCreateDeviceType();
  const updateMut = useUpdateDeviceType();
  const isEdit = !!rule;

  const [name, setName] = useState(rule?.name ?? "");
  const [pattern, setPattern] = useState(rule?.sys_object_id_pattern ?? "");
  const [deviceCategoryId, setDeviceCategoryId] = useState(rule?.device_category_id ?? "");
  const [vendor, setVendor] = useState(rule?.vendor ?? "");
  const [model, setModel] = useState(rule?.model ?? "");
  const [osFamily, setOsFamily] = useState(rule?.os_family ?? "");
  const [description, setDescription] = useState(rule?.description ?? "");
  const [priority, setPriority] = useState(rule?.priority ?? 0);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name || !pattern || !deviceCategoryId) return;

    try {
      if (isEdit && rule) {
        await updateMut.mutateAsync({
          id: rule.id,
          data: { name, sys_object_id_pattern: pattern, device_category_id: deviceCategoryId, vendor: vendor || undefined, model: model || undefined, os_family: osFamily || undefined, description: description || undefined, priority },
        });
      } else {
        await createMut.mutateAsync({
          name,
          sys_object_id_pattern: pattern,
          device_category_id: deviceCategoryId,
          vendor: vendor || undefined,
          model: model || undefined,
          os_family: osFamily || undefined,
          description: description || undefined,
          priority,
        });
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save device type");
    }
  };

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <Dialog open onClose={onClose} title={isEdit ? "Edit Device Type" : "Add Device Type"}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label>Name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Cisco Catalyst 9300" autoFocus />
        </div>

        <div className="space-y-1.5">
          <Label>sysObjectID Pattern</Label>
          <Input
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="e.g. 1.3.6.1.4.1.9.1.2571"
            className="font-mono"
          />
          <p className="text-xs text-zinc-500">
            OID prefix — longest match wins. Use dot-separated decimal notation.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label>Device Category</Label>
          <Select value={deviceCategoryId} onChange={(e) => setDeviceCategoryId(e.target.value)}>
            <option value="">Select device category</option>
            {(deviceCategories ?? []).map((dc) => (
              <option key={dc.id} value={dc.id}>{dc.name}</option>
            ))}
          </Select>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1.5">
            <Label>Vendor</Label>
            <Input value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="e.g. Cisco" />
          </div>
          <div className="space-y-1.5">
            <Label>Model</Label>
            <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="e.g. C9300" />
          </div>
          <div className="space-y-1.5">
            <Label>OS Family</Label>
            <Input value={osFamily} onChange={(e) => setOsFamily(e.target.value)} placeholder="e.g. IOS-XE" />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label>Description</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional" />
          </div>
          <div className="space-y-1.5">
            <Label>Priority</Label>
            <Input type="number" min={0} max={1000} value={priority} onChange={(e) => setPriority(Number(e.target.value))} />
          </div>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={!name || !pattern || !deviceCategoryId || isPending}>
            {isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {isEdit ? "Save" : "Add Device Type"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}

/* ── Delete confirmation ─────────────────────────────────── */

function DeleteRuleDialog({
  rule,
  onClose,
}: {
  rule: DeviceType | null;
  onClose: () => void;
}) {
  const deleteMut = useDeleteDeviceType();

  const handleDelete = async () => {
    if (!rule) return;
    await deleteMut.mutateAsync(rule.id);
    onClose();
  };

  return (
    <Dialog open={!!rule} onClose={onClose} title="Delete Device Type">
      <p className="text-sm text-zinc-400">
        Are you sure you want to delete the device type{" "}
        <span className="font-medium text-zinc-200">{rule?.name}</span>
        {rule?.sys_object_id_pattern && (
          <> (pattern <code className="font-mono text-xs text-zinc-300">{rule.sys_object_id_pattern}</code>)</>
        )}
        ? Devices already classified by this type will keep their category.
      </p>
      <DialogFooter>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="destructive" onClick={() => void handleDelete()} disabled={deleteMut.isPending}>
          {deleteMut.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Delete
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
