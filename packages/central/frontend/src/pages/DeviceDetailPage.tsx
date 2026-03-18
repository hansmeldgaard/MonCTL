import { useState, useEffect, useMemo, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Activity,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  ArrowUpDown,
  BarChart2,
  Bell,
  Clock,
  FileText,
  Gauge,
  Layout,
  ListChecks,
  Loader2,
  Monitor,
  Network,
  Plug,
  Plus,
  Save,
  Settings2,
  Tag,
  Pencil,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Tabs, TabsList, TabTrigger, TabsContent } from "@/components/ui/tabs.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { StatusBadge } from "@/components/StatusBadge.tsx";
import { AvailabilityChart } from "@/components/AvailabilityChart.tsx";
import { LabelEditor } from "@/components/LabelEditor.tsx";
import { TimeRangePicker, rangeToTimestamps } from "@/components/TimeRangePicker.tsx";
import type { TimeRangeValue } from "@/components/TimeRangePicker.tsx";
import {
  useCollectorGroups,
  useCollectors,
  useConnectors,
  useCreateAssignment,
  useCredentials,
  useDeleteAssignment,
  useUpdateAssignment,
  useDevice,
  useDeviceAssignments,
  useDeviceConfigData,
  useDeviceHistory,
  useDeviceMonitoring,
  useDeviceResults,
  useDeviceTypes,
  useInterfaceLatest,
  useInterfaceHistory,
  useInterfaceMetadata,
  useUpdateInterfaceSettings,
  useAppDetail,
  useApps,
  useSnmpOids,
  useSystemSettings,
  useTenants,
  useUpdateDevice,
  useUpdateDeviceMonitoring,
  useDeviceThresholds,
  useAlertInstances,
  useUpdateAlertInstance,
  useCreateThresholdOverride,
  useUpdateThresholdOverride,
  useDeleteThresholdOverride,
} from "@/api/hooks.ts";
import type { Device as DeviceType, DeviceAssignment, DeviceThresholdRow } from "@/types/api.ts";
import { ConfigDataRenderer } from "@/components/ConfigDataRenderer.tsx";
import { ApplyTemplateDialog } from "@/components/ApplyTemplateDialog.tsx";
import { InterfaceTrafficChart } from "@/components/InterfaceTrafficChart.tsx";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

// ── Default time range ────────────────────────────────────

const DEFAULT_RANGE: TimeRangeValue = { type: "preset", preset: "24h" };

// ── Add Assignment Dialog ────────────────────────────────

interface AddAssignmentDialogProps {
  deviceId: string;
  deviceCollectorGroupId: string | null;
  deviceCollectorGroupName: string | null;
  open: boolean;
  onClose: () => void;
}

