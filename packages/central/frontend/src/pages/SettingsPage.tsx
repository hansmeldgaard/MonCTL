import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Activity,
  Building2,
  Cpu,
  Database,
  KeyRound,
  Loader2,
  Network,
  Server,
  Settings,
  Shield,
  User,
  Users,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { useAuth } from "@/hooks/useAuth.tsx";
import {
  useHealth,
  useSystemSettings,
  useUpdateSystemSettings,
  useTlsCertificate,
  useGenerateTlsCert,
  useDeployTlsCert,
  useUpdateMyTimezone,
} from "@/api/hooks.ts";
import { cn } from "@/lib/utils.ts";

// Lazy-import existing page components to render inside tabs
import { DeviceTypesPage } from "@/pages/DeviceTypesPage.tsx";
import { CollectorsPage } from "@/pages/CollectorsPage.tsx";
import { CredentialsPage } from "@/pages/CredentialsPage.tsx";
import { SnmpOidsPage } from "@/pages/SnmpOidsPage.tsx";
import { UsersPage } from "@/pages/UsersPage.tsx";
import { TenantsPage } from "@/pages/TenantsPage.tsx";

const TABS = [
  { key: "profile", label: "Profile", icon: User },
  { key: "system", label: "System", icon: Settings },
  { key: "device-types", label: "Device Types", icon: Server },
  { key: "collectors", label: "Collectors", icon: Cpu },
  { key: "credentials", label: "Credentials", icon: KeyRound },
  { key: "snmp-oids", label: "SNMP OIDs", icon: Network },
  { key: "data-retention", label: "Data Retention", icon: Database },
  { key: "tls", label: "TLS / HTTPS", icon: Shield },
  { key: "users", label: "Users", icon: Users },
  { key: "tenants", label: "Tenants", icon: Building2 },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function ProfileTab() {
  const { user, refresh } = useAuth();
  const updateTimezone = useUpdateMyTimezone();
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
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setJobRetention(settings.job_status_retention_days ?? "7");
      setResultsRetention(settings.check_results_retention_days ?? "90");
    }
  }, [settings]);

  const modified = settings && (
    jobRetention !== (settings.job_status_retention_days ?? "7") ||
    resultsRetention !== (settings.check_results_retention_days ?? "90")
  );

  async function handleSave() {
    await updateSettings.mutateAsync({
      settings: {
        job_status_retention_days: jobRetention,
        check_results_retention_days: resultsRetention,
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
      case "system": return <SystemTab />;
      case "device-types": return <DeviceTypesPage />;
      case "collectors": return <CollectorsPage />;
      case "credentials": return <CredentialsPage />;
      case "snmp-oids": return <SnmpOidsPage />;
      case "data-retention": return <DataRetentionTab />;
      case "tls": return <TlsTab />;
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
