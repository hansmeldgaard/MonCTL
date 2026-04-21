import { lazy, Suspense, useMemo, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart2,
  Bell,
  Clock,
  Database,
  Gauge,
  Layout,
  ListChecks,
  Loader2,
  Monitor,
  Network,
  Settings2,
  Wrench,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  Tabs,
  TabsList,
  TabTrigger,
  TabsContent,
} from "@/components/ui/tabs.tsx";
import { DeviceIcon, categoryIconUrl } from "@/components/DeviceIcon.tsx";
import {
  useAutoApplyTemplates,
  useDevice,
  useDeviceCategories,
  useDeviceResults,
  useResolveTemplates,
} from "@/api/hooks.ts";
import type {
  Device as DeviceModel,
  ResolvedTemplateResult,
} from "@/types/api.ts";
import { formatUptime } from "@/lib/utils.ts";

// Each tab is its own chunk. Inactive tabs never mount (see TabsContent in
// components/ui/tabs.tsx), so only the current tab triggers a chunk load.
const _named =
  <T extends string>(name: T) =>
  async (mod: Record<string, unknown>) => ({
    default: mod[name] as React.ComponentType<{ deviceId: string }>,
  });

const OverviewTab = lazy(() =>
  import("./devices/tabs/OverviewTab.tsx").then(_named("OverviewTab")),
);
const PerformanceTab = lazy(() =>
  import("./devices/tabs/PerformanceTab.tsx").then(_named("PerformanceTab")),
);
const ConfigurationTab = lazy(() =>
  import("./devices/tabs/ConfigurationTab.tsx").then(
    _named("ConfigurationTab"),
  ),
);
const RetentionTab = lazy(() =>
  import("./devices/tabs/RetentionTab.tsx").then(_named("RetentionTab")),
);
const InterfacesTab = lazy(() =>
  import("./devices/tabs/InterfacesTab.tsx").then(_named("InterfacesTab")),
);
const AssignmentsTab = lazy(() =>
  import("./devices/tabs/AssignmentsTab.tsx").then(_named("AssignmentsTab")),
);
const SettingsTab = lazy(() =>
  import("./devices/tabs/SettingsTab.tsx").then(_named("SettingsTab")),
);
const ChecksTab = lazy(() =>
  import("./devices/tabs/ChecksTab.tsx").then(_named("ChecksTab")),
);
const AlertsTab = lazy(() =>
  import("./devices/tabs/AlertsTab.tsx").then(_named("AlertsTab")),
);
const IncidentsTab = lazy(() =>
  import("./devices/tabs/IncidentsTab.tsx").then(_named("IncidentsTab")),
);
const ThresholdsTab = lazy(() =>
  import("./devices/tabs/ThresholdsTab.tsx").then(_named("ThresholdsTab")),
);

const VALID_TABS = [
  "overview",
  "interfaces",
  "performance",
  "configuration",
  "assignments",
  "alerts",
  "incidents",
  "thresholds",
  "retention",
  "settings",
  "checks",
] as const;
type TabKey = (typeof VALID_TABS)[number];
const DEFAULT_TAB: TabKey = "overview";

function DuplicateBanner({ device }: { device: DeviceModel | undefined }) {
  const meta = (device?.metadata ?? {}) as Record<string, unknown>;
  const rawDupOf = meta.duplicate_of;
  const dupIds = Array.isArray(rawDupOf)
    ? rawDupOf.filter((x): x is string => typeof x === "string")
    : [];
  const { data: firstDup } = useDevice(dupIds[0]);
  if (dupIds.length === 0) return null;
  const basis = meta.serial
    ? `hardware serial ${String(meta.serial)}`
    : "sysName + sysObjectID";
  return (
    <div className="flex items-start gap-2 rounded border border-amber-600/40 bg-amber-950/30 p-3 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
      <div className="flex-1 space-y-1">
        <p className="text-amber-300">
          Possible duplicate device —{" "}
          {dupIds.length === 1
            ? "matches"
            : `matches ${dupIds.length} other devices on`}{" "}
          {basis}.
        </p>
        <p className="text-xs text-amber-200">
          {firstDup ? (
            <Link to={`/devices/${dupIds[0]}`} className="underline">
              {firstDup.name} ({firstDup.address})
            </Link>
          ) : (
            <Link to={`/devices/${dupIds[0]}`} className="underline font-mono">
              {dupIds[0]}
            </Link>
          )}
          {dupIds.length > 1 && (
            <span className="text-zinc-400"> +{dupIds.length - 1} more</span>
          )}
        </p>
      </div>
    </div>
  );
}

