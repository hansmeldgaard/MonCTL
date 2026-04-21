import { useState, useEffect, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Check,
  Key,
  Loader2,
  Network,
  Plus,
  Save,
  Search,
  Settings2,
  Tag,
  X,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { LabelEditor } from "@/components/LabelEditor.tsx";
import { SchemaConfigFields } from "@/components/SchemaConfigFields.tsx";
import { RuleFormDialog } from "@/pages/DiscoveryRulesPage.tsx";
import {
  useAppDetail,
  useApps,
  useCollectorGroups,
  useCredentials,
  useCredentialTypes,
  useDevice,
  useDeviceCategories,
  useDeviceMonitoring,
  useDeviceTypes,
  useDiscoverDevice,
  useSystemSettings,
  useTenants,
  useUpdateDevice,
  useUpdateDeviceMonitoring,
} from "@/api/hooks.ts";
import type { Device as DeviceModel } from "@/types/api.ts";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName, validateAddress } from "@/lib/validation.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

const INTERFACE_INTERVAL_OPTIONS = [
  { value: "60", label: "1 minute" },
  { value: "120", label: "2 minutes" },
  { value: "300", label: "5 minutes" },
  { value: "600", label: "10 minutes" },
  { value: "900", label: "15 minutes" },
  { value: "1800", label: "30 minutes" },
];

const INTERVAL_OPTIONS = [
  { value: "30", label: "30 seconds" },
  { value: "60", label: "60 seconds" },
  { value: "120", label: "2 minutes" },
  { value: "300", label: "5 minutes" },
];

