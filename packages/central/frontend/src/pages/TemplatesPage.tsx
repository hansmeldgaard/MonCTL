import { useState } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName } from "@/lib/validation.ts";
import { FileText, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  useTemplates,
  useCreateTemplate,
  useUpdateTemplate,
  useDeleteTemplate,
} from "@/api/hooks.ts";
import type { Template, TemplateConfig } from "@/types/api.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import { TemplateConfigEditor } from "@/components/TemplateConfigEditor.tsx";

export function TemplatesPage() {
  const tz = useTimezone();
  const { pageSize, scrollMode } = useTablePreferences();
  const listState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "description", label: "Description", sortable: false },
    ],
    defaultPageSize: pageSize,
    scrollMode,
  });
  const { data: response, isLoading, isFetching } = useTemplates(listState.params);
  const templates = response?.data ?? [];
  const meta = (response as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };
  const createTemplate = useCreateTemplate();
  const updateTemplate = useUpdateTemplate();
  const deleteTemplate = useDeleteTemplate();

  const [addOpen, setAddOpen] = useState(false);
  const addNameField = useField("", validateName);
  const [addDesc, setAddDesc] = useState("");
  const [addConfigObj, setAddConfigObj] = useState<TemplateConfig>({});
  const [addError, setAddError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<Template | null>(null);
  const editNameField = useField("", validateName);
  const [editDesc, setEditDesc] = useState("");
  const [editConfigObj, setEditConfigObj] = useState<TemplateConfig>({});
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<Template | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!validateAll(addNameField)) return;
    try {
      await createTemplate.mutateAsync({
        name: addNameField.value.trim(),
        description: addDesc.trim() || undefined,
        config: addConfigObj as Record<string, unknown>,
      });
      addNameField.reset(); setAddDesc(""); setAddConfigObj({}); setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create template");
    }
  }

  function openEdit(t: Template) {
    setEditTarget(t);
    editNameField.reset(t.name);
    setEditDesc(t.description ?? "");
    setEditConfigObj(t.config || {});
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    if (!validateAll(editNameField)) return;
    try {
      await updateTemplate.mutateAsync({
        id: editTarget.id,
        data: { name: editNameField.value.trim(), description: editDesc.trim(), config: editConfigObj as Record<string, unknown> },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update template");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try { await deleteTemplate.mutateAsync(deleteTarget.id); setDeleteTarget(null); } catch { /* silent */ }
  }

  function countItems(config: TemplateConfig): number {
    let count = 0;
    if (config.monitoring) {
      if (config.monitoring.availability) count++;
      if (config.monitoring.latency) count++;
      if (config.monitoring.interface) count++;
    }
    count += config.apps?.length ?? 0;
    return count;
  }

  if (isLoading) {
    return <div className="flex h-64 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Templates</h1>
          <p className="text-sm text-zinc-500">Reusable monitoring configurations for bulk device setup.</p>
        </div>
        <Button size="sm" onClick={() => { addNameField.reset(); setAddDesc(""); setAddConfigObj({}); setAddError(null); setAddOpen(true); }} className="gap-1.5">
          <Plus className="h-4 w-4" /> New Template
        </Button>
      </div>

      <Card>
        <CardContent className="pt-6">
          {templates.length === 0 && !listState.hasActiveFilters ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <FileText className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No templates defined</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <FilterableSortHead col="name" label="Name" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.name} onFilterChange={(v) => listState.setFilter("name", v)} />
                  <FilterableSortHead col="description" label="Description" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} sortable={false} filterValue={listState.filters.description} onFilterChange={(v) => listState.setFilter("description", v)} />
                  <TableHead>Items</TableHead>
                  <FilterableSortHead col="created_at" label="Created" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {templates.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-zinc-500 py-8">
                      No templates match your filters
                    </TableCell>
                  </TableRow>
                ) : templates.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium text-zinc-100">{t.name}</TableCell>
                    <TableCell className="text-zinc-400 max-w-[300px] truncate">{t.description ?? "\u2014"}</TableCell>
                    <TableCell>
                      <Badge variant="default">{countItems(t.config || {})} items</Badge>
                    </TableCell>
                    <TableCell className="text-zinc-500">{formatDate(t.created_at, tz)}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <button onClick={() => openEdit(t)} className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer" title="Edit">
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button onClick={() => setDeleteTarget(t)} className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer" title="Delete">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
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

      {/* Add Dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="New Template" size="lg">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tpl-name">Name</Label>
            <Input id="tpl-name" placeholder="e.g. Standard Server" value={addNameField.value} onChange={addNameField.onChange} onBlur={addNameField.onBlur} autoFocus />
            {addNameField.error && <p className="text-xs text-red-400 mt-0.5">{addNameField.error}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-desc">Description <span className="font-normal text-zinc-500">(optional)</span></Label>
            <Input id="tpl-desc" value={addDesc} onChange={e => setAddDesc(e.target.value)} />
          </div>
          <TemplateConfigEditor value={addConfigObj} onChange={setAddConfigObj} />
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createTemplate.isPending}>
              {createTemplate.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title={`Edit: ${editTarget?.name ?? ""}`} size="lg">
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tpl-edit-name">Name</Label>
            <Input id="tpl-edit-name" value={editNameField.value} onChange={editNameField.onChange} onBlur={editNameField.onBlur} autoFocus />
            {editNameField.error && <p className="text-xs text-red-400 mt-0.5">{editNameField.error}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-edit-desc">Description</Label>
            <Input id="tpl-edit-desc" value={editDesc} onChange={e => setEditDesc(e.target.value)} />
          </div>
          <TemplateConfigEditor value={editConfigObj} onChange={setEditConfigObj} />
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditTarget(null)}>Cancel</Button>
            <Button type="submit" disabled={updateTemplate.isPending}>
              {updateTemplate.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete Template">
        <p className="text-sm text-zinc-400">Delete template <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?</p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteTemplate.isPending}>
            {deleteTemplate.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
