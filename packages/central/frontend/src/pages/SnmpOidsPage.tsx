import { useMemo, useState } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName, validateOid } from "@/lib/validation.ts";
import { Loader2, Network, Pencil, Plus, Trash2 } from "lucide-react";
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
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";
import {
  useSnmpOids,
  useCreateSnmpOid,
  useUpdateSnmpOid,
  useDeleteSnmpOid,
} from "@/api/hooks.ts";
import { usePermissions } from "@/hooks/usePermissions.ts";
import type { SnmpOid } from "@/types/api.ts";

export function SnmpOidsPage() {
  const { canCreate, canEdit, canDelete } = usePermissions();
  const { data: oids, isLoading } = useSnmpOids();
  const createOid = useCreateSnmpOid();
  const updateOid = useUpdateSnmpOid();
  const deleteOid = useDeleteSnmpOid();

  // Add dialog
  const [addOpen, setAddOpen] = useState(false);
  const addNameField = useField("", validateName);
  const addOidField = useField("", validateOid);
  const [addDescription, setAddDescription] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  // Edit dialog
  const [editTarget, setEditTarget] = useState<SnmpOid | null>(null);
  const editNameField = useField("", validateName);
  const editOidField = useField("", validateOid);
  const [editDescription, setEditDescription] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  // Delete dialog
  const [deleteTarget, setDeleteTarget] = useState<SnmpOid | null>(null);

  function openEdit(o: SnmpOid) {
    setEditTarget(o);
    editNameField.reset(o.name);
    editOidField.reset(o.oid);
    setEditDescription(o.description ?? "");
    setEditError(null);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!validateAll(addNameField, addOidField)) return;
    try {
      await createOid.mutateAsync({
        name: addNameField.value.trim(),
        oid: addOidField.value.trim(),
        description: addDescription.trim() || undefined,
      });
      addNameField.reset();
      addOidField.reset();
      setAddDescription("");
      setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create OID");
    }
  }

  async function handleUpdate(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    if (!validateAll(editNameField, editOidField)) return;
    try {
      await updateOid.mutateAsync({
        id: editTarget.id,
        data: {
          name: editNameField.value.trim(),
          oid: editOidField.value.trim(),
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

  const { compact } = useDisplayPreferences();

  const columns = useMemo<FlexColumnDef<SnmpOid>[]>(
    () => [
      {
        key: "name",
        label: "Name",
        defaultWidth: 220,
        cellClassName: "font-medium text-zinc-200",
        cell: (o) => o.name,
      },
      {
        key: "oid",
        label: "OID",
        defaultWidth: 260,
        cellClassName: "font-mono text-xs text-zinc-400",
        cell: (o) => o.oid,
      },
      {
        key: "description",
        label: "Description",
        defaultWidth: 320,
        cellClassName: "text-zinc-400 text-sm",
        cell: (o) =>
          o.description ?? <span className="text-zinc-600 italic">—</span>,
      },
      {
        key: "__actions",
        label: "",
        pickerLabel: "Actions",
        sortable: false,
        filterable: false,
        defaultWidth: 90,
        cell: (o) => (
          <div className="flex items-center gap-1">
            {canEdit("device") && (
              <button
                onClick={() => openEdit(o)}
                className="rounded p-1 text-zinc-600 hover:text-brand-400 hover:bg-brand-500/10 transition-colors cursor-pointer"
                title="Edit"
              >
                <Pencil className="h-4 w-4" />
              </button>
            )}
            {canDelete("device") && (
              <button
                onClick={() => setDeleteTarget(o)}
                className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        ),
      },
    ],
    [canEdit, canDelete],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<SnmpOid>("snmp-oids", columns);

  const [sortBy, setSortBy] = useState("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const handleSort = (col: string) => {
    if (col === sortBy) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(col);
      setSortDir("asc");
    }
  };
  const sortedOids = useMemo(() => {
    if (!oids) return [];
    const copy = [...oids];
    const getter: Record<string, (o: SnmpOid) => any> = {
      name: (o) => o.name,
      oid: (o) => o.oid,
      description: (o) => o.description ?? "",
    };
    const g = getter[sortBy];
    if (!g) return copy;
    return copy.sort((a, b) =>
      sortDir === "asc"
        ? String(g(a)).localeCompare(String(g(b)))
        : String(g(b)).localeCompare(String(g(a))),
    );
  }, [oids, sortBy, sortDir]);

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
          <h1 className="text-lg font-semibold text-zinc-100">
            SNMP OID Catalog
          </h1>
          <p className="text-sm text-zinc-500">
            Define SNMP OIDs that can be selected for device monitoring checks.
          </p>
        </div>
        {canCreate("device") && (
          <Button
            size="sm"
            onClick={() => setAddOpen(true)}
            className="gap-1.5"
          >
            <Plus className="h-4 w-4" />
            Add OID
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Network className="h-4 w-4" />
            SNMP OIDs
            <Badge variant="default" className="ml-2">
              {oids?.length ?? 0}
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
          {!oids || oids.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Network className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No SNMP OIDs defined</p>
              {canCreate("device") && (
                <Button
                  size="sm"
                  variant="secondary"
                  className="mt-3 gap-1.5"
                  onClick={() => setAddOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  Add first OID
                </Button>
              )}
            </div>
          ) : (
            <div
              className={
                compact
                  ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
                  : ""
              }
            >
              <FlexTable<SnmpOid>
                orderedVisibleColumns={orderedVisibleColumns}
                configMap={configMap}
                onOrderChange={setOrder}
                onWidthChange={setWidth}
                rows={sortedOids}
                rowKey={(o) => o.id}
                sortBy={sortBy}
                sortDir={sortDir}
                onSort={handleSort}
                filters={{}}
                onFilterChange={() => {}}
                emptyState="No SNMP OIDs"
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add OID Dialog */}
      <Dialog
        open={addOpen}
        onClose={() => {
          setAddOpen(false);
          setAddError(null);
        }}
        title="Add SNMP OID"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="add-name">Name</Label>
            <Input
              id="add-name"
              placeholder="e.g. System Uptime"
              value={addNameField.value}
              onChange={addNameField.onChange}
              onBlur={addNameField.onBlur}
              autoFocus
            />
            {addNameField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {addNameField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="add-oid">OID</Label>
            <Input
              id="add-oid"
              placeholder="e.g. 1.3.6.1.2.1.1.3.0"
              value={addOidField.value}
              onChange={addOidField.onChange}
              onBlur={addOidField.onBlur}
              className="font-mono text-sm"
            />
            {addOidField.error && (
              <p className="text-xs text-red-400 mt-0.5">{addOidField.error}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="add-desc">
              Description{" "}
              <span className="font-normal text-zinc-500">(optional)</span>
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
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setAddOpen(false);
                setAddError(null);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createOid.isPending}>
              {createOid.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Add OID
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit OID Dialog */}
      <Dialog
        open={!!editTarget}
        onClose={() => {
          setEditTarget(null);
          setEditError(null);
        }}
        title="Edit SNMP OID"
      >
        <form onSubmit={handleUpdate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="edit-name">Name</Label>
            <Input
              id="edit-name"
              value={editNameField.value}
              onChange={editNameField.onChange}
              onBlur={editNameField.onBlur}
              autoFocus
            />
            {editNameField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {editNameField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-oid">OID</Label>
            <Input
              id="edit-oid"
              value={editOidField.value}
              onChange={editOidField.onChange}
              onBlur={editOidField.onBlur}
              className="font-mono text-sm"
            />
            {editOidField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {editOidField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-desc">
              Description{" "}
              <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="edit-desc"
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
            />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setEditTarget(null);
                setEditError(null);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={updateOid.isPending}>
              {updateOid.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Save Changes
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Confirm Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete SNMP OID"
      >
        <p className="text-sm text-zinc-400">
          Delete OID{" "}
          <span className="font-medium text-zinc-200">
            {deleteTarget?.name}
          </span>{" "}
          (
          <span className="font-mono text-xs text-zinc-300">
            {deleteTarget?.oid}
          </span>
          )? Devices using this OID will lose their SNMP check configuration.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteOid.isPending}
          >
            {deleteOid.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