export function DeviceDetailPage() {
  const { id, tab } = useParams<{ id: string; tab?: string }>();
  const navigate = useNavigate();
  const { data: deviceResults, isLoading: resultsLoading } =
    useDeviceResults(id);
  const { data: device, isLoading: deviceLoading } = useDevice(id);
  const { data: allCategories } = useDeviceCategories();
  const activeTab: TabKey = (VALID_TABS as readonly string[]).includes(
    tab ?? "",
  )
    ? (tab as TabKey)
    : DEFAULT_TAB;
  const handleTabChange = (next: string) => {
    navigate(`/devices/${id}/${next}`, { replace: false });
  };

  const resolveTemplates = useResolveTemplates();
  const autoApplyTemplates = useAutoApplyTemplates();
  const [autoAssignPreview, setAutoAssignPreview] =
    useState<ResolvedTemplateResult | null>(null);

  const uptimeSeconds = useMemo(() => {
    if (!deviceResults?.checks) return null;
    for (const c of deviceResults.checks) {
      const names: string[] | undefined = c.metric_names;
      const values: number[] | undefined = c.metric_values;
      if (!names || !values) continue;
      const idx = names.indexOf("uptime_seconds");
      if (idx >= 0 && values[idx] != null) return values[idx];
    }
    return null;
  }, [deviceResults]);

  const isLoading = deviceLoading || (resultsLoading && !device);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!device && !deviceResults) {
    return (
      <div className="space-y-4">
        <Link to="/devices">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4" />
            Back to Devices
          </Button>
        </Link>
        <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
          <Monitor className="mb-2 h-8 w-8 text-zinc-600" />
          <p className="text-sm">Device not found</p>
        </div>
      </div>
    );
  }

  const deviceName = device?.name ?? deviceResults?.device_name ?? "Unknown";
  const deviceAddress = device?.address ?? deviceResults?.device_address ?? "";
  const deviceCategory =
    device?.device_category ?? deviceResults?.device_category ?? "";
  const dc = (allCategories ?? []).find((c) => c.name === deviceCategory);
  const deviceId = id!;
  const upStatus = deviceResults?.up;

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Link to="/devices">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4" />
            Back to Devices
          </Button>
        </Link>
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold text-zinc-100">{deviceName}</h2>
          <Badge
            variant={
              upStatus === true
                ? "success"
                : upStatus === false
                  ? "destructive"
                  : "default"
            }
          >
            {upStatus === true ? "UP" : upStatus === false ? "DOWN" : "UNKNOWN"}
          </Badge>
          {uptimeSeconds != null && (
            <span className="inline-flex items-center gap-1 text-sm text-zinc-400">
              <Clock className="h-3.5 w-3.5" />
              {formatUptime(uptimeSeconds)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-sm text-zinc-500">
          <span className="font-mono">{deviceAddress}</span>
          {deviceCategory && (
            <span className="inline-flex items-center gap-1">
              <DeviceIcon
                icon={dc?.icon}
                customIconUrl={
                  dc?.has_custom_icon ? categoryIconUrl(dc.id) : null
                }
                className="h-3.5 w-3.5 text-zinc-400"
              />
              <Badge variant="info">{deviceCategory}</Badge>
            </span>
          )}
          {device?.device_type_name && (
            <span className="text-xs text-zinc-500">
              type:{" "}
              <span className="text-zinc-300">{device.device_type_name}</span>
              {device.device_type_vendor && (
                <span className="text-zinc-500 ml-1">
                  ({device.device_type_vendor})
                </span>
              )}
            </span>
          )}
          {device?.tenant_name && (
            <span className="text-xs text-zinc-500">
              tenant:{" "}
              <span className="text-zinc-300">{device.tenant_name}</span>
            </span>
          )}
          {device?.collector_group_name && (
            <span className="text-xs text-zinc-500">
              collector group:{" "}
              <span className="text-zinc-300">
                {device.collector_group_name}
              </span>
            </span>
          )}
          <Button
            variant="secondary"
            size="sm"
            className="ml-auto gap-1.5"
            disabled={resolveTemplates.isPending}
            onClick={async () => {
              const res = await resolveTemplates.mutateAsync([deviceId]);
              const result = res.data?.[0];
              if (result && result.source_templates.length > 0) {
                setAutoAssignPreview(result);
              } else {
                setAutoAssignPreview(null);
                alert(
                  "No templates are linked to this device's category or type.",
                );
              }
            }}
          >
            {resolveTemplates.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <ListChecks className="h-3.5 w-3.5" />
            )}
            Auto-Assign
          </Button>
        </div>
      </div>

      <DuplicateBanner device={device} />

      <Dialog
        open={!!autoAssignPreview}
        onClose={() => setAutoAssignPreview(null)}
        title="Auto-Assign Templates"
      >
        {autoAssignPreview && (
          <div className="space-y-4">
            <p className="text-sm text-zinc-400">
              The following templates will be applied based on device category
              and type hierarchy:
            </p>
            <div className="space-y-1.5">
              {autoAssignPreview.source_templates.map((t, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 rounded border border-zinc-800 bg-zinc-800/40 px-3 py-2 text-sm"
                >
                  <span className="flex-1 text-zinc-200">
                    {t.template_name}
                  </span>
                  <Badge
                    variant={t.level === "device_type" ? "info" : "default"}
                  >
                    {t.level === "device_type" ? "Type" : "Category"}
                  </Badge>
                  <span className="text-xs text-zinc-500 tabular-nums">
                    step {t.step}
                  </span>
                </div>
              ))}
            </div>
            {autoAssignPreview.resolved_config.monitoring && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-zinc-400">Monitoring</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(
                    autoAssignPreview.resolved_config.monitoring,
                  ).map(([role, check]) =>
                    check ? (
                      <Badge key={role} variant="info">
                        {role}: {check.app_name} ({check.interval_seconds}s)
                      </Badge>
                    ) : null,
                  )}
                </div>
              </div>
            )}
            {autoAssignPreview.resolved_config.apps &&
              autoAssignPreview.resolved_config.apps.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-zinc-400">Apps</p>
                  <div className="flex flex-wrap gap-1.5">
                    {autoAssignPreview.resolved_config.apps.map((a, i) => (
                      <Badge key={i} variant="default">
                        {a.app_name} ({a.schedule_value}s)
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            <DialogFooter>
              <Button
                variant="secondary"
                onClick={() => setAutoAssignPreview(null)}
              >
                Cancel
              </Button>
              <Button
                disabled={autoApplyTemplates.isPending}
                onClick={async () => {
                  await autoApplyTemplates.mutateAsync([deviceId]);
                  setAutoAssignPreview(null);
                }}
              >
                {autoApplyTemplates.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                Apply
              </Button>
            </DialogFooter>
          </div>
        )}
      </Dialog>

      <Tabs value={activeTab} onChange={handleTabChange}>
        <TabsList>
          <TabTrigger value="overview">
            <span className="flex items-center gap-1.5">
              <Layout className="h-3.5 w-3.5" />
              Overview
            </span>
          </TabTrigger>
          <TabTrigger value="interfaces">
            <span className="flex items-center gap-1.5">
              <Network className="h-3.5 w-3.5" />
              Interfaces
            </span>
          </TabTrigger>
          <TabTrigger value="performance">
            <span className="flex items-center gap-1.5">
              <BarChart2 className="h-3.5 w-3.5" />
              Performance
            </span>
          </TabTrigger>
          <TabTrigger value="configuration">
            <span className="flex items-center gap-1.5">
              <Wrench className="h-3.5 w-3.5" />
              Configuration
            </span>
          </TabTrigger>
          <TabTrigger value="assignments">
            <span className="flex items-center gap-1.5">
              <ListChecks className="h-3.5 w-3.5" />
              Assignments
            </span>
          </TabTrigger>
          <TabTrigger value="alerts">
            <span className="flex items-center gap-1.5">
              <Bell className="h-3.5 w-3.5" />
              Alerts
            </span>
          </TabTrigger>
          <TabTrigger value="incidents">
            <span className="flex items-center gap-1.5">
              <Zap className="h-3.5 w-3.5" />
              Incidents
            </span>
          </TabTrigger>
          <TabTrigger value="thresholds">
            <span className="flex items-center gap-1.5">
              <Gauge className="h-3.5 w-3.5" />
              Thresholds
            </span>
          </TabTrigger>
          <TabTrigger value="retention">
            <span className="flex items-center gap-1.5">
              <Database className="h-3.5 w-3.5" />
              Retention
            </span>
          </TabTrigger>
          <TabTrigger value="settings">
            <span className="flex items-center gap-1.5">
              <Settings2 className="h-3.5 w-3.5" />
              Settings
            </span>
          </TabTrigger>
          <TabTrigger value="checks">
            <span className="flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5" />
              Checks
            </span>
          </TabTrigger>
        </TabsList>

        <Suspense
          fallback={
            <div className="flex h-48 items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            </div>
          }
        >
          <TabsContent value="overview">
            <OverviewTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="interfaces">
            <InterfacesTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="performance">
            <PerformanceTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="configuration">
            <ConfigurationTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="assignments">
            <AssignmentsTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="alerts">
            <AlertsTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="incidents">
            <IncidentsTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="thresholds">
            <ThresholdsTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="retention">
            <RetentionTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="settings">
            <SettingsTab deviceId={deviceId} />
          </TabsContent>
          <TabsContent value="checks">
            <ChecksTab deviceId={deviceId} />
          </TabsContent>
        </Suspense>
      </Tabs>
    </div>
  );
}
