import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName } from "@/lib/validation.ts";
import {
  Activity,
  AlertTriangle,
  Building2,
  ScrollText,
  Copy,
  Cpu,
  Database,
  Download,
  Globe,
  KeyRound,
  LayoutList,
  Loader2,
  Lock,
  Network,
  Play,
  Plus,
  RefreshCw,
  Shield,
  ShieldCheck,
  Trash2,
  Upload,
  User,
  Users,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { useAuth } from "@/hooks/useAuth.tsx";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { useTablePreferences, PAGE_SIZE_OPTIONS } from "@/hooks/useTablePreferences.ts";
import {
  useSystemSettings,
  useUpdateSystemSettings,
  useTriggerTemplateAutoApplyAll,
  useTlsCertificate,
  useGenerateTlsCert,
  useUploadTlsCert,
  useDeployTlsCert,
  useUpdateMyTimezone,
  useUpdateMyIdleTimeout,
  useUpdateInterfacePreferences,
  useChangeMyPassword,
  useUserApiKeys,
  useCreateUserApiKey,
  useDeleteUserApiKey,
} from "@/api/hooks.ts";
import { cn, formatDate, timeAgo } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

// Lazy-import existing page components to render inside tabs
import { CollectorsPage } from "@/pages/CollectorsPage.tsx";
import { SnmpOidsPage } from "@/pages/SnmpOidsPage.tsx";
import { UsersPage } from "@/pages/UsersPage.tsx";
import { TenantsPage } from "@/pages/TenantsPage.tsx";
import { RolesPage } from "@/pages/RolesPage.tsx";
import { AuditLogPage } from "@/pages/AuditLogPage.tsx";

const TABS = [
  { key: "profile", label: "Profile", icon: User, adminOnly: false },
  { key: "api-keys", label: "API Keys", icon: KeyRound, adminOnly: false, resource: "api_key" as const },
  { key: "collectors", label: "Collectors", icon: Cpu, adminOnly: true },
  { key: "snmp-oids", label: "SNMP OIDs", icon: Network, adminOnly: true },
  { key: "automations", label: "Automations", icon: RefreshCw, adminOnly: true },
  { key: "data-retention", label: "Data Retention", icon: Database, adminOnly: true },
  { key: "network", label: "Network", icon: Globe, adminOnly: true },
  { key: "tls", label: "TLS / HTTPS", icon: Shield, adminOnly: true },
  { key: "roles", label: "Roles", icon: ShieldCheck, adminOnly: true },
  { key: "users", label: "Users", icon: Users, adminOnly: true },
  { key: "tenants", label: "Tenants", icon: Building2, adminOnly: true },
  { key: "audit", label: "Audit Log", icon: ScrollText, adminOnly: true },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function ProfileTab() {
  const { user, refresh } = useAuth();
  const updateTimezone = useUpdateMyTimezone();
  const updateIdleTimeout = useUpdateMyIdleTimeout();
  const { pageSize, scrollMode, updatePreferences, isUpdating: tablePrefUpdating } = useTablePreferences();
  const [tablePrefSaved, setTablePrefSaved] = useState(false);
  const [selectedTz, setSelectedTz] = useState(user?.timezone ?? "UTC");
  const [tzSaved, setTzSaved] = useState(false);
  const [idleTimeout, setIdleTimeout] = useState<string>("default");
  const [idleSaved, setIdleSaved] = useState(false);

  const allTimezones = useMemo(() => {
    try {
      return Intl.supportedValuesOf("timeZone");
    } catch {
      return ["UTC", "Europe/Copenhagen", "Europe/London", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Asia/Tokyo"];
    }
  }, []);

  useEffect(() => {
    if (user?.timezone) setSelectedTz(user.timezone);
  }, [user?.timezone]);

  useEffect(() => {
    if (user) {
      setIdleTimeout(user.idle_timeout_minutes != null ? String(user.idle_timeout_minutes) : "default");
    }
  }, [user?.idle_timeout_minutes]);

  const tzModified = selectedTz !== (user?.timezone ?? "UTC");
  const idleModified = (() => {
    const currentValue = user?.idle_timeout_minutes != null ? String(user.idle_timeout_minutes) : "default";
    return idleTimeout !== currentValue;
  })();

  async function handleSaveTimezone() {
    await updateTimezone.mutateAsync(selectedTz);
    await refresh();
    setTzSaved(true);
    setTimeout(() => setTzSaved(false), 2000);
  }

  async function handleSaveIdleTimeout() {
    const value = idleTimeout === "default" ? null : Number(idleTimeout);
    await updateIdleTimeout.mutateAsync({ idle_timeout_minutes: value });
    await refresh();
    setIdleSaved(true);
    setTimeout(() => setIdleSaved(false), 2000);
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <User className="h-4 w-4" />
            Profile
          </CardTitle>
        </CardHeader>
        <CardContent>
          {user ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Username</span>
                <span className="text-sm font-medium text-zinc-100">{user.username}</span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">User ID</span>
                <span className="font-mono text-xs text-zinc-300">{user.user_id}</span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Role</span>
                <Badge variant="info">{user.role}</Badge>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Timezone</span>
                <div className="flex items-center gap-2">
                  <select
                    value={selectedTz}
                    onChange={(e) => setSelectedTz(e.target.value)}
                    className="rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-sm text-zinc-200 focus:outline-none focus:ring-1 focus:ring-brand-500"
                  >
                    {allTimezones.map((tz) => (
                      <option key={tz} value={tz}>
                        {tz.replace(/_/g, " ")}
                      </option>
                    ))}
                  </select>
                  {tzModified && (
                    <Button size="sm" onClick={handleSaveTimezone} disabled={updateTimezone.isPending}>
                      {updateTimezone.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
                      Save
                    </Button>
                  )}
                  {tzSaved && <span className="text-sm text-emerald-400">Saved!</span>}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-zinc-500">User info not available</p>
          )}
        </CardContent>
      </Card>

      <ChangePasswordCard />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Session
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
            <div>
              <span className="text-sm text-zinc-400">Idle Timeout</span>
              <p className="text-xs text-zinc-600 mt-0.5">
                Automatically log out after this period of inactivity.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={idleTimeout}
                onChange={(e) => setIdleTimeout(e.target.value)}
                className="rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-sm text-zinc-200 focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                <option value="default">System default</option>
                <option value="15">15 minutes</option>
                <option value="30">30 minutes</option>
                <option value="60">1 hour</option>
                <option value="120">2 hours</option>
                <option value="240">4 hours</option>
                <option value="480">8 hours</option>
                <option value="0">Never</option>
              </select>
              {idleModified && (
                <Button size="sm" onClick={handleSaveIdleTimeout} disabled={updateIdleTimeout.isPending}>
                  {updateIdleTimeout.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
                  Save
                </Button>
              )}
              {idleSaved && <span className="text-sm text-emerald-400">Saved!</span>}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LayoutList className="h-4 w-4" />
            Table Display
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
              <div>
                <span className="text-sm text-zinc-400">Display Mode</span>
                <p className="text-xs text-zinc-600 mt-0.5">
                  {scrollMode === "infinite"
                    ? "Loads more rows as you scroll down"
                    : "Fixed number of rows with page navigation"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Select
                  value={scrollMode}
                  onChange={async (e) => {
                    await updatePreferences({ table_scroll_mode: e.target.value as "paginated" | "infinite" });
                    setTablePrefSaved(true);
                    setTimeout(() => setTablePrefSaved(false), 2000);
                  }}
                  disabled={tablePrefUpdating}
                  className="w-40"
                >
                  <option value="paginated">Paginated</option>
                  <option value="infinite">Infinite Scroll</option>
                </Select>
              </div>
            </div>
            <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
              <div>
                <span className="text-sm text-zinc-400">Rows per page</span>
                <p className="text-xs text-zinc-600 mt-0.5">
                  {scrollMode === "infinite"
                    ? "Rows loaded per batch when scrolling"
                    : "Rows displayed per page"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Select
                  value={String(pageSize)}
                  onChange={async (e) => {
                    await updatePreferences({ table_page_size: Number(e.target.value) });
                    setTablePrefSaved(true);
                    setTimeout(() => setTablePrefSaved(false), 2000);
                  }}
                  disabled={tablePrefUpdating}
                  className="w-24"
                >
                  {PAGE_SIZE_OPTIONS.map((s) => (
                    <option key={s} value={String(s)}>{s}</option>
                  ))}
                </Select>
                {tablePrefSaved && <span className="text-sm text-emerald-400">Saved!</span>}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <InterfaceDefaultsCard />
    </div>
  );
}

function ChangePasswordCard() {
  const changePassword = useChangeMyPassword();
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const canSubmit = currentPw.length > 0 && newPw.length >= 6 && newPw === confirmPw;

  async function handleSubmit() {
    setError(null);
    if (newPw !== confirmPw) {
      setError("Passwords do not match");
      return;
    }
    try {
      await changePassword.mutateAsync({ current_password: currentPw, new_password: newPw });
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e: any) {
      setError(e?.message ?? "Failed to change password");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Lock className="h-4 w-4" />
          Change Password
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3 max-w-sm">
          <div className="space-y-1">
            <Label>Current Password</Label>
            <Input type="password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>New Password</Label>
            <Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="Min. 6 characters" />
          </div>
          <div className="space-y-1">
            <Label>Confirm New Password</Label>
            <Input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} />
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
          {success && <p className="text-sm text-emerald-400">Password changed successfully!</p>}
          <Button onClick={handleSubmit} disabled={!canSubmit || changePassword.isPending}>
            {changePassword.isPending && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
            Change Password
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function InterfaceDefaultsCard() {
  const { user } = useAuth();
  const updateIfacePrefs = useUpdateInterfacePreferences();
  const [saved, setSaved] = useState(false);

  const handleChange = (data: Parameters<typeof updateIfacePrefs.mutate>[0]) => {
    updateIfacePrefs.mutate(data, {
      onSuccess: () => { setSaved(true); setTimeout(() => setSaved(false), 2000); },
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Network className="h-4 w-4" />
          Interface Tab Defaults
          {saved && <span className="text-sm text-emerald-400 ml-2">Saved!</span>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-zinc-500 mb-3">Applied when you open the Interfaces tab on any device.</p>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-xs text-zinc-400">Default status filter</label>
            <Select
              value={user?.iface_status_filter ?? "all"}
              onChange={e => handleChange({ iface_status_filter: e.target.value as any })}
              className="w-full"
            >
              <option value="all">All interfaces</option>
              <option value="up">Up only</option>
              <option value="down">Down only</option>
              <option value="unmonitored">Unmonitored only</option>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-zinc-400">Default traffic unit</label>
            <Select
              value={user?.iface_traffic_unit ?? "auto"}
              onChange={e => handleChange({ iface_traffic_unit: e.target.value as any })}
              className="w-full"
            >
              <option value="auto">Auto</option>
              <option value="kbps">Kbps</option>
              <option value="mbps">Mbps</option>
              <option value="gbps">Gbps</option>
              <option value="pct">% utilization</option>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-zinc-400">Default chart metric</label>
            <Select
              value={user?.iface_chart_metric ?? "traffic"}
              onChange={e => handleChange({ iface_chart_metric: e.target.value as any })}
              className="w-full"
            >
              <option value="traffic">Traffic</option>
              <option value="errors">Errors</option>
              <option value="discards">Discards</option>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-zinc-400">Default time range</label>
            <Select
              value={user?.iface_time_range ?? "24h"}
              onChange={e => handleChange({ iface_time_range: e.target.value as any })}
              className="w-full"
            >
              <option value="1h">Last 1 hour</option>
              <option value="6h">Last 6 hours</option>
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
            </Select>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ApiKeysTab() {
  const tz = useTimezone();
  const { canCreate: canCreateKey, canDelete: canDeleteKey } = usePermissions();
  const { data: keys, isLoading } = useUserApiKeys();
  const createKey = useCreateUserApiKey();
  const deleteKey = useDeleteUserApiKey();

  const [createOpen, setCreateOpen] = useState(false);
  const apiKeyNameField = useField("", validateName);
  const [newExpiry, setNewExpiry] = useState("");
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleCreate() {
    if (!validateAll(apiKeyNameField)) return;
    const result = await createKey.mutateAsync({
      name: apiKeyNameField.value.trim(),
      expires_at: newExpiry || undefined,
    });
    setRawKey(result.data.raw_key);
    apiKeyNameField.reset();
    setNewExpiry("");
  }

  function handleCloseCreate() {
    setCreateOpen(false);
    setRawKey(null);
    apiKeyNameField.reset();
    setNewExpiry("");
    setCopied(false);
  }

  async function handleCopy() {
    if (rawKey) {
      await navigator.clipboard.writeText(rawKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    await deleteKey.mutateAsync(deleteTarget);
    setDeleteTarget(null);
  }

  const now = new Date();

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
            <KeyRound className="h-4 w-4" />
            API Keys
            <Badge variant="default" className="text-[10px] ml-1">{keys?.length ?? 0}/10</Badge>
            {canCreateKey("api_key") && (
              <Button size="sm" className="ml-auto gap-1.5" onClick={() => setCreateOpen(true)}>
                <Plus className="h-3.5 w-3.5" />
                Create API Key
              </Button>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-zinc-500 mb-4">
            API keys inherit your role permissions and tenant access. Use them for external integrations.
          </p>
          {!keys || keys.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
              <KeyRound className="mb-2 h-6 w-6 text-zinc-600" />
              <p className="text-sm">No API keys yet. Create one to integrate with external systems.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-left text-xs text-zinc-500">
                    <th className="pb-2 pr-4 font-medium">Name</th>
                    <th className="pb-2 pr-4 font-medium">Key Prefix</th>
                    <th className="pb-2 pr-4 font-medium">Expires</th>
                    <th className="pb-2 pr-4 font-medium">Created</th>
                    <th className="pb-2 pr-4 font-medium">Last Used</th>
                    <th className="pb-2 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/50">
                  {keys.map((k) => {
                    const expired = k.expires_at && new Date(k.expires_at) < now;
                    return (
                      <tr key={k.id} className="text-zinc-300">
                        <td className="py-2.5 pr-4 text-xs font-medium">{k.name}</td>
                        <td className="py-2.5 pr-4 text-xs font-mono text-zinc-400">{k.key_prefix}...</td>
                        <td className="py-2.5 pr-4 text-xs">
                          {k.expires_at ? (
                            expired ? (
                              <Badge variant="destructive" className="text-[10px]">Expired</Badge>
                            ) : (
                              <span className="text-zinc-400">{formatDate(k.expires_at, tz)}</span>
                            )
                          ) : (
                            <span className="text-zinc-600">Never</span>
                          )}
                        </td>
                        <td className="py-2.5 pr-4 text-xs text-zinc-500">{formatDate(k.created_at, tz)}</td>
                        <td className="py-2.5 pr-4 text-xs text-zinc-500">
                          {k.last_used_at ? timeAgo(k.last_used_at) : <span className="text-zinc-600">Never</span>}
                        </td>
                        {canDeleteKey("api_key") && (
                          <td className="py-2.5 text-right">
                            <Button size="sm" variant="ghost" onClick={() => setDeleteTarget(k.id)}>
                              <Trash2 className="h-3.5 w-3.5 text-red-400" />
                            </Button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Dialog */}
      <Dialog open={createOpen} onClose={handleCloseCreate} title="Create API Key">
        <div className="space-y-4">
          {rawKey ? (
            <>
              <div className="rounded-md border border-emerald-800 bg-emerald-950/30 p-4 space-y-3">
                <p className="text-sm font-medium text-emerald-400">API key created successfully</p>
                <p className="text-xs text-zinc-400">Copy this key now — it will not be shown again.</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 rounded bg-zinc-900 px-3 py-2 font-mono text-xs text-zinc-200 break-all select-all">
                    {rawKey}
                  </code>
                  <Button size="sm" variant="secondary" onClick={handleCopy} className="shrink-0 gap-1.5">
                    <Copy className="h-3.5 w-3.5" />
                    {copied ? "Copied" : "Copy"}
                  </Button>
                </div>
              </div>
              <div className="rounded-md bg-zinc-900 p-3">
                <p className="text-[10px] text-zinc-500 mb-1">Example usage:</p>
                <code className="text-xs text-zinc-400 font-mono break-all">
                  curl -H "Authorization: Bearer {rawKey.slice(0, 20)}..." https://your-central/v1/devices
                </code>
              </div>
              <DialogFooter>
                <Button onClick={handleCloseCreate}>Done</Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label>Name</Label>
                <Input
                  placeholder="e.g. Grafana integration"
                  value={apiKeyNameField.value}
                  onChange={apiKeyNameField.onChange}
                  onBlur={apiKeyNameField.onBlur}
                  className="text-xs"
                  autoFocus
                />
                {apiKeyNameField.error && <p className="text-xs text-red-400 mt-0.5">{apiKeyNameField.error}</p>}
              </div>
              <div className="space-y-1.5">
                <Label>Expires (optional)</Label>
                <Input
                  type="date"
                  value={newExpiry}
                  onChange={(e) => setNewExpiry(e.target.value)}
                  className="text-xs"
                />
                <p className="text-[10px] text-zinc-500">Leave empty for a key that never expires.</p>
              </div>
              <DialogFooter>
                <Button variant="secondary" onClick={handleCloseCreate}>Cancel</Button>
                <Button onClick={handleCreate} disabled={createKey.isPending || !apiKeyNameField.value.trim()}>
                  {createKey.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Create
                </Button>
              </DialogFooter>
            </>
          )}
        </div>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Revoke API Key">
        <p className="text-sm text-zinc-400">
          Are you sure you want to revoke this API key? Any integrations using it will stop working immediately.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteKey.isPending}>
            {deleteKey.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Revoke
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

function formatRetentionDays(days: number): string {
  if (days >= 730) return `${Math.round(days / 365)} years`;
  if (days >= 365) return "1 year";
  return `${days} days`;
}

function RetentionTriple({
  rawValue, rawOnChange, rawOptions, rawDefault,
  hourlyValue, hourlyOnChange, hourlyOptions, hourlyDefault,
  dailyValue, dailyOnChange, dailyOptions, dailyDefault,
}: {
  rawValue: string; rawOnChange: (v: string) => void; rawOptions: number[]; rawDefault: number;
  hourlyValue: string; hourlyOnChange: (v: string) => void; hourlyOptions: number[]; hourlyDefault: number;
  dailyValue: string; dailyOnChange: (v: string) => void; dailyOptions: number[]; dailyDefault: number;
}) {
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-0.5">
          <span className="text-xs text-zinc-600">Raw</span>
          <Select value={rawValue} onChange={(e) => rawOnChange(e.target.value)}>
            {rawOptions.map((o) => (
              <option key={o} value={String(o)}>{formatRetentionDays(o)}{o === rawDefault ? " (default)" : ""}</option>
            ))}
          </Select>
        </div>
        <div className="space-y-0.5">
          <span className="text-xs text-zinc-600">Hourly rollup</span>
          <Select value={hourlyValue} onChange={(e) => hourlyOnChange(e.target.value)}>
            {hourlyOptions.map((o) => (
              <option key={o} value={String(o)}>{formatRetentionDays(o)}{o === hourlyDefault ? " (default)" : ""}</option>
            ))}
          </Select>
        </div>
        <div className="space-y-0.5">
          <span className="text-xs text-zinc-600">Daily rollup</span>
          <Select value={dailyValue} onChange={(e) => dailyOnChange(e.target.value)}>
            {dailyOptions.map((o) => (
              <option key={o} value={String(o)}>{formatRetentionDays(o)}{o === dailyDefault ? " (default)" : ""}</option>
            ))}
          </Select>
        </div>
      </div>
      <p className="text-xs text-zinc-600">Full-resolution → hourly aggregated → daily aggregated for long-term trends.</p>
    </div>
  );
}

function AutomationsTab() {
  const { data: settings, isLoading } = useSystemSettings();
  const updateSettings = useUpdateSystemSettings();
  const runNow = useTriggerTemplateAutoApplyAll();
  const [enabled, setEnabled] = useState("false");
  const [intervalHours, setIntervalHours] = useState("24");
  const [scope, setScope] = useState("has_type");
  const [saved, setSaved] = useState(false);
  const [runResult, setRunResult] = useState<{ applied: number; total: number } | null>(null);

  useEffect(() => {
    if (settings) {
      setEnabled(settings.template_auto_apply_enabled ?? "false");
      setIntervalHours(settings.template_auto_apply_interval_hours ?? "24");
      setScope(settings.template_auto_apply_scope ?? "has_type");
    }
  }, [settings]);

  const modified = settings && (
    enabled !== (settings.template_auto_apply_enabled ?? "false") ||
    intervalHours !== (settings.template_auto_apply_interval_hours ?? "24") ||
    scope !== (settings.template_auto_apply_scope ?? "has_type")
  );

  async function handleSave() {
    await updateSettings.mutateAsync({
      settings: {
        template_auto_apply_enabled: enabled,
        template_auto_apply_interval_hours: intervalHours,
        template_auto_apply_scope: scope,
      },
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function handleRunNow() {
    const res = await runNow.mutateAsync();
    setRunResult(res.data);
    setTimeout(() => setRunResult(null), 5000);
  }

  const lastRun = settings?.template_auto_apply_last_run;

  if (isLoading) return <div className="flex h-32 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-zinc-500" /></div>;

  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm text-zinc-300 flex items-center gap-2">
            <RefreshCw className="h-4 w-4 text-brand-400" />
            Template Auto-Apply
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <p className="text-xs text-zinc-500">
            Automatically re-apply device type and category templates to matching devices on a schedule.
            Useful for keeping monitoring assignments in sync after template changes.
          </p>

          <div className="space-y-4">
            {/* Enable */}
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-sm text-zinc-300">Enabled</Label>
                <p className="text-xs text-zinc-500 mt-0.5">Run auto-apply on the configured schedule</p>
              </div>
              <Select value={enabled} onChange={e => setEnabled(e.target.value)} className="w-24 h-8 text-sm">
                <option value="true">Yes</option>
                <option value="false">No</option>
              </Select>
            </div>

            {/* Interval */}
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-sm text-zinc-300">Run every</Label>
                <p className="text-xs text-zinc-500 mt-0.5">How often to apply templates automatically</p>
              </div>
              <Select value={intervalHours} onChange={e => setIntervalHours(e.target.value)} className="w-32 h-8 text-sm">
                <option value="1">1 hour</option>
                <option value="2">2 hours</option>
                <option value="4">4 hours</option>
                <option value="6">6 hours</option>
                <option value="12">12 hours</option>
                <option value="24">24 hours</option>
                <option value="48">48 hours</option>
                <option value="168">1 week</option>
              </Select>
            </div>

            {/* Scope */}
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-sm text-zinc-300">Apply to</Label>
                <p className="text-xs text-zinc-500 mt-0.5">Which devices to include in each run</p>
              </div>
              <Select value={scope} onChange={e => setScope(e.target.value)} className="w-52 h-8 text-sm">
                <option value="has_type">Devices with device type</option>
                <option value="all">All enabled devices</option>
              </Select>
            </div>

            {/* Last run */}
            {lastRun && (
              <div className="flex items-center justify-between text-xs text-zinc-500">
                <span>Last run</span>
                <span className="text-zinc-400">{timeAgo(lastRun)}</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3 pt-1 border-t border-zinc-800">
            <Button
              size="sm"
              disabled={!modified || updateSettings.isPending}
              onClick={handleSave}
            >
              {updateSettings.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : null}
              Save
            </Button>
            {saved && <span className="text-xs text-emerald-400">Saved</span>}
            <div className="ml-auto flex items-center gap-2">
              {runResult && (
                <span className="text-xs text-emerald-400">
                  Applied to {runResult.applied} / {runResult.total} devices
                </span>
              )}
              <Button
                variant="outline"
                size="sm"
                disabled={runNow.isPending}
                onClick={handleRunNow}
                title="Run auto-apply now using current scope setting"
              >
                {runNow.isPending
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                  : <Play className="h-3.5 w-3.5 mr-1.5" />}
                Run Now
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function DataRetentionTab() {
  const { data: settings, isLoading } = useSystemSettings();
  const updateSettings = useUpdateSystemSettings();
  const [jobRetention, setJobRetention] = useState("");
  const [ifaceInterval, setIfaceInterval] = useState("300");
  const [ifaceMetaRefresh, setIfaceMetaRefresh] = useState("3600");
  const [ifaceRawRetention, setIfaceRawRetention] = useState("7");
  const [ifaceHourlyRetention, setIfaceHourlyRetention] = useState("90");
  const [ifaceDailyRetention, setIfaceDailyRetention] = useState("730");
  const [configRetention, setConfigRetention] = useState("90");
  const [perfRawRetention, setPerfRawRetention] = useState("7");
  const [perfHourlyRetention, setPerfHourlyRetention] = useState("90");
  const [perfDailyRetention, setPerfDailyRetention] = useState("730");
  const [availRawRetention, setAvailRawRetention] = useState("30");
  const [availHourlyRetention, setAvailHourlyRetention] = useState("365");
  const [availDailyRetention, setAvailDailyRetention] = useState("1825");
  const [idleTimeoutDefault, setIdleTimeoutDefault] = useState("60");
  const [logRetention, setLogRetention] = useState("7");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setJobRetention(settings.job_status_retention_days ?? "7");
      setIfaceInterval(settings.interface_poll_interval_seconds ?? "300");
      setIfaceMetaRefresh(settings.interface_metadata_refresh_seconds ?? "3600");
      setIfaceRawRetention(settings.interface_raw_retention_days ?? "7");
      setIfaceHourlyRetention(settings.interface_hourly_retention_days ?? "90");
      setIfaceDailyRetention(settings.interface_daily_retention_days ?? "730");
      setConfigRetention(settings.config_retention_days ?? "90");
      setPerfRawRetention(settings.perf_raw_retention_days ?? "7");
      setPerfHourlyRetention(settings.perf_hourly_retention_days ?? "90");
      setPerfDailyRetention(settings.perf_daily_retention_days ?? "730");
      setAvailRawRetention(settings.avail_raw_retention_days ?? "30");
      setAvailHourlyRetention(settings.avail_hourly_retention_days ?? "365");
      setAvailDailyRetention(settings.avail_daily_retention_days ?? "1825");
      setIdleTimeoutDefault(settings.session_idle_timeout_minutes ?? "60");
      setLogRetention(settings.log_retention_days ?? "7");
    }
  }, [settings]);

  const modified = settings && (
    jobRetention !== (settings.job_status_retention_days ?? "7") ||
    ifaceInterval !== (settings.interface_poll_interval_seconds ?? "300") ||
    ifaceMetaRefresh !== (settings.interface_metadata_refresh_seconds ?? "3600") ||
    ifaceRawRetention !== (settings.interface_raw_retention_days ?? "7") ||
    ifaceHourlyRetention !== (settings.interface_hourly_retention_days ?? "90") ||
    ifaceDailyRetention !== (settings.interface_daily_retention_days ?? "730") ||
    configRetention !== (settings.config_retention_days ?? "90") ||
    perfRawRetention !== (settings.perf_raw_retention_days ?? "7") ||
    perfHourlyRetention !== (settings.perf_hourly_retention_days ?? "90") ||
    perfDailyRetention !== (settings.perf_daily_retention_days ?? "730") ||
    availRawRetention !== (settings.avail_raw_retention_days ?? "30") ||
    availHourlyRetention !== (settings.avail_hourly_retention_days ?? "365") ||
    availDailyRetention !== (settings.avail_daily_retention_days ?? "1825") ||
    idleTimeoutDefault !== (settings.session_idle_timeout_minutes ?? "60") ||
    logRetention !== (settings.log_retention_days ?? "7")
  );

  async function handleSave() {
    await updateSettings.mutateAsync({
      settings: {
        job_status_retention_days: jobRetention,
        interface_poll_interval_seconds: ifaceInterval,
        interface_metadata_refresh_seconds: ifaceMetaRefresh,
        interface_raw_retention_days: ifaceRawRetention,
        interface_hourly_retention_days: ifaceHourlyRetention,
        interface_daily_retention_days: ifaceDailyRetention,
        config_retention_days: configRetention,
        perf_raw_retention_days: perfRawRetention,
        perf_hourly_retention_days: perfHourlyRetention,
        perf_daily_retention_days: perfDailyRetention,
        avail_raw_retention_days: availRawRetention,
        avail_hourly_retention_days: availHourlyRetention,
        avail_daily_retention_days: availDailyRetention,
        session_idle_timeout_minutes: idleTimeoutDefault,
        log_retention_days: logRetention,
      },
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  if (isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-zinc-500" /></div>;
  }

  return (
    <div className="max-w-2xl space-y-6">
      {/* Interface Monitoring */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            Interface Monitoring
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm text-zinc-400">Default Poll Interval</label>
              <Select value={ifaceInterval} onChange={(e) => setIfaceInterval(e.target.value)}>
                <option value="60">1 minute</option>
                <option value="120">2 minutes</option>
                <option value="300">5 minutes (default)</option>
                <option value="600">10 minutes</option>
                <option value="900">15 minutes</option>
                <option value="1800">30 minutes</option>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm text-zinc-400">Metadata Refresh</label>
              <Select value={ifaceMetaRefresh} onChange={(e) => setIfaceMetaRefresh(e.target.value)}>
                <option value="900">15 minutes</option>
                <option value="1800">30 minutes</option>
                <option value="3600">1 hour (default)</option>
                <option value="7200">2 hours</option>
                <option value="14400">4 hours</option>
                <option value="21600">6 hours</option>
                <option value="43200">12 hours</option>
                <option value="86400">24 hours</option>
              </Select>
            </div>
          </div>
          <RetentionTriple
            rawValue={ifaceRawRetention} rawOnChange={setIfaceRawRetention}
            rawOptions={[3, 7, 14, 30, 60, 90]} rawDefault={7}
            hourlyValue={ifaceHourlyRetention} hourlyOnChange={setIfaceHourlyRetention}
            hourlyOptions={[30, 60, 90, 180, 365]} hourlyDefault={90}
            dailyValue={ifaceDailyRetention} dailyOnChange={setIfaceDailyRetention}
            dailyOptions={[180, 365, 730, 1095, 1825]} dailyDefault={730}
          />
        </CardContent>
      </Card>

      {/* Performance Data Retention */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            Performance Data Retention
          </CardTitle>
        </CardHeader>
        <CardContent>
          <RetentionTriple
            rawValue={perfRawRetention} rawOnChange={setPerfRawRetention}
            rawOptions={[3, 7, 14, 30, 60, 90]} rawDefault={7}
            hourlyValue={perfHourlyRetention} hourlyOnChange={setPerfHourlyRetention}
            hourlyOptions={[30, 60, 90, 180, 365]} hourlyDefault={90}
            dailyValue={perfDailyRetention} dailyOnChange={setPerfDailyRetention}
            dailyOptions={[180, 365, 730, 1095, 1825]} dailyDefault={730}
          />
        </CardContent>
      </Card>

      {/* Availability & Latency Retention */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Availability & Latency Retention
          </CardTitle>
          <p className="text-xs text-zinc-600">Ping, port check, and HTTP check data. Daily rollups enable years of device health history.</p>
        </CardHeader>
        <CardContent>
          <RetentionTriple
            rawValue={availRawRetention} rawOnChange={setAvailRawRetention}
            rawOptions={[7, 14, 30, 60, 90]} rawDefault={30}
            hourlyValue={availHourlyRetention} hourlyOnChange={setAvailHourlyRetention}
            hourlyOptions={[90, 180, 365, 730]} hourlyDefault={365}
            dailyValue={availDailyRetention} dailyOnChange={setAvailDailyRetention}
            dailyOptions={[365, 730, 1095, 1825, 2555]} dailyDefault={1825}
          />
        </CardContent>
      </Card>

      {/* Other Retention */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            Other Retention
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm text-zinc-400">Config Data</label>
              <Select value={configRetention} onChange={(e) => setConfigRetention(e.target.value)}>
                <option value="30">30 days</option>
                <option value="60">60 days</option>
                <option value="90">90 days (default)</option>
                <option value="180">180 days</option>
                <option value="365">1 year</option>
                <option value="730">2 years</option>
              </Select>
              <p className="text-xs text-zinc-600">Configuration change history.</p>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm text-zinc-400">Job Status</label>
              <Input type="number" value={jobRetention} onChange={e => setJobRetention(e.target.value)} className="max-w-32" />
              <p className="text-xs text-zinc-600">Job execution status records.</p>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm text-zinc-400">Log Data</label>
              <Select value={logRetention} onChange={(e) => setLogRetention(e.target.value)}>
                <option value="1">1 day</option>
                <option value="3">3 days</option>
                <option value="7">7 days (default)</option>
                <option value="14">14 days</option>
                <option value="30">30 days</option>
                <option value="60">60 days</option>
                <option value="90">90 days</option>
              </Select>
              <p className="text-xs text-zinc-600">Docker container and application logs in ClickHouse.</p>
            </div>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Session Settings
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Default Session Idle Timeout</label>
            <Select value={idleTimeoutDefault} onChange={(e) => setIdleTimeoutDefault(e.target.value)} className="max-w-48">
              <option value="15">15 minutes</option>
              <option value="30">30 minutes</option>
              <option value="60">1 hour (default)</option>
              <option value="120">2 hours</option>
              <option value="240">4 hours</option>
              <option value="480">8 hours</option>
              <option value="0">Never</option>
            </Select>
            <p className="text-xs text-zinc-600">
              Users are automatically logged out after this period of inactivity.
              Individual users can override this in their profile.
            </p>
          </div>
        </CardContent>
      </Card>
      <div className="flex items-center gap-3 pt-2">
        <Button size="sm" onClick={handleSave} disabled={!modified || updateSettings.isPending}>
          {updateSettings.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Save
        </Button>
        {saved && <span className="text-sm text-emerald-400">Saved!</span>}
      </div>
    </div>
  );
}

function NetworkTab() {
  const { data: settings, isLoading } = useSystemSettings();
  const updateSettings = useUpdateSystemSettings();
  const [networkMode, setNetworkMode] = useState("");
  const [proxyUrl, setProxyUrl] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setNetworkMode(settings.pypi_network_mode ?? "direct");
      setProxyUrl(settings.pypi_proxy_url ?? "");
    }
  }, [settings]);

  const modified = settings && (
    networkMode !== (settings.pypi_network_mode ?? "direct") ||
    proxyUrl !== (settings.pypi_proxy_url ?? "")
  );

  async function handleSave() {
    const newSettings: Record<string, string> = {
      pypi_network_mode: networkMode,
    };
    if (networkMode === "proxy") {
      newSettings.pypi_proxy_url = proxyUrl;
    }
    await updateSettings.mutateAsync({ settings: newSettings });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  if (isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-zinc-500" /></div>;
  }

  return (
    <div className="max-w-lg space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="h-4 w-4" />
            PyPI Network Mode
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Network Mode</label>
            <Select value={networkMode} onChange={(e) => setNetworkMode(e.target.value)} className="max-w-48">
              <option value="direct">Direct</option>
              <option value="proxy">Proxy</option>
              <option value="offline">Offline</option>
            </Select>
            <div className="text-xs text-zinc-600 mt-1">
              {networkMode === "direct" && "Collectors and central server can access PyPI directly."}
              {networkMode === "proxy" && "All PyPI traffic is routed through a configured HTTP proxy."}
              {networkMode === "offline" && "No internet access. Modules must be uploaded manually as .whl files."}
            </div>
          </div>

          {networkMode === "proxy" && (
            <div className="space-y-1.5">
              <label className="text-sm text-zinc-400">Proxy URL</label>
              <Input
                value={proxyUrl}
                onChange={(e) => setProxyUrl(e.target.value)}
                placeholder="http://proxy.example.com:8080"
              />
              <p className="text-xs text-zinc-600">HTTP(S) proxy URL for PyPI access.</p>
            </div>
          )}

          <div className="flex items-center gap-3 pt-2">
            <Button size="sm" onClick={handleSave} disabled={!modified || updateSettings.isPending}>
              {updateSettings.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
            {saved && <span className="text-sm text-emerald-400">Saved!</span>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function TlsTab() {
  const { data: cert, isLoading } = useTlsCertificate();
  const generateCert = useGenerateTlsCert();
  const uploadCert = useUploadTlsCert();
  const deployCert = useDeployTlsCert();
  const [generateOpen, setGenerateOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [cn, setCn] = useState("monctl.local");
  const [sanIps, setSanIps] = useState("10.145.210.40,10.145.210.41,10.145.210.42,10.145.210.43,10.145.210.44");
  const [sanDns, setSanDns] = useState("monctl.local,localhost");
  const [uploadName, setUploadName] = useState("");
  const [uploadCertPem, setUploadCertPem] = useState("");
  const [uploadKeyPem, setUploadKeyPem] = useState("");
  const [deployMsg, setDeployMsg] = useState("");

  if (isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-zinc-500" /></div>;
  }

  const isExpiringSoon = cert?.valid_to && (new Date(cert.valid_to).getTime() - Date.now()) < 30 * 24 * 60 * 60 * 1000;
  const isExpired = cert?.valid_to && new Date(cert.valid_to).getTime() < Date.now();

  async function handleDeploy() {
    setDeployMsg("");
    try {
      const res = await deployCert.mutateAsync();
      setDeployMsg(res.data?.message || "Deployed successfully.");
    } catch {
      setDeployMsg("Deploy failed.");
    }
  }

  async function handleGenerate() {
    const ips = sanIps.split(",").map(s => s.trim()).filter(Boolean);
    const dns = sanDns.split(",").map(s => s.trim()).filter(Boolean);
    await generateCert.mutateAsync({ cn, san_ips: ips, san_dns: dns });
    setGenerateOpen(false);
  }

  async function handleUpload() {
    await uploadCert.mutateAsync({ name: uploadName, cert_pem: uploadCertPem, key_pem: uploadKeyPem });
    setUploadOpen(false);
    setUploadName("");
    setUploadCertPem("");
    setUploadKeyPem("");
  }

  function handleDownload() {
    window.open("/v1/settings/tls/download", "_blank");
  }

  return (
    <div className="max-w-2xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-4 w-4" />
            Active Certificate
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {cert ? (
            <div className="space-y-3">
              {(isExpired || isExpiringSoon) && (
                <div className={`flex items-center gap-2 rounded-md px-4 py-2.5 text-sm ${isExpired ? "bg-red-900/30 text-red-400" : "bg-yellow-900/30 text-yellow-400"}`}>
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  {isExpired ? "This certificate has expired." : "This certificate expires within 30 days."}
                </div>
              )}
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Subject CN</span>
                <span className="text-sm font-medium text-zinc-100">{cert.subject_cn}</span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Type</span>
                <Badge variant={cert.is_self_signed ? "default" : "success"}>
                  {cert.is_self_signed ? "Self-signed" : "CA-signed"}
                </Badge>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Valid From</span>
                <span className="text-sm text-zinc-300">{cert.valid_from ? new Date(cert.valid_from).toLocaleDateString() : "\u2014"}</span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Valid To</span>
                <span className="text-sm text-zinc-300">{cert.valid_to ? new Date(cert.valid_to).toLocaleDateString() : "\u2014"}</span>
              </div>
              {cert.san_list?.length > 0 && (
                <div className="rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400 block mb-1.5">Subject Alternative Names</span>
                  <div className="flex flex-wrap gap-1.5">
                    {cert.san_list.map((san, i) => (
                      <Badge key={i} variant="default" className="text-xs font-mono">{san}</Badge>
                    ))}
                  </div>
                </div>
              )}
              {cert.fingerprint && (
                <div className="rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400 block mb-1">SHA-256 Fingerprint</span>
                  <span className="text-xs font-mono text-zinc-300 break-all">{cert.fingerprint}</span>
                </div>
              )}

              <div className="flex flex-wrap gap-2 pt-2">
                <Button size="sm" onClick={handleDeploy} disabled={deployCert.isPending}>
                  {deployCert.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Deploy to HAProxy
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setGenerateOpen(true)}>
                  Regenerate
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setUploadOpen(true)}>
                  <Upload className="h-3.5 w-3.5" />
                  Upload Certificate
                </Button>
                <Button size="sm" variant="ghost" onClick={handleDownload}>
                  <Download className="h-3.5 w-3.5" />
                  Download PEM
                </Button>
              </div>
              {deployMsg && (
                <p className="text-sm text-zinc-400 pt-1">{deployMsg}</p>
              )}
            </div>
          ) : (
            <div className="text-center py-8">
              <Shield className="h-8 w-8 text-zinc-600 mx-auto mb-2" />
              <p className="text-sm text-zinc-500 mb-4">No TLS certificate configured.</p>
              <div className="flex justify-center gap-2">
                <Button size="sm" onClick={() => setGenerateOpen(true)}>Generate Self-Signed Certificate</Button>
                <Button size="sm" variant="secondary" onClick={() => setUploadOpen(true)}>
                  <Upload className="h-3.5 w-3.5" />
                  Upload Certificate
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Generate self-signed dialog */}
      <Dialog open={generateOpen} onClose={() => setGenerateOpen(false)} title="Generate Self-Signed Certificate">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tls-cn">Common Name (CN)</Label>
            <Input id="tls-cn" value={cn} onChange={e => setCn(e.target.value)} placeholder="monctl.local" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tls-san-ips">IP SANs (comma-separated)</Label>
            <Input id="tls-san-ips" value={sanIps} onChange={e => setSanIps(e.target.value)} placeholder="10.145.210.40,10.145.210.41,..." />
            <p className="text-xs text-zinc-500">IP addresses to include as Subject Alternative Names.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tls-san-dns">DNS SANs (comma-separated)</Label>
            <Input id="tls-san-dns" value={sanDns} onChange={e => setSanDns(e.target.value)} placeholder="monctl.local,localhost" />
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setGenerateOpen(false)}>Cancel</Button>
            <Button onClick={handleGenerate} disabled={generateCert.isPending}>
              {generateCert.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Generate
            </Button>
          </DialogFooter>
        </div>
      </Dialog>

      {/* Upload certificate dialog */}
      <Dialog open={uploadOpen} onClose={() => setUploadOpen(false)} title="Upload Certificate">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="upload-name">Certificate Name</Label>
            <Input id="upload-name" value={uploadName} onChange={e => setUploadName(e.target.value)} placeholder="my-ca-cert" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="upload-cert">Certificate PEM</Label>
            <textarea
              id="upload-cert"
              value={uploadCertPem}
              onChange={e => setUploadCertPem(e.target.value)}
              placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
              rows={6}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm font-mono text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            />
            <p className="text-xs text-zinc-500">Paste the full certificate chain (server cert + intermediates).</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="upload-key">Private Key PEM</Label>
            <textarea
              id="upload-key"
              value={uploadKeyPem}
              onChange={e => setUploadKeyPem(e.target.value)}
              placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
              rows={6}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm font-mono text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            />
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setUploadOpen(false)}>Cancel</Button>
            <Button onClick={handleUpload} disabled={uploadCert.isPending || !uploadName || !uploadCertPem || !uploadKeyPem}>
              {uploadCert.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Upload
            </Button>
          </DialogFooter>
        </div>
      </Dialog>
    </div>
  );
}

export function SettingsPage() {
  const { tab } = useParams<{ tab?: string }>();
  const navigate = useNavigate();
  const { isAdmin, canView } = usePermissions();
  const visibleTabs = TABS.filter((t) => {
    if (t.adminOnly) return isAdmin;
    if ("resource" in t && t.resource) return canView(t.resource);
    return true;
  });
  const activeTab = (tab ?? "profile") as TabKey;

  function handleTabChange(key: TabKey) {
    navigate(key === "profile" ? "/settings" : `/settings/${key}`);
  }

  function renderTab() {
    switch (activeTab) {
      case "profile": return <ProfileTab />;
      case "api-keys": return <ApiKeysTab />;
      case "collectors": return <CollectorsPage />;
      case "snmp-oids": return <SnmpOidsPage />;
      case "automations": return <AutomationsTab />;
      case "data-retention": return <DataRetentionTab />;
      case "network": return <NetworkTab />;
      case "tls": return <TlsTab />;
      case "roles": return <RolesPage />;
      case "users": return <UsersPage />;
      case "tenants": return <TenantsPage />;
      case "audit": return <AuditLogPage />;
      default: return <ProfileTab />;
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Settings</h1>
        <p className="text-sm text-zinc-500">
          System configuration and administration.
        </p>
      </div>

      {/* Tab navigation */}
      <div className="flex gap-1 border-b border-zinc-800 pb-0 overflow-x-auto">
        {visibleTabs.map((t) => {
          const isActive = activeTab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => handleTabChange(t.key)}
              className={cn(
                "flex items-center gap-1.5 whitespace-nowrap px-3 py-2 text-sm font-medium border-b-2 transition-colors cursor-pointer",
                isActive
                  ? "border-brand-500 text-brand-400"
                  : "border-transparent text-zinc-500 hover:text-zinc-300 hover:border-zinc-600",
              )}
            >
              <t.icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div>{renderTab()}</div>
    </div>
  );
}
