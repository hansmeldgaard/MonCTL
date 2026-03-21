import { useState, useMemo } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateShortName } from "@/lib/validation.ts";
import { Loader2, Pencil, Plus, Server, Trash2 } from "lucide-react";
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
import {
  useCreateDeviceType,
  useUpdateDeviceType,
  useDeleteDeviceType,
  useDeviceTypes,
} from "@/api/hooks.ts";
import type { DeviceType } from "@/types/api.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

// Built-in (seeded) types that shouldn't be deleted
const BUILTIN_TYPES = new Set([
  "host", "network", "api", "database", "service",
  "container", "virtual-machine", "storage", "printer", "iot",
]);

const CATEGORIES = [
  "network", "server", "storage", "printer", "iot", "service", "database", "other",
] as const;

const CATEGORY_COLORS: Record<string, string> = {
  network: "info",
  server: "default",
  storage: "default",
  printer: "default",
  iot: "default",
  service: "info",
  database: "info",
  other: "default",
};

export function DeviceTypesPage() {
  const tz = useTimezone();
  const { data: deviceTypes, isLoading } = useDeviceTypes();
  const createType = useCreateDeviceType();
  const updateType = useUpdateDeviceType();
  const deleteType = useDeleteDeviceType();

  const [addOpen, setAddOpen] = useState(false);
  const nameField = useField("", validateShortName);
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("other");
  const [formError, setFormError] = useState<string | null>(null);

  // Edit state
  const [editTarget, setEditTarget] = useState<DeviceType | null>(null);
  const editNameField = useField("", validateShortName);
  const [editDescription, setEditDescription] = useState("");
  const [editCategory, setEditCategory] = useState("other");
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  // Group device types by category
  const grouped = useMemo(() => {
    if (!deviceTypes) return [];
    const map = new Map<string, DeviceType[]>();
    for (const dt of deviceTypes) {
      const cat = dt.category || "other";
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(dt);
    }
    // Sort categories in the order defined
    return CATEGORIES
      .filter((c) => map.has(c))
      .map((c) => ({ category: c, types: map.get(c)! }));
  }, [deviceTypes]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    if (!validateAll(nameField)) return;

    try {
      await createType.mutateAsync({
        name: nameField.value.trim().toLowerCase().replace(/\s+/g, "-"),
        description: description.trim() || undefined,
        category,
      });
      nameField.reset();
      setDescription("");
      setCategory("other");
      setAddOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create device type");
    }
  }

  function openEdit(dt: DeviceType) {
    setEditTarget(dt);
    editNameField.reset(dt.name);
    setEditDescription(dt.description ?? "");
    setEditCategory(dt.category || "other");
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    const isBuiltin = BUILTIN_TYPES.has(editTarget.name);
    try {
      await updateType.mutateAsync({
        id: editTarget.id,
        data: {
          ...(isBuiltin ? {} : { name: editNameField.value.trim().toLowerCase().replace(/\s+/g, "-") }),
          description: editDescription.trim() || undefined,
          category: editCategory,
        },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update device type");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteType.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      // Error handled silently — type may be in use
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
          <h1 className="text-lg font-semibold text-zinc-100">Device Types</h1>
          <p className="text-sm text-zinc-500">
            Define the categories of devices that can be monitored.
          </p>
        </div>
        <Button size="sm" onClick={() => setAddOpen(true)} className="gap-1.5">
          <Plus className="h-4 w-4" />
          Add Type
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-4 w-4" />
            Device Types
            <Badge variant="default" className="ml-auto">
              {deviceTypes?.length ?? 0}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!deviceTypes || deviceTypes.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Server className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No device types defined</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {grouped.map(({ category: cat, types }) => (
                  <>
                    <TableRow key={`header-${cat}`}>
                      <TableCell colSpan={5} className="bg-zinc-800/30 py-1.5 px-3">
                        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
                          {cat}
                        </span>
                      </TableCell>
                    </TableRow>
                    {types.map((dt) => {
                      const isBuiltin = BUILTIN_TYPES.has(dt.name);
                      return (
                        <TableRow key={dt.id}>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Badge variant="info" className="font-mono text-xs">
                                {dt.name}
                              </Badge>
                              {isBuiltin && (
                                <Badge variant="default" className="text-xs text-zinc-500">
                                  built-in
                                </Badge>
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge variant={CATEGORY_COLORS[dt.category] === "info" ? "info" : "default"} className="text-xs">
                              {dt.category}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-zinc-400 text-sm">
                            {dt.description ?? <span className="text-zinc-600 italic">—</span>}
                          </TableCell>
                          <TableCell className="text-zinc-500 text-sm">
                            {formatDate(dt.created_at, tz)}
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => openEdit(dt)}
                                className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                                title="Edit"
                              >
                                <Pencil className="h-4 w-4" />
                              </button>
                              {!isBuiltin && (
                                <button
                                  onClick={() => setDeleteTarget({ id: dt.id, name: dt.name })}
                                  className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                                  title="Delete"
                                >
                                  <Trash2 className="h-4 w-4" />
                                </button>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Add Type Dialog */}
      <Dialog open={addOpen} onClose={() => { setAddOpen(false); setFormError(null); }} title="Add Device Type">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="dt-name">Name</Label>
            <Input
              id="dt-name"
              placeholder="e.g. firewall, load-balancer"
              value={nameField.value}
              onChange={nameField.onChange}
              onBlur={nameField.onBlur}
              autoFocus
            />
            {nameField.error && <p className="text-xs text-red-400 mt-0.5">{nameField.error}</p>}
            <p className="text-xs text-zinc-500">
              Lowercase, hyphens allowed. Will be auto-formatted.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-category">Category</Label>
            <Select id="dt-category" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-description">
              Description <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="dt-description"
              placeholder="Short description of this device category"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          {formError && <p className="text-sm text-red-400">{formError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => { setAddOpen(false); setFormError(null); }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createType.isPending}>
              {createType.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Add Type
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Type Dialog */}
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title="Edit Device Type">
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="dt-edit-name">Name</Label>
            <Input
              id="dt-edit-name"
              value={editNameField.value}
              onChange={editNameField.onChange}
              onBlur={editNameField.onBlur}
              disabled={editTarget ? BUILTIN_TYPES.has(editTarget.name) : false}
              autoFocus
            />
            {editTarget && BUILTIN_TYPES.has(editTarget.name) && (
              <p className="text-xs text-zinc-500">Built-in type names cannot be changed.</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-edit-category">Category</Label>
            <Select id="dt-edit-category" value={editCategory} onChange={(e) => setEditCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-edit-description">Description</Label>
            <Input
              id="dt-edit-description"
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              placeholder="Short description"
            />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditTarget(null)}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateType.isPending}>
              {updateType.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Confirm Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Device Type"
      >
        <p className="text-sm text-zinc-400">
          Are you sure you want to delete the device type{" "}
          <span className="font-mono text-zinc-200">{deleteTarget?.name}</span>?
          Devices already using this type will retain the value, but it will
          no longer appear in the type selector.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteType.isPending}
          >
            {deleteType.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
