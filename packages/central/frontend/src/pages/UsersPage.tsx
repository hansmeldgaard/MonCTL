import { useState, useEffect } from "react";
import {
  Loader2,
  Plus,
  Shield,
  Trash2,
  UserCog,
  Users,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import {
  useUsers,
  useCreateUser,
  useUpdateUser,
  useDeleteUser,
  useUserTenants,
  useAssignTenantToUser,
  useRemoveTenantFromUser,
  useTenants,
} from "@/api/hooks.ts";
import type { User } from "@/types/api.ts";
import { useAuth } from "@/hooks/useAuth.tsx";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

// ── Role badge helper ────────────────────────────────────

function RoleBadge({ role }: { role: string }) {
  return (
    <Badge variant={role === "admin" ? "info" : "default"}>
      {role}
    </Badge>
  );
}

// ── Add User Dialog ───────────────────────────────────────

interface AddUserDialogProps {
  open: boolean;
  onClose: () => void;
}

function AddUserDialog({ open, onClose }: AddUserDialogProps) {
  const createUser = useCreateUser();
  const { data: allTenantsList } = useTenants();
  const assignTenant = useAssignTenantToUser();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [allTenants, setAllTenants] = useState(false);
  const [selectedTenantIds, setSelectedTenantIds] = useState<Set<string>>(new Set());
  const [formError, setFormError] = useState<string | null>(null);

  function reset() {
    setUsername("");
    setPassword("");
    setDisplayName("");
    setEmail("");
    setRole("viewer");
    setAllTenants(false);
    setSelectedTenantIds(new Set());
    setFormError(null);
  }

  function handleClose() {
    reset();
    onClose();
  }

  function toggleTenant(tenantId: string) {
    setSelectedTenantIds((prev) => {
      const next = new Set(prev);
      if (next.has(tenantId)) next.delete(tenantId);
      else next.add(tenantId);
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    if (!username.trim()) {
      setFormError("Username is required.");
      return;
    }
    if (!password) {
      setFormError("Password is required.");
      return;
    }

    try {
      const result = await createUser.mutateAsync({
        username: username.trim(),
        password,
        role,
        display_name: displayName.trim() || undefined,
        email: email.trim() || undefined,
        all_tenants: allTenants,
      });
      // Assign selected tenants after user creation
      if (!allTenants && selectedTenantIds.size > 0 && result.data) {
        const userId = result.data.id;
        for (const tenantId of selectedTenantIds) {
          try {
            await assignTenant.mutateAsync({ userId, tenantId });
          } catch {
            // tenant may already be assigned, skip
          }
        }
      }
      reset();
      onClose();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create user");
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} title="Add User">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="nu-username">Username *</Label>
            <Input
              id="nu-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="jdoe"
              autoComplete="off"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="nu-password">Password *</Label>
            <Input
              id="nu-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="nu-display">Display Name</Label>
            <Input
              id="nu-display"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="John Doe"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="nu-email">Email</Label>
            <Input
              id="nu-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="jdoe@example.com"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="nu-role">Role</Label>
            <Select id="nu-role" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="viewer">viewer</option>
              <option value="admin">admin</option>
            </Select>
          </div>
          <div className="flex items-end pb-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={allTenants}
                onChange={(e) => setAllTenants(e.target.checked)}
                className="rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500"
              />
              <span className="text-sm text-zinc-300">All tenants</span>
            </label>
          </div>
        </div>

        {!allTenants && allTenantsList && allTenantsList.length > 0 && (
          <div className="space-y-1.5">
            <Label>Assign Tenants</Label>
            <div className="rounded-md border border-zinc-800 max-h-40 overflow-y-auto divide-y divide-zinc-800">
              {allTenantsList.map((t) => (
                <label
                  key={t.id}
                  className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-zinc-800/50 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedTenantIds.has(t.id)}
                    onChange={() => toggleTenant(t.id)}
                    className="rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500"
                  />
                  <span className="text-sm text-zinc-300">{t.name}</span>
                </label>
              ))}
            </div>
            {selectedTenantIds.size === 0 && (
              <p className="text-xs text-zinc-500">
                No tenants selected — user will see no devices.
              </p>
            )}
          </div>
        )}

        {!allTenants && (!allTenantsList || allTenantsList.length === 0) && (
          <p className="text-xs text-zinc-500">
            No tenants exist yet. Create tenants first, or enable "All tenants".
          </p>
        )}

        {formError && <p className="text-sm text-red-400">{formError}</p>}

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={createUser.isPending}>
            {createUser.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Create User
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}

// ── Edit User Dialog ──────────────────────────────────────

interface EditUserDialogProps {
  user: User | null;
  onClose: () => void;
}

function EditUserDialog({ user, onClose }: EditUserDialogProps) {
  const updateUser = useUpdateUser();
  const { data: assignedTenants, isLoading: tenantsLoading } = useUserTenants(user?.id);
  const { data: allTenantsList } = useTenants();
  const assignTenant = useAssignTenantToUser();
  const removeTenant = useRemoveTenantFromUser();

  const [role, setRole] = useState(user?.role ?? "viewer");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [allTenants, setAllTenants] = useState(user?.all_tenants ?? false);
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [selectedTenantId, setSelectedTenantId] = useState("");

  const userId = user?.id;

  // Sync state when user prop changes (dialog re-opens for different user)
  useEffect(() => {
    if (user) {
      setRole(user.role ?? "viewer");
      setDisplayName(user.display_name ?? "");
      setEmail(user.email ?? "");
      setAllTenants(user.all_tenants ?? false);
      setIsActive(user.is_active ?? true);
    }
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!userId) return;
    setSaveError(null);
    setSaveSuccess(false);
    try {
      await updateUser.mutateAsync({
        id: userId,
        data: {
          role,
          display_name: displayName.trim() || null,
          email: email.trim() || null,
          all_tenants: allTenants,
          is_active: isActive,
        },
      });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save");
    }
  }

  async function handleAddTenant() {
    if (!userId || !selectedTenantId) return;
    try {
      await assignTenant.mutateAsync({ userId, tenantId: selectedTenantId });
      setSelectedTenantId("");
    } catch {
      // silently ignore (may already be assigned)
    }
  }

  async function handleRemoveTenant(tenantId: string) {
    if (!userId) return;
    try {
      await removeTenant.mutateAsync({ userId, tenantId });
    } catch {
      // silently ignore
    }
  }

  const assignedIds = new Set((assignedTenants ?? []).map((t) => t.id));
  const availableTenants = (allTenantsList ?? []).filter((t) => !assignedIds.has(t.id));

  if (!user) return null;

  return (
    <Dialog open={!!user} onClose={onClose} title={`Edit User: ${user.username}`}>
      <div className="space-y-5">
        {/* Basic settings */}
        <form onSubmit={handleSave} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="eu-display">Display Name</Label>
              <Input
                id="eu-display"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="John Doe"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="eu-email">Email</Label>
              <Input
                id="eu-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="eu-role">Role</Label>
              <Select id="eu-role" value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="viewer">viewer</option>
                <option value="admin">admin</option>
              </Select>
            </div>
            <div className="space-y-2 pt-1">
              <label className="flex items-center gap-2 cursor-pointer mt-6">
                <input
                  type="checkbox"
                  checked={allTenants}
                  onChange={(e) => setAllTenants(e.target.checked)}
                  className="rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500"
                />
                <span className="text-sm text-zinc-300">All tenants</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                  className="rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500"
                />
                <span className="text-sm text-zinc-300">Active</span>
              </label>
            </div>
          </div>

          {saveError && <p className="text-sm text-red-400">{saveError}</p>}
          {saveSuccess && <p className="text-sm text-emerald-400">Saved.</p>}

          <Button type="submit" size="sm" disabled={updateUser.isPending}>
            {updateUser.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Save Changes
          </Button>
        </form>

        {/* Tenant assignments (shown only when not all_tenants) */}
        {!allTenants && (
          <div className="space-y-2 border-t border-zinc-800 pt-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Tenant Assignments
            </p>

            {tenantsLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />
            ) : (
              <div className="space-y-2">
                {(assignedTenants ?? []).length === 0 ? (
                  <p className="text-xs text-zinc-600">No tenants assigned — user sees nothing.</p>
                ) : (
                  <div className="rounded-md border border-zinc-800 divide-y divide-zinc-800">
                    {(assignedTenants ?? []).map((t) => (
                      <div key={t.id} className="flex items-center justify-between px-3 py-2">
                        <span className="text-sm text-zinc-300">{t.name}</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveTenant(t.id)}
                          disabled={removeTenant.isPending}
                          className="rounded p-0.5 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                          title="Remove tenant"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {availableTenants.length > 0 && (
                  <div className="flex items-center gap-2">
                    <Select
                      value={selectedTenantId}
                      onChange={(e) => setSelectedTenantId(e.target.value)}
                      className="flex-1"
                    >
                      <option value="">— Select tenant —</option>
                      {availableTenants.map((t) => (
                        <option key={t.id} value={t.id}>{t.name}</option>
                      ))}
                    </Select>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={handleAddTenant}
                      disabled={!selectedTenantId || assignTenant.isPending}
                    >
                      {assignTenant.isPending
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <Plus className="h-3.5 w-3.5" />}
                      Add
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </div>
    </Dialog>
  );
}

// ── Main Page ─────────────────────────────────────────────

export function UsersPage() {
  const tz = useTimezone();
  const { user: currentUser } = useAuth();
  const { data: users, isLoading } = useUsers();
  const deleteUser = useDeleteUser();

  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<User | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<User | null>(null);

  // Guard: admin only
  if (currentUser && currentUser.role !== "admin") {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3 text-zinc-500">
        <Shield className="h-10 w-10 text-zinc-700" />
        <p className="text-sm">You need admin privileges to manage users.</p>
      </div>
    );
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteUser.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      // silently ignore (backend will reject self-delete)
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
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Users className="h-5 w-5 text-zinc-400" />
          <h1 className="text-xl font-semibold text-zinc-100">Users</h1>
          {users && (
            <Badge variant="default" className="text-xs">{users.length}</Badge>
          )}
        </div>
        <Button onClick={() => setAddOpen(true)} className="gap-1.5">
          <Plus className="h-4 w-4" />
          Add User
        </Button>
      </div>

      {/* Users table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <UserCog className="h-4 w-4" />
            User Accounts
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!users || users.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-600">
              <Users className="h-8 w-8 mb-2 text-zinc-700" />
              <p className="text-sm">No users found.</p>
              <Button
                size="sm"
                variant="secondary"
                className="mt-3 gap-1.5"
                onClick={() => setAddOpen(true)}
              >
                <Plus className="h-4 w-4" />
                Add first user
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Username</TableHead>
                  <TableHead>Display Name</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Tenants</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-medium text-zinc-200 font-mono text-sm">
                      {u.username}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {u.display_name ?? <span className="text-zinc-600">—</span>}
                    </TableCell>
                    <TableCell>
                      <RoleBadge role={u.role} />
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {u.role === "admin" || u.all_tenants ? (
                        <span className="text-emerald-400 text-xs font-medium">All tenants</span>
                      ) : (
                        <span className="text-zinc-500 text-xs">
                          {u.tenant_count ?? 0} assigned
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_active ? "success" : "default"}>
                        {u.is_active ? "active" : "disabled"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm">
                      {formatDate(u.created_at, tz)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setEditTarget(u)}
                          className="rounded p-1 text-zinc-600 hover:text-brand-400 hover:bg-brand-500/10 transition-colors cursor-pointer"
                          title="Edit user"
                        >
                          <UserCog className="h-4 w-4" />
                        </button>
                        {u.id !== currentUser?.user_id && (
                          <button
                            onClick={() => setDeleteTarget(u)}
                            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                            title="Delete user"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Dialogs */}
      <AddUserDialog open={addOpen} onClose={() => setAddOpen(false)} />

      <EditUserDialog user={editTarget} onClose={() => setEditTarget(null)} />

      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete User"
      >
        <p className="text-sm text-zinc-400">
          Permanently delete user{" "}
          <span className="font-semibold text-zinc-200">{deleteTarget?.username}</span>?
          This action cannot be undone.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteUser.isPending}
          >
            {deleteUser.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
