import { useState } from "react";
import { FileText, Loader2, Pencil, Plus, Search, Trash2 } from "lucide-react";
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
import type { Template } from "@/types/api.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useListState } from "@/hooks/useListState.ts";
import { SortableHead } from "@/components/SortableHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";

export function TemplatesPage() {
  const tz = useTimezone();
  const listState = useListState();
  const { data: response, isLoading } = useTemplates(listState.params);
  const templates = response?.data ?? [];
  const meta = (response as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };
  const createTemplate = useCreateTemplate();
  const updateTemplate = useUpdateTemplate();
  const deleteTemplate = useDeleteTemplate();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addConfig, setAddConfig] = useState("{}");
  const [addError, setAddError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<Template | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editConfig, setEditConfig] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<Template | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    let config: Record<string, unknown>;
    try { config = JSON.parse(addConfig); } catch { setAddError("Invalid JSON config."); return; }
    try {
      await createTemplate.mutateAsync({ name: addName.trim(), description: addDesc.trim() || undefined, config });
      setAddName(""); setAddDesc(""); setAddConfig("{}"); setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create template");
    }
  }

  function openEdit(t: Template) {
    setEditTarget(t);
    setEditName(t.name);
    setEditDesc(t.description ?? "");
    setEditConfig(JSON.stringify(t.config, null, 2));
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    let config: Record<string, unknown>;
    try { config = JSON.parse(editConfig); } catch { setEditError("Invalid JSON config."); return; }
    try {
      await updateTemplate.mutateAsync({
        id: editTarget.id,
        data: { name: editName.trim(), description: editDesc.trim(), config },
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
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <ClearableInput
              placeholder="Search templates..."
              className="pl-9 w-64"
              value={listState.search}
              onChange={(e) => listState.setSearch(e.target.value)}
              onClear={() => listState.setSearch("")}
            />
          </div>
          <Button size="sm" onClick={() => { setAddName(""); setAddDesc(""); setAddConfig("{}"); setAddError(null); setAddOpen(true); }} className="gap-1.5">
            <Plus className="h-4 w-4" /> New Template
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          {!templates || templates.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <FileText className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No templates defined</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead col="name" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>Name</SortableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Apps</TableHead>
                  <SortableHead col="created_at" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>Created</SortableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {templates.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium text-zinc-100">{t.name}</TableCell>
                    <TableCell className="text-zinc-400 max-w-[300px] truncate">{t.description ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant="default">{t.config?.apps?.length ?? 0} apps</Badge>
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
          />
        </CardContent>
      </Card>

      {/* Add Dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="New Template">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tpl-name">Name</Label>
            <Input id="tpl-name" placeholder="e.g. Standard Server" value={addName} onChange={e => setAddName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-desc">Description <span className="font-normal text-zinc-500">(optional)</span></Label>
            <Input id="tpl-desc" value={addDesc} onChange={e => setAddDesc(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-config">Config (JSON)</Label>
            <textarea id="tpl-config" value={addConfig} onChange={e => setAddConfig(e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 font-mono h-32 focus:outline-none focus:ring-1 focus:ring-brand-500" />
          </div>
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
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title={`Edit: ${editTarget?.name ?? ""}`}>
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tpl-edit-name">Name</Label>
            <Input id="tpl-edit-name" value={editName} onChange={e => setEditName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-edit-desc">Description</Label>
            <Input id="tpl-edit-desc" value={editDesc} onChange={e => setEditDesc(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-edit-config">Config (JSON)</Label>
            <textarea id="tpl-edit-config" value={editConfig} onChange={e => setEditConfig(e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 font-mono h-32 focus:outline-none focus:ring-1 focus:ring-brand-500" />
          </div>
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