function formatCredentialType(type: string): string {
  return type
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function MonitoringCard({
  deviceId,
  device,
}: {
  deviceId: string;
  device: DeviceModel | undefined;
}) {
  const { data: monitoring, isLoading: monLoading } =
    useDeviceMonitoring(deviceId);
  const { data: allAppsResp } = useApps();
  const allApps = allAppsResp?.data ?? [];
  const updateMonitoring = useUpdateDeviceMonitoring();

  const monitoringApps = useMemo(
    () => allApps.filter((a) => a.target_table === "availability_latency"),
    [allApps],
  );

  const interfaceApps = useMemo(
    () => (allApps ?? []).filter((a) => a.target_table === "interface"),
    [allApps],
  );

  const { data: systemSettings } = useSystemSettings();
  const systemDefaultInterval =
    systemSettings?.interface_poll_interval_seconds ?? "300";

  const [availAppName, setAvailAppName] = useState("");
  const [latencyAppName, setLatencyAppName] = useState("");
  const [availConfig, setAvailConfig] = useState<Record<string, unknown>>({});
  const [latencyConfig, setLatencyConfig] = useState<Record<string, unknown>>(
    {},
  );
  const [intervalSeconds, setIntervalSeconds] = useState("60");
  const [interfaceAppName, setInterfaceAppName] = useState("");
  const [interfaceConfig, setInterfaceConfig] = useState<
    Record<string, unknown>
  >({});
  const [interfaceInterval, setInterfaceInterval] = useState("300");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const selectedAvApp = monitoringApps.find((a) => a.name === availAppName);
  const selectedLatApp = monitoringApps.find((a) => a.name === latencyAppName);
  const selectedIfaceApp = interfaceApps.find(
    (a) => a.name === interfaceAppName,
  );
  const { data: avAppDetail } = useAppDetail(selectedAvApp?.id);
  const { data: latAppDetail } = useAppDetail(selectedLatApp?.id);
  const { data: ifaceAppDetail } = useAppDetail(selectedIfaceApp?.id);

  useEffect(() => {
    if (!monitoring) return;
    const av = monitoring.availability;
    const la = monitoring.latency;
    const iface = monitoring.interface;
    setAvailAppName(av?.app_name ?? "");
    setAvailConfig(av?.config ?? {});
    setLatencyAppName(la?.app_name ?? "");
    setLatencyConfig(la?.config ?? {});
    const interval = av?.interval_seconds ?? la?.interval_seconds ?? 60;
    setIntervalSeconds(String(interval));
    setInterfaceAppName(iface?.app_name ?? "");
    setInterfaceConfig(iface?.config ?? {});
    setInterfaceInterval(
      String(iface?.interval_seconds ?? systemDefaultInterval),
    );
  }, [monitoring, systemDefaultInterval]);

  function handleAppChange(
    role: "availability" | "latency",
    newAppName: string,
  ) {
    if (role === "availability") {
      setAvailAppName(newAppName);
      setAvailConfig({});
    } else {
      setLatencyAppName(newAppName);
      setLatencyConfig({});
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaveError(null);
    setSaveSuccess(false);

    const makeCheck = (
      appName: string,
      config: Record<string, unknown>,
      interval: string,
    ) => {
      if (!appName) return null;
      return {
        app_name: appName,
        config,
        interval_seconds: parseInt(interval, 10),
      };
    };

    try {
      await updateMonitoring.mutateAsync({
        id: deviceId,
        data: {
          availability: makeCheck(availAppName, availConfig, intervalSeconds),
          latency: makeCheck(latencyAppName, latencyConfig, intervalSeconds),
          interface: makeCheck(
            interfaceAppName,
            interfaceConfig,
            interfaceInterval,
          ),
        },
      });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Failed to save monitoring config",
      );
    }
  }

  const hasGroup = !!device?.collector_group_id;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="h-4 w-4" />
          Monitoring Configuration
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!hasGroup && (
          <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            This device must be assigned to a collector group before monitoring
            can be enabled.
          </div>
        )}
        {monLoading ? (
          <div className="flex h-16 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-brand-500" />
          </div>
        ) : (
          <form onSubmit={handleSave} className="space-y-5 max-w-2xl">
            <div className="space-y-1.5">
              <Label htmlFor="mon-interval">Check Interval</Label>
              <Select
                id="mon-interval"
                value={intervalSeconds}
                onChange={(e) => setIntervalSeconds(e.target.value)}
                disabled={!hasGroup}
              >
                {INTERVAL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Availability Check</Label>
              <div className="flex items-end gap-3 flex-wrap">
                <div className="space-y-1">
                  <Select
                    value={availAppName}
                    onChange={(e) =>
                      handleAppChange("availability", e.target.value)
                    }
                    disabled={!hasGroup}
                  >
                    <option value="">None</option>
                    {monitoringApps.map((a) => (
                      <option key={a.id} value={a.name}>
                        {a.description || a.name}
                      </option>
                    ))}
                  </Select>
                </div>
                {availAppName && (
                  <SchemaConfigFields
                    schema={avAppDetail?.config_schema}
                    config={availConfig}
                    onChange={setAvailConfig}
                    prefix="av"
                    disabled={!hasGroup}
                    deviceCredentials={device?.credentials}
                  />
                )}
              </div>
            </div>

            <div className="space-y-2">
              <Label>Latency Check</Label>
              <div className="flex items-end gap-3 flex-wrap">
                <div className="space-y-1">
                  <Select
                    value={latencyAppName}
                    onChange={(e) => handleAppChange("latency", e.target.value)}
                    disabled={!hasGroup}
                  >
                    <option value="">None</option>
                    {monitoringApps.map((a) => (
                      <option key={a.id} value={a.name}>
                        {a.description || a.name}
                      </option>
                    ))}
                  </Select>
                </div>
                {latencyAppName && (
                  <SchemaConfigFields
                    schema={latAppDetail?.config_schema}
                    config={latencyConfig}
                    onChange={setLatencyConfig}
                    prefix="la"
                    disabled={!hasGroup}
                    deviceCredentials={device?.credentials}
                  />
                )}
              </div>
            </div>

            <div className="border-t border-zinc-800 pt-4 mt-4">
              <div className="flex items-center gap-2 mb-3">
                <Network className="h-4 w-4 text-zinc-400" />
                <span className="text-sm font-medium text-zinc-200">
                  Interface Polling
                </span>
              </div>

              <div className="space-y-3">
                <div className="space-y-1">
                  <span className="text-xs text-zinc-400">
                    Interface Poller App
                  </span>
                  <Select
                    value={interfaceAppName}
                    onChange={(e) => {
                      setInterfaceAppName(e.target.value);
                      setInterfaceConfig({});
                    }}
                    disabled={!hasGroup}
                  >
                    <option value="">None</option>
                    {interfaceApps.map((a) => (
                      <option key={a.id} value={a.name}>
                        {a.description || a.name}
                      </option>
                    ))}
                  </Select>
                </div>

                {interfaceAppName && (
                  <>
                    <div className="space-y-1">
                      <span className="text-xs text-zinc-400">
                        Poll Interval
                        <span className="text-zinc-600 ml-1">
                          (system default:{" "}
                          {INTERFACE_INTERVAL_OPTIONS.find(
                            (o) => o.value === systemDefaultInterval,
                          )?.label ?? `${systemDefaultInterval}s`}
                          )
                        </span>
                      </span>
                      <Select
                        value={interfaceInterval}
                        onChange={(e) => setInterfaceInterval(e.target.value)}
                        disabled={!hasGroup}
                      >
                        {INTERFACE_INTERVAL_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </Select>
                    </div>

                    <SchemaConfigFields
                      schema={ifaceAppDetail?.config_schema}
                      config={interfaceConfig}
                      onChange={setInterfaceConfig}
                      prefix="iface"
                      disabled={!hasGroup}
                      deviceCredentials={device?.credentials}
                    />
                  </>
                )}
              </div>
            </div>

            {saveError && <p className="text-sm text-red-400">{saveError}</p>}
            {saveSuccess && (
              <p className="text-sm text-emerald-400">
                Monitoring configuration saved.
              </p>
            )}

            <Button
              type="submit"
              size="sm"
              disabled={updateMonitoring.isPending || !hasGroup}
            >
              {updateMonitoring.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Save Monitoring
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

function DiscoveryCard({
  deviceId,
  device,
}: {
  deviceId: string;
  device: DeviceModel | undefined;
}) {
  const discoverMut = useDiscoverDevice();
  const qc = useQueryClient();
  const tz = useTimezone();
  const meta = device?.metadata as Record<string, string> | undefined;
  const discovered = meta?.discovered_at;

  const [discoveryPhase, setDiscoveryPhase] = useState<
    "idle" | "polling" | "done" | "timeout"
  >("idle");
  const preDiscoverAt = useRef<string | undefined>(undefined);
  const [showCreateType, setShowCreateType] = useState(false);

  const fields = [
    { label: "Matched Type", value: device?.device_type_name || undefined },
    { label: "sysObjectID", key: "sys_object_id" },
    { label: "Vendor", key: "vendor" },
    { label: "Model", key: "model" },
    { label: "OS Family", key: "os_family" },
    { label: "sysDescr", key: "sys_descr" },
    { label: "sysName", key: "sys_name" },
  ];

  const handleDiscover = () => {
    preDiscoverAt.current = discovered;
    setDiscoveryPhase("polling");
    discoverMut.mutate(deviceId);
  };

  useEffect(() => {
    if (discoveryPhase !== "polling") return;
    const iv = setInterval(() => {
      qc.invalidateQueries({ queryKey: ["device", deviceId] });
    }, 2000);
    return () => clearInterval(iv);
  }, [discoveryPhase, deviceId, qc]);

  useEffect(() => {
    if (discoveryPhase !== "polling") return;
    if (discovered && discovered !== preDiscoverAt.current) {
      setDiscoveryPhase("done");
    }
  }, [discoveryPhase, discovered]);

  useEffect(() => {
    if (discoveryPhase !== "polling") return;
    const t = setTimeout(() => setDiscoveryPhase("timeout"), 60_000);
    return () => clearTimeout(t);
  }, [discoveryPhase]);

  useEffect(() => {
    if (discoveryPhase === "done") {
      const t = setTimeout(() => setDiscoveryPhase("idle"), 4000);
      return () => clearTimeout(t);
    }
    if (discoveryPhase === "timeout") {
      const t = setTimeout(() => setDiscoveryPhase("idle"), 8000);
      return () => clearTimeout(t);
    }
  }, [discoveryPhase]);

  const hasSysOid = !!meta?.sys_object_id;
  const hasMatch = !!device?.device_type_name;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            SNMP Discovery
          </CardTitle>
          <Button
            size="sm"
            variant="outline"
            onClick={handleDiscover}
            disabled={discoverMut.isPending || discoveryPhase === "polling"}
          >
            {discoverMut.isPending || discoveryPhase === "polling" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Search className="h-3.5 w-3.5" />
            )}
            {discovered ? "Re-discover" : "Discover"}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {discoveryPhase === "polling" && (
          <p className="text-xs text-amber-400 mb-3 flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" />
            Discovery queued — waiting for collector to complete SNMP query...
          </p>
        )}
        {discoveryPhase === "done" && (
          <p className="text-xs text-emerald-400 mb-3 flex items-center gap-1.5">
            <Check className="h-3 w-3" />
            Discovery complete — device updated.
          </p>
        )}
        {discoveryPhase === "timeout" && (
          <p className="text-xs text-amber-400 mb-3">
            Discovery timed out — collector may be offline.
          </p>
        )}
        {discoverMut.isError && discoveryPhase === "idle" && (
          <p className="text-xs text-red-400 mb-3">
            {discoverMut.error instanceof Error
              ? discoverMut.error.message
              : "Discovery failed"}
          </p>
        )}
        {!discovered && discoveryPhase === "idle" && !discoverMut.isError ? (
          <p className="text-sm text-zinc-500">
            This device has not been discovered yet. Assign an SNMP credential
            and click Discover.
          </p>
        ) : (
          <div className="grid grid-cols-[120px_1fr] gap-x-4 gap-y-1.5 text-sm">
            {fields.map((f) => {
              const val =
                "value" in f ? f.value : meta?.[(f as { key: string }).key];
              const key = "key" in f ? (f as { key: string }).key : f.label;
              return val ? (
                <div key={key} className="contents">
                  <span className="text-zinc-500">{f.label}</span>
                  <span
                    className={
                      key === "sys_object_id"
                        ? "font-mono text-xs text-zinc-300"
                        : "text-zinc-300"
                    }
                  >
                    {key === "sys_descr" && val.length > 100
                      ? val.slice(0, 100) + "..."
                      : val}
                  </span>
                </div>
              ) : null;
            })}
            {discovered && (
              <div className="contents">
                <span className="text-zinc-500">Discovered</span>
                <span className="text-zinc-400 text-xs">
                  {formatDate(discovered, tz)}
                </span>
              </div>
            )}
          </div>
        )}
        {hasSysOid && discoveryPhase === "idle" && (
          <div className="mt-3 pt-3 border-t border-zinc-800">
            <p className="text-xs text-zinc-500 mb-2">
              {hasMatch ? (
                <>
                  Matched{" "}
                  <span className="text-zinc-300">
                    {device?.device_type_name}
                  </span>{" "}
                  — you can create a more specific type for this sysObjectID.
                </>
              ) : (
                <>
                  No matching device type found for sysObjectID{" "}
                  <span className="font-mono">{meta?.sys_object_id}</span>
                </>
              )}
            </p>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowCreateType(true)}
            >
              <Plus className="h-3.5 w-3.5" />
              {hasMatch ? "Create Specific Type" : "Create Device Type"}
            </Button>
          </div>
        )}
        {showCreateType && (
          <RuleFormDialog
            prefill={{
              sys_object_id_pattern: meta?.sys_object_id ?? "",
              vendor: meta?.vendor ?? "",
              model: meta?.model ?? "",
              os_family: meta?.os_family ?? "",
              name: [meta?.vendor, meta?.model].filter(Boolean).join(" ") || "",
            }}
            onClose={() => setShowCreateType(false)}
            onSuccess={() => {
              setShowCreateType(false);
              preDiscoverAt.current = discovered;
              setDiscoveryPhase("polling");
              discoverMut.mutate(deviceId);
            }}
          />
        )}
      </CardContent>
    </Card>
  );
}

export function SettingsTab({ deviceId }: { deviceId: string }) {
  const { data: device, isLoading: deviceLoading } = useDevice(deviceId);
  const { data: deviceCategories } = useDeviceCategories();
  const { data: allDeviceTypes } = useDeviceTypes({ limit: 500 });
  const deviceTypes = allDeviceTypes?.data ?? [];
  const { data: tenants } = useTenants();
  const { data: collectorGroups } = useCollectorGroups();
  const { data: allCredentials } = useCredentials();
  const { data: credentialTypes } = useCredentialTypes();
  const updateDevice = useUpdateDevice();

  const settingsNameField = useField("", validateName);
  const settingsAddressField = useField("", validateAddress);
  const [deviceCategory, setDeviceCategory] = useState("");
  const [deviceTypeId, setDeviceTypeId] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [collectorGroupId, setCollectorGroupId] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [deviceCreds, setDeviceCreds] = useState<Record<string, string>>({});
  const [credsModified, setCredsModified] = useState(false);
  const [credsSaving, setCredsSaving] = useState(false);
  const [credsSaveSuccess, setCredsSaveSuccess] = useState(false);
  const [credError, setCredError] = useState<string | null>(null);

  const [labels, setLabels] = useState<Record<string, string>>({});
  const [labelsModified, setLabelsModified] = useState(false);
  const [labelsSaving, setLabelsSaving] = useState(false);
  const [labelsSaveSuccess, setLabelsSaveSuccess] = useState(false);
  const [labelError, setLabelError] = useState<string | null>(null);

  useEffect(() => {
    if (device) {
      settingsNameField.reset(device.name);
      settingsAddressField.reset(device.address);
      setDeviceCategory(device.device_category);
      setDeviceTypeId(device.device_type_id ?? "");
      setTenantId(device.tenant_id ?? "");
      setCollectorGroupId(device.collector_group_id ?? "");
      setLabels(device.labels ?? {});
      const cmap: Record<string, string> = {};
      for (const [ctype, info] of Object.entries(device.credentials ?? {})) {
        cmap[ctype] = info.id;
      }
      setDeviceCreds(cmap);
      setCredsModified(false);
    }
  }, [device]);

  async function handleSaveDevice(e: React.FormEvent) {
    e.preventDefault();
    setSaveError(null);
    setSaveSuccess(false);
    if (!validateAll(settingsNameField, settingsAddressField)) return;
    try {
      await updateDevice.mutateAsync({
        id: deviceId,
        data: {
          name: settingsNameField.value.trim(),
          address: settingsAddressField.value.trim(),
          device_category: deviceCategory,
          device_type_id: deviceTypeId || null,
          tenant_id: tenantId || null,
          collector_group_id: collectorGroupId || null,
          labels,
        },
      });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save");
    }
  }

  async function handleSaveLabels() {
    setLabelError(null);
    setLabelsSaving(true);
    setLabelsSaveSuccess(false);
    try {
      await updateDevice.mutateAsync({
        id: deviceId,
        data: {
          name: settingsNameField.value.trim(),
          address: settingsAddressField.value.trim(),
          device_category: deviceCategory,
          tenant_id: tenantId || null,
          collector_group_id: collectorGroupId || null,
          labels,
        },
      });
      setLabelsModified(false);
      setLabelsSaveSuccess(true);
      setTimeout(() => setLabelsSaveSuccess(false), 3000);
    } catch (err) {
      setLabelError(
        err instanceof Error ? err.message : "Failed to save labels",
      );
    } finally {
      setLabelsSaving(false);
    }
  }

  const credsByType = useMemo(() => {
    const map: Record<string, typeof allCredentials> = {};
    for (const c of allCredentials ?? []) {
      (map[c.credential_type] ??= []).push(c);
    }
    return map;
  }, [allCredentials]);

  const availableTypes = useMemo(() => {
    const typeNames = (credentialTypes ?? []).map((ct) => ct.name);
    for (const t of Object.keys(credsByType)) {
      if (!typeNames.includes(t)) typeNames.push(t);
    }
    return typeNames.filter((t) => !(t in deviceCreds));
  }, [credentialTypes, credsByType, deviceCreds]);

  async function handleSaveCredentials() {
    setCredError(null);
    setCredsSaving(true);
    setCredsSaveSuccess(false);
    try {
      await updateDevice.mutateAsync({
        id: deviceId,
        data: { credentials: deviceCreds },
      });
      setCredsModified(false);
      setCredsSaveSuccess(true);
      setTimeout(() => setCredsSaveSuccess(false), 3000);
    } catch (err) {
      setCredError(
        err instanceof Error ? err.message : "Failed to save credentials",
      );
    } finally {
      setCredsSaving(false);
    }
  }

  if (deviceLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Device Settings
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSaveDevice}>
            <div className="grid grid-cols-2 gap-x-8 gap-y-3">
              <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                <Label htmlFor="s-name" className="text-right">
                  Name
                </Label>
                <div>
                  <Input
                    id="s-name"
                    value={settingsNameField.value}
                    onChange={settingsNameField.onChange}
                    onBlur={settingsNameField.onBlur}
                  />
                  {settingsNameField.error && (
                    <p className="text-xs text-red-400 mt-0.5">
                      {settingsNameField.error}
                    </p>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                <Label htmlFor="s-dtype" className="text-right">
                  Category
                </Label>
                <Select
                  id="s-dtype"
                  value={deviceCategory}
                  onChange={(e) => setDeviceCategory(e.target.value)}
                >
                  {(deviceCategories ?? []).map((dc) => (
                    <option key={dc.id} value={dc.name}>
                      {dc.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                <Label htmlFor="s-address" className="text-right">
                  Address
                </Label>
                <div>
                  <Input
                    id="s-address"
                    value={settingsAddressField.value}
                    onChange={settingsAddressField.onChange}
                    onBlur={settingsAddressField.onBlur}
                  />
                  {settingsAddressField.error && (
                    <p className="text-xs text-red-400 mt-0.5">
                      {settingsAddressField.error}
                    </p>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                <Label htmlFor="s-devtype" className="text-right">
                  Device Type
                </Label>
                <Select
                  id="s-devtype"
                  value={deviceTypeId}
                  onChange={(e) => setDeviceTypeId(e.target.value)}
                >
                  <option value="">
                    {"\u2014"} No device type {"\u2014"}
                  </option>
                  {deviceTypes.map((dt) => (
                    <option key={dt.id} value={dt.id}>
                      {dt.name}
                    </option>
                  ))}
                </Select>
              </div>
              {tenants && tenants.length > 0 ? (
                <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                  <Label htmlFor="s-tenant" className="text-right">
                    Tenant
                  </Label>
                  <Select
                    id="s-tenant"
                    value={tenantId}
                    onChange={(e) => setTenantId(e.target.value)}
                  >
                    <option value="">
                      {"\u2014"} No tenant {"\u2014"}
                    </option>
                    {tenants.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </Select>
                </div>
              ) : (
                <div />
              )}
              <div />
              <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                <Label htmlFor="s-cgroup" className="text-right">
                  Collector Group
                </Label>
                <Select
                  id="s-cgroup"
                  value={collectorGroupId}
                  onChange={(e) => setCollectorGroupId(e.target.value)}
                >
                  <option value="">
                    {"\u2014"} No group {"\u2014"}
                  </option>
                  {(collectorGroups ?? []).map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="mt-4 pt-4 border-t border-zinc-800 flex items-center gap-3">
              <Button type="submit" size="sm" disabled={updateDevice.isPending}>
                {updateDevice.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                Save Changes
              </Button>
              {saveError && <p className="text-sm text-red-400">{saveError}</p>}
              {saveSuccess && (
                <p className="text-sm text-emerald-400">Saved.</p>
              )}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Key className="h-4 w-4" />
            Default Credentials
            {credsModified && (
              <Button
                size="sm"
                className="ml-auto gap-1.5"
                onClick={handleSaveCredentials}
                disabled={credsSaving}
              >
                {credsSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                Save Credentials
              </Button>
            )}
            {credsSaveSuccess && (
              <span className="ml-auto text-sm text-emerald-400">Saved.</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {Object.keys(deviceCreds).length === 0 &&
          availableTypes.length === 0 ? (
            <p className="text-sm text-zinc-500">
              No credentials configured. Create credentials first.
            </p>
          ) : (
            <div className="space-y-2">
              {Object.entries(deviceCreds).map(([ctype, credId]) => (
                <div key={ctype} className="flex items-center gap-2">
                  <Badge
                    variant="default"
                    className="text-xs min-w-[130px] justify-center"
                  >
                    {formatCredentialType(ctype)}
                  </Badge>
                  <Select
                    className="flex-1"
                    value={credId}
                    onChange={(e) => {
                      setDeviceCreds((prev) => ({
                        ...prev,
                        [ctype]: e.target.value,
                      }));
                      setCredsModified(true);
                    }}
                  >
                    <option value="">-- Select --</option>
                    {(credsByType[ctype] ?? allCredentials ?? [])
                      .filter((c) => c.credential_type === ctype)
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                  </Select>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 text-zinc-500 hover:text-red-400"
                    onClick={() => {
                      setDeviceCreds((prev) => {
                        const next = { ...prev };
                        delete next[ctype];
                        return next;
                      });
                      setCredsModified(true);
                    }}
                    title="Remove"
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
              {availableTypes.length > 0 && (
                <Select
                  className="max-w-xs text-zinc-500"
                  value=""
                  onChange={(e) => {
                    if (e.target.value) {
                      setDeviceCreds((prev) => ({
                        ...prev,
                        [e.target.value]: "",
                      }));
                      setCredsModified(true);
                    }
                  }}
                >
                  <option value="">+ Add credential type...</option>
                  {availableTypes.map((t) => (
                    <option key={t} value={t}>
                      {formatCredentialType(t)}
                    </option>
                  ))}
                </Select>
              )}
            </div>
          )}
          {credError && (
            <p className="text-xs text-red-400 mt-2">{credError}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Tag className="h-4 w-4" />
            Labels
            {labelsModified && (
              <Button
                size="sm"
                className="ml-auto gap-1.5"
                onClick={handleSaveLabels}
                disabled={labelsSaving}
              >
                {labelsSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                Save Labels
              </Button>
            )}
            {labelsSaveSuccess && (
              <span className="ml-auto text-sm text-emerald-400">Saved.</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <LabelEditor
            labels={labels}
            onChange={(newLabels) => {
              setLabels(newLabels);
              setLabelsModified(true);
            }}
          />
          {labelError && (
            <p className="text-xs text-red-400 mt-2">{labelError}</p>
          )}
        </CardContent>
      </Card>

      <DiscoveryCard deviceId={deviceId} device={device} />

      <MonitoringCard deviceId={deviceId} device={device} />
    </div>
  );
}
