import { useEffect, useMemo, useState } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import {
  validateUsername,
  validatePassword,
  validateEmail,
} from "@/lib/validation.ts";
import {
  Key,
  Loader2,
  Plus,
  Shield,
  Trash2,
  UserCog,
  Users,
  X,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  useUsers,
  useCreateUser,
  useUpdateUser,
  useDeleteUser,
  useAdminResetUserPassword,
  useUserTenants,
  useAssignTenantToUser,
  useRemoveTenantFromUser,
  useTenants,
  useRoles,
} from "@/api/hooks.ts";
import type { User } from "@/types/api.ts";
import { useAuth } from "@/hooks/useAuth.tsx";
import { formatTime } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";

// ── Role badge helper ────────────────────────────────────

function RoleBadge({ role }: { role: string }) {
  return <Badge variant={role === "admin" ? "info" : "default"}>{role}</Badge>;
}

// ── Add User Dialog ───────────────────────────────────────

interface AddUserDialogProps {
  open: boolean;
  onClose: () => void;
}

function AddUserDialog({ open, onClose }: AddUserDialogProps) {
  const createUser = useCreateUser();
  const { data: allTenantsList } = useTenants();
  const { data: roles } = useRoles();
  const assignTenant = useAssignTenantToUser();

  const usernameField = useField("", validateUsername);
  const passwordField = useField("", validatePassword);
  const [displayName, setDisplayName] = useState("");
  const emailField = useField("", validateEmail);
  const [role, setRole] = useState("user");
  const [roleId, setRoleId] = useState("");
  const [allTenants, setAllTenants] = useState(false);
  const [selectedTenantIds, setSelectedTenantIds] = useState<Set<string>>(
    new Set(),
  );
  const [formError, setFormError] = useState<string | null>(null);

  function reset() {
    usernameField.reset();
    passwordField.reset();
    setDisplayName("");
    emailField.reset();
    setRole("user");
    setRoleId("");
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

    if (!validateAll(usernameField, passwordField, emailField)) return;

    try {
      const result = await createUser.mutateAsync({
        username: usernameField.value.trim(),
        password: passwordField.value,
        role,
        role_id: role !== "admin" && roleId ? roleId : undefined,
        display_name: displayName.trim() || undefined,
        email: emailField.value.trim() || undefined,
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
      setFormError(
        err instanceof Error ? err.message : "Failed to create user",
      );
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
              value={usernameField.value}
              onChange={usernameField.onChange}
              onBlur={usernameField.onBlur}
              placeholder="jdoe"
              autoComplete="off"
            />
            {usernameField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {usernameField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="nu-password">Password *</Label>
            <Input
              id="nu-password"
              type="password"
              value={passwordField.value}
              onChange={passwordField.onChange}
              onBlur={passwordField.onBlur}
              autoComplete="new-password"
            />
            {passwordField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {passwordField.error}
              </p>
            )}
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
              value={emailField.value}
              onChange={emailField.onChange}
              onBlur={emailField.onBlur}
              placeholder="jdoe@example.com"
            />
            {emailField.error && (
              <p className="text-xs text-red-400 mt-0.5">{emailField.error}</p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="nu-role">User Type</Label>
            <Select
              id="nu-role"
              value={role}
              onChange={(e) => {
                setRole(e.target.value);
                if (e.target.value === "admin") setRoleId("");
              }}
            >
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </Select>
          </div>
          {role !== "admin" && (
            <div className="space-y-1.5">
              <Label htmlFor="nu-role-id">Assigned Role</Label>
              <Select
                id="nu-role-id"
                value={roleId}
                onChange={(e) => setRoleId(e.target.value)}
              >
                <option value="">— No role —</option>
                {(roles ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </Select>
            </div>
          )}
        </div>

        {role !== "admin" && (
          <div className="flex items-center">
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
        )}

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
            {createUser.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
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
  const { data: assignedTenants, isLoading: tenantsLoading } = useUserTenants(
    user?.id,
  );
  const { data: allTenantsList } = useTenants();
  const { data: roles } = useRoles();
  const assignTenant = useAssignTenantToUser();
  const removeTenant = useRemoveTenantFromUser();

  const [role, setRole] = useState(user?.role ?? "user");
  const [roleId, setRoleId] = useState(user?.role_id ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const editEmailField = useField(user?.email ?? "", validateEmail);
  const [allTenants, setAllTenants] = useState(user?.all_tenants ?? false);
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [selectedTenantId, setSelectedTenantId] = useState("");

  const userId = user?.id;

  // Sync state when user prop changes (dialog re-opens for different user)
  useEffect(() => {
    if (user) {
      setRole(user.role ?? "user");
      setRoleId(user.role_id ?? "");
      setDisplayName(user.display_name ?? "");
      editEmailField.reset(user.email ?? "");
      setAllTenants(user.all_tenants ?? false);
      setIsActive(user.is_active ?? true);
    }
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!userId) return;
    setSaveError(null);
    setSaveSuccess(false);
    if (!validateAll(editEmailField)) return;
    try {
      await updateUser.mutateAsync({
        id: userId,
        data: {
          role,
          role_id: role !== "admin" ? roleId || null : null,
          display_name: displayName.trim() || null,
          email: editEmailField.value.trim() || null,
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
  const availableTenants = (allTenantsList ?? []).filter(
    (t) => !assignedIds.has(t.id),
  );

  if (!user) return null;

  return (
    <Dialog
      open={!!user}
      onClose={onClose}
      title={`Edit User: ${user.username}`}
    >
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
                value={editEmailField.value}
                onChange={editEmailField.onChange}
                onBlur={editEmailField.onBlur}
              />
              {editEmailField.error && (
                <p className="text-xs text-red-400 mt-0.5">
                  {editEmailField.error}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="eu-role">User Type</Label>
              <Select
                id="eu-role"
                value={role}
                onChange={(e) => {
                  setRole(e.target.value);
                  if (e.target.value === "admin") setRoleId("");
                }}
              >
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </Select>
            </div>
            {role !== "admin" ? (
              <div className="space-y-1.5">
                <Label htmlFor="eu-role-id">Assigned Role</Label>
                <Select
                  id="eu-role-id"
                  value={roleId}
                  onChange={(e) => setRoleId(e.target.value)}
                >
                  <option value="">— No role —</option>
                  {(roles ?? []).map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </Select>
              </div>
            ) : (
              <div className="flex items-end pb-1">
                <p className="text-xs text-zinc-500">Admins have full access</p>
              </div>
            )}
          </div>

          <div className="flex items-center gap-6">
            {role !== "admin" && (
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allTenants}
                  onChange={(e) => setAllTenants(e.target.checked)}
                  className="rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500"
                />
                <span className="text-sm text-zinc-300">All tenants</span>
              </label>
            )}
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

          {saveError && <p className="text-sm text-red-400">{saveError}</p>}
          {saveSuccess && <p className="text-sm text-emerald-400">Saved.</p>}

          <Button type="submit" size="sm" disabled={updateUser.isPending}>
            {updateUser.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
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
                  <p className="text-xs text-zinc-600">
                    No tenants assigned — user sees nothing.
                  </p>
                ) : (
                  <div className="rounded-md border border-zinc-800 divide-y divide-zinc-800">
                    {(assignedTenants ?? []).map((t) => (
                      <div
                        key={t.id}
                        className="flex items-center justify-between px-3 py-2"
                      >
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
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </Select>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={handleAddTenant}
                      disabled={!selectedTenantId || assignTenant.isPending}
                    >
                      {assignTenant.isPending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plus className="h-3.5 w-3.5" />
                      )}
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
  const { mode } = useTimeDisplayMode();
  const { compact } = useDisplayPreferences();
  const { user: currentUser } = useAuth();
  const { data: users, isLoading } = useUsers();
  const deleteUser = useDeleteUser();

  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<User | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<User | null>(null);
  const [passwordTarget, setPasswordTarget] = useState<User | null>(null);

  const columns = useMemo<FlexColumnDef<User>[]>(
    () => [
      {
        key: "username",
        label: "Username",
        defaultWidth: 180,
        cellClassName: "font-medium text-zinc-200 font-mono text-sm",
        cell: (u) => u.username,
      },
      {
        key: "display_name",
        label: "Display Name",
        defaultWidth: 200,
        cellClassName: "text-zinc-400 text-sm",
        cell: (u) => u.display_name ?? <span className="text-zinc-600">—</span>,
      },
      {
        key: "role",
        label: "Role",
        defaultWidth: 160,
        cell: (u) => (
          <div className="flex items-center gap-1.5">
            <RoleBadge role={u.role} />
            {u.role_name && (
              <span className="text-xs text-zinc-500">{u.role_name}</span>
            )}
          </div>
        ),
      },
      {
        key: "__tenants",
        label: "Tenants",
        pickerLabel: "Tenants",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-400 text-sm",
        cell: (u) =>
          u.role === "admin" || u.all_tenants ? (
            <span className="text-emerald-400 text-xs font-medium">
              All tenants
            </span>
          ) : (
            <span className="text-zinc-500 text-xs">
              {u.tenant_count ?? 0} assigned
            </span>
          ),
      },
      {
        key: "is_active",
        label: "Status",
        filterable: false,
        defaultWidth: 100,
        cell: (u) => (
          <Badge variant={u.is_active ? "success" : "default"}>
            {u.is_active ? "active" : "disabled"}
          </Badge>
        ),
      },
      {
        key: "created_at",
        label: "Created",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 text-sm",
        cell: (u) => formatTime(u.created_at, mode, tz),
      },
      {
        key: "__actions",
        label: "",
        pickerLabel: "Actions",
        sortable: false,
        filterable: false,
        defaultWidth: 80,
        cell: (u) => (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setEditTarget(u)}
              className="rounded p-1 text-zinc-600 hover:text-brand-400 hover:bg-brand-500/10 transition-colors cursor-pointer"
              title="Edit user"
            >
              <UserCog className="h-4 w-4" />
            </button>
            <button
              onClick={() => setPasswordTarget(u)}
              className="rounded p-1 text-zinc-600 hover:text-amber-400 hover:bg-amber-500/10 transition-colors cursor-pointer"
              title="Reset password"
            >
              <Key className="h-4 w-4" />
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
        ),
      },
    ],
    [currentUser?.user_id, mode, tz],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<User>("users", columns);

  // Client-side sort (no API sort param, data returns as-is).
  const [sortBy, setSortBy] = useState("username");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const handleSort = (col: string) => {
    if (col === sortBy) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(col);
      setSortDir("asc");
    }
  };
  const sortedUsers = useMemo(() => {
    if (!users) return [];
    const copy = [...users];
    const getter: Record<string, (u: User) => any> = {
      username: (u) => u.username,
      display_name: (u) => u.display_name ?? "",
      role: (u) => u.role,
      is_active: (u) => (u.is_active ? 1 : 0),
      created_at: (u) => (u.created_at ? new Date(u.created_at).getTime() : 0),
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
  }, [users, sortBy, sortDir]);

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
            <Badge variant="default" className="text-xs">
              {users.length}
            </Badge>
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
            <div
              className={
                compact
                  ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
                  : ""
              }
            >
              <FlexTable<User>
                orderedVisibleColumns={orderedVisibleColumns}
                configMap={configMap}
                onOrderChange={setOrder}
                onWidthChange={setWidth}
                rows={sortedUsers}
                rowKey={(u) => u.id}
                sortBy={sortBy}
                sortDir={sortDir}
                onSort={handleSort}
                filters={{}}
                onFilterChange={() => {}}
                emptyState="No users"
              />
            </div>
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
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.username}
          </span>
          ? This action cannot be undone.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteUser.isPending}
          >
            {deleteUser.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>

      <ResetPasswordDialog
        user={passwordTarget}
        onClose={() => setPasswordTarget(null)}
      />
    </div>
  );
}

// ── Reset Password Dialog ────────────────────────────────

function ResetPasswordDialog({
  user,
  onClose,
}: {
  user: User | null;
  onClose: () => void;
}) {
  const resetPassword = useAdminResetUserPassword();
  const passwordField = useField("", validatePassword);
  const [error, setError] = useState("");

  useEffect(() => {
    if (user) {
      passwordField.reset();
      setError("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  async function handleSubmit() {
    if (!user) return;
    if (!validateAll(passwordField)) return;
    setError("");
    try {
      await resetPassword.mutateAsync({
        id: user.id,
        new_password: passwordField.value,
      });
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to reset password");
    }
  }

  return (
    <Dialog open={!!user} onClose={onClose} title="Reset Password">
      <p className="text-sm text-zinc-400">
        Set a new password for{" "}
        <span className="font-semibold text-zinc-200">{user?.username}</span>.
        All active sessions for this user will be invalidated — they'll need to
        sign in again with the new password.
      </p>
      <div className="mt-4 space-y-1">
        <Label htmlFor="rp-password">New password</Label>
        <Input
          id="rp-password"
          type="password"
          value={passwordField.value}
          onChange={passwordField.onChange}
          onBlur={passwordField.onBlur}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          autoFocus
        />
        {passwordField.error && (
          <p className="text-xs text-red-400">{passwordField.error}</p>
        )}
      </div>
      {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
      <DialogFooter>
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleSubmit} disabled={resetPassword.isPending}>
          {resetPassword.isPending && (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          Reset
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
