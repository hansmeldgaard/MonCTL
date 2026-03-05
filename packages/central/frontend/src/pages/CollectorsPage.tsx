import { useState } from "react";
import {
  Cpu,
  Layers,
  Loader2,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
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
import {
  useCollectors,
  useCollectorGroups,
  useCreateCollectorGroup,
  useUpdateCollectorGroup,
  useDeleteCollectorGroup,
  useUpdateCollector,
  useDeleteCollector,
} from "@/api/hooks.ts";
import type { Collector, CollectorGroup } from "@/types/api.ts";
import { timeAgo } from "@/lib/utils.ts";

// ── Collector Groups Section ──────────────────────────────────────────────────

function CollectorGroupsCard() {
  const { data: groups, isLoading } = useCollectorGroups();
  const { data: collectors } = useCollectors();
  const createGroup = useCreateCollectorGroup();
  const updateGroup = useUpdateCollectorGroup();
  const deleteGroup = useDeleteCollectorGroup();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<CollectorGroup | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<CollectorGroup | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    try {
      await createGroup.mutateAsync({ name: addName.trim(), description: addDesc.trim() || undefined });
      setAddName(""); setAddDesc(""); setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create group");
    }
  }

  function openEdit(g: CollectorGroup) {
    setEditTarget(g);
    setEditName(g.name);
    setEditDesc(g.description ?? "");
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    if (!editName.trim()) { setEditError("Name is required."); return; }
    try {
      await updateGroup.mutateAsync({
        id: editTarget.id,
        data: { name: editName.trim(), description: editDesc.trim() || undefined },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update group");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteGroup.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch { /* silent */ }
  }

  // Count collectors per group from the collectors list
  const countByGroup = (groupId: string) =>
    collectors?.filter((c) => c.group_id === groupId).length ?? 0;

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Layers className="h-4 w-4" />
            Collector Groups
            <Badge variant="default" className="ml-auto">
              {groups?.length ?? 0}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
          ) : !groups || groups.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-zinc-500">
              <Layers className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No collector groups defined</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Collectors</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.map((g) => {
                  const cnt = countByGroup(g.id);
                  return (
                    <TableRow key={g.id}>
                      <TableCell className="font-medium text-zinc-100">{g.name}</TableCell>
                      <TableCell className="text-zinc-400 text-sm">
                        {g.description ?? <span className="italic text-zinc-600">—</span>}
                      </TableCell>
                      <TableCell className="text-right text-zinc-400 text-sm">{cnt}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => openEdit(g)}
                            className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                            title="Edit"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => setDeleteTarget(g)}
                            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}

          <div className="mt-4 flex justify-end border-t border-zinc-800 pt-4">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => { setAddName(""); setAddDesc(""); setAddError(null); setAddOpen(true); }}
              className="gap-1.5"
            >
              <Plus className="h-4 w-4" />
              New Group
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Add Group Dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="New Collector Group">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="cg-name">Name</Label>
            <Input
              id="cg-name"
              placeholder="e.g. EU-West"
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cg-desc">
              Description <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="cg-desc"
              placeholder="Short description"
              value={addDesc}
              onChange={(e) => setAddDesc(e.target.value)}
            />
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createGroup.isPending}>
              {createGroup.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Group Dialog */}
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title="Edit Collector Group">
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="cg-edit-name">Name</Label>
            <Input
              id="cg-edit-name"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cg-edit-desc">Description</Label>
            <Input
              id="cg-edit-desc"
              value={editDesc}
              onChange={(e) => setEditDesc(e.target.value)}
            />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditTarget(null)}>Cancel</Button>
            <Button type="submit" disabled={updateGroup.isPending}>
              {updateGroup.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Group Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete Collector Group">
        <p className="text-sm text-zinc-400">
          Delete group{" "}
          <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?
          Collectors in this group will be unassigned. Devices targeting this group
          will lose their group assignment.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteGroup.isPending}>
            {deleteGroup.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Collectors Section ────────────────────────────────────────────────────────

function EditCollectorDialog({
  collector,
  groups,
  onClose,
}: {
  collector: Collector;
  groups: CollectorGroup[];
  onClose: () => void;
}) {
  const updateCollector = useUpdateCollector();
  const [name, setName] = useState(collector.name);
  const [groupId, setGroupId] = useState(collector.group_id ?? "");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await updateCollector.mutateAsync({
        id: collector.id,
        data: { name: name.trim(), group_id: groupId || "" },
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update collector");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="col-name">Name</Label>
        <Input
          id="col-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="col-group">Collector Group</Label>
        <select
          id="col-group"
          value={groupId}
          onChange={(e) => setGroupId(e.target.value)}
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          <option value="">— No group —</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>{g.name}</option>
          ))}
        </select>
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={updateCollector.isPending}>
          {updateCollector.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Save
        </Button>
      </DialogFooter>
    </form>
  );
}