function AddAssignmentDialog({
  deviceId,
  deviceCollectorGroupId,
  deviceCollectorGroupName,
  open,
  onClose,
}: AddAssignmentDialogProps) {
  const { data: apps } = useApps();
  const { data: collectors } = useCollectors();
  const { data: connectors } = useConnectors();
  const { data: credentials } = useCredentials();
  const [selectedAppId, setSelectedAppId] = useState("");
  const { data: appDetail } = useAppDetail(selectedAppId || undefined);
  const createAssignment = useCreateAssignment();

  // "group" = let collector group handle routing; "specific" = pick a collector manually
  const [routingMode, setRoutingMode] = useState<"group" | "specific">(
    deviceCollectorGroupId ? "group" : "specific"
  );
  const [collectorId, setCollectorId] = useState("");
  const [scheduleType, setScheduleType] = useState("interval");
  const [scheduleValue, setScheduleValue] = useState("60");
  const [versionMode, setVersionMode] = useState<"latest" | "pinned">("latest");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [configText, setConfigText] = useState("{}");
  const [parsedConfig, setParsedConfig] = useState<Record<string, unknown>>({});
  const [configError, setConfigError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // Connector bindings
  interface BindingRow {
    alias: string;
    connector_id: string;
    version_mode: "latest" | "pinned";
    connector_version_id: string;
    credential_id: string;
    settings: string;
  }
  const [bindings, setBindings] = useState<BindingRow[]>([]);

  useEffect(() => {
    if (apps?.length && !selectedAppId) setSelectedAppId(apps[0].id);
  }, [apps, selectedAppId]);

  useEffect(() => {
    if (collectors?.length && !collectorId) setCollectorId(collectors[0].id);
  }, [collectors, collectorId]);

  // Reset routing mode when the dialog opens/device changes
  useEffect(() => {
    setRoutingMode(deviceCollectorGroupId ? "group" : "specific");
  }, [deviceCollectorGroupId, open]);

  // Reset version/config when app changes
  useEffect(() => {
    setVersionMode("latest");
    setSelectedVersionId("");
    setParsedConfig({});
    setConfigText("{}");
  }, [selectedAppId]);

  function reset() {
    setSelectedAppId(apps?.[0]?.id ?? "");
    setCollectorId(collectors?.[0]?.id ?? "");
    setRoutingMode(deviceCollectorGroupId ? "group" : "specific");
    setVersionMode("latest");
    setSelectedVersionId("");
    setScheduleType("interval");
    setScheduleValue("60");
    setConfigText("{}");
    setParsedConfig({});
    setConfigError(null);
    setFormError(null);
    setBindings([]);
  }

  function handleClose() {
    reset();
    onClose();
  }

  const hasSchemaFields = appDetail?.config_schema &&
    Object.keys((appDetail.config_schema as { properties?: Record<string, unknown> }).properties ?? {}).length > 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setConfigError(null);

    let config: Record<string, unknown> = {};
    if (hasSchemaFields && Object.keys(parsedConfig).length > 0) {
      config = parsedConfig;
    } else {
      try {
        config = JSON.parse(configText);
      } catch {
        setConfigError("Invalid JSON");
        return;
      }
    }

    if (!selectedAppId) {
      setFormError("App is required.");
      return;
    }

    if (routingMode === "specific" && !collectorId) {
      setFormError("Select a collector or switch to collector group routing.");
      return;
    }

    const latestVersion = appDetail?.versions?.find((v) => v.is_latest);
    if (!latestVersion && versionMode === "latest") {
      setFormError("The selected app has no latest version.");
      return;
    }

    const versionId = versionMode === "latest" ? latestVersion!.id : selectedVersionId;
    if (!versionId) {
      setFormError("Select a version.");
      return;
    }

    try {
      // Build connector bindings payload
      const connectorBindings = bindings.length > 0 ? bindings.map((b) => {
        let settings: Record<string, unknown> = {};
        try { settings = JSON.parse(b.settings || "{}"); } catch { /* ignore */ }
        return {
          alias: b.alias,
          connector_id: b.connector_id,
          connector_version_id: b.version_mode === "latest" ? undefined : b.connector_version_id,
          use_latest: b.version_mode === "latest",
          credential_id: b.credential_id || undefined,
          settings,
        };
      }) : undefined;

      await createAssignment.mutateAsync({
        app_id: selectedAppId,
        app_version_id: versionId,
        collector_id: routingMode === "specific" ? collectorId : null,
        device_id: deviceId,
        schedule_type: scheduleType,
        schedule_value: scheduleValue,
        config,
        use_latest: versionMode === "latest",
        connector_bindings: connectorBindings,
      });
      reset();
      onClose();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create assignment");
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} title="Add App Assignment">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="aa-app">App</Label>
          <Select
            id="aa-app"
            value={selectedAppId}
            onChange={(e) => setSelectedAppId(e.target.value)}
          >
            {(apps ?? []).map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </Select>
          {appDetail && appDetail.versions.length > 0 && (
            <div className="space-y-2 mt-2">
              <Label>Version</Label>
              <label className="flex items-center gap-2.5 cursor-pointer rounded-md border border-zinc-700 px-3 py-2.5 hover:border-zinc-600 transition-colors">
                <input
                  type="radio"
                  name="version-mode"
                  value="latest"
                  checked={versionMode === "latest"}
                  onChange={() => setVersionMode("latest")}
                  className="accent-brand-500"
                />
                <span className="text-sm text-zinc-200">
                  Use latest
                  {appDetail.versions.find((v) => v.is_latest) && (
                    <span className="ml-1.5 text-xs text-zinc-500 font-normal">
                      (currently {appDetail.versions.find((v) => v.is_latest)!.version})
                    </span>
                  )}
                </span>
              </label>
              <label className="flex items-center gap-2.5 cursor-pointer rounded-md border border-zinc-700 px-3 py-2.5 hover:border-zinc-600 transition-colors">
                <input
                  type="radio"
                  name="version-mode"
                  value="pinned"
                  checked={versionMode === "pinned"}
                  onChange={() => {
                    setVersionMode("pinned");
                    if (!selectedVersionId && appDetail.versions.length > 0) {
                      setSelectedVersionId(appDetail.versions[0].id);
                    }
                  }}
                  className="accent-brand-500"
                />
                <span className="text-sm text-zinc-200">Pin to version</span>
              </label>
              {versionMode === "pinned" && (
                <Select
                  value={selectedVersionId}
                  onChange={(e) => setSelectedVersionId(e.target.value)}
                  className="mt-1"
                >
                  {appDetail.versions.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.version}{v.is_latest ? " (latest)" : ""}
                    </option>
                  ))}
                </Select>
              )}
            </div>
          )}
          {appDetail && appDetail.versions.length === 0 && (
            <p className="text-xs text-red-400 mt-1">No versions — publish a version first</p>
          )}
        </div>

        {/* Routing mode */}
        <div className="space-y-2">
          <Label>Collector Routing</Label>
          {deviceCollectorGroupId && (
            <label className="flex items-center gap-2.5 cursor-pointer rounded-md border border-zinc-700 px-3 py-2.5 hover:border-zinc-600 transition-colors">
              <input
                type="radio"
                name="routing"
                value="group"
                checked={routingMode === "group"}
                onChange={() => setRoutingMode("group")}
                className="accent-brand-500"
              />
              <span className="text-sm text-zinc-200">
                Use collector group
                <span className="ml-1.5 text-xs text-zinc-500 font-normal">
                  ({deviceCollectorGroupName ?? deviceCollectorGroupId})
                </span>
              </span>
            </label>
          )}
          <label className="flex items-center gap-2.5 cursor-pointer rounded-md border border-zinc-700 px-3 py-2.5 hover:border-zinc-600 transition-colors">
            <input
              type="radio"
              name="routing"
              value="specific"
              checked={routingMode === "specific"}
              onChange={() => setRoutingMode("specific")}
              className="accent-brand-500"
            />
            <span className="text-sm text-zinc-200">Use specific collector</span>
          </label>

          {routingMode === "specific" && (
            <Select
              id="aa-collector"
              value={collectorId}
              onChange={(e) => setCollectorId(e.target.value)}
              className="mt-1"
            >
              {(collectors ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.name || c.hostname}</option>
              ))}
            </Select>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="aa-sched-type">Schedule Type</Label>
            <Select
              id="aa-sched-type"
              value={scheduleType}
              onChange={(e) => setScheduleType(e.target.value)}
            >
              <option value="interval">Interval (seconds)</option>
              <option value="cron">Cron expression</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="aa-sched-val">
              {scheduleType === "interval" ? "Interval (s)" : "Cron"}
            </Label>
            <Input
              id="aa-sched-val"
              value={scheduleValue}
              onChange={(e) => setScheduleValue(e.target.value)}
              placeholder={scheduleType === "interval" ? "60" : "*/5 * * * *"}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label>Config</Label>
          {hasSchemaFields ? (
            <div className="space-y-3 rounded-md border border-zinc-800 p-3">
              <SchemaConfigFields
                schema={appDetail!.config_schema}
                config={parsedConfig}
                onChange={(newConfig) => {
                  setParsedConfig(newConfig);
                  setConfigText(JSON.stringify(newConfig, null, 2));
                }}
                prefix="add-assign"
                disabled={false}
              />
              <details className="text-xs">
                <summary className="cursor-pointer text-zinc-600 hover:text-zinc-400">
                  Show raw JSON
                </summary>
                <textarea
                  rows={3}
                  value={configText}
                  onChange={(e) => {
                    setConfigText(e.target.value);
                    try { setParsedConfig(JSON.parse(e.target.value || "{}")); } catch { /* typing */ }
                  }}
                  className="mt-2 w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 font-mono text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 resize-none"
                />
              </details>
            </div>
          ) : (
            <textarea
              rows={4}
              value={configText}
              onChange={(e) => setConfigText(e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 font-mono text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 resize-none"
              placeholder="{}"
            />
          )}
          {configError && <p className="text-xs text-red-400">{configError}</p>}
        </div>

        {/* Connector Bindings */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="flex items-center gap-1.5">
              <Plug className="h-3.5 w-3.5" /> Connector Bindings
            </Label>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="gap-1"
              onClick={() => setBindings([...bindings, {
                alias: "",
                connector_id: connectors?.[0]?.id ?? "",
                version_mode: "latest",
                connector_version_id: "",
                credential_id: "",
                settings: "{}",
              }])}
            >
              <Plus className="h-3 w-3" /> Add Connector
            </Button>
          </div>
          {bindings.map((b, idx) => (
            <div key={idx} className="rounded-md border border-zinc-700 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-400">Binding #{idx + 1}</span>
                <button
                  type="button"
                  onClick={() => setBindings(bindings.filter((_, i) => i !== idx))}
                  className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                  title="Remove"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Alias</Label>
                  <Input
                    value={b.alias}
                    onChange={(e) => {
                      const next = [...bindings];
                      next[idx] = { ...next[idx], alias: e.target.value };
                      setBindings(next);
                    }}
                    placeholder="e.g. snmp_main"
                    className="text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Connector</Label>
                  <Select
                    value={b.connector_id}
                    onChange={(e) => {
                      const next = [...bindings];
                      next[idx] = { ...next[idx], connector_id: e.target.value, connector_version_id: "" };
                      setBindings(next);
                    }}
                    className="text-xs"
                  >
                    <option value="">-- Select --</option>
                    {(connectors ?? []).map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Version</Label>
                  <Select
                    value={b.version_mode}
                    onChange={(e) => {
                      const next = [...bindings];
                      next[idx] = { ...next[idx], version_mode: e.target.value as "latest" | "pinned" };
                      setBindings(next);
                    }}
                    className="text-xs"
                  >
                    <option value="latest">Use Latest</option>
                    <option value="pinned">Pin Version</option>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Credential <span className="font-normal text-zinc-500">(opt.)</span></Label>
                  <Select
                    value={b.credential_id}
                    onChange={(e) => {
                      const next = [...bindings];
                      next[idx] = { ...next[idx], credential_id: e.target.value };
                      setBindings(next);
                    }}
                    className="text-xs"
                  >
                    <option value="">-- None --</option>
                    {(credentials ?? []).map((cr) => (
                      <option key={cr.id} value={cr.id}>{cr.name}</option>
                    ))}
                  </Select>
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Settings (JSON)</Label>
                <textarea
                  rows={2}
                  value={b.settings}
                  onChange={(e) => {
                    const next = [...bindings];
                    next[idx] = { ...next[idx], settings: e.target.value };
                    setBindings(next);
                  }}
                  className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1.5 font-mono text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50 resize-none"
                  placeholder="{}"
                />
              </div>
            </div>
          ))}
        </div>

        {formError && <p className="text-sm text-red-400">{formError}</p>}

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={createAssignment.isPending}>
            {createAssignment.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Add Assignment
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}

// ── Edit Assignment Dialog ────────────────────────────────

interface EditAssignmentDialogProps {
  assignment: DeviceAssignment | null;
  open: boolean;
  onClose: () => void;
}

function EditAssignmentDialog({ assignment, open, onClose }: EditAssignmentDialogProps) {
  const updateAssignment = useUpdateAssignment();
  const { data: appDetail } = useAppDetail(assignment?.app.id);
  const { data: connectors } = useConnectors();
  const { data: credentials } = useCredentials();

  const [scheduleType, setScheduleType] = useState("interval");
  const [scheduleValue, setScheduleValue] = useState("60");
  const [configText, setConfigText] = useState("{}");
  const [parsedConfig, setParsedConfig] = useState<Record<string, unknown>>({});
  const [configError, setConfigError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [versionMode, setVersionMode] = useState<"latest" | "pinned">("latest");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [bindings, setBindings] = useState<{
    alias: string;
    connector_id: string;
    version_mode: string;
    connector_version_id: string;
    credential_id: string;
    settings: string;
  }[]>([]);

  // Populate fields when assignment changes
  useEffect(() => {
    if (assignment) {
      setScheduleType(assignment.schedule_type);
      setScheduleValue(assignment.schedule_value);
      setConfigText(JSON.stringify(assignment.config, null, 2));
      setParsedConfig(assignment.config ?? {});
      setEnabled(assignment.enabled);
      setVersionMode(assignment.use_latest ? "latest" : "pinned");
      setSelectedVersionId(assignment.app_version_id);
      setConfigError(null);
      setFormError(null);
      setBindings(
        (assignment.connector_bindings ?? []).map((b) => ({
          alias: b.alias,
          connector_id: b.connector_id,
          version_mode: b.use_latest ? "latest" : "pinned",
          connector_version_id: b.connector_version_id,
          credential_id: b.credential_id ?? "",
          settings: JSON.stringify(b.settings ?? {}, null, 2),
        })),
      );
    }
  }, [assignment]);

  const editHasSchemaFields = appDetail?.config_schema &&
    Object.keys((appDetail.config_schema as { properties?: Record<string, unknown> }).properties ?? {}).length > 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!assignment) return;
    setFormError(null);
    setConfigError(null);

    let config: Record<string, unknown> = {};
    if (editHasSchemaFields && Object.keys(parsedConfig).length > 0) {
      config = parsedConfig;
    } else {
      try {
        config = JSON.parse(configText);
      } catch {
        setConfigError("Invalid JSON");
        return;
      }
    }

    const latestVersion = appDetail?.versions?.find((v) => v.is_latest);
    const versionId = versionMode === "latest" ? latestVersion?.id : selectedVersionId;
    if (!versionId) {
      setFormError(versionMode === "latest" ? "No latest version available." : "Select a version.");
      return;
    }

    // Build connector bindings payload
    const connectorBindingsPayload = bindings.map((b) => {
      const conn = connectors?.find((c) => c.id === b.connector_id);
      return {
        alias: b.alias,
        connector_id: b.connector_id,
        connector_version_id: b.version_mode === "latest" && conn?.latest_version_id ? conn.latest_version_id : b.connector_version_id,
        credential_id: b.credential_id || null,
        use_latest: b.version_mode === "latest",
        settings: (() => { try { return JSON.parse(b.settings); } catch { return {}; } })(),
      };
    });

    try {
      await updateAssignment.mutateAsync({
        id: assignment.id,
        data: {
          schedule_type: scheduleType,
          schedule_value: scheduleValue,
          config,
          enabled,
          app_version_id: versionId,
          use_latest: versionMode === "latest",
          connector_bindings: connectorBindingsPayload,
        },
      });
      onClose();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to update assignment");
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={`Edit Assignment — ${assignment?.app.name ?? ""}`}>
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Version picker */}
        {appDetail && appDetail.versions.length > 0 && (
          <div className="space-y-2">
            <Label>Version</Label>
            <label className="flex items-center gap-2.5 cursor-pointer rounded-md border border-zinc-700 px-3 py-2.5 hover:border-zinc-600 transition-colors">
              <input
                type="radio"
                name="edit-version-mode"
                value="latest"
                checked={versionMode === "latest"}
                onChange={() => setVersionMode("latest")}
                className="accent-brand-500"
              />
              <span className="text-sm text-zinc-200">
                Use latest
                {appDetail.versions.find((v) => v.is_latest) && (
                  <span className="ml-1.5 text-xs text-zinc-500 font-normal">
                    (currently {appDetail.versions.find((v) => v.is_latest)!.version})
                  </span>
                )}
              </span>
            </label>
            <label className="flex items-center gap-2.5 cursor-pointer rounded-md border border-zinc-700 px-3 py-2.5 hover:border-zinc-600 transition-colors">
              <input
                type="radio"
                name="edit-version-mode"
                value="pinned"
                checked={versionMode === "pinned"}
                onChange={() => {
                  setVersionMode("pinned");
                  if (!selectedVersionId && appDetail.versions.length > 0) {
                    setSelectedVersionId(appDetail.versions[0].id);
                  }
                }}
                className="accent-brand-500"
              />
              <span className="text-sm text-zinc-200">Pin to version</span>
            </label>
            {versionMode === "pinned" && (
              <Select
                value={selectedVersionId}
                onChange={(e) => setSelectedVersionId(e.target.value)}
                className="mt-1"
              >
                {appDetail.versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.version}{v.is_latest ? " (latest)" : ""}
                  </option>
                ))}
              </Select>
            )}
          </div>
        )}

        {/* Schedule */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="ea-sched-type">Schedule Type</Label>
            <Select
              id="ea-sched-type"
              value={scheduleType}
              onChange={(e) => setScheduleType(e.target.value)}
            >
              <option value="interval">Interval (seconds)</option>
              <option value="cron">Cron expression</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ea-sched-val">
              {scheduleType === "interval" ? "Interval (s)" : "Cron"}
            </Label>
            <Input
              id="ea-sched-val"
              value={scheduleValue}
              onChange={(e) => setScheduleValue(e.target.value)}
              placeholder={scheduleType === "interval" ? "60" : "*/5 * * * *"}
            />
          </div>
        </div>

        {/* Config */}
        <div className="space-y-1.5">
          <Label>Config</Label>
          {editHasSchemaFields ? (
            <div className="space-y-3 rounded-md border border-zinc-800 p-3">
              <SchemaConfigFields
                schema={appDetail!.config_schema}
                config={parsedConfig}
                onChange={(newConfig) => {
                  setParsedConfig(newConfig);
                  setConfigText(JSON.stringify(newConfig, null, 2));
                }}
                prefix="edit-assign"
                disabled={false}
              />
              <details className="text-xs">
                <summary className="cursor-pointer text-zinc-600 hover:text-zinc-400">
                  Show raw JSON
                </summary>
                <textarea
                  rows={3}
                  value={configText}
                  onChange={(e) => {
                    setConfigText(e.target.value);
                    try { setParsedConfig(JSON.parse(e.target.value || "{}")); } catch { /* typing */ }
                  }}
                  className="mt-2 w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 font-mono text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 resize-none"
                />
              </details>
            </div>
          ) : (
            <textarea
              rows={4}
              value={configText}
              onChange={(e) => setConfigText(e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 font-mono text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 resize-none"
              placeholder="{}"
            />
          )}
          {configError && <p className="text-xs text-red-400">{configError}</p>}
        </div>

        {/* Connector Bindings */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="flex items-center gap-1.5">
              <Plug className="h-3.5 w-3.5" /> Connector Bindings
            </Label>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="gap-1"
              onClick={() => setBindings([...bindings, {
                alias: "",
                connector_id: connectors?.[0]?.id ?? "",
                version_mode: "latest",
                connector_version_id: "",
                credential_id: "",
                settings: "{}",
              }])}
            >
              <Plus className="h-3 w-3" /> Add Connector
            </Button>
          </div>
          {bindings.map((b, idx) => (
            <div key={idx} className="rounded-md border border-zinc-700 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-400">Binding #{idx + 1}</span>
                <button
                  type="button"
                  onClick={() => setBindings(bindings.filter((_, i) => i !== idx))}
                  className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                  title="Remove"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Alias</Label>
                  <Input
                    value={b.alias}
                    onChange={(e) => {
                      const next = [...bindings];
                      next[idx] = { ...next[idx], alias: e.target.value };
                      setBindings(next);
                    }}
                    placeholder="e.g. snmp"
                    className="text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Connector</Label>
                  <Select
                    value={b.connector_id}
                    onChange={(e) => {
                      const next = [...bindings];
                      next[idx] = { ...next[idx], connector_id: e.target.value, connector_version_id: "" };
                      setBindings(next);
                    }}
                    className="text-xs"
                  >
                    <option value="">-- Select --</option>
                    {(connectors ?? []).map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Version</Label>
                  <Select
                    value={b.version_mode}
                    onChange={(e) => {
                      const next = [...bindings];
                      next[idx] = { ...next[idx], version_mode: e.target.value };
                      setBindings(next);
                    }}
                    className="text-xs"
                  >
                    <option value="latest">Use Latest</option>
                    <option value="pinned">Pin Version</option>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Credential <span className="font-normal text-zinc-500">(opt.)</span></Label>
                  <Select
                    value={b.credential_id}
                    onChange={(e) => {
                      const next = [...bindings];
                      next[idx] = { ...next[idx], credential_id: e.target.value };
                      setBindings(next);
                    }}
                    className="text-xs"
                  >
                    <option value="">-- None --</option>
                    {(credentials ?? []).map((cr) => (
                      <option key={cr.id} value={cr.id}>{cr.name}</option>
                    ))}
                  </Select>
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Settings (JSON)</Label>
                <textarea
                  rows={2}
                  value={b.settings}
                  onChange={(e) => {
                    const next = [...bindings];
                    next[idx] = { ...next[idx], settings: e.target.value };
                    setBindings(next);
                  }}
                  className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1.5 font-mono text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50 resize-none"
                  placeholder="{}"
                />
              </div>
            </div>
          ))}
        </div>

        {/* Enabled toggle */}
        <label className="flex items-center gap-2.5 cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="accent-brand-500"
          />
          <span className="text-sm text-zinc-200">Enabled</span>
        </label>

        {formError && <p className="text-sm text-red-400">{formError}</p>}

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={updateAssignment.isPending}>
            {updateAssignment.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Save Changes
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}

// ── Tab 1: Overview ──────────────────────────────────────

function OverviewTab({ deviceId }: { deviceId: string }) {
  const tz = useTimezone();
  const [timeRange, setTimeRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const { fromTs, toTs } = useMemo(() => rangeToTimestamps(timeRange), [timeRange]);
  const { data: deviceResults } = useDeviceResults(deviceId);
  const { data: history, isLoading: histLoading } = useDeviceHistory(
    deviceId,
    fromTs,
    toTs,
    5000,
  );

  return (
    <div className="space-y-4">
      {/* Chart header + time picker */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-zinc-400">Availability &amp; Latency</h3>
        <TimeRangePicker value={timeRange} onChange={setTimeRange} timezone={tz} />
      </div>

      {/* Chart card */}
      <Card>
        <CardContent className="pt-4">
          {histLoading ? (
            <div className="flex h-48 items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            </div>
          ) : (
            <AvailabilityChart results={history ?? []} fromTs={fromTs} toTs={toTs} timezone={tz} />
          )}
        </CardContent>
      </Card>

      {/* Current Checks */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Monitor className="h-4 w-4" />
            Current Checks
            {deviceResults && (
              <Badge variant="default" className="ml-auto text-xs">
                {deviceResults.checks.length}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!deviceResults || deviceResults.checks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
              <p className="text-sm">No checks configured. Add apps on the Settings tab.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>State</TableHead>
                  <TableHead>App</TableHead>
                  <TableHead>Output</TableHead>
                  <TableHead>Latency</TableHead>
                  <TableHead>Executed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {deviceResults.checks.map((check) => (
                  <TableRow key={check.assignment_id}>
                    <TableCell>
                      <StatusBadge state={check.state_name} />
                    </TableCell>
                    <TableCell className="font-medium text-zinc-200">{check.app_name}</TableCell>
                    <TableCell
                      className="max-w-[280px] truncate text-zinc-400 text-sm"
                      title={check.output}
                    >
                      {check.output || "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm font-mono">
                      {check.rtt_ms != null
                        ? `${check.rtt_ms}ms`
                        : check.response_time_ms != null
                          ? `${check.response_time_ms}ms`
                          : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm">
                      {timeAgo(check.executed_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Events placeholder */}
      <Card>
        <CardHeader>
          <CardTitle className="text-zinc-400 text-sm">Events &amp; Alerts</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-8 text-zinc-600">
            <p className="text-sm">Event log and alert history coming in a future update.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Tab 2: Performance ───────────────────────────────────

function PerformanceTab({ deviceId }: { deviceId: string }) {
  const tz = useTimezone();
  const [timeRange, setTimeRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const { fromTs, toTs } = useMemo(() => rangeToTimestamps(timeRange), [timeRange]);
  const { data: history, isLoading } = useDeviceHistory(deviceId, fromTs, toTs, 1000);
  const tableHistory = history ?? [];
  const { sortBy, sortDir, toggle: onSort } = useSort("executed_at");
  const [filterCheck, setFilterCheck] = useState("");
  const [filterState, setFilterState] = useState("");
  const [filterAvail, setFilterAvail] = useState("");

  const checkNames = useMemo(() => [...new Set(tableHistory.map((r) => r.app_name).filter(Boolean))].sort(), [tableHistory]);
  const stateNames = useMemo(() => [...new Set(tableHistory.map((r) => r.state_name).filter(Boolean))].sort(), [tableHistory]);

  const filtered = useMemo(() => {
    let data = tableHistory;
    if (filterCheck) data = data.filter((r) => r.app_name === filterCheck);
    if (filterState) data = data.filter((r) => r.state_name === filterState);
    if (filterAvail === "up") data = data.filter((r) => r.reachable);
    if (filterAvail === "down") data = data.filter((r) => !r.reachable);

    return [...data].sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case "state": cmp = (a.state_name ?? "").localeCompare(b.state_name ?? ""); break;
        case "check": cmp = (a.app_name ?? "").localeCompare(b.app_name ?? ""); break;
        case "availability": cmp = (a.reachable ? 1 : 0) - (b.reachable ? 1 : 0); break;
        case "latency": {
          const la = a.rtt_ms ?? a.response_time_ms ?? 0;
          const lb = b.rtt_ms ?? b.response_time_ms ?? 0;
          cmp = la - lb;
          break;
        }
        case "executed_at": cmp = a.executed_at.localeCompare(b.executed_at); break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [tableHistory, filterCheck, filterState, filterAvail, sortBy, sortDir]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-zinc-400">Check History</h3>
        <TimeRangePicker value={timeRange} onChange={setTimeRange} timezone={tz} />
      </div>

      {isLoading ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
        </div>
      ) : tableHistory.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-zinc-600">
            <BarChart2 className="h-8 w-8 text-zinc-700 mb-2" />
            <p className="text-sm text-zinc-500">No results in this time range.</p>
            <p className="text-xs text-zinc-600 mt-1">Try "All time" or a wider range.</p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">
              Check History
              <span className="ml-2 text-zinc-500 font-normal text-xs">
                ({filtered.length}{filtered.length !== tableHistory.length ? ` of ${tableHistory.length}` : ""} results)
              </span>
            </CardTitle>
            <div className="flex items-center gap-2 pt-2">
              <Select value={filterCheck} onChange={(e) => setFilterCheck(e.target.value)} className="w-40 text-xs">
                <option value="">All Checks</option>
                {checkNames.map((n) => <option key={n} value={n!}>{n}</option>)}
              </Select>
              <Select value={filterState} onChange={(e) => setFilterState(e.target.value)} className="w-36 text-xs">
                <option value="">All States</option>
                {stateNames.map((s) => <option key={s} value={s!}>{s}</option>)}
              </Select>
              <Select value={filterAvail} onChange={(e) => setFilterAvail(e.target.value)} className="w-36 text-xs">
                <option value="">All</option>
                <option value="up">UP</option>
                <option value="down">DOWN</option>
              </Select>
              {(filterCheck || filterState || filterAvail) && (
                <Button variant="ghost" size="sm" onClick={() => { setFilterCheck(""); setFilterState(""); setFilterAvail(""); }}>
                  <X className="h-3 w-3" /> Clear
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead label="State" field="state" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                  <SortableHead label="Check" field="check" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                  <SortableHead label="Availability" field="availability" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                  <SortableHead label="Latency" field="latency" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                  <TableHead>Output</TableHead>
                  <SortableHead label="Executed" field="executed_at" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.slice(0, 500).map((r, idx) => (
                  <TableRow key={`${r.assignment_id}-${idx}`}>
                    <TableCell>
                      <StatusBadge state={r.state_name} />
                    </TableCell>
                    <TableCell className="text-zinc-300 text-sm">{r.app_name ?? "—"}</TableCell>
                    <TableCell>
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                          r.reachable ? "text-emerald-400" : "text-red-400"
                        }`}
                      >
                        <span
                          className={`inline-block h-2 w-2 rounded-full ${
                            r.reachable ? "bg-emerald-500" : "bg-red-500"
                          }`}
                        />
                        {r.reachable ? "UP" : "DOWN"}
                      </span>
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm font-mono">
                      {r.rtt_ms != null
                        ? `${r.rtt_ms}ms`
                        : r.response_time_ms != null
                          ? `${r.response_time_ms}ms`
                          : "—"}
                    </TableCell>
                    <TableCell
                      className="max-w-[220px] truncate text-zinc-500 text-sm"
                      title={r.output}
                    >
                      {r.output || "—"}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm">
                      {formatDate(r.executed_at, tz)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Tab 3: Configuration ─────────────────────────────────

function ConfigurationTab({ deviceId }: { deviceId: string }) {
  const { data: configRows, isLoading } = useDeviceConfigData(deviceId);

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!configRows || configRows.length === 0) {
    return (
      <div className="space-y-4">
        <Card>
          <CardContent className="py-12 flex flex-col items-center gap-3 text-zinc-600">
            <Wrench className="h-8 w-8 text-zinc-700" />
            <p className="text-sm text-zinc-500">No configuration data yet.</p>
            <p className="text-xs text-zinc-700 text-center max-w-sm">
              Config apps will populate structured data here once they have been assigned and executed.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Group by app_id → component_type → component, collect latest key/value pairs
  const grouped = new Map<string, { appName: string; data: Record<string, string> }>();
  for (const row of configRows) {
    const appId = String(row.app_id ?? "unknown");
    const key = String(row.config_key ?? "");
    const value = String(row.config_value ?? "");
    const appName = String(row.app_name ?? appId);
    if (!grouped.has(appId)) {
      grouped.set(appId, { appName, data: {} });
    }
    const entry = grouped.get(appId)!;
    // Keep the latest value (results are newest-first)
    if (!(key in entry.data)) {
      entry.data[key] = value;
    }
  }

  return (
    <div className="space-y-4">
      {[...grouped.entries()].map(([appId, { appName, data }]) => (
        <Card key={appId}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Wrench className="h-4 w-4" />
              {appName}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ConfigDataRenderer template={null} data={data} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Interface Helpers ─────────────────────────────────────

function formatSpeed(mbps: number): string {
  if (mbps >= 100000) return `${(mbps / 1000).toFixed(0)} Gbps`;
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(1)} Gbps`;
  return `${mbps} Mbps`;
}

function formatBps(bps: number): string {
  if (bps >= 1e9) return `${(bps / 1e9).toFixed(2)} Gbps`;
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(2)} Mbps`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(1)} Kbps`;
  return `${bps.toFixed(0)} bps`;
}

// formatBytes removed — traffic columns now show rates (bps) only

// ── Tab: Interfaces ──────────────────────────────────────

type IfaceSortKey = "status" | "if_index" | "if_name" | "if_alias" | "speed" | "in_traffic" | "out_traffic" | "in_errors" | "out_errors" | "last_polled";

const METRIC_TYPES = ["traffic", "errors", "discards", "status"] as const;

function parseMetrics(poll_metrics: string): Set<string> {
  if (poll_metrics === "all") return new Set(METRIC_TYPES);
  return new Set(poll_metrics.split(",").filter(Boolean));
}

function serializeMetrics(set: Set<string>): string {
  if (METRIC_TYPES.every(m => set.has(m))) return "all";
  if (set.size === 0) return "status"; // minimum: always poll status
  return [...set].join(",");
}

function InterfacesTab({ deviceId }: { deviceId: string }) {
  const { data: interfaces, isLoading } = useInterfaceLatest(deviceId);
  const { data: metadata } = useInterfaceMetadata(deviceId);
  const updateSettings = useUpdateInterfaceSettings();
  const [selectedInterfaceId, setSelectedInterfaceId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [timeRange, setTimeRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const [searchText, setSearchText] = useState("");
  const [filterOperStatus, setFilterOperStatus] = useState<string>("");
  const [filterSpeed, setFilterSpeed] = useState<string>("");
  const [sortKey, setSortKey] = useState<IfaceSortKey>("if_index");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const tz = useTimezone();
  const { fromTs, toTs } = useMemo(() => rangeToTimestamps(timeRange), [timeRange]);

  const { data: history } = useInterfaceHistory(
    deviceId,
    fromTs,
    toTs,
    selectedInterfaceId,
    2000,
  );

  // Build metadata lookup
  const metaMap = useMemo(() => {
    const m = new Map<string, { polling_enabled: boolean; alerting_enabled: boolean; poll_metrics: string }>();
    for (const meta of metadata ?? []) {
      m.set(meta.id, { polling_enabled: meta.polling_enabled, alerting_enabled: meta.alerting_enabled, poll_metrics: meta.poll_metrics ?? "all" });
    }
    return m;
  }, [metadata]);

  // Dynamic filter options
  const availableOperStatuses = useMemo(() =>
    [...new Set((interfaces ?? []).map(i => i.if_oper_status))].sort(), [interfaces]);
  const availableSpeeds = useMemo(() =>
    [...new Set((interfaces ?? []).map(i => i.if_speed_mbps))].filter(Boolean).sort((a, b) => a - b), [interfaces]);

  // Filter — supports multiple terms: plain text matches name/alias/index,
  // "o:up" matches oper status, "a:down" matches admin status
  const filtered = useMemo(() => {
    let data = interfaces ?? [];
    if (searchText) {
      const terms = searchText.toLowerCase().split(/\s+/).filter(Boolean);
      data = data.filter(i => {
        return terms.every(term => {
          if (term.startsWith("o:")) {
            const val = term.slice(2);
            return val ? i.if_oper_status.toLowerCase().includes(val) : true;
          }
          if (term.startsWith("a:")) {
            const val = term.slice(2);
            return val ? i.if_admin_status.toLowerCase().includes(val) : true;
          }
          return (
            i.if_name.toLowerCase().includes(term) ||
            i.if_alias.toLowerCase().includes(term) ||
            String(i.if_index).includes(term)
          );
        });
      });
    }
    if (filterOperStatus) data = data.filter(i => i.if_oper_status === filterOperStatus);
    if (filterSpeed) data = data.filter(i => i.if_speed_mbps === Number(filterSpeed));
    return data;
  }, [interfaces, searchText, filterOperStatus, filterSpeed]);

  // Sort
  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      switch (sortKey) {
        case "status": return (a.if_oper_status === "up" ? 0 : 1) - (b.if_oper_status === "up" ? 0 : 1);
        case "if_index": return (a.if_index - b.if_index) * dir;
        case "if_name": return a.if_name.localeCompare(b.if_name) * dir;
        case "if_alias": return (a.if_alias || "").localeCompare(b.if_alias || "") * dir;
        case "speed": return (a.if_speed_mbps - b.if_speed_mbps) * dir;
        case "in_traffic": return (a.in_rate_bps - b.in_rate_bps) * dir;
        case "out_traffic": return (a.out_rate_bps - b.out_rate_bps) * dir;
        case "in_errors": return (a.in_errors - b.in_errors) * dir;
        case "out_errors": return (a.out_errors - b.out_errors) * dir;
        case "last_polled": return a.executed_at.localeCompare(b.executed_at) * dir;
        default: return 0;
      }
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const toggleSort = (key: IfaceSortKey) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("asc"); }
  };

  // Selection helpers
  const filteredIds = useMemo(() => new Set(filtered.map(i => i.interface_id)), [filtered]);
  const allFilteredSelected = filtered.length > 0 && filtered.every(i => selectedIds.has(i.interface_id));
  const someFilteredSelected = filtered.some(i => selectedIds.has(i.interface_id));

  const toggleSelectAll = () => {
    if (allFilteredSelected) {
      // Deselect all filtered
      setSelectedIds(prev => {
        const next = new Set(prev);
        for (const i of filtered) next.delete(i.interface_id);
        return next;
      });
    } else {
      // Select all filtered
      setSelectedIds(prev => {
        const next = new Set(prev);
        for (const i of filtered) next.add(i.interface_id);
        return next;
      });
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Bulk metric toggle for selected interfaces
  const bulkToggleMetric = (metric: string, enable: boolean) => {
    const ids = [...selectedIds].filter(id => filteredIds.has(id));
    if (ids.length === 0) return;

    // For each selected interface, compute new poll_metrics
    for (const id of ids) {
      const meta = metaMap.get(id);
      const current = parseMetrics(meta?.poll_metrics ?? "all");
      if (enable) current.add(metric);
      else current.delete(metric);
      const newVal = serializeMetrics(current);
      updateSettings.mutate({ deviceId, interfaceId: id, data: { poll_metrics: newVal } });
    }
  };

  // Check if all selected interfaces have a given metric enabled
  const selectedHaveMetric = (metric: string): boolean | "mixed" => {
    const ids = [...selectedIds].filter(id => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map(id => parseMetrics(metaMap.get(id)?.poll_metrics ?? "all").has(metric));
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const SortHead = ({ col, children }: { col: IfaceSortKey; children: React.ReactNode }) => (
    <TableHead className="cursor-pointer select-none" onClick={() => toggleSort(col)}>
      <span className="flex items-center gap-1">
        {children}
        {sortKey === col ? (sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ArrowUpDown className="h-3 w-3 text-zinc-600" />}
      </span>
    </TableHead>
  );

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!interfaces?.length) {
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center justify-center text-zinc-500">
            <Network className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No interface data collected yet.</p>
            <p className="text-xs text-zinc-600 mt-1">
              Assign an interface poller app to this device to start collecting data.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const upCount = interfaces.filter((i) => i.if_oper_status === "up").length;
  const downCount = interfaces.filter((i) => i.if_oper_status === "down").length;
  const activeSelectedCount = [...selectedIds].filter(id => filteredIds.has(id)).length;

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-zinc-500">Interfaces:</span>
          <Badge variant="default">{interfaces.length}</Badge>
          <Badge variant="success">{upCount} up</Badge>
          {downCount > 0 && <Badge variant="destructive">{downCount} down</Badge>}
          {activeSelectedCount > 0 && (
            <Badge variant="default">{activeSelectedCount} selected</Badge>
          )}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Input
            placeholder="Search name/alias o:up a:down..."
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            className="h-7 w-64 text-xs"
          />
          {availableOperStatuses.length > 1 && (
            <Select value={filterOperStatus} onChange={e => setFilterOperStatus(e.target.value)} className="h-7 text-xs w-28">
              <option value="">All status</option>
              {availableOperStatuses.map(s => <option key={s} value={s}>{s}</option>)}
            </Select>
          )}
          {availableSpeeds.length > 1 && (
            <Select value={filterSpeed} onChange={e => setFilterSpeed(e.target.value)} className="h-7 text-xs w-28">
              <option value="">All speeds</option>
              {availableSpeeds.map(s => <option key={s} value={String(s)}>{formatSpeed(s)}</option>)}
            </Select>
          )}
          <TimeRangePicker value={timeRange} onChange={setTimeRange} timezone={tz} />
        </div>
      </div>

      {/* Bulk metric controls — shown when interfaces are selected */}
      {activeSelectedCount > 0 && (
        <Card>
          <CardContent className="py-2">
            <div className="flex items-center gap-6 text-xs">
              <span className="text-zinc-400 font-medium">Metrics for {activeSelectedCount} selected:</span>
              {METRIC_TYPES.map(metric => {
                const state = selectedHaveMetric(metric);
                return (
                  <label key={metric} className="flex items-center gap-1.5 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={state === true}
                      ref={el => { if (el) el.indeterminate = state === "mixed"; }}
                      onChange={() => bulkToggleMetric(metric, state !== true)}
                      className="accent-brand-500 cursor-pointer"
                    />
                    <span className="text-zinc-300 capitalize">{metric}</span>
                  </label>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Traffic chart for selected interface */}
      {selectedInterfaceId != null && history?.length ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-zinc-400 flex items-center gap-2">
              Traffic — {interfaces.find((i) => i.interface_id === selectedInterfaceId)?.if_name ?? selectedInterfaceId}
              <button
                onClick={() => setSelectedInterfaceId(null)}
                className="ml-2 text-zinc-600 hover:text-zinc-300 cursor-pointer"
              >
                <X className="h-3.5 w-3.5 inline" />
              </button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <InterfaceTrafficChart data={history} timezone={tz} />
          </CardContent>
        </Card>
      ) : null}

      {/* Interface table */}
      <Card>
        <CardContent className="pt-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" onClick={e => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={allFilteredSelected}
                    ref={el => { if (el) el.indeterminate = !allFilteredSelected && someFilteredSelected; }}
                    onChange={toggleSelectAll}
                    className="accent-brand-500 cursor-pointer"
                  />
                </TableHead>
                <SortHead col="status">Status</SortHead>
                <SortHead col="if_index">Index</SortHead>
                <SortHead col="if_name">Name</SortHead>
                <SortHead col="if_alias">Alias</SortHead>
                <SortHead col="speed">Speed</SortHead>
                <SortHead col="in_traffic">In Traffic</SortHead>
                <SortHead col="out_traffic">Out Traffic</SortHead>
                <SortHead col="in_errors">In Err</SortHead>
                <SortHead col="out_errors">Out Err</SortHead>
                <SortHead col="last_polled">Last Polled</SortHead>
                <TableHead className="w-14 text-center">Poll</TableHead>
                <TableHead className="w-14 text-center">Alert</TableHead>
                <TableHead className="text-center">Traffic</TableHead>
                <TableHead className="text-center">Errors</TableHead>
                <TableHead className="text-center">Discards</TableHead>
                <TableHead className="text-center">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((iface) => {
                const meta = metaMap.get(iface.interface_id);
                const pollingOn = meta?.polling_enabled ?? true;
                const alertingOn = meta?.alerting_enabled ?? true;
                const metrics = parseMetrics(meta?.poll_metrics ?? "all");
                const isSelected = selectedIds.has(iface.interface_id);

                const toggleMetric = (metric: string) => {
                  const next = new Set(metrics);
                  if (next.has(metric)) next.delete(metric);
                  else next.add(metric);
                  updateSettings.mutate({
                    deviceId,
                    interfaceId: iface.interface_id,
                    data: { poll_metrics: serializeMetrics(next) },
                  });
                };

                return (
                <TableRow
                  key={iface.interface_id}
                  className={`cursor-pointer transition-colors ${
                    selectedInterfaceId === iface.interface_id
                      ? "bg-brand-500/10"
                      : isSelected
                        ? "bg-zinc-800/70"
                        : "hover:bg-zinc-800/50"
                  }`}
                  onClick={() =>
                    setSelectedInterfaceId(
                      selectedInterfaceId === iface.interface_id ? null : iface.interface_id,
                    )
                  }
                >
                  <TableCell onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(iface.interface_id)}
                      className="accent-brand-500 cursor-pointer"
                    />
                  </TableCell>
                  <TableCell>
                    <div
                      className={`h-2.5 w-2.5 rounded-full ${
                        iface.if_oper_status === "up"
                          ? "bg-emerald-500"
                          : iface.if_oper_status === "down"
                            ? "bg-red-500"
                            : "bg-zinc-600"
                      }`}
                    />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-zinc-500">
                    {iface.if_index}
                  </TableCell>
                  <TableCell className="font-medium text-zinc-100">
                    {iface.if_name}
                  </TableCell>
                  <TableCell className="text-zinc-400 text-sm">
                    {iface.if_alias || "\u2014"}
                  </TableCell>
                  <TableCell className="text-zinc-300 text-sm">
                    {formatSpeed(iface.if_speed_mbps)}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-cyan-400">
                    {iface.in_rate_bps > 0
                      ? formatBps(iface.in_rate_bps)
                      : "\u2014"}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-indigo-400">
                    {iface.out_rate_bps > 0
                      ? formatBps(iface.out_rate_bps)
                      : "\u2014"}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    <span className={iface.in_errors > 0 ? "text-amber-400" : "text-zinc-600"}>
                      {iface.in_errors.toLocaleString()}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    <span className={iface.out_errors > 0 ? "text-amber-400" : "text-zinc-600"}>
                      {iface.out_errors.toLocaleString()}
                    </span>
                  </TableCell>
                  <TableCell className="text-zinc-500 text-xs">
                    {timeAgo(iface.executed_at)}
                  </TableCell>
                  <TableCell className="text-center" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={pollingOn}
                      onChange={() => updateSettings.mutate({
                        deviceId,
                        interfaceId: iface.interface_id,
                        data: { polling_enabled: !pollingOn },
                      })}
                      className="accent-brand-500 cursor-pointer"
                    />
                  </TableCell>
                  <TableCell className="text-center" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={alertingOn}
                      onChange={() => updateSettings.mutate({
                        deviceId,
                        interfaceId: iface.interface_id,
                        data: { alerting_enabled: !alertingOn },
                      })}
                      className="accent-amber-500 cursor-pointer"
                    />
                  </TableCell>
                  <TableCell className="text-center" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={metrics.has("traffic")}
                      onChange={() => toggleMetric("traffic")}
                      className="accent-cyan-500 cursor-pointer"
                    />
                  </TableCell>
                  <TableCell className="text-center" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={metrics.has("errors")}
                      onChange={() => toggleMetric("errors")}
                      className="accent-amber-500 cursor-pointer"
                    />
                  </TableCell>
                  <TableCell className="text-center" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={metrics.has("discards")}
                      onChange={() => toggleMetric("discards")}
                      className="accent-orange-500 cursor-pointer"
                    />
                  </TableCell>
                  <TableCell className="text-center" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={metrics.has("status")}
                      onChange={() => toggleMetric("status")}
                      className="accent-emerald-500 cursor-pointer"
                    />
                  </TableCell>
                </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Monitoring Config Card ────────────────────────────────

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

// Renders config fields dynamically from an app's config_schema
function SchemaConfigFields({
  schema,
  config,
  onChange,
  prefix,
  disabled,
}: {
  schema: Record<string, unknown> | null | undefined;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  prefix: string;
  disabled?: boolean;
}) {
  const { data: snmpOids } = useSnmpOids();
  const { data: credentials } = useCredentials();

  if (!schema || typeof schema !== "object") return null;
  const properties = (schema as { properties?: Record<string, Record<string, unknown>> }).properties;
  if (!properties) return null;

  const setField = (key: string, value: unknown) => {
    onChange({ ...config, [key]: value });
  };

  return (
    <>
      {Object.entries(properties).map(([key, prop]) => {
        const widget = prop["x-widget"] as string | undefined;
        const title = (prop.title as string) ?? key;
        const defaultVal = prop.default;
        const currentVal = config[key] ?? defaultVal ?? "";

        // SNMP OID selector
        if (widget === "snmp-oid") {
          return (
            <div key={key} className="space-y-1">
              <span className="text-xs text-zinc-400">{title}</span>
              <Select
                id={`${prefix}-${key}`}
                value={String(currentVal)}
                onChange={(e) => setField(key, e.target.value)}
                disabled={disabled}
              >
                <option value="">-- {title} --</option>
                {(snmpOids ?? []).map((o) => (
                  <option key={o.id} value={o.oid}>{o.name} ({o.oid})</option>
                ))}
              </Select>
            </div>
          );
        }

        // Credential selector
        if (widget === "credential") {
          // Strip "$credential:" prefix for display — stored as "$credential:name"
          const credName = typeof currentVal === "string" && currentVal.startsWith("$credential:")
            ? currentVal.slice("$credential:".length)
            : String(currentVal);
          return (
            <div key={key} className="space-y-1">
              <span className="text-xs text-zinc-400">{title}</span>
              <Select
                id={`${prefix}-${key}`}
                value={credName}
                onChange={(e) => setField(key, e.target.value ? `$credential:${e.target.value}` : "")}
                disabled={disabled}
              >
                <option value="">-- {title} --</option>
                {(credentials ?? []).map((c) => (
                  <option key={c.id} value={c.name}>{c.name}</option>
                ))}
              </Select>
            </div>
          );
        }

        // Number input
        if (prop.type === "integer" || prop.type === "number") {
          return (
            <div key={key} className="space-y-1">
              <span className="text-xs text-zinc-400">{title}</span>
              <Input
                id={`${prefix}-${key}`}
                type="number"
                min={prop.minimum as number | undefined}
                max={prop.maximum as number | undefined}
                value={currentVal !== "" ? String(currentVal) : String(defaultVal ?? "")}
                onChange={(e) => setField(key, e.target.value ? parseInt(e.target.value, 10) : undefined)}
                className="w-28"
                disabled={disabled}
              />
            </div>
          );
        }

        // Default: text input
        return (
          <div key={key} className="space-y-1">
            <span className="text-xs text-zinc-400">{title}</span>
            <Input
              id={`${prefix}-${key}`}
              value={String(currentVal)}
              onChange={(e) => setField(key, e.target.value)}
              disabled={disabled}
            />
          </div>
        );
      })}
    </>
  );
}

function MonitoringCard({ deviceId, device }: { deviceId: string; device: DeviceType | undefined }) {
  const { data: monitoring, isLoading: monLoading } = useDeviceMonitoring(deviceId);
  const { data: allApps } = useApps();
  const updateMonitoring = useUpdateDeviceMonitoring();

  // Only apps targeting availability_latency can be used for avail/latency monitoring
  const monitoringApps = useMemo(
    () => (allApps ?? []).filter((a) => a.target_table === "availability_latency"),
    [allApps],
  );

  // Interface-capable apps (target_table = "interface")
  const interfaceApps = useMemo(
    () => (allApps ?? []).filter((a) => a.target_table === "interface"),
    [allApps],
  );

  // System default for interface interval
  const { data: systemSettings } = useSystemSettings();
  const systemDefaultInterval = systemSettings?.interface_poll_interval_seconds ?? "300";

  // Fetch config_schema for selected apps
  const [availAppName, setAvailAppName] = useState("");
  const [latencyAppName, setLatencyAppName] = useState("");
  const [availConfig, setAvailConfig] = useState<Record<string, unknown>>({});
  const [latencyConfig, setLatencyConfig] = useState<Record<string, unknown>>({});
  const [intervalSeconds, setIntervalSeconds] = useState("60");
  const [interfaceAppName, setInterfaceAppName] = useState("");
  const [interfaceConfig, setInterfaceConfig] = useState<Record<string, unknown>>({});
  const [interfaceInterval, setInterfaceInterval] = useState("300");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const selectedAvApp = monitoringApps.find((a) => a.name === availAppName);
  const selectedLatApp = monitoringApps.find((a) => a.name === latencyAppName);
  const selectedIfaceApp = interfaceApps.find((a) => a.name === interfaceAppName);
  const { data: avAppDetail } = useAppDetail(selectedAvApp?.id);
  const { data: latAppDetail } = useAppDetail(selectedLatApp?.id);
  const { data: ifaceAppDetail } = useAppDetail(selectedIfaceApp?.id);

  // Sync state when monitoring data loads
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
    setInterfaceInterval(String(iface?.interval_seconds ?? systemDefaultInterval));
  }, [monitoring, systemDefaultInterval]);

  function handleAppChange(role: "availability" | "latency", newAppName: string) {
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

    const makeCheck = (appName: string, config: Record<string, unknown>, interval: string) => {
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
          interface: makeCheck(interfaceAppName, interfaceConfig, interfaceInterval),
        },
      });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save monitoring config");
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
            This device must be assigned to a collector group before monitoring can be enabled.
          </div>
        )}
        {monLoading ? (
          <div className="flex h-16 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-brand-500" />
          </div>
        ) : (
          <form onSubmit={handleSave} className="space-y-5 max-w-2xl">
            {/* Shared interval */}
            <div className="space-y-1.5">
              <Label htmlFor="mon-interval">Check Interval</Label>
              <Select
                id="mon-interval"
                value={intervalSeconds}
                onChange={(e) => setIntervalSeconds(e.target.value)}
                disabled={!hasGroup}
              >
                {INTERVAL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </div>

            {/* Availability check */}
            <div className="space-y-2">
              <Label>Availability Check</Label>
              <div className="flex items-end gap-3 flex-wrap">
                <div className="space-y-1">
                  <Select
                    value={availAppName}
                    onChange={(e) => handleAppChange("availability", e.target.value)}
                    disabled={!hasGroup}
                  >
                    <option value="">None</option>
                    {monitoringApps.map((a) => (
                      <option key={a.id} value={a.name}>{a.description || a.name}</option>
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
                  />
                )}
              </div>
            </div>

            {/* Latency check */}
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
                      <option key={a.id} value={a.name}>{a.description || a.name}</option>
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
                  />
                )}
              </div>
            </div>

            {/* ── Interface Polling ─────────────────────── */}
            <div className="border-t border-zinc-800 pt-4 mt-4">
              <div className="flex items-center gap-2 mb-3">
                <Network className="h-4 w-4 text-zinc-400" />
                <span className="text-sm font-medium text-zinc-200">Interface Polling</span>
              </div>

              <div className="space-y-3">
                <div className="space-y-1">
                  <span className="text-xs text-zinc-400">Interface Poller App</span>
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
                          (system default: {INTERFACE_INTERVAL_OPTIONS.find((o) => o.value === systemDefaultInterval)?.label ?? `${systemDefaultInterval}s`})
                        </span>
                      </span>
                      <Select
                        value={interfaceInterval}
                        onChange={(e) => setInterfaceInterval(e.target.value)}
                        disabled={!hasGroup}
                      >
                        {INTERFACE_INTERVAL_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </Select>
                    </div>

                    <SchemaConfigFields
                      schema={ifaceAppDetail?.config_schema}
                      config={interfaceConfig}
                      onChange={setInterfaceConfig}
                      prefix="iface"
                      disabled={!hasGroup}
                    />
                  </>
                )}
              </div>
            </div>

            {saveError && <p className="text-sm text-red-400">{saveError}</p>}
            {saveSuccess && <p className="text-sm text-emerald-400">Monitoring configuration saved.</p>}

            <Button type="submit" size="sm" disabled={updateMonitoring.isPending || !hasGroup}>
              {updateMonitoring.isPending
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : <Save className="h-4 w-4" />}
              Save Monitoring
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

// ── Tab: Assignments ──────────────────────────────────────

const ROLE_COLORS: Record<string, string> = {
  availability: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  latency: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  interface: "bg-purple-500/15 text-purple-400 border-purple-500/30",
};

function formatInterval(seconds: number): string {
  if (seconds >= 600) return `${seconds / 60}m`;
  if (seconds >= 60) return `${seconds / 60}m`;
  return `${seconds}s`;
}

function AssignmentsTab({ deviceId }: { deviceId: string }) {
  const { data: device } = useDevice(deviceId);
  const { data: assignments, isLoading } = useDeviceAssignments(deviceId);
  const deleteAssignment = useDeleteAssignment();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [applyTemplateOpen, setApplyTemplateOpen] = useState(false);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!assignments || assignments.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex flex-col items-center justify-center h-48 text-zinc-500 gap-2">
          <ListChecks className="h-10 w-10 text-zinc-600" />
          <p className="text-sm">No app assignments for this device.</p>
          <Button size="sm" variant="secondary" className="mt-2 gap-1.5" onClick={() => setAddOpen(true)}>
            <Plus className="h-3.5 w-3.5" /> Assign App
          </Button>
        </div>
        <AddAssignmentDialog
          deviceId={deviceId}
          deviceCollectorGroupId={device?.collector_group_id ?? null}
          deviceCollectorGroupName={device?.collector_group_name ?? null}
          open={addOpen}
          onClose={() => setAddOpen(false)}
        />
      </div>
    );
  }

  const editing = editingId ? assignments.find((a) => a.id === editingId) : null;
  const deleting = deleteConfirmId ? assignments.find((a) => a.id === deleteConfirmId) : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-500">{assignments.length} assignment{assignments.length !== 1 ? "s" : ""}</p>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setApplyTemplateOpen(true)} className="gap-1.5">
            <FileText className="h-3.5 w-3.5" /> Apply Template
          </Button>
          <Button size="sm" onClick={() => setAddOpen(true)} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" /> Assign App
          </Button>
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs py-1">App</TableHead>
            <TableHead className="text-xs py-1">Role</TableHead>
            <TableHead className="text-xs py-1">Interval</TableHead>
            <TableHead className="text-xs py-1">Connectors</TableHead>
            <TableHead className="text-xs py-1">Enabled</TableHead>
            <TableHead className="text-xs py-1 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {assignments.map((a) => (
            <TableRow key={a.id}>
              <TableCell className="py-1.5 font-mono text-sm">{a.app.name}</TableCell>
              <TableCell className="py-1.5">
                {a.role ? (
                  <Badge className={`text-[10px] ${ROLE_COLORS[a.role] ?? "bg-zinc-500/15 text-zinc-400 border-zinc-500/30"}`}>
                    {a.role}
                  </Badge>
                ) : (
                  <span className="text-zinc-600 text-xs">{"\u2014"}</span>
                )}
              </TableCell>
              <TableCell className="py-1.5 text-xs font-mono text-zinc-400">
                {a.schedule_type === "interval" ? formatInterval(Number(a.schedule_value)) : a.schedule_value}
              </TableCell>
              <TableCell className="py-1.5">
                {a.connector_bindings && a.connector_bindings.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {a.connector_bindings.map((cb) => (
                      <Badge key={cb.id || cb.alias} variant="info" className="text-[10px] gap-1">
                        <Plug className="h-2.5 w-2.5" />
                        {cb.alias}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <span className="text-zinc-600 text-xs">{"\u2014"}</span>
                )}
              </TableCell>
              <TableCell className="py-1.5">
                <Badge variant={a.enabled ? "success" : "default"} className="text-[10px]">
                  {a.enabled ? "enabled" : "disabled"}
                </Badge>
              </TableCell>
              <TableCell className="py-1.5 text-right">
                <div className="flex items-center justify-end gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 w-6 p-0"
                    onClick={() => setEditingId(a.id)}
                    title="Edit"
                  >
                    <Pencil className="h-3 w-3" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 w-6 p-0 text-red-400 hover:text-red-300"
                    onClick={() => setDeleteConfirmId(a.id)}
                    title="Delete"
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {/* Delete confirmation dialog */}
      {deleting && (
        <Dialog open={!!deleteConfirmId} onClose={() => setDeleteConfirmId(null)} title="Delete Assignment">
          <p className="text-sm text-zinc-300 mb-4">
            Are you sure you want to delete the <span className="font-mono font-semibold">{deleting.app.name}</span> assignment?
            This will stop monitoring and delete associated data.
          </p>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setDeleteConfirmId(null)}>Cancel</Button>
            <Button
              variant="destructive"
              onClick={async () => {
                await deleteAssignment.mutateAsync(deleting.id);
                setDeleteConfirmId(null);
              }}
              disabled={deleteAssignment.isPending}
            >
              {deleteAssignment.isPending && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              Delete
            </Button>
          </DialogFooter>
        </Dialog>
      )}

      {/* Edit dialog uses the existing EditAssignmentDialog */}
      <EditAssignmentDialog
        assignment={editing ?? null}
        open={!!editingId}
        onClose={() => setEditingId(null)}
      />

      <AddAssignmentDialog
        deviceId={deviceId}
        deviceCollectorGroupId={device?.collector_group_id ?? null}
        deviceCollectorGroupName={device?.collector_group_name ?? null}
        open={addOpen}
        onClose={() => setAddOpen(false)}
      />

      <ApplyTemplateDialog
        open={applyTemplateOpen}
        onClose={() => setApplyTemplateOpen(false)}
        deviceIds={[deviceId]}
        deviceName={device?.name}
      />
    </div>
  );
}

// ── Tab: Settings ──────────────────────────────────────

function SettingsTab({ deviceId }: { deviceId: string }) {
  const { data: device, isLoading: deviceLoading } = useDevice(deviceId);
  const { data: deviceTypes } = useDeviceTypes();
  const { data: tenants } = useTenants();
  const { data: collectorGroups } = useCollectorGroups();
  const updateDevice = useUpdateDevice();

  // Device fields
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [deviceType, setDeviceType] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [collectorGroupId, setCollectorGroupId] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Labels
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [labelsModified, setLabelsModified] = useState(false);
  const [labelsSaving, setLabelsSaving] = useState(false);
  const [labelsSaveSuccess, setLabelsSaveSuccess] = useState(false);
  const [labelError, setLabelError] = useState<string | null>(null);

  // Initialize form fields when device loads
  useEffect(() => {
    if (device) {
      setName(device.name);
      setAddress(device.address);
      setDeviceType(device.device_type);
      setTenantId(device.tenant_id ?? "");
      setCollectorGroupId(device.collector_group_id ?? "");
      setLabels(device.labels ?? {});
    }
  }, [device]);

  async function handleSaveDevice(e: React.FormEvent) {
    e.preventDefault();
    setSaveError(null);
    setSaveSuccess(false);
    try {
      await updateDevice.mutateAsync({
        id: deviceId,
        data: {
          name: name.trim(),
          address: address.trim(),
          device_type: deviceType,
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
          name: name.trim(),
          address: address.trim(),
          device_type: deviceType,
          tenant_id: tenantId || null,
          collector_group_id: collectorGroupId || null,
          labels,
        },
      });
      setLabelsModified(false);
      setLabelsSaveSuccess(true);
      setTimeout(() => setLabelsSaveSuccess(false), 3000);
    } catch (err) {
      setLabelError(err instanceof Error ? err.message : "Failed to save labels");
    } finally {
      setLabelsSaving(false);
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
      {/* Edit Device */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Device Settings
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSaveDevice} className="space-y-4 max-w-md">
            <div className="space-y-1.5">
              <Label htmlFor="s-name">Name</Label>
              <Input id="s-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="s-address">Address</Label>
              <Input id="s-address" value={address} onChange={(e) => setAddress(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="s-dtype">Device Type</Label>
              <Select id="s-dtype" value={deviceType} onChange={(e) => setDeviceType(e.target.value)}>
                {(deviceTypes ?? []).map((dt) => (
                  <option key={dt.id} value={dt.name}>{dt.name}</option>
                ))}
              </Select>
            </div>
            {tenants && tenants.length > 0 && (
              <div className="space-y-1.5">
                <Label htmlFor="s-tenant">Tenant</Label>
                <Select id="s-tenant" value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
                  <option value="">— No tenant —</option>
                  {tenants.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="s-cgroup">Collector Group</Label>
              <Select id="s-cgroup" value={collectorGroupId} onChange={(e) => setCollectorGroupId(e.target.value)}>
                <option value="">— No group —</option>
                {(collectorGroups ?? []).map((g) => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </Select>
            </div>
            {saveError && <p className="text-sm text-red-400">{saveError}</p>}
            {saveSuccess && <p className="text-sm text-emerald-400">Saved successfully.</p>}
            <Button type="submit" size="sm" disabled={updateDevice.isPending}>
              {updateDevice.isPending
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : <Save className="h-4 w-4" />}
              Save Changes
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Labels */}
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
                {labelsSaving
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <Save className="h-4 w-4" />}
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
          {labelError && <p className="text-xs text-red-400 mt-2">{labelError}</p>}
        </CardContent>
      </Card>

      {/* Monitoring Configuration */}
      <MonitoringCard deviceId={deviceId} device={device} />
    </div>
  );
}

// ── Sortable Header helper ───────────────────────────────

type SortDir = "asc" | "desc";

function SortableHead({
  label,
  field,
  sortBy,
  sortDir,
  onSort,
}: {
  label: string;
  field: string;
  sortBy: string;
  sortDir: SortDir;
  onSort: (field: string) => void;
}) {
  const active = sortBy === field;
  return (
    <TableHead
      className="cursor-pointer select-none hover:text-zinc-200"
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
        ) : (
          <ArrowUpDown className="h-3 w-3 text-zinc-600" />
        )}
      </span>
    </TableHead>
  );
}

function useSort(defaultField: string, defaultDir: SortDir = "desc") {
  const [sortBy, setSortBy] = useState(defaultField);
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir);
  const toggle = useCallback((field: string) => {
    if (field === sortBy) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(field);
      setSortDir("desc");
    }
  }, [sortBy]);
  return { sortBy, sortDir, toggle };
}

// ── Tab 5: History ───────────────────────────────────────

function HistoryTab({ deviceId }: { deviceId: string }) {
  const tz = useTimezone();
  const [range, setRange] = useState<TimeRangeValue>({ type: "preset", preset: "24h" });
  const { fromTs: from } = useMemo(() => rangeToTimestamps(range), [range]);
  const { data: history, isLoading } = useDeviceHistory(deviceId, from, null, 500);
  const { sortBy, sortDir, toggle: onSort } = useSort("executed_at");
  const [filterApp, setFilterApp] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterCollector, setFilterCollector] = useState("");

  const records = history ?? [];

  // Unique values for filter dropdowns
  const appNames = useMemo(() => [...new Set(records.map((r) => r.app_name).filter(Boolean))].sort(), [records]);
  const statuses = useMemo(() => [...new Set(records.map((r) => r.state_name).filter(Boolean))].sort(), [records]);
  const collectors = useMemo(() => [...new Set(records.map((r) => r.collector_name).filter(Boolean))].sort(), [records]);

  // Filter + sort
  const filtered = useMemo(() => {
    let data = records;
    if (filterApp) data = data.filter((r) => r.app_name === filterApp);
    if (filterStatus) data = data.filter((r) => r.state_name === filterStatus);
    if (filterCollector) data = data.filter((r) => r.collector_name === filterCollector);

    return [...data].sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case "app_name": cmp = (a.app_name ?? "").localeCompare(b.app_name ?? ""); break;
        case "started_at": cmp = (a.started_at ?? "").localeCompare(b.started_at ?? ""); break;
        case "executed_at": cmp = a.executed_at.localeCompare(b.executed_at); break;
        case "duration": {
          const da = a.execution_time_ms ?? 0;
          const db = b.execution_time_ms ?? 0;
          cmp = da - db;
          break;
        }
        case "collector": cmp = (a.collector_name ?? "").localeCompare(b.collector_name ?? ""); break;
        case "status": cmp = (a.state_name ?? "").localeCompare(b.state_name ?? ""); break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [records, filterApp, filterStatus, filterCollector, sortBy, sortDir]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Job Execution History
            <span className="text-zinc-500 font-normal text-xs ml-1">
              ({filtered.length}{filtered.length !== records.length ? ` of ${records.length}` : ""} results)
            </span>
          </CardTitle>
          <TimeRangePicker value={range} onChange={setRange} timezone={tz} />
        </div>
        {/* Filters */}
        <div className="flex items-center gap-2 pt-2">
          <Select value={filterApp} onChange={(e) => setFilterApp(e.target.value)} className="w-40 text-xs">
            <option value="">All Apps</option>
            {appNames.map((n) => <option key={n} value={n!}>{n}</option>)}
          </Select>
          <Select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="w-36 text-xs">
            <option value="">All Statuses</option>
            {statuses.map((s) => <option key={s} value={s!}>{s}</option>)}
          </Select>
          <Select value={filterCollector} onChange={(e) => setFilterCollector(e.target.value)} className="w-40 text-xs">
            <option value="">All Collectors</option>
            {collectors.map((c) => <option key={c} value={c!}>{c}</option>)}
          </Select>
          {(filterApp || filterStatus || filterCollector) && (
            <Button variant="ghost" size="sm" onClick={() => { setFilterApp(""); setFilterStatus(""); setFilterCollector(""); }}>
              <X className="h-3 w-3" /> Clear
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {filtered.length === 0 ? (
          <p className="text-sm text-zinc-500 py-8 text-center">No results match the current filters.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <SortableHead label="App" field="app_name" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                <SortableHead label="Started" field="started_at" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                <SortableHead label="Completed" field="executed_at" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                <SortableHead label="Duration" field="duration" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                <SortableHead label="Collector" field="collector" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
                <SortableHead label="Status" field="status" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((r, i) => {
                const startedAt = r.started_at ? new Date(r.started_at) : null;
                const executedAt = new Date(r.executed_at);
                const durationMs = r.execution_time_ms ?? (startedAt ? executedAt.getTime() - startedAt.getTime() : null);
                return (
                  <TableRow key={`${r.assignment_id}-${i}`}>
                    <TableCell className="font-medium text-zinc-200">{r.app_name ?? "—"}</TableCell>
                    <TableCell className="text-zinc-400 text-xs">
                      {startedAt ? formatDate(startedAt.toISOString(), tz) : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-xs">
                      {formatDate(r.executed_at, tz)}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-300">
                      {durationMs != null ? `${Math.round(durationMs)}ms` : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {r.collector_name ?? "—"}
                    </TableCell>
                    <TableCell>
                      <StatusBadge state={r.state_name} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ── Tab: Alerts ──────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  const variants: Record<string, string> = {
    info: "bg-blue-500/15 text-blue-400 border-blue-500/20",
    warning: "bg-amber-500/15 text-amber-400 border-amber-500/20",
    critical: "bg-red-500/15 text-red-400 border-red-500/20",
    emergency: "bg-purple-500/15 text-purple-400 border-purple-500/20",
    recovery: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  };
  return (
    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium ${variants[severity] ?? variants.warning}`}>
      {severity}
    </span>
  );
}

function AlertsTab({ deviceId }: { deviceId: string }) {
  const { data: instances, isLoading } = useAlertInstances({ device_id: deviceId });
  const updateInstance = useUpdateAlertInstance();

  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!instances || instances.length === 0) {
    return (
      <Card>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Bell className="h-10 w-10 mb-3 text-zinc-600" />
            <p className="text-sm">No alert definitions for this device</p>
            <p className="text-xs text-zinc-600 mt-1">
              Alert definitions are created on apps and automatically applied when assigned
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Group by app name
  const grouped: Record<string, typeof instances> = {};
  for (const inst of instances) {
    const key = inst.app_name ?? "Unknown";
    (grouped[key] ??= []).push(inst);
  }

  return (
    <div className="space-y-4">
      {Object.entries(grouped).map(([appName, appInstances]) => (
        <Card key={appName}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              {appName}
              <Badge variant="default" className="text-xs">{appInstances.length}</Badge>
              {appInstances.some((i) => i.state === "firing") && (
                <Badge variant="destructive" className="text-xs">
                  {appInstances.filter((i) => i.state === "firing").length} firing
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[80px]">State</TableHead>
                  <TableHead>Alert Name</TableHead>
                  <TableHead>Expression</TableHead>
                  <TableHead className="w-[90px]">Severity</TableHead>
                  <TableHead className="w-[80px]">Value</TableHead>
                  <TableHead className="w-[100px]">Firing Since</TableHead>
                  <TableHead className="w-[70px] text-center">Enabled</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {appInstances.map((inst) => (
                  <TableRow key={inst.id}>
                    <TableCell>
                      <Badge variant={inst.state === "firing" ? "destructive" : "success"}>
                        {inst.state}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-medium text-zinc-200">
                      {inst.definition_name ?? "\u2014"}
                      {inst.entity_labels?.if_name && (
                        <span className="ml-1.5 text-xs text-zinc-500">
                          ({inst.entity_labels.if_name})
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-400 max-w-[250px] truncate">
                      {inst.definition_expression ?? "\u2014"}
                    </TableCell>
                    <TableCell>
                      <SeverityBadge severity={inst.definition_severity ?? "warning"} />
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-300">
                      {inst.current_value != null ? Number(inst.current_value).toFixed(1) : "\u2014"}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-xs">
                      {inst.state === "firing" && inst.started_at ? timeAgo(inst.started_at) : "\u2014"}
                    </TableCell>
                    <TableCell className="text-center">
                      <input
                        type="checkbox"
                        checked={inst.enabled}
                        onChange={() => updateInstance.mutate({ id: inst.id, enabled: !inst.enabled })}
                        className="accent-brand-500 cursor-pointer"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Thresholds Tab ───────────────────────────────────────

function ThresholdsTab({ deviceId }: { deviceId: string }) {
  const { data: thresholds, isLoading } = useDeviceThresholds(deviceId);
  const updateInstance = useUpdateAlertInstance();
  const createOverride = useCreateThresholdOverride();
  const updateOverride = useUpdateThresholdOverride();
  const deleteOverride = useDeleteThresholdOverride();

  const severityVariant = (severity: string) => {
    switch (severity?.toLowerCase()) {
      case "critical":
      case "emergency":
        return "destructive" as const;
      case "warning":
        return "warning" as const;
      case "recovery":
        return "success" as const;
      case "info":
        return "info" as const;
      default:
        return "default" as const;
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!thresholds || thresholds.length === 0) {
    return (
      <Card>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Bell className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No alert definitions for this device</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Group by app_name
  const grouped = thresholds.reduce<Record<string, DeviceThresholdRow[]>>((acc, row) => {
    const key = row.app_name || "Unknown";
    if (!acc[key]) acc[key] = [];
    acc[key].push(row);
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {Object.entries(grouped).map(([appName, rows]) => (
        <Card key={appName}>
          <CardHeader>
            <CardTitle className="text-sm">{appName}</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Alert Name</TableHead>
                  <TableHead>Expression</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Default</TableHead>
                  <TableHead>Override</TableHead>
                  <TableHead>Enabled</TableHead>
                  <TableHead>State</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <ThresholdRow
                    key={row.definition_id}
                    row={row}
                    severityVariant={severityVariant}
                    onToggleEnabled={(id, enabled) =>
                      updateInstance.mutate({ id, enabled })
                    }
                    onSaveOverride={(defId, overrides, existingId) => {
                      if (existingId) {
                        updateOverride.mutate({ id: existingId, overrides });
                      } else {
                        createOverride.mutate({
                          definition_id: defId,
                          device_id: deviceId,
                          overrides,
                        });
                      }
                    }}
                    onDeleteOverride={(id) => deleteOverride.mutate(id)}
                  />
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ThresholdRow({
  row,
  severityVariant,
  onToggleEnabled,
  onSaveOverride,
  onDeleteOverride,
}: {
  row: DeviceThresholdRow;
  severityVariant: (s: string) => "destructive" | "warning" | "success" | "info" | "default";
  onToggleEnabled: (id: string, enabled: boolean) => void;
  onSaveOverride: (defId: string, overrides: Record<string, number | string>, existingId?: string) => void;
  onDeleteOverride: (id: string) => void;
}) {
  const [editValue, setEditValue] = useState<string>("");
  const [editing, setEditing] = useState(false);

  const firstThreshold = row.default_thresholds[0];
  const overrideValue = row.override?.overrides?.[firstThreshold?.name];

  const handleSave = () => {
    if (!firstThreshold) return;
    const val = parseFloat(editValue);
    if (isNaN(val)) return;
    onSaveOverride(
      row.definition_id,
      { [firstThreshold.name]: val },
      row.override?.id
    );
    setEditing(false);
  };

  return (
    <TableRow>
      <TableCell className="font-medium text-zinc-100">{row.name}</TableCell>
      <TableCell className="text-zinc-400 font-mono text-xs max-w-xs truncate">
        {row.expression}
      </TableCell>
      <TableCell>
        <Badge variant={severityVariant(row.severity)}>{row.severity}</Badge>
      </TableCell>
      <TableCell className="text-zinc-400">
        {firstThreshold ? `${firstThreshold.default}` : "—"}
      </TableCell>
      <TableCell>
        {editing ? (
          <div className="flex items-center gap-1">
            <Input
              className="w-20 h-7 text-xs"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSave();
                if (e.key === "Escape") setEditing(false);
              }}
              autoFocus
            />
            <Button size="sm" variant="ghost" className="h-7 px-1" onClick={handleSave}>
              <Save className="h-3 w-3" />
            </Button>
            <Button size="sm" variant="ghost" className="h-7 px-1" onClick={() => setEditing(false)}>
              <X className="h-3 w-3" />
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-1">
            <span
              className={`text-sm cursor-pointer ${overrideValue != null ? "text-brand-400 font-medium" : "text-zinc-500"}`}
              onClick={() => {
                setEditValue(
                  overrideValue != null
                    ? String(overrideValue)
                    : firstThreshold
                      ? String(firstThreshold.default)
                      : ""
                );
                setEditing(true);
              }}
            >
              {overrideValue != null ? String(overrideValue) : "—"}
            </span>
            {row.override && (
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-1 text-zinc-500 hover:text-red-400"
                onClick={() => onDeleteOverride(row.override!.id)}
              >
                <X className="h-3 w-3" />
              </Button>
            )}
          </div>
        )}
      </TableCell>
      <TableCell>
        {row.instance_id && (
          <button
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium cursor-pointer ${
              row.instance_enabled
                ? "bg-emerald-500/20 text-emerald-400"
                : "bg-zinc-700/50 text-zinc-500"
            }`}
            onClick={() =>
              onToggleEnabled(row.instance_id!, !row.instance_enabled)
            }
          >
            {row.instance_enabled ? "On" : "Off"}
          </button>
        )}
      </TableCell>
      <TableCell>
        {row.instance_state && (
          <Badge
            variant={row.instance_state === "firing" ? "destructive" : "success"}
          >
            {row.instance_state}
          </Badge>
        )}
      </TableCell>
    </TableRow>
  );
}


// ── Main Page ────────────────────────────────────────────

export function DeviceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: deviceResults, isLoading: resultsLoading } = useDeviceResults(id);
  const { data: device, isLoading: deviceLoading } = useDevice(id);
  const [activeTab, setActiveTab] = useState("overview");

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

  // Use device data as primary source, deviceResults as supplement
  const deviceName = device?.name ?? deviceResults?.device_name ?? "Unknown";
  const deviceAddress = device?.address ?? deviceResults?.device_address ?? "";
  const deviceType = device?.device_type ?? deviceResults?.device_type ?? "";
  const deviceId = id!;
  const upStatus = deviceResults?.up;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="space-y-1.5">
        <Link to="/devices">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4" />
            Back to Devices
          </Button>
        </Link>
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold text-zinc-100">
            {deviceName}
          </h2>
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
        </div>
        <div className="flex items-center gap-3 text-sm text-zinc-500">
          <span className="font-mono">{deviceAddress}</span>
          {deviceType && <Badge variant="info">{deviceType}</Badge>}
          {device?.tenant_name && (
            <span className="text-xs text-zinc-500">
              tenant: <span className="text-zinc-300">{device.tenant_name}</span>
            </span>
          )}
          {device?.collector_group_name && (
            <span className="text-xs text-zinc-500">
              collector group: <span className="text-zinc-300">{device.collector_group_name}</span>
            </span>
          )}
        </div>
      </div>

      {/* 4-tab layout */}
      <Tabs value={activeTab} onChange={setActiveTab}>
        <TabsList>
          <TabTrigger value="overview">
            <span className="flex items-center gap-1.5">
              <Layout className="h-3.5 w-3.5" />
              Overview
            </span>
          </TabTrigger>
          <TabTrigger value="performance">
            <span className="flex items-center gap-1.5">
              <BarChart2 className="h-3.5 w-3.5" />
              Performance
            </span>
          </TabTrigger>
          <TabTrigger value="interfaces">
            <span className="flex items-center gap-1.5">
              <Network className="h-3.5 w-3.5" />
              Interfaces
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
          <TabTrigger value="thresholds">
            <span className="flex items-center gap-1.5">
              <Gauge className="h-3.5 w-3.5" />
              Thresholds
            </span>
          </TabTrigger>
          <TabTrigger value="settings">
            <span className="flex items-center gap-1.5">
              <Settings2 className="h-3.5 w-3.5" />
              Settings
            </span>
          </TabTrigger>
          <TabTrigger value="history">
            <span className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5" />
              History
            </span>
          </TabTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab deviceId={deviceId} />
        </TabsContent>
        <TabsContent value="performance">
          <PerformanceTab deviceId={deviceId} />
        </TabsContent>
        <TabsContent value="interfaces">
          <InterfacesTab deviceId={deviceId} />
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
        <TabsContent value="thresholds">
          <ThresholdsTab deviceId={deviceId} />
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab deviceId={deviceId} />
        </TabsContent>
        <TabsContent value="history">
          <HistoryTab deviceId={deviceId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
