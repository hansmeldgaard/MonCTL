import { useMemo, useState } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName } from "@/lib/validation.ts";
import { Building2, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
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
import { KeyValueEditor } from "@/components/KeyValueEditor.tsx";
import {
  useCreateTenant,
  useDeleteTenant,
  useTenants,
  useUpdateTenantFull,
} from "@/api/hooks.ts";
import type { Tenant } from "@/types/api.ts";
import { useAuth } from "@/hooks/useAuth.tsx";
import { formatTime } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";

export function TenantsPage() {
  const tz = useTimezone();
  const { mode } = useTimeDisplayMode();
  const { compact } = useDisplayPreferences();
  const { data: tenants, isLoading } = useTenants();
  const createTenant = useCreateTenant();
  const updateTenant = useUpdateTenantFull();
  const deleteTenant = useDeleteTenant();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  // Add dialog
  const [addOpen, setAddOpen] = useState(false);
  const addNameField = useField("", validateName);
  const [addError, setAddError] = useState<string | null>(null);

  // Edit dialog
  const [editTarget, setEditTarget] = useState<Tenant | null>(null);
  const editNameField = useField("", validateName);
  const [editMetadata, setEditMetadata] = useState<Record<string, string>>({});
  const [editError, setEditError] = useState<string | null>(null);

  // Delete dialog
  const [deleteTarget, setDeleteTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!validateAll(addNameField)) return;
    try {
      await createTenant.mutateAsync({ name: addNameField.value.trim() });
      addNameField.reset();
      setAddOpen(false);
    } catch (err) {
      setAddError(
        err instanceof Error ? err.message : "Failed to create tenant",
      );
    }
  }

  function openEdit(t: Tenant) {
    setEditTarget(t);
    editNameField.reset(t.name);
    setEditMetadata(t.metadata || {});
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    if (!validateAll(editNameField)) return;
    try {
      await updateTenant.mutateAsync({
        id: editTarget.id,
        data: { name: editNameField.value.trim(), metadata: editMetadata },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(
        err instanceof Error ? err.message : "Failed to update tenant",
      );
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteTenant.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      // silent
    }
  }

  const columns = useMemo<FlexColumnDef<Tenant>[]>(
    () => [
      {
        key: "name",
        label: "Name",
        defaultWidth: 220,
        cellClassName: "font-medium text-zinc-100",
        cell: (t) => t.name,
      },
      {
        key: "__metadata",
        label: "Metadata",
        pickerLabel: "Metadata",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-400 text-sm",
        cell: (t) => {
          const metaCount = Object.keys(t.metadata || {}).length;
          return metaCount > 0 ? (
            <Badge variant="default" className="text-xs">
              {metaCount} {metaCount === 1 ? "key" : "keys"}
            </Badge>
          ) : (
            <span className="text-zinc-600 text-xs">—</span>
          );
        },
      },
      {
        key: "created_at",
        label: "Created",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 text-sm",
        cell: (t) => formatTime(t.created_at, mode, tz),
      },
      {
        key: "__actions",
        label: "",
        pickerLabel: "Actions",
        sortable: false,
        filterable: false,
        defaultWidth: 80,
        cell: (t) =>
          isAdmin ? (
            <div className="flex items-center gap-1">
              <button
                onClick={() => openEdit(t)}
                className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                title="Edit"
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                onClick={() => setDeleteTarget({ id: t.id, name: t.name })}
                className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ) : null,
      },
    ],
    [isAdmin, mode, tz],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<Tenant>("tenants", columns);

  const [sortBy, setSortBy] = useState("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const handleSort = (col: string) => {
    if (col === sortBy) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(col);
      setSortDir("asc");
    }
  };
  const sortedTenants = useMemo(() => {
    if (!tenants) return [];
    const copy = [...tenants];
    const getter: Record<string, (t: Tenant) => any> = {
      name: (t) => t.name,
      created_at: (t) => (t.created_at ? new Date(t.created_at).getTime() : 0),
    };
    const g = getter[sortBy];
    if (!g) return copy;
    return copy.sort((a, b) => {
      const av = g(a);
      const bv = g(b);
      if (typeof av === "number" && typeof bv === "number")
        return sortDir === "asc" ? av - bv : bv - av;
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
  }, [tenants, sortBy, sortDir]);

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
          <h1 className="text-lg font-semibold text-zinc-100">Tenants</h1>
          <p className="text-sm text-zinc-500">
            Manage tenant isolation. Devices and users are scoped to tenants.
          </p>
        </div>
        {isAdmin && (
          <Button
            size="sm"
            onClick={() => {
              addNameField.reset();
              setAddError(null);
              setAddOpen(true);
            }}
            className="gap-1.5"
          >
            <Plus className="h-4 w-4" />
            New Tenant
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-4 w-4" />
            Tenants
            <Badge variant="default" className="ml-2">
              {tenants?.length ?? 0}
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
          {!tenants || tenants.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Building2 className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No tenants defined</p>
              {isAdmin && (
                <p className="mt-1 text-xs text-zinc-600">
                  Create a tenant to start scoping devices and users.
                </p>
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
              <FlexTable<Tenant>
                orderedVisibleColumns={orderedVisibleColumns}
                configMap={configMap}
                onOrderChange={setOrder}
                onWidthChange={setWidth}
                rows={sortedTenants}
                rowKey={(t) => t.id}
                sortBy={sortBy}
                sortDir={sortDir}
                onSort={handleSort}
                filters={{}}
                onFilterChange={() => {}}
                emptyState="No tenants"
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add Tenant Dialog */}
      <Dialog
        open={addOpen}
        onClose={() => {
          setAddOpen(false);
          setAddError(null);
        }}
        title="New Tenant"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tenant-name">Name</Label>
            <Input
              id="tenant-name"
              placeholder="e.g. Acme Corp"
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
            <Button type="submit" disabled={createTenant.isPending}>
              {createTenant.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Tenant Dialog */}
      <Dialog
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        title="Edit Tenant"
      >
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tenant-edit-name">Name</Label>
            <Input
              id="tenant-edit-name"
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
            <Label>Metadata</Label>
            <KeyValueEditor value={editMetadata} onChange={setEditMetadata} />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setEditTarget(null)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={updateTenant.isPending}>
              {updateTenant.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Confirm Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Tenant"
      >
        <p className="text-sm text-zinc-400">
          Are you sure you want to delete tenant{" "}
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.name}
          </span>
          ? Devices assigned to this tenant will be unlinked (their tenant will
          be cleared).
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteTenant.isPending}
          >
            {deleteTenant.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