function CollectorsCard() {
  const { data: collectors, isLoading } = useCollectors();
  const { data: groups } = useCollectorGroups();
  const deleteCollector = useDeleteCollector();

  const [editTarget, setEditTarget] = useState<Collector | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Collector | null>(null);

  const online = collectors?.filter((c) => c.status === "ACTIVE").length ?? 0;
  const total = collectors?.length ?? 0;

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteCollector.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch { /* silent */ }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-4 w-4" />
            Collectors
            <span className="ml-2 text-sm font-normal text-zinc-500">
              {online}/{total} online
            </span>
            <Badge variant="default" className="ml-auto">{total}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
          ) : !collectors || collectors.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-zinc-500">
              <Cpu className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No collectors registered</p>
              <p className="mt-1 text-xs text-zinc-600">
                Collectors register automatically on first connection.
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">Status</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Hostname</TableHead>
                  <TableHead>IP Address</TableHead>
                  <TableHead>Group</TableHead>
                  <TableHead>Labels</TableHead>
                  <TableHead>Last Seen</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {collectors.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <span
                        className={`inline-block h-2.5 w-2.5 rounded-full ${
                          c.status === "ACTIVE"
                            ? "bg-emerald-500 animate-pulse-dot"
                            : "bg-red-500"
                        }`}
                        title={c.status}
                      />
                    </TableCell>
                    <TableCell className="font-medium text-zinc-100">{c.name}</TableCell>
                    <TableCell className="font-mono text-xs text-zinc-400">
                      {c.hostname ?? "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-400">
                      {c.ip_addresses && c.ip_addresses.length > 0
                        ? c.ip_addresses.join(", ")
                        : <span className="italic text-zinc-600">—</span>}
                    </TableCell>
                    <TableCell>
                      {c.group_name ? (
                        <Badge variant="info" className="text-xs">{c.group_name}</Badge>
                      ) : (
                        <span className="text-zinc-600 text-xs italic">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(c.labels ?? {}).map(([k, v]) => (
                          <Badge key={k} variant="default" className="text-xs">
                            {k}: {v}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm">
                      {timeAgo(c.last_seen_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setEditTarget(c)}
                          className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                          title="Edit"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setDeleteTarget(c)}
                          className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Edit Collector Dialog */}
      <Dialog
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        title="Edit Collector"
      >
        {editTarget && (
          <EditCollectorDialog
            collector={editTarget}
            groups={groups ?? []}
            onClose={() => setEditTarget(null)}
          />
        )}
      </Dialog>

      {/* Delete Collector Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Collector"
      >
        <p className="text-sm text-zinc-400">
          Delete collector{" "}
          <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?
          Its API key, app assignments, and historical check data will be removed.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteCollector.isPending}>
            {deleteCollector.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export function CollectorsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Collectors</h1>
        <p className="text-sm text-zinc-500">
          Manage collector groups and registered collectors.
        </p>
      </div>
      <CollectorGroupsCard />
      <CollectorsCard />
    </div>
  );
}
