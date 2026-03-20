import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Activity,
  Building2,
  Copy,
  Cpu,
  Database,
  Globe,
  KeyRound,
  LayoutList,
  Loader2,
  Network,
  Plus,
  Server,
  Settings,
  Shield,
  ShieldCheck,
  Tag,
  Trash2,
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
import { useTablePreferences, PAGE_SIZE_OPTIONS } from "@/hooks/useTablePreferences.ts";
import {
  useHealth,
  useSystemSettings,
  useUpdateSystemSettings,
  useTlsCertificate,
  useGenerateTlsCert,
  useDeployTlsCert,
  useUpdateMyTimezone,
  useUserApiKeys,
  useCreateUserApiKey,
  useDeleteUserApiKey,
} from "@/api/hooks.ts";
import { cn, formatDate, timeAgo } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

// Lazy-import existing page components to render inside tabs
import { DeviceTypesPage } from "@/pages/DeviceTypesPage.tsx";
import { CollectorsPage } from "@/pages/CollectorsPage.tsx";
import { CredentialsPage } from "@/pages/CredentialsPage.tsx";
import { SnmpOidsPage } from "@/pages/SnmpOidsPage.tsx";
import { UsersPage } from "@/pages/UsersPage.tsx";
import { TenantsPage } from "@/pages/TenantsPage.tsx";
import { LabelKeysPage } from "@/pages/LabelKeysPage.tsx";
import { RolesPage } from "@/pages/RolesPage.tsx";

