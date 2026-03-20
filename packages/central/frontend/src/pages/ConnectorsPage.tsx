import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, Plug, Plus, Search, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
import { Label } from "@/components/ui/label.tsx";
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
import { useConnectors, useCreateConnector, useDeleteConnector } from "@/api/hooks.ts";
import { useListState } from "@/hooks/useListState.ts";
import { SortableHead } from "@/components/SortableHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { ConnectorSummary } from "@/types/api.ts";

export function ConnectorsPage() {
  const listState = useListState();
  const { data: response, isLoading } = useConnectors(listState.params);
  const connectors = response?.data ?? [];
  const meta = (response as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };
  const createConnector = useCreateConnector();
  const deleteConnector = useDeleteConnector();
  const navigate = useNavigate();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addType, setAddType] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<ConnectorSummary | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    if (!addType.trim()) { setAddError("Type is required."); return; }
    try {
      const result = await createConnector.mutateAsync({
        name: addName.trim(),
        description: addDesc.trim() || undefined,
        connector_type: addType.trim(),
      });
      setAddName(""); setAddDesc(""); setAddType(""); setAddOpen(false);
      if (result.data?.id) navigate(`/connectors/${result.data.id}`);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create connector");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteConnector.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete connector");
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
          <h1 className="text-lg font-semibold text-zinc-100">Connectors</h1>
          <p className="text-sm text-zinc-500">
            Manage connectors and their versions.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <ClearableInput
              placeholder="Search connectors..."
              className="pl-9 w-64"
              value={listState.search}
              onChange={(e) => listState.setSearch(e.target.value)}
              onClear={() => listState.setSearch("")}
            />
          </div>
          <Button size="sm" onClick={() => { setAddName(""); setAddDesc(""); setAddType(""); setAddError(null); setAddOpen(true); }} className="gap-1.5">
            <Plus className="h-4 w-4" />
            New Connector
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plug className="h-4 w-4" />
            Connectors
            <Badge variant="default" className="ml-auto">{meta.total}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {connectors.length === 0 && !listState.search ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Plug className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No connectors registered</p>
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <SortableHead col="name" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>Name</SortableHead>
                    <SortableHead col="connector_type" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>Type</SortableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>Versions</TableHead>
                    <TableHead>Latest Version</TableHead>
                    <TableHead>Built-in</TableHead>
                    <TableHead className="w-12"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {connectors.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center text-zinc-500 py-8">
                        No connectors match your search
                      </TableCell>
                    </TableRow>
                  ) : (
                    connectors.map((c) => (
                      <TableRow key={c.id}>
                        <TableCell>
                          <Link
                            to={`/connectors/${c.id}`}
                            className="font-medium text-brand-400 hover:text-brand-300 transition-colors"
                          >
                            {c.name}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Badge variant="info">
                            {c.connector_type}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-zinc-400 text-sm max-w-[400px] truncate">
                          {c.description ?? <span className="text-zinc-600 italic">—</span>}
                        </TableCell>
                        <TableCell className="text-zinc-400 text-sm">
                          {c.version_count}
                        </TableCell>
                        <TableCell>
                          {c.latest_version ? (
                            <Badge variant="default" className="font-mono text-xs">{c.latest_version}</Badge>
                          ) : (
                            <span className="text-zinc-600 italic text-sm">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          {c.is_builtin && (
                            <Badge variant="success">built-in</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <button
                            onClick={() => setDeleteTarget(c)}
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

      {/* Add Connector Dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="New Connector">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="conn-name">Name</Label>
            <Input id="conn-name" placeholder="e.g. snmp_connector" value={addName} onChange={(e) => setAddName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="conn-type">Connector Type</Label>
            <Input id="conn-type" placeholder="e.g. snmp, http, sql" value={addType} onChange={(e) => setAddType(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="conn-desc">Description <span className="font-normal text-zinc-500">(optional)</span></Label>
            <Input id="conn-desc" value={addDesc} onChange={(e) => setAddDesc(e.target.value)} />
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createConnector.isPending}>
              {createConnector.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Connector Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => { setDeleteTarget(null); setDeleteError(null); }} title="Delete Connector">
        <p className="text-sm text-zinc-400">
          Delete connector <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span> and all its versions?
        </p>
        {deleteError && <p className="text-sm text-red-400 mt-2">{deleteError}</p>}
        <DialogFooter>
          <Button variant="secondary" onClick={() => { setDeleteTarget(null); setDeleteError(null); }}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteConnector.isPending}>
            {deleteConnector.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
