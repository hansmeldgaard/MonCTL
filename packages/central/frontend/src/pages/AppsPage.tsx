import { useState } from "react";
import { Link } from "react-router-dom";
import { AppWindow, Loader2, Plus, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
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
import type { AppSummary } from "@/types/api.ts";

export function AppsPage() {
  const { data: apps, isLoading } = useApps();
  const createApp = useCreateApp();
  const deleteApp = useDeleteApp();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addType, setAddType] = useState("script");
  const [addError, setAddError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<AppSummary | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    try {
      await createApp.mutateAsync({
        name: addName.trim(),
        description: addDesc.trim() || undefined,
        app_type: addType,
      });
      setAddName(""); setAddDesc(""); setAddType("script"); setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create app");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try { await deleteApp.mutateAsync(deleteTarget.id); setDeleteTarget(null); } catch { /* silent */ }
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
        <Button size="sm" onClick={() => { setAddName(""); setAddDesc(""); setAddType("script"); setAddError(null); setAddOpen(true); }} className="gap-1.5">
          <Plus className="h-4 w-4" />
          New App
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AppWindow className="h-4 w-4" />
            Apps
            <Badge variant="default" className="ml-auto">{apps?.length ?? 0}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!apps || apps.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <AppWindow className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No apps registered</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="w-12"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {apps.map((app) => (
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
                      <Badge variant={app.app_type === "builtin" ? "default" : "info"}>
                        {app.app_type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm max-w-[400px] truncate">
                      {app.description ?? <span className="text-zinc-600 italic">—</span>}
                    </TableCell>
                    <TableCell>
                      {app.app_type !== "builtin" && (
                        <button
                          onClick={() => setDeleteTarget(app)}
                          className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
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
            <Label htmlFor="app-desc">Description <span className="font-normal text-zinc-500">(optional)</span></Label>
            <Input id="app-desc" value={addDesc} onChange={(e) => setAddDesc(e.target.value)} />
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
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete App">
        <p className="text-sm text-zinc-400">
          Delete app <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?
          All versions and assignments will be removed.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteApp.isPending}>
            {deleteApp.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
