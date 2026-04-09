import { useState } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateShortName } from "@/lib/validation.ts";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { Loader2, Plus, Pencil, Trash2, ShieldCheck } from "lucide-react";
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
import {
  useRoles,
  useRoleResources,
  useCreateRole,
  useUpdateRole,
  useDeleteRole,
} from "@/api/hooks.ts";
import type { Role } from "@/types/api.ts";

function PermissionMatrix({
  permissions,
  onChange,
  resourceActions,
}: {
  permissions: { resource: string; action: string }[];
  onChange: (perms: { resource: string; action: string }[]) => void;
  resourceActions: Record<string, string[]>;
}) {
  const allActions = ["view", "create", "edit", "delete", "manage"];
  const resources = Object.keys(resourceActions);

  const permSet = new Set(permissions.map((p) => `${p.resource}:${p.action}`));

  function toggle(resource: string, action: string) {
    const key = `${resource}:${action}`;
    if (permSet.has(key)) {
      onChange(
        permissions.filter(
          (p) => !(p.resource === resource && p.action === action),
        ),
      );
    } else {
      onChange([...permissions, { resource, action }]);
    }
  }

  function toggleRow(resource: string) {
    const actions = resourceActions[resource];
    const allChecked = actions.every((a) => permSet.has(`${resource}:${a}`));
    if (allChecked) {
      onChange(permissions.filter((p) => p.resource !== resource));
    } else {
      const existing = permissions.filter((p) => p.resource !== resource);
      onChange([...existing, ...actions.map((a) => ({ resource, action: a }))]);
    }
  }

  function toggleCol(action: string) {
    const applicable = resources.filter((r) =>
      resourceActions[r].includes(action),
    );
    const allChecked = applicable.every((r) => permSet.has(`${r}:${action}`));
    if (allChecked) {
      onChange(
        permissions.filter(
          (p) => p.action !== action || !applicable.includes(p.resource),
        ),
      );
    } else {
      const kept = permissions.filter(
        (p) => p.action !== action || !applicable.includes(p.resource),
      );
      onChange([...kept, ...applicable.map((r) => ({ resource: r, action }))]);
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-800">
            <th className="text-left py-2 pr-3 font-medium text-zinc-400">
              Resource
            </th>
            {allActions.map((a) => (
              <th
                key={a}
                className="py-2 px-2 font-medium text-zinc-400 text-center"
              >
                <button
                  type="button"
                  onClick={() => toggleCol(a)}
                  className="hover:text-zinc-200 cursor-pointer capitalize"
                >
                  {a}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {resources.map((res) => (
            <tr key={res}>
              <td className="py-1.5 pr-3">
                <button
                  type="button"
                  onClick={() => toggleRow(res)}
                  className="text-zinc-300 hover:text-white cursor-pointer capitalize"
                >
                  {res}
                </button>
              </td>
              {allActions.map((act) => {
                const valid = resourceActions[res].includes(act);
                const checked = permSet.has(`${res}:${act}`);
                return (
                  <td key={act} className="py-1.5 px-2 text-center">
                    {valid ? (
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(res, act)}
                        className="rounded border-zinc-600 cursor-pointer"
                      />
                    ) : (
                      <span className="text-zinc-700">—</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RolesPage() {
  const { data: roles, isLoading } = useRoles();
  const { data: resourceActions } = useRoleResources();
  const createRole = useCreateRole();
  const updateRole = useUpdateRole();
  const deleteRole = useDeleteRole();
  const { isAdmin } = usePermissions();

  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Role | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null);

  // Create form
  const newNameField = useField("", validateShortName);
  const [newDesc, setNewDesc] = useState("");
  const [newPerms, setNewPerms] = useState<
    { resource: string; action: string }[]
  >([]);

  // Edit form
  const editNameField = useField("", validateShortName);
  const [editDesc, setEditDesc] = useState("");
  const [editPerms, setEditPerms] = useState<
    { resource: string; action: string }[]
  >([]);

  function openCreate() {
    newNameField.reset();
    setNewDesc("");
    setNewPerms([]);
    setCreateOpen(true);
  }

  function openEdit(role: Role) {
    editNameField.reset(role.name);
    setEditDesc(role.description ?? "");
    setEditPerms(
      role.permissions.map((p) => ({ resource: p.resource, action: p.action })),
    );
    setEditTarget(role);
  }

  async function handleCreate() {
    if (!validateAll(newNameField)) return;
    await createRole.mutateAsync({
      name: newNameField.value.trim(),
      description: newDesc.trim() || undefined,
      permissions: newPerms,
    });
    setCreateOpen(false);
  }

  async function handleUpdate() {
    if (!editTarget) return;
    if (!validateAll(editNameField)) return;
    await updateRole.mutateAsync({
      id: editTarget.id,
      data: {
        name: editNameField.value.trim(),
        description: editDesc.trim() || undefined,
        permissions: editPerms,
      },
    });
    setEditTarget(null);
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    await deleteRole.mutateAsync(deleteTarget.id);
    setDeleteTarget(null);
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" />
            Roles
            {isAdmin && (
              <Button
                size="sm"
                className="ml-auto gap-1.5"
                onClick={openCreate}
              >
                <Plus className="h-3.5 w-3.5" />
                Add Role
              </Button>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!roles || roles.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
              <ShieldCheck className="mb-2 h-6 w-6 text-zinc-600" />
              <p className="text-sm">No roles defined yet.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-left text-xs text-zinc-500">
                    <th className="pb-2 pr-4 font-medium">Name</th>
                    <th className="pb-2 pr-4 font-medium">Description</th>
                    <th className="pb-2 pr-4 font-medium">Permissions</th>
                    <th className="pb-2 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/50">
                  {roles.map((role) => (
                    <tr key={role.id} className="text-zinc-300">
                      <td className="py-2.5 pr-4 text-xs font-medium">
                        {role.name}
                        {role.is_system && (
                          <Badge variant="default" className="ml-2 text-[10px]">
                            System
                          </Badge>
                        )}
                      </td>
                      <td className="py-2.5 pr-4 text-xs text-zinc-400">
                        {role.description ?? "—"}
                      </td>
                      <td className="py-2.5 pr-4 text-xs text-zinc-400">
                        {role.permissions.length} permissions
                      </td>
                      <td className="py-2.5 text-right">
                        {isAdmin && (
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => openEdit(role)}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setDeleteTarget(role)}
                              disabled={role.is_system}
                            >
                              <Trash2 className="h-3.5 w-3.5 text-red-400" />
                            </Button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Dialog */}
      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create Role"
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input
              placeholder="e.g. Network Operator"
              value={newNameField.value}
              onChange={newNameField.onChange}
              onBlur={newNameField.onBlur}
              className="text-xs"
              autoFocus
            />
            {newNameField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {newNameField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label>Description</Label>
            <Input
              placeholder="What this role can do"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              className="text-xs"
            />
          </div>
          {resourceActions && (
            <div className="space-y-1.5">
              <Label>Permissions</Label>
              <PermissionMatrix
                permissions={newPerms}
                onChange={setNewPerms}
                resourceActions={resourceActions}
              />
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={createRole.isPending || !newNameField.value.trim()}
            >
              {createRole.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Create
            </Button>
          </DialogFooter>
        </div>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        title={`Edit "${editTarget?.name}"`}
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input
              value={editNameField.value}
              onChange={editNameField.onChange}
              onBlur={editNameField.onBlur}
              className="text-xs"
            />
            {editNameField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {editNameField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label>Description</Label>
            <Input
              value={editDesc}
              onChange={(e) => setEditDesc(e.target.value)}
              className="text-xs"
            />
          </div>
          {resourceActions && (
            <div className="space-y-1.5">
              <Label>Permissions</Label>
              <PermissionMatrix
                permissions={editPerms}
                onChange={setEditPerms}
                resourceActions={resourceActions}
              />
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setEditTarget(null)}>
              Cancel
            </Button>
            <Button onClick={handleUpdate} disabled={updateRole.isPending}>
              {updateRole.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Save
            </Button>
          </DialogFooter>
        </div>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Role"
      >
        <p className="text-sm text-zinc-400">
          Are you sure you want to delete the role{" "}
          <strong className="text-zinc-200">"{deleteTarget?.name}"</strong>?
          Users assigned to this role will lose their permissions.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteRole.isPending}
          >
            {deleteRole.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
