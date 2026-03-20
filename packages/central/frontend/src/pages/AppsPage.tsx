import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AppWindow, Loader2, Plug, Plus, Search, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { useApps, useCreateApp, useDeleteApp } from "@/api/hooks.ts";
import { useListState } from "@/hooks/useListState.ts";
import { SortableHead } from "@/components/SortableHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { AppSummary } from "@/types/api.ts";

export function AppsPage() {
  const listState = useListState();
  const { data: response, isLoading } = useApps(listState.params);
  const apps = response?.data ?? [];
  const meta = (response as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };
  const createApp = useCreateApp();
  const deleteApp = useDeleteApp();
  const navigate = useNavigate();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addType, setAddType] = useState("script");
  const [addTargetTable, setAddTargetTable] = useState("availability_latency");
  const [addConfigSchema, setAddConfigSchema] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<AppSummary | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    let parsedSchema: Record<string, unknown> | undefined;
    if (addConfigSchema.trim()) {
      try {
        parsedSchema = JSON.parse(addConfigSchema.trim());
      } catch {
        setAddError("Config Schema is not valid JSON."); return;
      }
    }
    try {
      const result = await createApp.mutateAsync({
        name: addName.trim(),
        description: addDesc.trim() || undefined,
        app_type: addType,
        target_table: addTargetTable,
        config_schema: parsedSchema,
      });
      setAddName(""); setAddDesc(""); setAddType("script"); setAddTargetTable("availability_latency"); setAddConfigSchema(""); setAddOpen(false);
      if (result.data?.id) navigate(`/apps/${result.data.id}`);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create app");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteApp.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete app");
    }
  }

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
          <h1 className="text-lg font-semibold text-zinc-100">Apps</h1>
          <p className="text-sm text-zinc-500">
            Manage monitoring apps and their versions.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <ClearableInput
              placeholder="Search apps..."
              className="pl-9 w-64"
              value={listState.search}
              onChange={(e) => listState.setSearch(e.target.value)}
              onClear={() => listState.setSearch("")}
            />
          </div>
          <Button size="sm" onClick={() => { setAddName(""); setAddDesc(""); setAddType("script"); setAddTargetTable("availability_latency"); setAddConfigSchema(""); setAddError(null); setAddOpen(true); }} className="gap-1.5">
            <Plus className="h-4 w-4" />
            New App
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AppWindow className="h-4 w-4" />
            Apps
            <Badge variant="default" className="ml-auto">{meta.total}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {apps.length === 0 && !listState.search ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <AppWindow className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No apps registered</p>
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <SortableHead col="name" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>Name</SortableHead>
                    <SortableHead col="app_type" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>Type</SortableHead>
                    <SortableHead col="target_table" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>Target Table</SortableHead>
                    <TableHead>Connectors</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="w-12"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {apps.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center text-zinc-500 py-8">
                        No apps match your search
                      </TableCell>
                    </TableRow>
                  ) : (
                    apps.map((app) => (
                      <TableRow key={app.id}>
                        <TableCell>
                          <Link
                            to={`/apps/${app.id}`}
                            className="font-medium text-brand-400 hover:text-brand-300 transition-colors"
                          >
                            {app.name}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Badge variant="info">
                            {app.app_type}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="default" className="font-mono text-xs">
                            {app.target_table}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {app.connector_bindings && app.connector_bindings.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {app.connector_bindings.map((cb) => (
                                <Badge key={cb.alias} variant="info" className="text-xs gap-1">
                                  <Plug className="h-2.5 w-2.5" />
                                  {cb.connector_name || cb.alias}
                                </Badge>
                              ))}
                            </div>
                          ) : (
                            <span className="text-zinc-600 text-xs">{"\u2014"}</span>
                          )}
                        </TableCell>
                        <TableCell className="text-zinc-400 text-sm max-w-[400px] truncate">
                          {app.description ?? <span className="text-zinc-600 italic">—</span>}
                        </TableCell>
                        <TableCell>
                          <button
                            onClick={() => setDeleteTarget(app)}
                            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
              <PaginationBar page={listState.page} pageSize={listState.pageSize} total={meta.total} count={meta.count} onPageChange={listState.setPage} />
            </>
          )}
        </CardContent>
      </Card>

      {/* Add App Dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="New App">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="app-name">Name</Label>
            <Input id="app-name" placeholder="e.g. http_check" value={addName} onChange={(e) => setAddName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-type">Type</Label>
            <Select id="app-type" value={addType} onChange={(e) => setAddType(e.target.value)}>
              <option value="script">script</option>
              <option value="sdk">sdk</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-target">Target Table</Label>
            <Select id="app-target" value={addTargetTable} onChange={(e) => setAddTargetTable(e.target.value)}>
              <option value="availability_latency">availability_latency</option>
              <option value="performance">performance</option>
              <option value="interface">interface</option>
              <option value="config">config</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-desc">Description <span className="font-normal text-zinc-500">(optional)</span></Label>
            <Input id="app-desc" value={addDesc} onChange={(e) => setAddDesc(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-schema">Config Schema <span className="font-normal text-zinc-500">(JSON, optional)</span></Label>
            <textarea
              id="app-schema"
              value={addConfigSchema}
              onChange={(e) => setAddConfigSchema(e.target.value)}
              placeholder='{"type": "object", "properties": { ... }}'
              rows={5}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 placeholder:text-zinc-600"
            />
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createApp.isPending}>
              {createApp.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete App Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => { setDeleteTarget(null); setDeleteError(null); }} title="Delete App">
        <p className="text-sm text-zinc-400">
          Delete app <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span> and all its versions?
        </p>
        {deleteError && <p className="text-sm text-red-400 mt-2">{deleteError}</p>}
        <DialogFooter>
          <Button variant="secondary" onClick={() => { setDeleteTarget(null); setDeleteError(null); }}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteApp.isPending}>
            {deleteApp.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
