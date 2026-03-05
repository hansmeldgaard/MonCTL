import { useState } from "react";
import { Loader2, Network, Pencil, Plus, Trash2 } from "lucide-react";
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
  useSnmpOids,
  useCreateSnmpOid,
  useUpdateSnmpOid,
  useDeleteSnmpOid,
} from "@/api/hooks.ts";
import type { SnmpOid } from "@/types/api.ts";

export function SnmpOidsPage() {
  const { data: oids, isLoading } = useSnmpOids();
  const createOid = useCreateSnmpOid();
  const updateOid = useUpdateSnmpOid();
  const deleteOid = useDeleteSnmpOid();

  // Add dialog
  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addOid, setAddOid] = useState("");
  const [addDescription, setAddDescription] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  // Edit dialog
  const [editTarget, setEditTarget] = useState<SnmpOid | null>(null);
  const [editName, setEditName] = useState("");
  const [editOid, setEditOid] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  // Delete dialog
  const [deleteTarget, setDeleteTarget] = useState<SnmpOid | null>(null);

  function openEdit(o: SnmpOid) {
    setEditTarget(o);
    setEditName(o.name);
    setEditOid(o.oid);
    setEditDescription(o.description ?? "");
    setEditError(null);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    if (!addOid.trim()) { setAddError("OID is required."); return; }
    try {
      await createOid.mutateAsync({
        name: addName.trim(),
        oid: addOid.trim(),
        description: addDescription.trim() || undefined,
      });
      setAddName(""); setAddOid(""); setAddDescription("");
      setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create OID");
    }
  }

  async function handleUpdate(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    if (!editName.trim()) { setEditError("Name is required."); return; }
    if (!editOid.trim()) { setEditError("OID is required."); return; }
    try {
      await updateOid.mutateAsync({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          oid: editOid.trim(),
          description: editDescription.trim() || undefined,
        },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update OID");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteOid.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      // silent
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
          <h1 className="text-lg font-semibold text-zinc-100">SNMP OID Catalog</h1>
          <p className="text-sm text-zinc-500">
            Define SNMP OIDs that can be selected for device monitoring checks.
          </p>
        </div>
        <Button size="sm" onClick={() => setAddOpen(true)} className="gap-1.5">
          <Plus className="h-4 w-4" />
          Add OID
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Network className="h-4 w-4" />
            SNMP OIDs
            <Badge variant="default" className="ml-auto">
              {oids?.length ?? 0}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!oids || oids.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Network className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No SNMP OIDs defined</p>
              <Button
                size="sm"
                variant="secondary"
                className="mt-3 gap-1.5"
                onClick={() => setAddOpen(true)}
              >
                <Plus className="h-4 w-4" />
                Add first OID
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>OID</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {oids.map((o) => (
                  <TableRow key={o.id}>
                    <TableCell className="font-medium text-zinc-200">{o.name}</TableCell>
                    <TableCell className="font-mono text-xs text-zinc-400">{o.oid}</TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {o.description ?? <span className="text-zinc-600 italic">—</span>}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => openEdit(o)}
                          className="rounded p-1 text-zinc-600 hover:text-brand-400 hover:bg-brand-500/10 transition-colors cursor-pointer"
                          title="Edit"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setDeleteTarget(o)}
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

      {/* Add OID Dialog */}
      <Dialog open={addOpen} onClose={() => { setAddOpen(false); setAddError(null); }} title="Add SNMP OID">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="add-name">Name</Label>
            <Input
              id="add-name"
              placeholder="e.g. System Uptime"
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="add-oid">OID</Label>
            <Input
              id="add-oid"
              placeholder="e.g. 1.3.6.1.2.1.1.3.0"
              value={addOid}
              onChange={(e) => setAddOid(e.target.value)}
              className="font-mono text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="add-desc">
              Description <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="add-desc"
              placeholder="What this OID measures"
              value={addDescription}
              onChange={(e) => setAddDescription(e.target.value)}
            />
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => { setAddOpen(false); setAddError(null); }}>
              Cancel
            </Button>
            <Button type="submit" disabled={createOid.isPending}>
              {createOid.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Add OID
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit OID Dialog */}
      <Dialog open={!!editTarget} onClose={() => { setEditTarget(null); setEditError(null); }} title="Edit SNMP OID">
        <form onSubmit={handleUpdate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="edit-name">Name</Label>
            <Input
              id="edit-name"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-oid">OID</Label>
            <Input
              id="edit-oid"
              value={editOid}
              onChange={(e) => setEditOid(e.target.value)}
              className="font-mono text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-desc">
              Description <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="edit-desc"
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
            />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => { setEditTarget(null); setEditError(null); }}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateOid.isPending}>
              {updateOid.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save Changes
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Confirm Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete SNMP OID">
        <p className="text-sm text-zinc-400">
          Delete OID{" "}
          <span className="font-medium text-zinc-200">{deleteTarget?.name}</span>{" "}
          (<span className="font-mono text-xs text-zinc-300">{deleteTarget?.oid}</span>)?
          Devices using this OID will lose their SNMP check configuration.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteOid.isPending}>
            {deleteOid.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