const TABS = [
  { key: "profile", label: "Profile", icon: User },
  { key: "api-keys", label: "API Keys", icon: KeyRound },
  { key: "system", label: "System", icon: Settings },
  { key: "device-types", label: "Device Types", icon: Server },
  { key: "labels", label: "Labels", icon: Tag },
  { key: "collectors", label: "Collectors", icon: Cpu },
  { key: "credentials", label: "Credentials", icon: KeyRound },
  { key: "snmp-oids", label: "SNMP OIDs", icon: Network },
  { key: "data-retention", label: "Data Retention", icon: Database },
  { key: "network", label: "Network", icon: Globe },
  { key: "tls", label: "TLS / HTTPS", icon: Shield },
  { key: "roles", label: "Roles", icon: ShieldCheck },
  { key: "users", label: "Users", icon: Users },
  { key: "tenants", label: "Tenants", icon: Building2 },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function ProfileTab() {
  const { user, refresh } = useAuth();
  const updateTimezone = useUpdateMyTimezone();
  const { pageSize, scrollMode, updatePreferences, isUpdating: tablePrefUpdating } = useTablePreferences();
  const [tablePrefSaved, setTablePrefSaved] = useState(false);
  const [selectedTz, setSelectedTz] = useState(user?.timezone ?? "UTC");
  const [tzSaved, setTzSaved] = useState(false);

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

  const tzModified = selectedTz !== (user?.timezone ?? "UTC");

  async function handleSaveTimezone() {
    await updateTimezone.mutateAsync(selectedTz);
    await refresh();
    setTzSaved(true);
    setTimeout(() => setTzSaved(false), 2000);
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
    </div>
  );
}

function ApiKeysTab() {
  const tz = useTimezone();
  const { data: keys, isLoading } = useUserApiKeys();
  const createKey = useCreateUserApiKey();
  const deleteKey = useDeleteUserApiKey();

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newExpiry, setNewExpiry] = useState("");
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleCreate() {
    const result = await createKey.mutateAsync({
      name: newName.trim(),
      expires_at: newExpiry || undefined,
    });
    setRawKey(result.data.raw_key);
    setNewName("");
    setNewExpiry("");
  }

  function handleCloseCreate() {
    setCreateOpen(false);
    setRawKey(null);
    setNewName("");
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
            <Button size="sm" className="ml-auto gap-1.5" onClick={() => setCreateOpen(true)}>
              <Plus className="h-3.5 w-3.5" />
              Create API Key
            </Button>
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
                        <td className="py-2.5 text-right">
                          <Button size="sm" variant="ghost" onClick={() => setDeleteTarget(k.id)}>
                            <Trash2 className="h-3.5 w-3.5 text-red-400" />
                          </Button>
                        </td>
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
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="text-xs"
                  autoFocus
                />
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
                <Button onClick={handleCreate} disabled={createKey.isPending || !newName.trim()}>
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

function SystemTab() {
  const { data: health, isLoading: healthLoading } = useHealth();

  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-4 w-4" />
            System Health
          </CardTitle>
        </CardHeader>
        <CardContent>
          {healthLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            </div>
          ) : health ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Status</span>
                <Badge variant={health.status === "healthy" || health.status === "ok" ? "success" : "destructive"}>
                  {health.status}
                </Badge>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Version</span>
                <span className="font-mono text-xs text-zinc-300">{health.version}</span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Instance ID</span>
                <span className="font-mono text-xs text-zinc-300">{health.instance_id}</span>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
              <Activity className="mb-2 h-6 w-6 text-zinc-600" />
              <p className="text-sm">Unable to fetch system health</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function DataRetentionTab() {
  const { data: settings, isLoading } = useSystemSettings();
  const updateSettings = useUpdateSystemSettings();
  const [jobRetention, setJobRetention] = useState("");
  const [resultsRetention, setResultsRetention] = useState("");
  const [ifaceInterval, setIfaceInterval] = useState("300");
  const [ifaceMetaRefresh, setIfaceMetaRefresh] = useState("3600");
  const [ifaceRawRetention, setIfaceRawRetention] = useState("7");
  const [ifaceHourlyRetention, setIfaceHourlyRetention] = useState("90");
  const [ifaceDailyRetention, setIfaceDailyRetention] = useState("730");
  const [configRetention, setConfigRetention] = useState("90");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setJobRetention(settings.job_status_retention_days ?? "7");
      setResultsRetention(settings.check_results_retention_days ?? "90");
      setIfaceInterval(settings.interface_poll_interval_seconds ?? "300");
      setIfaceMetaRefresh(settings.interface_metadata_refresh_seconds ?? "3600");
      setIfaceRawRetention(settings.interface_raw_retention_days ?? "7");
      setIfaceHourlyRetention(settings.interface_hourly_retention_days ?? "90");
      setIfaceDailyRetention(settings.interface_daily_retention_days ?? "730");
      setConfigRetention(settings.config_retention_days ?? "90");
    }
  }, [settings]);

  const modified = settings && (
    jobRetention !== (settings.job_status_retention_days ?? "7") ||
    resultsRetention !== (settings.check_results_retention_days ?? "90") ||
    ifaceInterval !== (settings.interface_poll_interval_seconds ?? "300") ||
    ifaceMetaRefresh !== (settings.interface_metadata_refresh_seconds ?? "3600") ||
    ifaceRawRetention !== (settings.interface_raw_retention_days ?? "7") ||
    ifaceHourlyRetention !== (settings.interface_hourly_retention_days ?? "90") ||
    ifaceDailyRetention !== (settings.interface_daily_retention_days ?? "730") ||
    configRetention !== (settings.config_retention_days ?? "90")
  );

  async function handleSave() {
    await updateSettings.mutateAsync({
      settings: {
        job_status_retention_days: jobRetention,
        check_results_retention_days: resultsRetention,
        interface_poll_interval_seconds: ifaceInterval,
        interface_metadata_refresh_seconds: ifaceMetaRefresh,
        interface_raw_retention_days: ifaceRawRetention,
        interface_hourly_retention_days: ifaceHourlyRetention,
        interface_daily_retention_days: ifaceDailyRetention,
        config_retention_days: configRetention,
      },
    });
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
            <Database className="h-4 w-4" />
            Data Retention
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Job Status Retention (days)</label>
            <Input type="number" value={jobRetention} onChange={e => setJobRetention(e.target.value)} className="max-w-32" />
            <p className="text-xs text-zinc-600">How long to keep job execution status records.</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Check Results Retention (days)</label>
            <Input type="number" value={resultsRetention} onChange={e => setResultsRetention(e.target.value)} className="max-w-32" />
            <p className="text-xs text-zinc-600">How long to keep check results in ClickHouse.</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Default Interface Poll Interval</label>
            <Select value={ifaceInterval} onChange={(e) => setIfaceInterval(e.target.value)} className="max-w-48">
              <option value="60">1 minute</option>
              <option value="120">2 minutes</option>
              <option value="300">5 minutes (default)</option>
              <option value="600">10 minutes</option>
              <option value="900">15 minutes</option>
              <option value="1800">30 minutes</option>
            </Select>
            <p className="text-xs text-zinc-600">Default polling interval for interface monitoring. Can be overridden per device.</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Interface Metadata Refresh</label>
            <Select value={ifaceMetaRefresh} onChange={(e) => setIfaceMetaRefresh(e.target.value)} className="max-w-48">
              <option value="900">15 minutes</option>
              <option value="1800">30 minutes</option>
              <option value="3600">1 hour (default)</option>
              <option value="7200">2 hours</option>
              <option value="14400">4 hours</option>
              <option value="21600">6 hours</option>
              <option value="43200">12 hours</option>
              <option value="86400">24 hours</option>
            </Select>
            <p className="text-xs text-zinc-600">How often to refresh interface metadata (name, alias, speed) from devices.</p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            Interface Data Retention
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Raw Data</label>
            <Select value={ifaceRawRetention} onChange={(e) => setIfaceRawRetention(e.target.value)} className="max-w-48">
              <option value="3">3 days</option>
              <option value="7">7 days (default)</option>
              <option value="14">14 days</option>
              <option value="30">30 days</option>
              <option value="60">60 days</option>
              <option value="90">90 days</option>
            </Select>
            <p className="text-xs text-zinc-600">Full-resolution interface data (every poll interval).</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Hourly Rollup</label>
            <Select value={ifaceHourlyRetention} onChange={(e) => setIfaceHourlyRetention(e.target.value)} className="max-w-48">
              <option value="30">30 days</option>
              <option value="60">60 days</option>
              <option value="90">90 days (default)</option>
              <option value="180">180 days</option>
              <option value="365">1 year</option>
            </Select>
            <p className="text-xs text-zinc-600">Hourly aggregated data (avg, max, p95).</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Daily Rollup</label>
            <Select value={ifaceDailyRetention} onChange={(e) => setIfaceDailyRetention(e.target.value)} className="max-w-48">
              <option value="180">180 days</option>
              <option value="365">1 year</option>
              <option value="730">2 years (default)</option>
              <option value="1095">3 years</option>
              <option value="1825">5 years</option>
            </Select>
            <p className="text-xs text-zinc-600">Daily aggregated data for long-term trends.</p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            Config Data Retention
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm text-zinc-400">Config Change History</label>
            <Select value={configRetention} onChange={(e) => setConfigRetention(e.target.value)} className="max-w-48">
              <option value="30">30 days</option>
              <option value="60">60 days</option>
              <option value="90">90 days (default)</option>
              <option value="180">180 days</option>
              <option value="365">1 year</option>
              <option value="730">2 years</option>
            </Select>
            <p className="text-xs text-zinc-600">How long to keep configuration change history in ClickHouse.</p>
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
  const deployCert = useDeployTlsCert();
  const [cn, setCn] = useState("monctl.local");
  const [generateOpen, setGenerateOpen] = useState(false);

  if (isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-zinc-500" /></div>;
  }

  return (
    <div className="max-w-lg space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-4 w-4" />
            TLS / HTTPS
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {cert ? (
            <div className="space-y-3">
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
                <span className="text-sm text-zinc-300">{cert.valid_from ? new Date(cert.valid_from).toLocaleDateString() : "—"}</span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                <span className="text-sm text-zinc-400">Valid To</span>
                <span className="text-sm text-zinc-300">{cert.valid_to ? new Date(cert.valid_to).toLocaleDateString() : "—"}</span>
              </div>
              <div className="flex gap-2 pt-2">
                <Button size="sm" onClick={() => deployCert.mutateAsync()} disabled={deployCert.isPending}>
                  {deployCert.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Deploy to HAProxy
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setGenerateOpen(true)}>
                  Regenerate
                </Button>
              </div>
            </div>
          ) : (
            <div className="text-center py-8">
              <Shield className="h-8 w-8 text-zinc-600 mx-auto mb-2" />
              <p className="text-sm text-zinc-500 mb-4">No TLS certificate configured.</p>
              <Button size="sm" onClick={() => setGenerateOpen(true)}>Generate Self-Signed Certificate</Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={generateOpen} onClose={() => setGenerateOpen(false)} title="Generate Self-Signed Certificate">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tls-cn">Common Name (CN)</Label>
            <Input id="tls-cn" value={cn} onChange={e => setCn(e.target.value)} placeholder="monctl.local" />
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setGenerateOpen(false)}>Cancel</Button>
            <Button onClick={async () => { await generateCert.mutateAsync({ cn }); setGenerateOpen(false); }} disabled={generateCert.isPending}>
              {generateCert.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Generate
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
  const activeTab = (tab ?? "profile") as TabKey;

  function handleTabChange(key: TabKey) {
    navigate(key === "profile" ? "/settings" : `/settings/${key}`);
  }

  function renderTab() {
    switch (activeTab) {
      case "profile": return <ProfileTab />;
      case "api-keys": return <ApiKeysTab />;
      case "system": return <SystemTab />;
      case "device-types": return <DeviceTypesPage />;
      case "labels": return <LabelKeysPage />;
      case "collectors": return <CollectorsPage />;
      case "credentials": return <CredentialsPage />;
      case "snmp-oids": return <SnmpOidsPage />;
      case "data-retention": return <DataRetentionTab />;
      case "network": return <NetworkTab />;
      case "tls": return <TlsTab />;
      case "roles": return <RolesPage />;
      case "users": return <UsersPage />;
      case "tenants": return <TenantsPage />;
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
        {TABS.map((t) => {
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
