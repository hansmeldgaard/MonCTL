import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Loader2,
  Pencil,
  Plus,
  Search,
  Server,
  Trash2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { SearchableSelect } from "@/components/ui/searchable-select.tsx";
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
  useDeviceTypeTemplateBindings,
  useCategoryTemplateBindings,
  useBindDeviceTypeTemplate,
  useUnbindDeviceTypeTemplate,
  useTemplates,
} from "@/api/hooks.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { DeviceCategoriesPage } from "@/pages/DeviceTypesPage.tsx";
import { cn } from "@/lib/utils.ts";
import type { DeviceType, TemplateBinding } from "@/types/api.ts";
import { ArrowDown, ArrowUp, ChevronDown, FileText, X } from "lucide-react";

const TABS = [
  { key: "types", label: "Device Types", icon: Search },
  { key: "categories", label: "Categories", icon: Server },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function DeviceTypesPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("types");

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-zinc-800">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px cursor-pointer",
              activeTab === tab.key
                ? "border-brand-500 text-brand-400"
                : "border-transparent text-zinc-500 hover:text-zinc-300",
            )}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "types" && <DeviceTypesTab />}
      {activeTab === "categories" && <DeviceCategoriesPage />}
    </div>
  );
}

function DeviceTypesTab() {
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
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

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
                <TableHead className="text-center">Devices</TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-zinc-500 py-8">
                    {listState.hasActiveFilters
                      ? "No device types match your filters"
                      : "No device types defined — add types to enable SNMP device auto-classification"}
                  </TableCell>
                </TableRow>
              ) : (
                rules.map((rule) => (
                  <>
                    <TableRow
                      key={rule.id}
                      className="cursor-pointer hover:bg-zinc-800/50"
                      onClick={() => setExpandedRow(expandedRow === rule.id ? null : rule.id)}
                    >
                      <TableCell className="font-medium text-zinc-100">
                        <span className="flex items-center gap-1.5">
                          <ChevronDown className={cn("h-3.5 w-3.5 text-zinc-600 transition-transform", expandedRow === rule.id ? "" : "-rotate-90")} />
                          {rule.name}
                          {rule.pack_id && (
                            <Badge variant="default" className="text-xs text-zinc-500">pack</Badge>
                          )}
                        </span>
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
                      <TableCell className="text-center">
                        {(rule as any).device_count > 0 ? (
                          <Link
                            to={`/devices?device_type_name=${encodeURIComponent(rule.name)}`}
                            className="text-sm font-medium text-brand-400 hover:text-brand-300 transition-colors"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {(rule as any).device_count}
                          </Link>
                        ) : (
                          <span className="text-sm text-zinc-600">0</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
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
                    {expandedRow === rule.id && (
                      <TableRow key={`${rule.id}-templates`}>
                        <TableCell colSpan={8} className="bg-zinc-900/50 px-6 py-3">
                          <DeviceTypeTemplateBindingsPanel
                            deviceTypeId={rule.id}
                            deviceCategoryId={rule.device_category_id}
                          />
                        </TableCell>
                      </TableRow>
                    )}
                  </>
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

export interface RuleFormPrefill {
  sys_object_id_pattern?: string;
  vendor?: string;
  model?: string;
  os_family?: string;
  name?: string;
}

export function RuleFormDialog({
  rule,
  prefill,
  onClose,
  onSuccess,
}: {
  rule?: DeviceType;
  prefill?: RuleFormPrefill;
  onClose: () => void;
  onSuccess?: () => void;
}) {
  const { data: deviceCategories } = useDeviceCategories();
  const createMut = useCreateDeviceType();
  const updateMut = useUpdateDeviceType();
  const isEdit = !!rule;

  const [name, setName] = useState(rule?.name ?? prefill?.name ?? "");
  const [pattern, setPattern] = useState(rule?.sys_object_id_pattern ?? prefill?.sys_object_id_pattern ?? "");
  const [deviceCategoryId, setDeviceCategoryId] = useState(rule?.device_category_id ?? "");
  const [vendor, setVendor] = useState(rule?.vendor ?? prefill?.vendor ?? "");
  const [model, setModel] = useState(rule?.model ?? prefill?.model ?? "");
  const [osFamily, setOsFamily] = useState(rule?.os_family ?? prefill?.os_family ?? "");
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
      onSuccess?.();
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


/* ── Template bindings panel (shown inside expanded row) ── */

function DeviceTypeTemplateBindingsPanel({
  deviceTypeId,
  deviceCategoryId,
}: {
  deviceTypeId: string;
  deviceCategoryId: string;
}) {
  const { data: typeBindingsData, refetch: refetchType } = useDeviceTypeTemplateBindings(deviceTypeId);
  const { data: catBindingsData } = useCategoryTemplateBindings(deviceCategoryId);
  const bindTemplate = useBindDeviceTypeTemplate();
  const unbindTemplate = useUnbindDeviceTypeTemplate();
  const { data: templatesData } = useTemplates({ limit: 200 });

  const typeBindings: TemplateBinding[] = typeBindingsData?.data ?? [];
  const catBindings: TemplateBinding[] = catBindingsData?.data ?? [];
  const allTemplates = templatesData?.data ?? [];

  const [addTemplateId, setAddTemplateId] = useState("");

  const boundTypeIds = new Set(typeBindings.map((b) => b.template_id));

  async function handleSwap(idx: number, dir: -1 | 1) {
    const target = idx + dir;
    if (target < 0 || target >= typeBindings.length) return;
    const a = typeBindings[idx];
    const b = typeBindings[target];
    await Promise.all([
      bindTemplate.mutateAsync({ device_type_id: deviceTypeId, template_id: a.template_id, step: b.step }),
      bindTemplate.mutateAsync({ device_type_id: deviceTypeId, template_id: b.template_id, step: a.step }),
    ]);
    refetchType();
  }

  async function handleAdd() {
    if (!addTemplateId) return;
    const nextStep = typeBindings.length > 0 ? Math.max(...typeBindings.map((b) => b.step)) + 1 : 100;
    await bindTemplate.mutateAsync({
      device_type_id: deviceTypeId,
      template_id: addTemplateId,
      step: nextStep,
    });
    setAddTemplateId("");
    refetchType();
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs font-medium text-zinc-400">
        <FileText className="h-3.5 w-3.5" />
        Linked Templates
      </div>

      <p className="text-xs text-zinc-500">
        Device type templates (step 100 → 199) are applied after category templates (step 1 → 99). Same app names at type level override category level.
      </p>

      {/* Inherited from category */}
      {catBindings.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-zinc-500">Inherited from category</p>
          <div className="space-y-1">
            {catBindings.map((b) => (
              <div key={b.id} className="flex items-center gap-2 rounded border border-zinc-800/50 bg-zinc-800/20 px-2.5 py-1.5 text-sm">
                <span className="w-8 text-center text-xs text-zinc-600 tabular-nums font-mono">{b.step}</span>
                <span className="flex-1 truncate text-zinc-400">{b.template_name}</span>
                <Badge variant="default" className="text-[10px]">category</Badge>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Type-level bindings */}
      <div className="space-y-1">
        {catBindings.length > 0 && typeBindings.length > 0 && (
          <p className="text-xs text-zinc-500">Device type overrides</p>
        )}
        {typeBindings.map((b, idx) => (
          <div key={b.id} className="flex items-center gap-2 rounded border border-zinc-800 bg-zinc-800/40 px-2.5 py-1.5 text-sm">
            <span className="w-8 text-center text-xs text-zinc-500 tabular-nums font-mono">{b.step}</span>
            <span className="flex-1 truncate text-zinc-200">{b.template_name}</span>
            <Badge variant="info" className="text-[10px]">type</Badge>
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                disabled={idx === 0}
                onClick={() => handleSwap(idx, -1)}
                className="rounded p-1 text-zinc-600 hover:text-zinc-300 disabled:opacity-20 disabled:cursor-default cursor-pointer"
              >
                <ArrowUp className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                disabled={idx === typeBindings.length - 1}
                onClick={() => handleSwap(idx, 1)}
                className="rounded p-1 text-zinc-600 hover:text-zinc-300 disabled:opacity-20 disabled:cursor-default cursor-pointer"
              >
                <ArrowDown className="h-3.5 w-3.5" />
              </button>
            </div>
            <button
              type="button"
              onClick={async () => {
                await unbindTemplate.mutateAsync(b.id);
                refetchType();
              }}
              className="rounded p-0.5 text-zinc-600 hover:text-red-400 cursor-pointer"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        {typeBindings.length === 0 && catBindings.length === 0 && (
          <p className="text-xs text-zinc-500 italic">No templates linked.</p>
        )}
      </div>

      {/* Add binding */}
      <div className="flex items-end gap-2">
        <div className="flex-1 space-y-1">
          <Label className="text-xs text-zinc-500">Add template</Label>
          <SearchableSelect
            value={addTemplateId}
            onChange={setAddTemplateId}
            options={allTemplates
              .filter((t) => !boundTypeIds.has(t.id))
              .map((t) => ({ value: t.id, label: t.name }))}
            placeholder="Select template…"
          />
        </div>
        <Button
          type="button"
          size="sm"
          disabled={!addTemplateId || bindTemplate.isPending}
          onClick={handleAdd}
        >
          {bindTemplate.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
        </Button>
      </div>
    </div>
  );
}
