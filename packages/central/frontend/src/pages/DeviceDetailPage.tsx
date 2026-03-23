import { useState, useEffect, useMemo, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName, validateAddress } from "@/lib/validation.ts";
import {
  Activity,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  ArrowUpDown,
  BarChart2,
  Bell,
  Clock,
  Database,
  FileText,
  Gauge,
  Key,
  Layout,
  ListChecks,
  Loader2,
  Monitor,
  Network,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  Tag,
  Pencil,
  Pin,
  Check,
  CheckCheck,
  Trash2,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { InterfaceToggleCell } from "@/components/InterfaceToggleCell";
import { InterfaceToggleBulkHead } from "@/components/InterfaceToggleBulkHead";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
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
import type { TimeRangeValue, TimeRangePreset } from "@/components/TimeRangePicker.tsx";
import {
  useCollectorGroups,
  useCollectors,
  useCreateAssignment,
  useCredentials,
  useCredentialTypes,
  useDeleteAssignment,
  useUpdateAssignment,
  useDevice,
  useDeviceAssignments,
  useDeviceConfigData,
  useDeviceConfigTemplates,
  useAvailabilityHistory,
  useDeviceHistory,
  useDeviceMonitoring,
  useDeviceResults,
  useDeviceTypes,
  useInterfaceLatest,
  useMultiInterfaceHistory,
  useRefreshInterfaceMetadata,
  useInterfaceMetadata,
  useUpdateInterfaceSettings,
  useBulkUpdateInterfaceSettings,
  useAppDetail,
  useApps,
  useSnmpOids,
  useSystemSettings,
  useTenants,
  useUpdateDevice,
  useUpdateDeviceMonitoring,
  usePerformanceSummary,
  usePerformanceHistory,
  useDeviceThresholds,
  useAlertInstances,
  useUpdateAlertInstance,
  useCreateThresholdOverride,
  useUpdateThresholdOverride,
  useDeleteThresholdOverride,
  useConfigChangelog,
  useConfigDiff,
  useConfigChangeTimestamps,
  useConfigCompare,
  useDeviceRetention,
  useSetDeviceRetention,
  useDeleteDeviceRetention,
  useUpdateInterfacePreferences,
  useDeviceAlertLog,
  useDeviceActiveEvents,
  useDeviceClearedEvents,
  useAcknowledgeEvents,
  useClearEvents,
} from "@/api/hooks.ts";
import { useAuth } from "@/hooks/useAuth.tsx";
import type { Device as DeviceType, DeviceAssignment, DeviceThresholdRow, ConfigDiffEntry, DeviceRetentionEntry, AlertLogEntry, MonitoringEvent } from "@/types/api.ts";
import { useListState } from "@/hooks/useListState.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import { ConfigDataRenderer } from "@/components/ConfigDataRenderer.tsx";
import { ApplyTemplateDialog } from "@/components/ApplyTemplateDialog.tsx";
import { PerformanceChart } from "@/components/PerformanceChart.tsx";
import { MultiInterfaceChart, formatTraffic } from "@/components/InterfaceTrafficChart.tsx";
import type { TrafficUnit, ChartMetric, ChartMode } from "@/components/InterfaceTrafficChart.tsx";
import { CredentialCell } from "@/components/CredentialCell.tsx";
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
  const { data: appsResp } = useApps();
  const apps = appsResp?.data ?? [];
  const { data: credentials } = useCredentials();
  const [selectedAppId, setSelectedAppId] = useState("");
  const { data: appDetail } = useAppDetail(selectedAppId || undefined);
  const createAssignment = useCreateAssignment();

  const scheduleValidator = (v: string) => { const n = Number(v); if (isNaN(n) || n < 10 || n > 86400) return "Must be 10-86400"; return null; };
  const [scheduleType, setScheduleType] = useState("interval");
  const scheduleValueField = useField("60", scheduleValidator);
  const [versionMode, setVersionMode] = useState<"latest" | "pinned">("latest");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [selectedCredentialId, setSelectedCredentialId] = useState("");
  const [pinToCollector, setPinToCollector] = useState(false);
  const [pinnedCollectorId, setPinnedCollectorId] = useState("");
  const { data: groupCollectors } = useCollectors(
    pinToCollector && deviceCollectorGroupId ? { group_id: deviceCollectorGroupId } : undefined
  );
  const [configText, setConfigText] = useState("{}");
  const [parsedConfig, setParsedConfig] = useState<Record<string, unknown>>({});
  const [configError, setConfigError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (apps?.length && !selectedAppId) setSelectedAppId(apps[0].id);
  }, [apps, selectedAppId]);

  useEffect(() => {
    setVersionMode("latest");
    setSelectedVersionId("");
    setParsedConfig({});
    setConfigText("{}");
  }, [selectedAppId]);

  function reset() {
    setSelectedAppId(apps?.[0]?.id ?? "");
    setVersionMode("latest");
    setSelectedVersionId("");
    setSelectedCredentialId("");
    setPinToCollector(false);
    setPinnedCollectorId("");
    setScheduleType("interval");
    scheduleValueField.reset("60");
    setConfigText("{}");
    setParsedConfig({});
    setConfigError(null);
    setFormError(null);
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

    // Validate schedule value
    if (scheduleType === "interval") {
      if (!validateAll(scheduleValueField)) return;
    } else if (scheduleType === "cron") {
      const parts = scheduleValueField.value.trim().split(/\s+/);
      if (parts.length < 5) {
        setFormError("Cron expression must have at least 5 fields: min hour day month weekday");
        return;
      }
    }

    if (!selectedAppId) {
      setFormError("App is required.");
      return;
    }

    if (!deviceCollectorGroupId) {
      setFormError("Device must be assigned to a collector group before adding assignments.");
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
      await createAssignment.mutateAsync({
        app_id: selectedAppId,
        app_version_id: versionId,
        collector_id: pinToCollector && pinnedCollectorId ? pinnedCollectorId : null,
        device_id: deviceId,
        schedule_type: scheduleType,
        schedule_value: scheduleValueField.value,
        config,
        use_latest: versionMode === "latest",
        credential_id: selectedCredentialId || null,
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

        {/* Collector Group (read-only) */}
        <div className="space-y-1.5">
          <Label>Collector Group</Label>
          {deviceCollectorGroupId ? (
            <p className="text-sm text-zinc-300 rounded-md border border-zinc-700 px-3 py-2.5">
              {deviceCollectorGroupName ?? deviceCollectorGroupId}
            </p>
          ) : (
            <p className="text-sm text-amber-400">
              This device is not assigned to a collector group. Assign it to a group in Settings before adding apps.
            </p>
          )}
        </div>

        {/* Credential */}
        <div className="space-y-1.5">
          <Label htmlFor="aa-credential">Credential <span className="font-normal text-zinc-500">(optional)</span></Label>
          <Select id="aa-credential" value={selectedCredentialId} onChange={(e) => setSelectedCredentialId(e.target.value)}>
            <option value="">Device default</option>
            {(credentials ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.credential_type})</option>
            ))}
          </Select>
        </div>

        {/* Pin to collector */}
        {deviceCollectorGroupId && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="pin-collector"
                checked={pinToCollector}
                onChange={(e) => { setPinToCollector(e.target.checked); if (!e.target.checked) setPinnedCollectorId(""); }}
                className="accent-brand-500 cursor-pointer"
              />
              <Label htmlFor="pin-collector" className="text-sm text-zinc-400 font-normal cursor-pointer">
                Pin to a specific collector
              </Label>
            </div>
            {pinToCollector && (
              <>
                <Select value={pinnedCollectorId} onChange={(e) => setPinnedCollectorId(e.target.value)}>
                  <option value="">Select collector...</option>
                  {(groupCollectors ?? []).map((c: { id: string; name: string; status: string }) => (
                    <option key={c.id} value={c.id}>{c.name}{c.status !== "ACTIVE" ? ` (${c.status})` : ""}</option>
                  ))}
                </Select>
                <p className="text-xs text-zinc-500">
                  This assignment will only run on the selected collector. If the collector goes down, the assignment pauses until it recovers.
                </p>
              </>
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="aa-sched-type">Schedule Type</Label>
            <Select
              id="aa-sched-type"
              value={scheduleType}
              onChange={(e) => {
                const newType = e.target.value;
                setScheduleType(newType);
                if (newType === "cron") {
                  scheduleValueField.reset("*/5 * * * *");
                } else {
                  scheduleValueField.reset("60");
                }
              }}
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
              value={scheduleValueField.value}
              onChange={scheduleValueField.onChange}
              onBlur={scheduleValueField.onBlur}
              placeholder={scheduleType === "interval" ? "60" : "*/5 * * * *"}
            />
            {scheduleValueField.error && <p className="text-xs text-red-400 mt-0.5">{scheduleValueField.error}</p>}
            <p className="text-xs text-zinc-500">
              {scheduleType === "interval"
                ? "How often to run, in seconds"
                : "Standard cron: min hour day month weekday"}
            </p>
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
  deviceCollectorGroupId: string | null;
  open: boolean;
  onClose: () => void;
}

function EditAssignmentDialog({ assignment, deviceCollectorGroupId, open, onClose }: EditAssignmentDialogProps) {
  const updateAssignment = useUpdateAssignment();
  const { data: appDetail } = useAppDetail(assignment?.app.id);
  const { data: credentials } = useCredentials();

  const editScheduleValidator = (v: string) => { const n = Number(v); if (isNaN(n) || n < 10 || n > 86400) return "Must be 10-86400"; return null; };
  const [scheduleType, setScheduleType] = useState("interval");
  const editScheduleValueField = useField("60", editScheduleValidator);
  const [configText, setConfigText] = useState("{}");
  const [parsedConfig, setParsedConfig] = useState<Record<string, unknown>>({});
  const [configError, setConfigError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [versionMode, setVersionMode] = useState<"latest" | "pinned">("latest");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [selectedCredentialId, setSelectedCredentialId] = useState("");
  const [pinToCollector, setPinToCollector] = useState(false);
  const [pinnedCollectorId, setPinnedCollectorId] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const { data: groupCollectors } = useCollectors(
    pinToCollector && deviceCollectorGroupId ? { group_id: deviceCollectorGroupId } : undefined
  );

  useEffect(() => {
    if (assignment) {
      setScheduleType(assignment.schedule_type);
      editScheduleValueField.reset(assignment.schedule_value);
      setConfigText(JSON.stringify(assignment.config, null, 2));
      setParsedConfig(assignment.config ?? {});
      setEnabled(assignment.enabled);
      setVersionMode(assignment.use_latest ? "latest" : "pinned");
      setSelectedVersionId(assignment.app_version_id);
      setSelectedCredentialId(assignment.credential_id ?? "");
      setPinToCollector(!!assignment.collector_id);
      setPinnedCollectorId(assignment.collector_id ?? "");
      setConfigError(null);
      setFormError(null);
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

    // Validate schedule value
    if (scheduleType === "interval") {
      if (!validateAll(editScheduleValueField)) return;
    } else if (scheduleType === "cron") {
      const parts = editScheduleValueField.value.trim().split(/\s+/);
      if (parts.length < 5) {
        setFormError("Cron expression must have at least 5 fields: min hour day month weekday");
        return;
      }
    }

    const latestVersion = appDetail?.versions?.find((v) => v.is_latest);
    const versionId = versionMode === "latest" ? latestVersion?.id : selectedVersionId;
    if (!versionId) {
      setFormError(versionMode === "latest" ? "No latest version available." : "Select a version.");
      return;
    }

    if (pinToCollector && !pinnedCollectorId) {
      setFormError("Select a collector or uncheck 'Pin to a specific collector'.");
      return;
    }

    try {
      await updateAssignment.mutateAsync({
        id: assignment.id,
        data: {
          schedule_type: scheduleType,
          schedule_value: editScheduleValueField.value,
          config,
          enabled,
          app_version_id: versionId,
          use_latest: versionMode === "latest",
          credential_id: selectedCredentialId || null,
          collector_id: pinToCollector && pinnedCollectorId
            ? pinnedCollectorId
            : null,
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
              onChange={(e) => {
                const newType = e.target.value;
                setScheduleType(newType);
                if (newType === "cron" && !/\s/.test(editScheduleValueField.value)) {
                  editScheduleValueField.reset("*/5 * * * *");
                } else if (newType === "interval" && /\s/.test(editScheduleValueField.value)) {
                  editScheduleValueField.reset("60");
                }
              }}
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
              value={editScheduleValueField.value}
              onChange={editScheduleValueField.onChange}
              onBlur={editScheduleValueField.onBlur}
              placeholder={scheduleType === "interval" ? "60" : "*/5 * * * *"}
            />
            {editScheduleValueField.error && <p className="text-xs text-red-400 mt-0.5">{editScheduleValueField.error}</p>}
            <p className="text-xs text-zinc-500">
              {scheduleType === "interval"
                ? "How often to run, in seconds"
                : "Standard cron: min hour day month weekday"}
            </p>
          </div>
        </div>

        {/* Credential */}
        <div className="space-y-1.5">
          <Label htmlFor="ea-credential">Credential <span className="font-normal text-zinc-500">(optional)</span></Label>
          <Select id="ea-credential" value={selectedCredentialId} onChange={(e) => setSelectedCredentialId(e.target.value)}>
            <option value="">Device default</option>
            {(credentials ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.credential_type})</option>
            ))}
          </Select>
        </div>

        {/* Pin to collector */}
        {deviceCollectorGroupId && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="edit-pin-collector"
                checked={pinToCollector}
                onChange={(e) => { setPinToCollector(e.target.checked); if (!e.target.checked) setPinnedCollectorId(""); }}
                className="accent-brand-500 cursor-pointer"
              />
              <Label htmlFor="edit-pin-collector" className="text-sm text-zinc-400 font-normal cursor-pointer">
                Pin to a specific collector
              </Label>
            </div>
            {pinToCollector && (
              <>
                <Select value={pinnedCollectorId} onChange={(e) => setPinnedCollectorId(e.target.value)}>
                  <option value="">Select collector...</option>
                  {(groupCollectors ?? []).map((c: { id: string; name: string; status: string }) => (
                    <option key={c.id} value={c.id}>{c.name}{c.status !== "ACTIVE" ? ` (${c.status})` : ""}</option>
                  ))}
                </Select>
                <p className="text-xs text-zinc-500">
                  This assignment will only run on the selected collector. If the collector goes down, the assignment pauses until it recovers.
                </p>
              </>
            )}
          </div>
        )}

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
  const { data: history, isLoading: histLoading } = useAvailabilityHistory(
    deviceId,
    fromTs,
    toTs,
    5000,
  );

  // ── Staleness detection ───────────────────────────────────
  const STALE_THRESHOLD_MS = 15 * 60 * 1000; // 15 minutes
  const staleSince = useMemo(() => {
    if (!deviceResults?.checks?.length) return null;
    // Only consider availability/latency checks for staleness — other apps
    // (config, performance) have their own tabs and should not drive this indicator.
    const monitoringChecks = deviceResults.checks.filter(
      (c: any) => c.role === "availability" || c.role === "latency"
    );
    if (!monitoringChecks.length) return null;
    const latest = monitoringChecks.reduce((newest: number, check: any) => {
      const ts = new Date(check.executed_at).getTime();
      return ts > newest ? ts : newest;
    }, 0);
    if (latest === 0) return null;
    const ageMs = Date.now() - latest;
    return ageMs > STALE_THRESHOLD_MS ? new Date(latest) : null;
  }, [deviceResults]);

  return (
    <div className="space-y-4">
      {/* Staleness warning */}
      {staleSince && (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
          <Clock className="h-4 w-4 flex-shrink-0" />
          <span>
            No data received since{" "}
            <span className="font-medium text-amber-200">
              {formatDate(staleSince.toISOString(), tz)}
            </span>
            {" "}({timeAgo(staleSince.toISOString())}).
            Check collector connectivity and assignment status.
          </span>
        </div>
      )}

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

  const { data: summary, isLoading: summaryLoading } = usePerformanceSummary(deviceId);

  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);
  const [selectedComponentType, setSelectedComponentType] = useState<string | null>(null);
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null);
  const [selectedComponents, setSelectedComponents] = useState<string[]>([]);
  const [componentFilter, setComponentFilter] = useState("");

  // Auto-select first app
  useEffect(() => {
    if (summary?.length && !selectedAppId) {
      const first = summary[0];
      setSelectedAppId(first.app_id);
      const ctKeys = Object.keys(first.component_types).sort();
      if (ctKeys.length) {
        setSelectedComponentType(ctKeys[0]);
        const ct = first.component_types[ctKeys[0]];
        if (ct.metric_names.length) setSelectedMetric(ct.metric_names[0]);
        setSelectedComponents(ct.components.slice(0, 10));
      }
    }
  }, [summary, selectedAppId]);

  const currentApp = summary?.find((a) => a.app_id === selectedAppId);
  const currentCT = currentApp && selectedComponentType
    ? currentApp.component_types[selectedComponentType] : null;
  const availableComponents = currentCT?.components ?? [];
  const availableMetrics = currentCT?.metric_names ?? [];

  const { data: perfData, isLoading: dataLoading } = usePerformanceHistory(
    deviceId, fromTs, toTs, selectedAppId, selectedComponentType,
    selectedComponents.length ? selectedComponents : null, 5000,
  );

  const filteredComponents = useMemo(() => {
    if (!componentFilter) return availableComponents;
    const q = componentFilter.toLowerCase();
    return availableComponents.filter((c) => c.toLowerCase().includes(q));
  }, [availableComponents, componentFilter]);

  const toggleComponent = (comp: string) => {
    setSelectedComponents((prev) =>
      prev.includes(comp) ? prev.filter((c) => c !== comp) : [...prev, comp]
    );
  };
  const selectAll = () => {
    setSelectedComponents((prev) => {
      const s = new Set(prev);
      filteredComponents.forEach((c) => s.add(c));
      return [...s];
    });
  };
  const selectNone = () => {
    setSelectedComponents((prev) => prev.filter((c) => !filteredComponents.includes(c)));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-zinc-300">Performance Metrics</h3>
        <TimeRangePicker value={timeRange} onChange={setTimeRange} />
      </div>

      {summaryLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
        </div>
      ) : !summary?.length ? (
        <Card>
          <CardContent>
            <div className="flex flex-col items-center justify-center py-12 text-zinc-600">
              <BarChart2 className="h-8 w-8 text-zinc-700 mb-2" />
              <p className="text-sm text-zinc-500">No performance data collected for this device yet.</p>
              <p className="text-xs text-zinc-700 mt-1">Assign a performance monitoring app to start collecting metrics.</p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="flex gap-4">
          {/* Sidebar */}
          <div className="w-64 shrink-0 space-y-3">
            <Card>
              <CardHeader className="py-2 px-3">
                <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">App</CardTitle>
              </CardHeader>
              <CardContent className="px-3 pb-3 space-y-1">
                {summary.map((app) => (
                  <button
                    key={app.app_id}
                    onClick={() => {
                      setSelectedAppId(app.app_id);
                      const ctKeys = Object.keys(app.component_types).sort();
                      if (ctKeys.length) {
                        setSelectedComponentType(ctKeys[0]);
                        const ct = app.component_types[ctKeys[0]];
                        setSelectedMetric(ct.metric_names[0] ?? null);
                        setSelectedComponents(ct.components.slice(0, 10));
                        setComponentFilter("");
                      }
                    }}
                    className={`w-full text-left px-2 py-1.5 rounded text-sm transition-colors cursor-pointer ${
                      selectedAppId === app.app_id
                        ? "bg-brand-500/20 text-brand-400"
                        : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
                    }`}
                  >
                    {app.app_name}
                  </button>
                ))}
              </CardContent>
            </Card>

            {currentApp && Object.keys(currentApp.component_types).length > 1 && (
              <Card>
                <CardHeader className="py-2 px-3">
                  <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">Type</CardTitle>
                </CardHeader>
                <CardContent className="px-3 pb-3 space-y-1">
                  {Object.keys(currentApp.component_types).sort().map((ct) => (
                    <button
                      key={ct}
                      onClick={() => {
                        setSelectedComponentType(ct);
                        const entry = currentApp.component_types[ct];
                        setSelectedMetric(entry.metric_names[0] ?? null);
                        setSelectedComponents(entry.components.slice(0, 10));
                        setComponentFilter("");
                      }}
                      className={`w-full text-left px-2 py-1.5 rounded text-sm transition-colors cursor-pointer ${
                        selectedComponentType === ct
                          ? "bg-zinc-700 text-zinc-200"
                          : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800"
                      }`}
                    >
                      {ct}
                    </button>
                  ))}
                </CardContent>
              </Card>
            )}

            {availableMetrics.length > 1 && (
              <Card>
                <CardHeader className="py-2 px-3">
                  <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">Metric</CardTitle>
                </CardHeader>
                <CardContent className="px-3 pb-3 space-y-1">
                  {availableMetrics.map((m) => (
                    <button
                      key={m}
                      onClick={() => setSelectedMetric(m)}
                      className={`w-full text-left px-2 py-1.5 rounded text-sm font-mono transition-colors cursor-pointer ${
                        selectedMetric === m
                          ? "bg-zinc-700 text-zinc-200"
                          : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800"
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </CardContent>
              </Card>
            )}

            {availableComponents.length > 0 && (
              <Card>
                <CardHeader className="py-2 px-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">
                      Components ({selectedComponents.length}/{availableComponents.length})
                    </CardTitle>
                    <div className="flex gap-1">
                      <button onClick={selectAll} className="text-[10px] text-zinc-500 hover:text-zinc-300 px-1 cursor-pointer">All</button>
                      <button onClick={selectNone} className="text-[10px] text-zinc-500 hover:text-zinc-300 px-1 cursor-pointer">None</button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="px-3 pb-3">
                  {availableComponents.length > 15 && (
                    <div className="mb-2">
                      <Input
                        placeholder="Filter components..."
                        value={componentFilter}
                        onChange={(e) => setComponentFilter(e.target.value)}
                        className="h-7 text-xs bg-zinc-800 border-zinc-700"
                      />
                    </div>
                  )}
                  <div className="max-h-64 overflow-y-auto space-y-0.5">
                    {filteredComponents.length === 0 ? (
                      <p className="text-xs text-zinc-600 px-1 py-2">No match</p>
                    ) : filteredComponents.map((comp) => (
                      <label key={comp} className="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-zinc-800 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={selectedComponents.includes(comp)}
                          onChange={() => toggleComponent(comp)}
                          className="accent-brand-500 h-3.5 w-3.5"
                        />
                        <span className="text-xs text-zinc-400 font-mono truncate">{comp}</span>
                      </label>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Chart area */}
          <div className="flex-1 min-w-0">
            <Card>
              <CardContent className="pt-4">
                {dataLoading ? (
                  <div className="flex items-center justify-center h-72">
                    <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
                  </div>
                ) : selectedMetric && perfData ? (
                  <PerformanceChart
                    data={perfData}
                    selectedComponents={selectedComponents}
                    metricName={selectedMetric}
                    timezone={tz}
                    unit={selectedMetric.includes("pct") ? "%" :
                          selectedMetric.includes("_ms") ? "ms" :
                          selectedMetric.includes("_bytes") ? "B" : ""}
                    title={`${selectedComponentType ?? ""} — ${selectedMetric ?? ""}`}
                  />
                ) : (
                  <div className="flex items-center justify-center h-72 text-zinc-600 text-sm">
                    Select a metric and components to visualize.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tab 3: Configuration ─────────────────────────────────

function ConfigurationTab({ deviceId }: { deviceId: string }) {
  const tz = useTimezone();
  const { data: configRows, isLoading } = useDeviceConfigData(deviceId);
  const { data: configTemplates } = useDeviceConfigTemplates(deviceId);
  const { data: assignments } = useDeviceAssignments(deviceId);
  const [configView, setConfigView] = useState<"current" | "changes" | "compare">("current");
  const [selectedConfigApp, setSelectedConfigApp] = useState<string | null>(null);

  // Changelog
  const [changelogPage, setChangelogPage] = useState(0);
  const PAGE_SIZE = 50;
  const { data: changelogResp } = useConfigChangelog(deviceId, {
    app_id: selectedConfigApp ?? undefined,
    limit: PAGE_SIZE,
    offset: changelogPage * PAGE_SIZE,
  });
  const changelog = changelogResp?.data ?? [];
  const changelogMeta = (changelogResp as unknown as Record<string, unknown>)?.meta as
    | { total?: number; count?: number }
    | undefined;

  // Diff dialog for single key
  const [diffKey, setDiffKey] = useState<string | null>(null);
  const { data: diffResp } = useConfigDiff(deviceId, diffKey ?? "", selectedConfigApp ?? undefined, 20);
  const diffRows = diffResp?.data ?? [];

  // Compare view
  const { data: timestamps } = useConfigChangeTimestamps(deviceId, {
    app_id: selectedConfigApp ?? undefined,
  });
  const tsData = timestamps?.data ?? [];
  const [compareTimeA, setCompareTimeA] = useState<string | null>(null);
  const [compareTimeB, setCompareTimeB] = useState<string | null>(null);
  const { data: compareResult } = useConfigCompare(
    deviceId, compareTimeA, compareTimeB, selectedConfigApp ?? undefined
  );

  // Auto-set compare timestamps when data loads
  useEffect(() => {
    if (tsData.length >= 2 && !compareTimeA && !compareTimeB) {
      setCompareTimeA(tsData[1].change_time);
      setCompareTimeB(tsData[0].change_time);
    }
  }, [tsData, compareTimeA, compareTimeB]);

  // Recent changes badge — stable timestamp to prevent infinite re-fetch loop
  const recentCutoff = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0); // start of today — stable across renders
    return d.toISOString();
  }, []);
  const { data: recentResp } = useConfigChangelog(deviceId, {
    from_ts: recentCutoff,
    limit: 1,
  });
  const hasRecentChanges = (recentResp?.data?.length ?? 0) > 0;

  // Group by app_id for sidebar and current view
  const configApps = useMemo(() => {
    const apps = new Map<string, { appName: string; data: Record<string, string>; lastCollected: string | null; intervalSeconds: number | null }>();
    // Build a map of app_id -> interval from assignments
    const intervalByAppId = new Map<string, number>();
    for (const a of (assignments ?? [])) {
      if (a.schedule_type === "interval") {
        intervalByAppId.set(a.app.id, Number(a.schedule_value));
      }
    }
    for (const row of (configRows ?? [])) {
      const appId = String(row.app_id ?? "unknown");
      const key = String(row.config_key ?? "");
      const value = String(row.config_value ?? "");
      const appName = String(row.app_name ?? appId);
      const executedAt = String(row.executed_at ?? "");
      if (!apps.has(appId)) {
        apps.set(appId, { appName, data: {}, lastCollected: null, intervalSeconds: intervalByAppId.get(appId) ?? null });
      }
      const entry = apps.get(appId)!;
      if (!(key in entry.data)) {
        entry.data[key] = value;
      }
      if (executedAt && (!entry.lastCollected || executedAt > entry.lastCollected)) {
        entry.lastCollected = executedAt;
      }
    }
    return apps;
  }, [configRows, assignments]);

  // Auto-select first app
  useEffect(() => {
    if (!selectedConfigApp && configApps.size > 0) {
      setSelectedConfigApp([...configApps.keys()][0]);
    }
  }, [configApps, selectedConfigApp]);

  // Reset changelog page when switching apps
  useEffect(() => { setChangelogPage(0); }, [selectedConfigApp]);

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  if (configApps.size === 0) {
    return (
      <Card>
        <CardContent className="py-12 flex flex-col items-center gap-3 text-zinc-600">
          <Wrench className="h-8 w-8 text-zinc-700" />
          <p className="text-sm text-zinc-500">No configuration data yet.</p>
          <p className="text-xs text-zinc-700 text-center max-w-sm">
            Config apps will populate structured data here once they have been assigned and executed.
          </p>
        </CardContent>
      </Card>
    );
  }

  const selectedAppData = selectedConfigApp ? configApps.get(selectedConfigApp) : null;

  return (
    <div className="flex gap-4">
      {/* Left sidebar — app selector */}
      <div className="w-48 shrink-0">
        <Card>
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-xs text-zinc-500 uppercase tracking-wide">Apps</CardTitle>
          </CardHeader>
          <CardContent className="p-1.5 space-y-0.5">
            {[...configApps.entries()].map(([appId, { appName }]) => (
              <button
                key={appId}
                onClick={() => setSelectedConfigApp(appId)}
                className={`w-full text-left rounded-md px-2.5 py-1.5 text-xs transition-colors cursor-pointer truncate ${
                  selectedConfigApp === appId
                    ? "bg-brand-500/15 text-brand-400 font-medium"
                    : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                }`}
              >
                {appName}
              </button>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Main content area */}
      <div className="flex-1 min-w-0 space-y-4">
        {/* Sub-tabs */}
        <div className="flex items-center gap-2">
          <Button
            variant={configView === "current" ? "default" : "outline"}
            size="sm"
            onClick={() => setConfigView("current")}
          >
            <Wrench className="h-3.5 w-3.5 mr-1" />
            Current
          </Button>
          <Button
            variant={configView === "changes" ? "default" : "outline"}
            size="sm"
            onClick={() => setConfigView("changes")}
          >
            <Clock className="h-3.5 w-3.5 mr-1" />
            Changes
            {hasRecentChanges && (
              <span className="ml-1.5 text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 font-semibold">
                New
              </span>
            )}
          </Button>
          <Button
            variant={configView === "compare" ? "default" : "outline"}
            size="sm"
            onClick={() => setConfigView("compare")}
          >
            <FileText className="h-3.5 w-3.5 mr-1" />
            Compare
          </Button>
        </div>

        {/* Current view */}
        {configView === "current" && selectedAppData && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <Wrench className="h-4 w-4" />
                {selectedAppData.appName}
                {selectedAppData.lastCollected && (() => {
                  const ageSec = (Date.now() - new Date(selectedAppData.lastCollected).getTime()) / 1000;
                  const interval = selectedAppData.intervalSeconds;
                  // green = within 1.5x interval, yellow = within 2.5x, red = beyond
                  const missedPolls = interval ? ageSec / interval : 0;
                  const statusColor = !interval ? "bg-zinc-700 text-zinc-300"
                    : missedPolls <= 1.5 ? "bg-emerald-900/60 text-emerald-400 border border-emerald-700/50"
                    : missedPolls <= 2.5 ? "bg-amber-900/60 text-amber-400 border border-amber-700/50"
                    : "bg-red-900/60 text-red-400 border border-red-700/50";
                  return (
                    <span
                      className={`ml-auto text-xs font-medium px-2 py-0.5 rounded ${statusColor}`}
                      title={`Last polled: ${formatDate(selectedAppData.lastCollected, tz)}${interval ? ` · Interval: ${interval}s` : ""}`}
                    >
                      {timeAgo(selectedAppData.lastCollected)}
                    </span>
                  );
                })()}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ConfigDataRenderer
                template={
                  selectedConfigApp && configTemplates?.[selectedConfigApp]?.display_template?.html
                    ? {
                        html: configTemplates[selectedConfigApp].display_template!.html,
                        css: configTemplates[selectedConfigApp].display_template!.css ?? undefined,
                        key_mappings: [],
                      }
                    : null
                }
                data={selectedAppData.data}
              />
            </CardContent>
          </Card>
        )}

        {/* Changes view — changelog timeline */}
        {configView === "changes" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                Config Change History
                {changelogMeta?.total ? (
                  <Badge variant="default" className="text-[10px] px-1.5 py-0">
                    {changelogMeta.total}
                  </Badge>
                ) : null}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {changelog.length === 0 ? (
                <div className="py-8 text-center">
                  <Clock className="h-6 w-6 text-zinc-700 mx-auto mb-2" />
                  <p className="text-sm text-zinc-500">No configuration changes detected.</p>
                  <p className="text-xs text-zinc-600 mt-1 max-w-sm mx-auto">
                    Changes will appear here automatically when config values on this device change between poll cycles.
                  </p>
                </div>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Time</TableHead>
                        <TableHead>App</TableHead>
                        <TableHead>Component</TableHead>
                        <TableHead>Key</TableHead>
                        <TableHead>Value</TableHead>
                        <TableHead className="w-16">Diff</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {changelog.map((row, i) => (
                        <TableRow key={`${row.executed_at}-${row.config_key}-${i}`}>
                          <TableCell className="text-xs text-zinc-400 whitespace-nowrap" title={formatDate(row.executed_at, tz)}>
                            {timeAgo(row.executed_at)}
                          </TableCell>
                          <TableCell className="text-xs">{row.app_name}</TableCell>
                          <TableCell className="text-xs font-mono text-zinc-500">
                            {row.component ? `${row.component_type}/${row.component}` : "—"}
                          </TableCell>
                          <TableCell className="text-xs font-mono">{row.config_key}</TableCell>
                          <TableCell className="text-xs font-mono max-w-[250px] truncate" title={row.config_value}>
                            {row.config_value}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-xs"
                              onClick={() => setDiffKey(row.config_key)}
                            >
                              <FileText className="h-3 w-3" />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {(changelogMeta?.total ?? 0) > PAGE_SIZE && (
                    <div className="flex items-center justify-between mt-3 text-xs text-zinc-400">
                      <span>
                        {changelogPage * PAGE_SIZE + 1}–
                        {Math.min((changelogPage + 1) * PAGE_SIZE, changelogMeta?.total ?? 0)} of{" "}
                        {changelogMeta?.total}
                      </span>
                      <div className="flex gap-1">
                        <Button variant="outline" size="sm" className="h-6 px-2 text-xs"
                          disabled={changelogPage === 0}
                          onClick={() => setChangelogPage((p) => p - 1)}>
                          Prev
                        </Button>
                        <Button variant="outline" size="sm" className="h-6 px-2 text-xs"
                          disabled={(changelogPage + 1) * PAGE_SIZE >= (changelogMeta?.total ?? 0)}
                          onClick={() => setChangelogPage((p) => p + 1)}>
                          Next
                        </Button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        )}

        {/* Compare view — side-by-side diff */}
        {configView === "compare" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Compare Snapshots</CardTitle>
            </CardHeader>
            <CardContent>
              {tsData.length < 2 ? (
                <div className="py-8 text-center">
                  <FileText className="h-6 w-6 text-zinc-700 mx-auto mb-2" />
                  <p className="text-sm text-zinc-500">No changes to compare yet.</p>
                  <p className="text-xs text-zinc-600 mt-1 max-w-sm mx-auto">
                    The comparison view requires at least two different configuration snapshots.
                    Changes will become available once config values on this device change between poll cycles.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center gap-3 flex-wrap">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-zinc-500">Before:</span>
                      <Select
                        value={compareTimeA ?? ""}
                        onChange={(e) => setCompareTimeA(e.target.value)}
                        className="min-w-[280px] text-xs"
                      >
                        {tsData.map((ts) => (
                          <option key={ts.change_time} value={ts.change_time}>
                            {formatDate(ts.change_time, tz)} ({ts.change_count} keys)
                          </option>
                        ))}
                      </Select>
                    </div>
                    <span className="text-zinc-600">vs</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-zinc-500">After:</span>
                      <Select
                        value={compareTimeB ?? ""}
                        onChange={(e) => setCompareTimeB(e.target.value)}
                        className="min-w-[280px] text-xs"
                      >
                        {tsData.map((ts) => (
                          <option key={ts.change_time} value={ts.change_time}>
                            {formatDate(ts.change_time, tz)} ({ts.change_count} keys)
                          </option>
                        ))}
                      </Select>
                    </div>
                  </div>

                  {compareResult && (() => {
                    const added = compareResult.changes.filter((d) => d.change_type === "added");
                    const removed = compareResult.changes.filter((d) => d.change_type === "removed");
                    const modified = compareResult.changes.filter((d) => d.change_type === "modified");
                    const unchangedList = compareResult.unchanged ?? [];

                    const renderDiffRow = (d: ConfigDiffEntry, i: number) => {
                      const rowBg =
                        d.change_type === "added" ? "bg-emerald-950/20" :
                        d.change_type === "removed" ? "bg-red-950/20" :
                        d.change_type === "modified" ? "bg-amber-950/20" : "";
                      const statusIcon =
                        d.change_type === "added" ? "+" :
                        d.change_type === "removed" ? "\u2212" :
                        d.change_type === "modified" ? "~" : "=";
                      const statusColor =
                        d.change_type === "added" ? "text-emerald-400" :
                        d.change_type === "removed" ? "text-red-400" :
                        d.change_type === "modified" ? "text-amber-400" : "text-zinc-600";

                      return (
                        <TableRow key={`${d.component_type}-${d.component}-${d.config_key}-${i}`} className={rowBg}>
                          <TableCell className={`text-sm font-bold w-8 text-center ${statusColor}`}>
                            {statusIcon}
                          </TableCell>
                          <TableCell className="text-xs font-mono">{d.config_key}</TableCell>
                          <TableCell className="text-xs font-mono max-w-[250px] truncate" title={d.value_a ?? ""}>
                            {d.change_type === "added" ? (
                              <span className="text-zinc-600">&mdash;</span>
                            ) : (
                              <span className={d.change_type === "removed" || d.change_type === "modified" ? "text-red-400" : "text-zinc-400"}>{d.value_a}</span>
                            )}
                          </TableCell>
                          <TableCell className="text-xs font-mono max-w-[250px] truncate" title={d.value_b ?? ""}>
                            {d.change_type === "removed" ? (
                              <span className="text-zinc-600">&mdash;</span>
                            ) : (
                              <span className={d.change_type === "added" || d.change_type === "modified" ? "text-emerald-400" : "text-zinc-400"}>{d.value_b}</span>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    };

                    return (
                      <>
                        {/* Summary badges */}
                        <div className="flex items-center gap-2 flex-wrap">
                          {added.length > 0 && (
                            <Badge variant="success" className="text-[10px]">+{added.length} added</Badge>
                          )}
                          {removed.length > 0 && (
                            <Badge variant="destructive" className="text-[10px]">&minus;{removed.length} removed</Badge>
                          )}
                          {modified.length > 0 && (
                            <Badge variant="warning" className="text-[10px]">~{modified.length} changed</Badge>
                          )}
                          {unchangedList.length > 0 && (
                            <Badge variant="default" className="text-[10px]">{unchangedList.length} unchanged</Badge>
                          )}
                        </div>

                        {compareResult.changes.length === 0 && unchangedList.length === 0 ? (
                          <p className="text-sm text-zinc-500 py-4 text-center">
                            No configuration data found for the selected timestamps.
                          </p>
                        ) : compareResult.changes.length === 0 ? (
                          <p className="text-sm text-zinc-500 py-4 text-center">
                            No differences between these two snapshots.
                          </p>
                        ) : (
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-8"></TableHead>
                                <TableHead>Key</TableHead>
                                <TableHead>Before</TableHead>
                                <TableHead>After</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {compareResult.changes.map(renderDiffRow)}
                            </TableBody>
                          </Table>
                        )}

                        {/* Unchanged keys in collapsible section */}
                        {unchangedList.length > 0 && (
                          <details className="mt-2">
                            <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-300 select-none">
                              {unchangedList.length} unchanged key{unchangedList.length !== 1 ? "s" : ""}
                            </summary>
                            <div className="mt-2">
                              <Table>
                                <TableHeader>
                                  <TableRow>
                                    <TableHead className="w-8"></TableHead>
                                    <TableHead>Key</TableHead>
                                    <TableHead>Before</TableHead>
                                    <TableHead>After</TableHead>
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {unchangedList.map(renderDiffRow)}
                                </TableBody>
                              </Table>
                            </div>
                          </details>
                        )}
                      </>
                    );
                  })()}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Diff dialog for single key */}
        {diffKey && (
          <Dialog open onClose={() => setDiffKey(null)} title={`History: ${diffKey}`}>
            <div className="max-h-[60vh] overflow-auto">
              {diffRows.length === 0 ? (
                <p className="text-sm text-zinc-500 p-4">No history found.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Time</TableHead>
                      <TableHead>Value</TableHead>
                      <TableHead className="w-20">Hash</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {diffRows.map((row, i) => {
                      const prevRow = diffRows[i + 1];
                      const changed = !prevRow || prevRow.config_hash !== row.config_hash;
                      return (
                        <TableRow
                          key={`${row.executed_at}-${i}`}
                          className={changed ? "bg-amber-500/10" : ""}
                        >
                          <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                            {formatDate(row.executed_at, tz)}
                          </TableCell>
                          <TableCell className="text-xs font-mono max-w-[400px] whitespace-pre-wrap break-all">
                            {row.config_value}
                          </TableCell>
                          <TableCell className="text-xs font-mono text-zinc-500">
                            {row.config_hash.slice(0, 8)}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" size="sm" onClick={() => setDiffKey(null)}>
                Close
              </Button>
            </DialogFooter>
          </Dialog>
        )}
      </div>
    </div>
  );
}

// ── Tab: Retention ────────────────────────────────────────

const DATA_TYPE_LABELS: Record<string, string> = {
  config: "Config",
  performance: "Performance",
  availability_latency: "Availability & Latency",
  interface: "Interface",
};

const DATA_TYPE_COLORS: Record<string, string> = {
  config: "bg-purple-500/20 text-purple-400",
  performance: "bg-indigo-500/20 text-indigo-400",
  availability_latency: "bg-emerald-500/20 text-emerald-400",
  interface: "bg-cyan-500/20 text-cyan-400",
};

function RetentionTab({ deviceId }: { deviceId: string }) {
  const { data: entries, isLoading } = useDeviceRetention(deviceId);
  const setRetention = useSetDeviceRetention();
  const deleteRetention = useDeleteDeviceRetention();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!entries || entries.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 flex flex-col items-center gap-3 text-zinc-600">
          <Database className="h-8 w-8 text-zinc-700" />
          <p className="text-sm text-zinc-500">No apps assigned to this device.</p>
          <p className="text-xs text-zinc-700">Assign apps on the Assignments tab to configure data retention.</p>
        </CardContent>
      </Card>
    );
  }

  // Group by data_type
  const grouped = new Map<string, DeviceRetentionEntry[]>();
  for (const e of entries) {
    const list = grouped.get(e.data_type) ?? [];
    list.push(e);
    grouped.set(e.data_type, list);
  }

  async function handleSave(entry: DeviceRetentionEntry) {
    const days = parseInt(editValue, 10);
    if (isNaN(days) || days < 1) return;
    await setRetention.mutateAsync({
      deviceId,
      app_id: entry.app_id,
      data_type: entry.data_type,
      retention_days: days,
    });
    setEditingId(null);
  }

  async function handleReset(entry: DeviceRetentionEntry) {
    if (!entry.override_id) return;
    await deleteRetention.mutateAsync({ deviceId, overrideId: entry.override_id });
  }

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-blue-800/40 bg-blue-950/20 px-4 py-3">
        <p className="text-xs text-blue-300">
          Device-specific retention overrides the global default.
          Edit a value to customize, or reset to inherit from global settings.
        </p>
      </div>

      {[...grouped.entries()].map(([dataType, items]) => (
        <Card key={dataType}>
          <CardHeader className="py-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Badge className={`text-[10px] ${DATA_TYPE_COLORS[dataType] ?? ""}`}>
                {DATA_TYPE_LABELS[dataType] ?? dataType}
              </Badge>
              data retention
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>App</TableHead>
                  <TableHead className="w-36">Retention</TableHead>
                  <TableHead className="w-32">Source</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((entry) => {
                  const isEditing = editingId === `${entry.app_id}-${entry.data_type}`;
                  return (
                    <TableRow key={`${entry.app_id}-${entry.data_type}`}>
                      <TableCell className="text-xs font-medium">{entry.app_name}</TableCell>
                      <TableCell>
                        {isEditing ? (
                          <div className="flex items-center gap-1.5">
                            <Input
                              type="number"
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              className="w-20 h-7 text-xs"
                              autoFocus
                              onKeyDown={(e) => {
                                if (e.key === "Enter") handleSave(entry);
                                if (e.key === "Escape") setEditingId(null);
                              }}
                            />
                            <span className="text-xs text-zinc-500">days</span>
                            <Button size="sm" className="h-6 px-2 text-xs" onClick={() => handleSave(entry)}
                              disabled={setRetention.isPending}>
                              <Save className="h-3 w-3" />
                            </Button>
                            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => setEditingId(null)}>
                              <X className="h-3 w-3" />
                            </Button>
                          </div>
                        ) : (
                          <button
                            className="text-xs text-zinc-200 hover:text-brand-400 cursor-pointer"
                            onClick={() => {
                              setEditingId(`${entry.app_id}-${entry.data_type}`);
                              setEditValue(String(entry.retention_days));
                            }}
                          >
                            {entry.retention_days} days
                          </button>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={entry.source === "device_override" ? "info" : "default"}
                          className="text-[10px]"
                        >
                          {entry.source === "device_override" ? "device override" : "global default"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {entry.source === "device_override" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2 text-xs text-zinc-500 hover:text-zinc-300"
                            onClick={() => handleReset(entry)}
                            disabled={deleteRetention.isPending}
                          >
                            Reset
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
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

// formatBps removed — traffic columns now use formatTraffic from InterfaceTrafficChart

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

function matchesTextFilter(value: string, filter: string): boolean {
  if (!filter) return true;
  const lower = value.toLowerCase();
  const f = filter.toLowerCase();
  if (f.includes("*") || f.startsWith("^") || f.endsWith("$")) {
    try {
      return new RegExp(f.replace(/\*/g, ".*")).test(lower);
    } catch {
      return lower.includes(f);
    }
  }
  return lower.includes(f);
}

const MAX_CHART_INTERFACES = 8;

type IfaceStatusFilter = "all" | "up" | "down" | "unmonitored";

function InterfacesTab({ deviceId }: { deviceId: string }) {
  const { user } = useAuth();
  const { data: interfaces, isLoading } = useInterfaceLatest(deviceId);
  const { data: metadata } = useInterfaceMetadata(deviceId);
  const updateSettings = useUpdateInterfaceSettings();
  const bulkUpdate = useBulkUpdateInterfaceSettings();
  const refreshMeta = useRefreshInterfaceMetadata();
  const updateIfacePrefs = useUpdateInterfacePreferences();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [timeRange, setTimeRange] = useState<TimeRangeValue>(() => {
    const pref = user?.iface_time_range;
    if (pref && ["1h", "6h", "24h", "7d", "30d"].includes(pref)) {
      return { type: "preset", preset: pref as TimeRangePreset };
    }
    return DEFAULT_RANGE;
  });
  const [sortKey, setSortKey] = useState<IfaceSortKey>("if_index");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [trafficUnit, setTrafficUnit] = useState<TrafficUnit>(
    (user?.iface_traffic_unit as TrafficUnit) ?? "auto"
  );
  const [chartMetric, setChartMetric] = useState<ChartMetric>(
    (user?.iface_chart_metric as ChartMetric) ?? "traffic"
  );
  const [chartMode, setChartMode] = useState<ChartMode>("overlaid");
  const [statusFilter, setStatusFilter] = useState<IfaceStatusFilter>(
    (user?.iface_status_filter as IfaceStatusFilter) ?? "all"
  );
  const [filterName, setFilterName] = useState("");
  const [filterAlias, setFilterAlias] = useState("");
  const [filterOperStatus, setFilterOperStatus] = useState<string>("");
  const [filterSpeed, setFilterSpeed] = useState<string>("");
  const tz = useTimezone();
  const { data: monitoring } = useDeviceMonitoring(deviceId);
  const { fromTs, toTs } = useMemo(() => rangeToTimestamps(timeRange), [timeRange]);

  // Build metadata lookup
  const metaMap = useMemo(() => {
    const m = new Map<string, { polling_enabled: boolean; alerting_enabled: boolean; poll_metrics: string }>();
    for (const meta of metadata ?? []) {
      m.set(meta.id, { polling_enabled: meta.polling_enabled, alerting_enabled: meta.alerting_enabled, poll_metrics: meta.poll_metrics ?? "all" });
    }
    return m;
  }, [metadata]);

  // Device has an interface poller app assigned?
  const hasInterfacePoller = !!monitoring?.interface?.app_name;

  const isUnmonitored = useCallback(
    (iface: { interface_id: string }) => {
      if (!hasInterfacePoller) return true;
      const meta = metaMap.get(iface.interface_id);
      return !(meta?.polling_enabled ?? true);
    },
    [hasInterfacePoller, metaMap],
  );

  // Filter out orphaned ClickHouse rows (interface_id not in metadata).
  // This happens when metadata is recreated with a new UUID — the old
  // ClickHouse rows reference a stale interface_id that no longer exists in PG.
  const validInterfaces = useMemo(() => {
    if (!metadata?.length) return interfaces ?? [];
    const metaIds = new Set(metadata.map(m => m.id));
    return (interfaces ?? []).filter(i => metaIds.has(i.interface_id));
  }, [interfaces, metadata]);

  // Dynamic filter options
  const availableOperStatuses = useMemo(() =>
    [...new Set(validInterfaces.map(i => i.if_oper_status))].sort(), [validInterfaces]);
  const availableSpeeds = useMemo(() =>
    [...new Set(validInterfaces.map(i => i.if_speed_mbps))].filter(Boolean).sort((a, b) => a - b), [validInterfaces]);

  // Filter
  const filtered = useMemo(() => {
    let data = validInterfaces;
    // Status badge filter
    if (statusFilter === "up") data = data.filter(i => i.if_oper_status === "up" && !isUnmonitored(i));
    else if (statusFilter === "down") data = data.filter(i => i.if_oper_status !== "up" && !isUnmonitored(i));
    else if (statusFilter === "unmonitored") data = data.filter(i => isUnmonitored(i));
    // Column filters
    if (filterName) data = data.filter(i => matchesTextFilter(i.if_name, filterName));
    if (filterAlias) data = data.filter(i => matchesTextFilter(i.if_alias || "", filterAlias));
    if (filterOperStatus) data = data.filter(i => i.if_oper_status === filterOperStatus);
    if (filterSpeed) data = data.filter(i => i.if_speed_mbps === Number(filterSpeed));
    return data;
  }, [validInterfaces, statusFilter, filterName, filterAlias, filterOperStatus, filterSpeed, isUnmonitored]);

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
  const activeSelectedCount = [...selectedIds].filter(id => filteredIds.has(id)).length;

  const toggleSelectAll = () => {
    if (allFilteredSelected) {
      setSelectedIds(prev => { const next = new Set(prev); for (const i of filtered) next.delete(i.interface_id); return next; });
    } else {
      setSelectedIds(prev => { const next = new Set(prev); for (const i of filtered) next.add(i.interface_id); return next; });
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  };

  // Multi-interface chart data
  const chartInterfaceIds = useMemo(() => {
    return [...selectedIds].filter(id => filteredIds.has(id)).slice(0, MAX_CHART_INTERFACES);
  }, [selectedIds, filteredIds]);
  const showMultiChart = chartInterfaceIds.length > 0;
  const tooManySelected = activeSelectedCount > MAX_CHART_INTERFACES;

  const { data: multiHistory } = useMultiInterfaceHistory(
    deviceId, fromTs, toTs, showMultiChart ? chartInterfaceIds : [],
  );

  // Bulk metric toggle for selected interfaces
  const bulkToggleMetric = (metric: string, enable: boolean) => {
    const ids = [...selectedIds].filter(id => filteredIds.has(id));
    if (ids.length === 0) return;
    for (const id of ids) {
      const meta = metaMap.get(id);
      const current = parseMetrics(meta?.poll_metrics ?? "all");
      if (enable) current.add(metric); else current.delete(metric);
      updateSettings.mutate({ deviceId, interfaceId: id, data: { poll_metrics: serializeMetrics(current) } });
    }
  };

  const selectedHaveMetric = (metric: string): boolean | "mixed" => {
    const ids = [...selectedIds].filter(id => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map(id => parseMetrics(metaMap.get(id)?.poll_metrics ?? "all").has(metric));
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const selectedHavePolling = (): boolean | "mixed" => {
    const ids = [...selectedIds].filter(id => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map(id => metaMap.get(id)?.polling_enabled ?? true);
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const selectedHaveAlerting = (): boolean | "mixed" => {
    const ids = [...selectedIds].filter(id => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map(id => metaMap.get(id)?.alerting_enabled ?? true);
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const bulkTogglePolling = (enable: boolean) => {
    const ids = [...selectedIds].filter(id => filteredIds.has(id));
    if (ids.length === 0) return;
    bulkUpdate.mutate({ deviceId, data: { interface_ids: ids, polling_enabled: enable } });
  };

  const bulkToggleAlerting = (enable: boolean) => {
    const ids = [...selectedIds].filter(id => filteredIds.has(id));
    if (ids.length === 0) return;
    bulkUpdate.mutate({ deviceId, data: { interface_ids: ids, alerting_enabled: enable } });
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
    return <div className="flex h-64 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>;
  }

  if (!interfaces?.length) {
    return (
      <Card><CardContent className="py-12">
        <div className="flex flex-col items-center justify-center text-zinc-500">
          <Network className="mb-2 h-8 w-8 text-zinc-600" />
          <p className="text-sm">No interface data collected yet.</p>
          <p className="text-xs text-zinc-600 mt-1">Assign an interface poller app to this device to start collecting data.</p>
        </div>
      </CardContent></Card>
    );
  }

  const upCount = validInterfaces.filter(i => i.if_oper_status === "up" && !isUnmonitored(i)).length;
  const downCount = validInterfaces.filter(i => i.if_oper_status !== "up" && !isUnmonitored(i)).length;
  const unmonitoredCount = validInterfaces.filter(isUnmonitored).length;

  const handleStatusFilter = (next: IfaceStatusFilter) => {
    setStatusFilter(next);
    updateIfacePrefs.mutate({ iface_status_filter: next });
  };
  const handleTrafficUnit = (next: TrafficUnit) => {
    setTrafficUnit(next);
    updateIfacePrefs.mutate({ iface_traffic_unit: next as any });
  };
  const handleChartMetric = (next: ChartMetric) => {
    setChartMetric(next);
    updateIfacePrefs.mutate({ iface_chart_metric: next });
  };
  const handleTimeRange = (next: TimeRangeValue) => {
    setTimeRange(next);
    if (next.type === "preset" && ["1h", "6h", "24h", "7d", "30d"].includes(next.preset)) {
      updateIfacePrefs.mutate({ iface_time_range: next.preset as any });
    }
  };

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2 text-sm flex-wrap">
          <span className="text-zinc-500">Interfaces:</span>
          {([
            { value: "all" as const, count: validInterfaces.length, label: "all", cls: "bg-zinc-700 text-zinc-200 border-zinc-600" },
            { value: "up" as const, count: upCount, label: "up", cls: "bg-green-900/60 text-green-400 border-green-700" },
            { value: "down" as const, count: downCount, label: "down", cls: "bg-red-900/60 text-red-400 border-red-700" },
            { value: "unmonitored" as const, count: unmonitoredCount, label: "unmonitored", cls: "bg-zinc-800 text-zinc-400 border-zinc-600" },
          ]).map(({ value, count, label, cls }) => (
            <button
              key={value}
              onClick={() => handleStatusFilter(value)}
              className={[
                "inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium transition-all",
                cls,
                statusFilter === value
                  ? "ring-2 ring-offset-1 ring-offset-zinc-900 ring-brand-500 opacity-100"
                  : "opacity-55 hover:opacity-80",
              ].join(" ")}
            >
              {count} {label}
            </button>
          ))}
          {activeSelectedCount > 0 && <Badge variant="default">{activeSelectedCount} selected</Badge>}
        </div>
        <Button variant="outline" size="sm" className="h-7 text-xs gap-1" disabled={refreshMeta.isPending} onClick={() => refreshMeta.mutate(deviceId)}>
          {refreshMeta.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          Refresh Metadata
        </Button>
        {refreshMeta.isSuccess && <span className="text-xs text-emerald-400">Queued</span>}
        <div className="ml-auto flex items-center gap-2">
          <Select value={trafficUnit} onChange={e => handleTrafficUnit(e.target.value as TrafficUnit)} className="h-7 text-xs w-24">
            <option value="auto">Auto</option>
            <option value="kbps">Kbps</option>
            <option value="mbps">Mbps</option>
            <option value="gbps">Gbps</option>
            <option value="pct">% util</option>
          </Select>
          <Select value={chartMetric} onChange={e => handleChartMetric(e.target.value as ChartMetric)} className="h-7 text-xs w-28">
            <option value="traffic">Traffic</option>
            <option value="errors">Errors</option>
            <option value="discards">Discards</option>
          </Select>
          <TimeRangePicker value={timeRange} onChange={handleTimeRange} timezone={tz} />
        </div>
      </div>

      {/* Multi-interface chart */}
      {showMultiChart && multiHistory ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-zinc-400 flex items-center gap-2 flex-wrap">
              <span>
                {chartMetric === "traffic" ? "Traffic" : chartMetric === "errors" ? "Errors" : "Discards"}
                {" \u2014 "}{chartInterfaceIds.length} interface{chartInterfaceIds.length > 1 ? "s" : ""}
              </span>
              <div className="ml-auto flex items-center gap-2">
                <div className="flex items-center gap-0.5 border border-zinc-700 rounded px-0.5">
                  <button onClick={() => setChartMode("overlaid")}
                    className={`px-1.5 py-0.5 text-xs rounded ${chartMode === "overlaid" ? "bg-zinc-700 text-zinc-200" : "text-zinc-500"}`}>Overlay</button>
                  <button onClick={() => setChartMode("stacked")}
                    className={`px-1.5 py-0.5 text-xs rounded ${chartMode === "stacked" ? "bg-zinc-700 text-zinc-200" : "text-zinc-500"}`}>Stacked</button>
                </div>
                <button onClick={() => setSelectedIds(new Set())} className="text-zinc-600 hover:text-zinc-300">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MultiInterfaceChart
              interfaceIds={chartInterfaceIds}
              interfaceNames={chartInterfaceIds.map(id => interfaces?.find(i => i.interface_id === id)?.if_name ?? id)}
              historyPerInterface={multiHistory}
              metric={chartMetric}
              unit={trafficUnit}
              mode={chartMode}
              timezone={tz}
            />
          </CardContent>
        </Card>
      ) : tooManySelected ? (
        <Card><CardContent className="py-3">
          <p className="text-sm text-zinc-400 text-center">
            Select up to {MAX_CHART_INTERFACES} interfaces to show the chart. Currently {activeSelectedCount} selected.
          </p>
        </CardContent></Card>
      ) : null}

      {/* Interface table */}
      <Card>
        <CardContent className="pt-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" onClick={e => e.stopPropagation()}>
                  <input type="checkbox" checked={allFilteredSelected}
                    ref={el => { if (el) el.indeterminate = !allFilteredSelected && someFilteredSelected; }}
                    onChange={toggleSelectAll} className="accent-brand-500 cursor-pointer" />
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
                <InterfaceToggleBulkHead
                  activeSelectedCount={activeSelectedCount}
                  state={{
                    polling: selectedHavePolling(),
                    alerting: selectedHaveAlerting(),
                    traffic: selectedHaveMetric("traffic"),
                    errors: selectedHaveMetric("errors"),
                    discards: selectedHaveMetric("discards"),
                    status: selectedHaveMetric("status"),
                  }}
                  onTogglePolling={bulkTogglePolling}
                  onToggleAlerting={bulkToggleAlerting}
                  onToggleMetric={(metric, enable) => bulkToggleMetric(metric, enable)}
                />
              </TableRow>
              {/* Filter row */}
              <TableRow className="bg-zinc-900/50">
                <TableCell />
                <TableCell>
                  {availableOperStatuses.length > 1 && (
                    <Select value={filterOperStatus} onChange={e => setFilterOperStatus(e.target.value)} className="h-6 text-[10px] w-full">
                      <option value="">All</option>
                      {availableOperStatuses.map(s => <option key={s} value={s}>{s}</option>)}
                    </Select>
                  )}
                </TableCell>
                <TableCell />
                <TableCell>
                  <ClearableInput placeholder="Filter..." value={filterName} onChange={e => setFilterName(e.target.value)} onClear={() => setFilterName("")} className="h-6 text-[10px]" />
                </TableCell>
                <TableCell>
                  <ClearableInput placeholder="Filter..." value={filterAlias} onChange={e => setFilterAlias(e.target.value)} onClear={() => setFilterAlias("")} className="h-6 text-[10px]" />
                </TableCell>
                <TableCell>
                  {availableSpeeds.length > 1 && (
                    <Select value={filterSpeed} onChange={e => setFilterSpeed(e.target.value)} className="h-6 text-[10px] w-full">
                      <option value="">All</option>
                      {availableSpeeds.map(s => <option key={s} value={String(s)}>{formatSpeed(s)}</option>)}
                    </Select>
                  )}
                </TableCell>
                <TableCell /><TableCell /><TableCell /><TableCell /><TableCell />
                <TableCell /> {/* Toggles — no filter */}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((iface) => {
                const meta = metaMap.get(iface.interface_id);
                const pollingOn = meta?.polling_enabled ?? true;
                const alertingOn = meta?.alerting_enabled ?? true;
                const metrics = parseMetrics(meta?.poll_metrics ?? "all");
                const isSelected = selectedIds.has(iface.interface_id);
                const unmonitored = isUnmonitored(iface);

                const toggleMetric = (metric: string) => {
                  const next = new Set(metrics);
                  if (next.has(metric)) next.delete(metric); else next.add(metric);
                  updateSettings.mutate({ deviceId, interfaceId: iface.interface_id, data: { poll_metrics: serializeMetrics(next) } });
                };

                return (
                <TableRow key={iface.interface_id}
                  className={`cursor-pointer transition-colors ${isSelected ? "bg-zinc-800/70" : "hover:bg-zinc-800/50"} ${unmonitored ? "opacity-40" : ""}`}
                  onClick={() => toggleSelect(iface.interface_id)}
                >
                  <TableCell onClick={e => e.stopPropagation()}>
                    <input type="checkbox" checked={isSelected} onChange={() => toggleSelect(iface.interface_id)} className="accent-brand-500 cursor-pointer" />
                  </TableCell>
                  <TableCell>
                    <div className={`h-2.5 w-2.5 rounded-full ${iface.if_oper_status === "up" ? "bg-emerald-500" : iface.if_oper_status === "down" ? "bg-red-500" : "bg-zinc-600"}`} />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-zinc-500">{iface.if_index}</TableCell>
                  <TableCell className="font-medium text-zinc-100">{iface.if_name}</TableCell>
                  <TableCell className="text-zinc-400 text-sm">{iface.if_alias || "\u2014"}</TableCell>
                  <TableCell className="text-zinc-300 text-sm">{formatSpeed(iface.if_speed_mbps)}</TableCell>
                  <TableCell className="font-mono text-xs text-cyan-400">
                    {iface.in_rate_bps > 0 ? formatTraffic(iface.in_rate_bps, trafficUnit, iface.if_speed_mbps) : "\u2014"}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-indigo-400">
                    {iface.out_rate_bps > 0 ? formatTraffic(iface.out_rate_bps, trafficUnit, iface.if_speed_mbps) : "\u2014"}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    <span className={iface.in_errors > 0 ? "text-amber-400" : "text-zinc-600"}>{iface.in_errors.toLocaleString()}</span>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    <span className={iface.out_errors > 0 ? "text-amber-400" : "text-zinc-600"}>{iface.out_errors.toLocaleString()}</span>
                  </TableCell>
                  <TableCell className="text-zinc-500 text-xs">{timeAgo(iface.executed_at)}</TableCell>
                  <TableCell className="text-center" onClick={e => e.stopPropagation()}>
                    <InterfaceToggleCell
                      state={{
                        polling_enabled: pollingOn,
                        alerting_enabled: alertingOn,
                        traffic: metrics.has("traffic"),
                        errors: metrics.has("errors"),
                        discards: metrics.has("discards"),
                        status: metrics.has("status"),
                      }}
                      onTogglePolling={() => updateSettings.mutate({ deviceId, interfaceId: iface.interface_id, data: { polling_enabled: !pollingOn } })}
                      onToggleAlerting={() => updateSettings.mutate({ deviceId, interfaceId: iface.interface_id, data: { alerting_enabled: !alertingOn } })}
                      onToggleMetric={toggleMetric}
                    />
                  </TableCell>
                </TableRow>
                );
              })}
              {sorted.length === 0 && (
                <TableRow>
                  <TableCell colSpan={12} className="text-center py-8 text-zinc-500 text-sm">
                    {statusFilter === "unmonitored"
                      ? "No unmonitored interfaces."
                      : statusFilter === "up"
                      ? "No interfaces are currently up."
                      : statusFilter === "down"
                      ? "No interfaces are currently down."
                      : "No interfaces match your filters."}
                  </TableCell>
                </TableRow>
              )}
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
  const { data: allAppsResp } = useApps();
  const allApps = allAppsResp?.data ?? [];
  const updateMonitoring = useUpdateDeviceMonitoring();

  // Only apps targeting availability_latency can be used for avail/latency monitoring
  const monitoringApps = useMemo(
    () => allApps.filter((a) => a.target_table === "availability_latency"),
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
            <TableHead className="text-xs py-1">Version</TableHead>
            <TableHead className="text-xs py-1">Role</TableHead>
            <TableHead className="text-xs py-1">Interval</TableHead>
            <TableHead className="text-xs py-1">Credential(s)</TableHead>
            <TableHead className="text-xs py-1">Collector</TableHead>
            <TableHead className="text-xs py-1">Enabled</TableHead>
            <TableHead className="text-xs py-1 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {assignments.map((a) => (
            <TableRow key={a.id}>
              <TableCell className="py-1.5 font-mono text-sm">{a.app.name}</TableCell>
              <TableCell className="py-1.5">
                <div className="flex items-center gap-1">
                  <Badge variant="default" className="text-[10px]">
                    v{a.app.version}
                  </Badge>
                  {a.use_latest && (
                    <Badge variant="default" className="text-[10px] text-zinc-500 border-zinc-700">
                      latest
                    </Badge>
                  )}
                </div>
              </TableCell>
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
                <CredentialCell
                  credentialName={a.credential_name}
                  credentialOverrides={a.credential_overrides}
                  deviceDefaultCredentialName={a.device_default_credential_name}
                />
              </TableCell>
              <TableCell className="py-1.5">
                {a.collector_id ? (
                  <span className="inline-flex items-center gap-1 text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded px-1.5 py-0.5">
                    <Pin className="h-2.5 w-2.5" />
                    {a.collector_name ?? "pinned"}
                  </span>
                ) : (
                  <span className="text-zinc-600 text-xs">group</span>
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
        deviceCollectorGroupId={device?.collector_group_id ?? null}
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

function formatCredentialType(type: string): string {
  return type
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function SettingsTab({ deviceId }: { deviceId: string }) {
  const { data: device, isLoading: deviceLoading } = useDevice(deviceId);
  const { data: deviceTypes } = useDeviceTypes();
  const { data: tenants } = useTenants();
  const { data: collectorGroups } = useCollectorGroups();
  const { data: allCredentials } = useCredentials();
  const { data: credentialTypes } = useCredentialTypes();
  const updateDevice = useUpdateDevice();

  // Device fields
  const settingsNameField = useField("", validateName);
  const settingsAddressField = useField("", validateAddress);
  const [deviceType, setDeviceType] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [collectorGroupId, setCollectorGroupId] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Credentials (per-protocol)
  const [deviceCreds, setDeviceCreds] = useState<Record<string, string>>({});
  const [credsModified, setCredsModified] = useState(false);
  const [credsSaving, setCredsSaving] = useState(false);
  const [credsSaveSuccess, setCredsSaveSuccess] = useState(false);
  const [credError, setCredError] = useState<string | null>(null);

  // Labels
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [labelsModified, setLabelsModified] = useState(false);
  const [labelsSaving, setLabelsSaving] = useState(false);
  const [labelsSaveSuccess, setLabelsSaveSuccess] = useState(false);
  const [labelError, setLabelError] = useState<string | null>(null);

  // Retention overrides
  const { data: systemSettings } = useSystemSettings();
  const [retentionOverrides, setRetentionOverrides] = useState<Record<string, string>>({});
  const [retentionModified, setRetentionModified] = useState(false);
  const [retentionSaving, setRetentionSaving] = useState(false);
  const [retentionSaveSuccess, setRetentionSaveSuccess] = useState(false);
  const [retentionError, setRetentionError] = useState<string | null>(null);

  // Initialize form fields when device loads
  useEffect(() => {
    if (device) {
      settingsNameField.reset(device.name);
      settingsAddressField.reset(device.address);
      setDeviceType(device.device_type);
      setTenantId(device.tenant_id ?? "");
      setCollectorGroupId(device.collector_group_id ?? "");
      setLabels(device.labels ?? {});
      setRetentionOverrides(device.retention_overrides ?? {});
      setRetentionModified(false);
      // Build credentials state from resolved credentials
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
          name: settingsNameField.value.trim(),
          address: settingsAddressField.value.trim(),
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

  // Group all credentials by type for dropdowns
  const credsByType = useMemo(() => {
    const map: Record<string, typeof allCredentials> = {};
    for (const c of allCredentials ?? []) {
      (map[c.credential_type] ??= []).push(c);
    }
    return map;
  }, [allCredentials]);

  // Available credential types (from managed list, not already assigned)
  const availableTypes = useMemo(() => {
    const typeNames = (credentialTypes ?? []).map((ct) => ct.name);
    // Also include types that have credentials but aren't in the managed list
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
      setCredError(err instanceof Error ? err.message : "Failed to save credentials");
    } finally {
      setCredsSaving(false);
    }
  }

  async function handleSaveRetention() {
    setRetentionError(null);
    setRetentionSaving(true);
    setRetentionSaveSuccess(false);
    try {
      const cleanOverrides: Record<string, string> = {};
      for (const [k, v] of Object.entries(retentionOverrides)) {
        if (v != null && v !== "") cleanOverrides[k] = v;
      }
      await updateDevice.mutateAsync({
        id: deviceId,
        data: { retention_overrides: cleanOverrides },
      });
      setRetentionModified(false);
      setRetentionSaveSuccess(true);
      setTimeout(() => setRetentionSaveSuccess(false), 3000);
    } catch (err) {
      setRetentionError(err instanceof Error ? err.message : "Failed to save retention overrides");
    } finally {
      setRetentionSaving(false);
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
          <form onSubmit={handleSaveDevice}>
            <div className="grid grid-cols-2 gap-x-8 gap-y-3">
              <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                <Label htmlFor="s-name" className="text-right">Name</Label>
                <div>
                  <Input id="s-name" value={settingsNameField.value} onChange={settingsNameField.onChange} onBlur={settingsNameField.onBlur} />
                  {settingsNameField.error && <p className="text-xs text-red-400 mt-0.5">{settingsNameField.error}</p>}
                </div>
              </div>
              <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                <Label htmlFor="s-dtype" className="text-right">Device Type</Label>
                <Select id="s-dtype" value={deviceType} onChange={(e) => setDeviceType(e.target.value)}>
                  {(deviceTypes ?? []).map((dt) => (
                    <option key={dt.id} value={dt.name}>{dt.name}</option>
                  ))}
                </Select>
              </div>
              <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                <Label htmlFor="s-address" className="text-right">Address</Label>
                <div>
                  <Input id="s-address" value={settingsAddressField.value} onChange={settingsAddressField.onChange} onBlur={settingsAddressField.onBlur} />
                  {settingsAddressField.error && <p className="text-xs text-red-400 mt-0.5">{settingsAddressField.error}</p>}
                </div>
              </div>
              {tenants && tenants.length > 0 ? (
                <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                  <Label htmlFor="s-tenant" className="text-right">Tenant</Label>
                  <Select id="s-tenant" value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
                    <option value="">{"\u2014"} No tenant {"\u2014"}</option>
                    {tenants.map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </Select>
                </div>
              ) : <div />}
              <div />
              <div className="grid grid-cols-[110px_1fr] items-center gap-2">
                <Label htmlFor="s-cgroup" className="text-right">Collector Group</Label>
                <Select id="s-cgroup" value={collectorGroupId} onChange={(e) => setCollectorGroupId(e.target.value)}>
                  <option value="">{"\u2014"} No group {"\u2014"}</option>
                  {(collectorGroups ?? []).map((g) => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="mt-4 pt-4 border-t border-zinc-800 flex items-center gap-3">
              <Button type="submit" size="sm" disabled={updateDevice.isPending}>
                {updateDevice.isPending
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <Save className="h-4 w-4" />}
                Save Changes
              </Button>
              {saveError && <p className="text-sm text-red-400">{saveError}</p>}
              {saveSuccess && <p className="text-sm text-emerald-400">Saved.</p>}
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Credentials */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Key className="h-4 w-4" />
            Credentials
            {credsModified && (
              <Button
                size="sm"
                className="ml-auto gap-1.5"
                onClick={handleSaveCredentials}
                disabled={credsSaving}
              >
                {credsSaving
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <Save className="h-4 w-4" />}
                Save Credentials
              </Button>
            )}
            {credsSaveSuccess && (
              <span className="ml-auto text-sm text-emerald-400">Saved.</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {Object.keys(deviceCreds).length === 0 && availableTypes.length === 0 ? (
            <p className="text-sm text-zinc-500">No credentials configured. Create credentials first.</p>
          ) : (
            <div className="space-y-2">
              {Object.entries(deviceCreds).map(([ctype, credId]) => (
                <div key={ctype} className="flex items-center gap-2">
                  <Badge variant="default" className="text-xs min-w-[130px] justify-center">
                    {formatCredentialType(ctype)}
                  </Badge>
                  <Select
                    className="flex-1"
                    value={credId}
                    onChange={(e) => {
                      setDeviceCreds((prev) => ({ ...prev, [ctype]: e.target.value }));
                      setCredsModified(true);
                    }}
                  >
                    <option value="">-- Select --</option>
                    {(credsByType[ctype] ?? allCredentials ?? [])
                      .filter((c) => c.credential_type === ctype)
                      .map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
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
                      setDeviceCreds((prev) => ({ ...prev, [e.target.value]: "" }));
                      setCredsModified(true);
                    }
                  }}
                >
                  <option value="">+ Add credential type...</option>
                  {availableTypes.map((t) => (
                    <option key={t} value={t}>{formatCredentialType(t)}</option>
                  ))}
                </Select>
              )}
            </div>
          )}
          {credError && <p className="text-xs text-red-400 mt-2">{credError}</p>}
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

      {/* Data Retention Overrides */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            Data Retention Overrides
            {retentionModified && (
              <Button size="sm" className="ml-auto gap-1.5" onClick={handleSaveRetention} disabled={retentionSaving}>
                {retentionSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Save Retention
              </Button>
            )}
            {retentionSaveSuccess && <span className="ml-auto text-sm text-emerald-400">Saved.</span>}
          </CardTitle>
          <p className="text-xs text-zinc-600">Override system-wide retention settings for this device. Leave empty to use the system default.</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <span className="text-sm font-medium text-zinc-300">Interface Data</span>
            <RetentionOverrideRow label="Raw Data" settingKey="interface_raw_retention_days" systemDefault={systemSettings?.interface_raw_retention_days ?? "7"} value={retentionOverrides.interface_raw_retention_days} onChange={(v) => { setRetentionOverrides(prev => ({ ...prev, interface_raw_retention_days: v ?? "" })); setRetentionModified(true); }} options={[3, 7, 14, 30, 60, 90]} />
            <RetentionOverrideRow label="Hourly Rollup" settingKey="interface_hourly_retention_days" systemDefault={systemSettings?.interface_hourly_retention_days ?? "90"} value={retentionOverrides.interface_hourly_retention_days} onChange={(v) => { setRetentionOverrides(prev => ({ ...prev, interface_hourly_retention_days: v ?? "" })); setRetentionModified(true); }} options={[30, 60, 90, 180, 365]} />
            <RetentionOverrideRow label="Daily Rollup" settingKey="interface_daily_retention_days" systemDefault={systemSettings?.interface_daily_retention_days ?? "730"} value={retentionOverrides.interface_daily_retention_days} onChange={(v) => { setRetentionOverrides(prev => ({ ...prev, interface_daily_retention_days: v ?? "" })); setRetentionModified(true); }} options={[365, 730, 1095, 1825]} />
          </div>
          <div className="space-y-2">
            <span className="text-sm font-medium text-zinc-300">Performance Data</span>
            <RetentionOverrideRow label="Raw Data" settingKey="perf_raw_retention_days" systemDefault={systemSettings?.perf_raw_retention_days ?? "7"} value={retentionOverrides.perf_raw_retention_days} onChange={(v) => { setRetentionOverrides(prev => ({ ...prev, perf_raw_retention_days: v ?? "" })); setRetentionModified(true); }} options={[3, 7, 14, 30, 60, 90]} />
            <RetentionOverrideRow label="Hourly Rollup" settingKey="perf_hourly_retention_days" systemDefault={systemSettings?.perf_hourly_retention_days ?? "90"} value={retentionOverrides.perf_hourly_retention_days} onChange={(v) => { setRetentionOverrides(prev => ({ ...prev, perf_hourly_retention_days: v ?? "" })); setRetentionModified(true); }} options={[30, 60, 90, 180, 365]} />
            <RetentionOverrideRow label="Daily Rollup" settingKey="perf_daily_retention_days" systemDefault={systemSettings?.perf_daily_retention_days ?? "730"} value={retentionOverrides.perf_daily_retention_days} onChange={(v) => { setRetentionOverrides(prev => ({ ...prev, perf_daily_retention_days: v ?? "" })); setRetentionModified(true); }} options={[365, 730, 1095, 1825]} />
          </div>
          {retentionError && <p className="text-xs text-red-400">{retentionError}</p>}
        </CardContent>
      </Card>

      {/* Monitoring Configuration */}
      <MonitoringCard deviceId={deviceId} device={device} />
    </div>
  );
}


function RetentionOverrideRow({ label, systemDefault, value, onChange, options }: {
  label: string;
  settingKey: string;
  systemDefault: string;
  value: string | undefined;
  onChange: (v: string | undefined) => void;
  options: number[];
}) {
  const isOverridden = value != null && value !== "";
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-zinc-400 w-28">{label}</span>
      <Select value={value ?? ""} onChange={(e) => onChange(e.target.value || undefined)} className="max-w-52">
        <option value="">System default ({systemDefault}d)</option>
        {options.map((d) => <option key={d} value={String(d)}>{d} days</option>)}
      </Select>
      {isOverridden && (
        <button className="text-xs text-zinc-600 hover:text-zinc-400" onClick={() => onChange(undefined)}>Reset</button>
      )}
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
  const [subTab, setSubTab] = useState<"active" | "history">("active");
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1">
        {(["active", "history"] as const).map((t) => (
          <button key={t} onClick={() => setSubTab(t)}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${subTab === t ? "bg-zinc-700 text-white" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"}`}
          >{t === "active" ? "Active" : "History"}</button>
        ))}
      </div>
      {subTab === "active" ? <DeviceActiveAlerts deviceId={deviceId} /> : <DeviceAlertHistory deviceId={deviceId} />}
    </div>
  );
}

function DeviceActiveAlerts({ deviceId }: { deviceId: string }) {
  const listState = useListState({
    columns: [
      { key: "state", label: "State", filterable: false },
      { key: "definition_name", label: "Alert" },
      { key: "app_name", label: "App" },
      { key: "entity_key", label: "Entity" },
      { key: "current_value", label: "Value", filterable: false },
      { key: "fire_count", label: "Fires", filterable: false },
      { key: "started_firing_at", label: "Since", filterable: false },
    ],
    defaultSortBy: "state",
    defaultSortDir: "desc",
  });
  const { data: response, isLoading } = useAlertInstances({
    device_id: deviceId,
    ...listState.params,
  });
  const instances = (response as any)?.data ?? response ?? [];
  const meta = (response as any)?.meta ?? { limit: 50, offset: 0, count: instances.length, total: instances.length };
  const updateInstance = useUpdateAlertInstance();

  if (isLoading) return <div className="flex h-48 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-brand-500" /></div>;

  if (!instances || instances.length === 0) {
    return (
      <Card><CardContent className="py-12">
        <div className="flex flex-col items-center justify-center text-zinc-500">
          <Bell className="h-10 w-10 mb-3 text-zinc-600" />
          <p className="text-sm">No alert definitions for this device</p>
          <p className="text-xs text-zinc-600 mt-1">Alert definitions are created on apps and automatically applied when assigned</p>
        </div>
      </CardContent></Card>
    );
  }

  const firing = instances.filter((i: any) => i.state === "firing");

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-4 w-4" /> Active Alerts
            {firing.length > 0 && <Badge variant="destructive" className="ml-1.5 text-xs">{firing.length} firing</Badge>}
          </CardTitle>
          <span className="text-xs text-zinc-500">{meta.total} total</span>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <FilterableSortHead col="state" label="State" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
              <FilterableSortHead col="definition_name" label="Alert" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.definition_name} onFilterChange={(v) => listState.setFilter("definition_name", v)} />
              <FilterableSortHead col="app_name" label="App" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.app_name} onFilterChange={(v) => listState.setFilter("app_name", v)} />
              <FilterableSortHead col="entity_key" label="Entity" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.entity_key} onFilterChange={(v) => listState.setFilter("entity_key", v)} />
              <FilterableSortHead col="current_value" label="Value" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
              <FilterableSortHead col="fire_count" label="Fires" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
              <FilterableSortHead col="started_firing_at" label="Since" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
              <TableHead className="w-16">Enabled</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {instances.map((inst: any) => (
              <TableRow key={inst.id} className={inst.state === "firing" ? "bg-red-500/5" : ""}>
                <TableCell><Badge variant={inst.state === "firing" ? "destructive" : inst.state === "resolved" ? "warning" : "success"}>{inst.state}</Badge></TableCell>
                <TableCell className="font-medium">
                  {inst.definition_name ?? "\u2014"}
                  {inst.entity_labels?.if_name && <span className="ml-1.5 text-xs text-zinc-500">({inst.entity_labels.if_name})</span>}
                </TableCell>
                <TableCell className="text-zinc-400 text-sm">{inst.app_name ?? "\u2014"}</TableCell>
                <TableCell className="text-zinc-400 text-xs font-mono">{inst.entity_labels?.if_name || inst.entity_labels?.component || inst.entity_key || "\u2014"}</TableCell>
                <TableCell className="font-mono text-xs">{inst.current_value != null ? Number(inst.current_value).toFixed(2) : "\u2014"}</TableCell>
                <TableCell className="font-mono text-xs">{inst.fire_count ?? 0}</TableCell>
                <TableCell className="text-xs text-zinc-400">{inst.started_firing_at ? timeAgo(inst.started_firing_at) : "\u2014"}</TableCell>
                <TableCell className="text-center">
                  <button className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${inst.enabled ? "bg-brand-500" : "bg-zinc-600"}`}
                    onClick={() => updateInstance.mutate({ id: inst.id, enabled: !inst.enabled })}>
                    <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${inst.enabled ? "translate-x-4.5" : "translate-x-0.5"}`} />
                  </button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <PaginationBar page={listState.page} pageSize={listState.pageSize} total={meta.total} count={meta.count} onPageChange={listState.setPage} />
      </CardContent>
    </Card>
  );
}

function DeviceAlertHistory({ deviceId }: { deviceId: string }) {
  const [actionFilter, setActionFilter] = useState<string | undefined>(undefined);
  const listState = useListState({
    columns: [
      { key: "definition_name", label: "Alert" },
      { key: "severity", label: "Severity", filterable: false },
      { key: "message", label: "Message" },
      { key: "occurred_at", label: "Time", filterable: false },
    ],
    defaultSortBy: "occurred_at",
    defaultSortDir: "desc",
  });

  const { data: response, isLoading } = useDeviceAlertLog(deviceId, listState.params, { action: actionFilter });
  const logEntries = (response as any)?.data ?? [];
  const meta = (response as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-4 w-4" /> Alert History
            <Badge variant="default" className="ml-1.5 text-xs">{meta.total}</Badge>
          </CardTitle>
          <div className="flex items-center gap-1 text-xs">
            {([
              { val: undefined, label: "All", cls: "" },
              { val: "fire", label: "Fires", cls: "bg-red-500/20 text-red-400" },
              { val: "clear", label: "Clears", cls: "bg-green-500/20 text-green-400" },
            ] as const).map(({ val, label, cls }) => (
              <button key={label} onClick={() => setActionFilter(val)}
                className={`px-2 py-0.5 rounded ${actionFilter === val ? cls || "bg-zinc-700 text-white" : "text-zinc-400 hover:text-zinc-200"}`}>
                {label}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex h-32 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-brand-500" /></div>
        ) : logEntries.length === 0 ? (
          <p className="text-sm text-zinc-500 text-center py-8">No alert history for this device</p>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">Action</TableHead>
                  <FilterableSortHead col="definition_name" label="Alert" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.definition_name} onFilterChange={(v) => listState.setFilter("definition_name", v)} />
                  <TableHead>Entity</TableHead>
                  <FilterableSortHead col="severity" label="Severity" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
                  <TableHead>Value</TableHead>
                  <FilterableSortHead col="message" label="Message" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.message} onFilterChange={(v) => listState.setFilter("message", v)} sortable={false} />
                  <FilterableSortHead col="occurred_at" label="Time" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
                </TableRow>
              </TableHeader>
              <TableBody>
                {logEntries.map((entry: AlertLogEntry, idx: number) => (
                  <TableRow key={`${entry.definition_id}-${entry.occurred_at}-${idx}`} className={entry.action === "fire" ? "bg-red-500/5" : "bg-green-500/5"}>
                    <TableCell><Badge variant={entry.action === "fire" ? "destructive" : "success"}>{entry.action}</Badge></TableCell>
                    <TableCell className="font-medium">{entry.definition_name}</TableCell>
                    <TableCell className="text-zinc-400 text-xs font-mono">{entry.entity_key || "\u2014"}</TableCell>
                    <TableCell><SeverityBadge severity={entry.severity} /></TableCell>
                    <TableCell className="font-mono text-xs">{entry.current_value != null ? Number(entry.current_value).toFixed(2) : "\u2014"}</TableCell>
                    <TableCell className="text-xs text-zinc-400 max-w-[200px] truncate" title={entry.message}>{entry.message || "\u2014"}</TableCell>
                    <TableCell className="text-xs text-zinc-400 whitespace-nowrap">{timeAgo(entry.occurred_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <PaginationBar page={listState.page} pageSize={listState.pageSize} total={meta.total} count={meta.count} onPageChange={listState.setPage} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function EventsTab({ deviceId }: { deviceId: string }) {
  const [subTab, setSubTab] = useState<"active" | "cleared">("active");
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1">
        {(["active", "cleared"] as const).map((t) => (
          <button key={t} onClick={() => setSubTab(t)}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${subTab === t ? "bg-zinc-700 text-white" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"}`}
          >{t === "active" ? "Active" : "Cleared"}</button>
        ))}
      </div>
      {subTab === "active" ? <DeviceActiveEvents deviceId={deviceId} /> : <DeviceClearedEvents deviceId={deviceId} />}
    </div>
  );
}

function DeviceActiveEvents({ deviceId }: { deviceId: string }) {
  const listState = useListState({
    columns: [
      { key: "severity", label: "Severity", filterable: false },
      { key: "source", label: "Source" },
      { key: "policy_name", label: "Policy", sortable: false },
      { key: "message", label: "Message", sortable: false },
      { key: "occurred_at", label: "Occurred", filterable: false },
    ],
    defaultSortBy: "occurred_at",
    defaultSortDir: "desc",
  });
  const { data: response, isLoading } = useDeviceActiveEvents(deviceId, listState.params);
  const events = (response as any)?.data ?? [];
  const meta = (response as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const ackMut = useAcknowledgeEvents();
  const clearMut = useClearEvents();

  const toggle = (id: string) => setSelected((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const toggleAll = () => selected.size === events.length ? setSelected(new Set()) : setSelected(new Set(events.map((e: any) => e.id)));

  if (isLoading) return <Card><CardContent className="py-12"><div className="flex h-32 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-brand-500" /></div></CardContent></Card>;
  if (events.length === 0) return <Card><CardContent className="py-12"><div className="flex flex-col items-center justify-center text-zinc-500"><Zap className="h-10 w-10 mb-3 text-zinc-600" /><p className="text-sm">No active events for this device</p></div></CardContent></Card>;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2"><Zap className="h-4 w-4" /> Active Events ({meta.total})</CardTitle>
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" disabled={ackMut.isPending} onClick={async () => { await ackMut.mutateAsync([...selected]); setSelected(new Set()); }}>
                <Check className="h-3.5 w-3.5" /> Acknowledge ({selected.size})
              </Button>
              <Button size="sm" variant="outline" disabled={clearMut.isPending} onClick={async () => { await clearMut.mutateAsync([...selected]); setSelected(new Set()); }}>
                <CheckCheck className="h-3.5 w-3.5" /> Clear ({selected.size})
              </Button>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10"><input type="checkbox" checked={selected.size === events.length && events.length > 0} onChange={toggleAll} className="accent-brand-500 cursor-pointer" /></TableHead>
              <FilterableSortHead col="severity" label="Severity" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
              <FilterableSortHead col="source" label="Source" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.source} onFilterChange={(v) => listState.setFilter("source", v)} />
              <FilterableSortHead col="policy_name" label="Policy" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.policy_name} onFilterChange={(v) => listState.setFilter("policy_name", v)} sortable={false} />
              <FilterableSortHead col="message" label="Message" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.message} onFilterChange={(v) => listState.setFilter("message", v)} sortable={false} />
              <TableHead>State</TableHead>
              <FilterableSortHead col="occurred_at" label="Occurred" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((evt: MonitoringEvent) => (
              <TableRow key={evt.id}>
                <TableCell><input type="checkbox" checked={selected.has(evt.id)} onChange={() => toggle(evt.id)} className="accent-brand-500 cursor-pointer" /></TableCell>
                <TableCell><SeverityBadge severity={evt.severity} /></TableCell>
                <TableCell className="text-xs text-zinc-400">{evt.source}</TableCell>
                <TableCell className="text-xs">{evt.policy_name}</TableCell>
                <TableCell className="text-xs text-zinc-300 max-w-[300px] truncate" title={evt.message}>{evt.message}</TableCell>
                <TableCell><Badge variant={evt.state === "acknowledged" ? "warning" : "default"}>{evt.state}</Badge></TableCell>
                <TableCell className="text-xs text-zinc-400 whitespace-nowrap">{timeAgo(evt.occurred_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <PaginationBar page={listState.page} pageSize={listState.pageSize} total={meta.total} count={meta.count} onPageChange={listState.setPage} />
      </CardContent>
    </Card>
  );
}

function DeviceClearedEvents({ deviceId }: { deviceId: string }) {
  const listState = useListState({
    columns: [
      { key: "severity", label: "Severity", filterable: false },
      { key: "source", label: "Source" },
      { key: "policy_name", label: "Policy", sortable: false },
      { key: "occurred_at", label: "Occurred", filterable: false },
    ],
    defaultSortBy: "occurred_at",
    defaultSortDir: "desc",
  });
  const { data: response, isLoading } = useDeviceClearedEvents(deviceId, listState.params);
  const events = (response as any)?.data ?? [];
  const meta = (response as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };

  if (isLoading) return <Card><CardContent className="py-12"><div className="flex h-32 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-brand-500" /></div></CardContent></Card>;
  if (events.length === 0) return <Card><CardContent className="py-12"><div className="flex flex-col items-center justify-center text-zinc-500"><Zap className="h-10 w-10 mb-3 text-zinc-600" /><p className="text-sm">No cleared events for this device</p></div></CardContent></Card>;

  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><Clock className="h-4 w-4" /> Cleared Events ({meta.total})</CardTitle></CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <FilterableSortHead col="severity" label="Severity" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
              <FilterableSortHead col="source" label="Source" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.source} onFilterChange={(v) => listState.setFilter("source", v)} />
              <FilterableSortHead col="policy_name" label="Policy" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterValue={listState.filters.policy_name} onFilterChange={(v) => listState.setFilter("policy_name", v)} sortable={false} />
              <TableHead>Message</TableHead>
              <FilterableSortHead col="occurred_at" label="Occurred" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort} filterable={false} />
              <TableHead>Cleared</TableHead>
              <TableHead>Cleared By</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((evt: MonitoringEvent) => (
              <TableRow key={evt.id}>
                <TableCell><SeverityBadge severity={evt.severity} /></TableCell>
                <TableCell className="text-xs text-zinc-400">{evt.source}</TableCell>
                <TableCell className="text-xs">{evt.policy_name}</TableCell>
                <TableCell className="text-xs text-zinc-300 max-w-[300px] truncate" title={evt.message}>{evt.message}</TableCell>
                <TableCell className="text-xs text-zinc-400 whitespace-nowrap">{timeAgo(evt.occurred_at)}</TableCell>
                <TableCell className="text-xs text-zinc-400 whitespace-nowrap">{evt.cleared_at ? timeAgo(evt.cleared_at) : "\u2014"}</TableCell>
                <TableCell className="text-xs text-zinc-400">{evt.cleared_by || (evt.event_type === "alert_resolved" ? "auto" : "\u2014")}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <PaginationBar page={listState.page} pageSize={listState.pageSize} total={meta.total} count={meta.count} onPageChange={listState.setPage} />
      </CardContent>
    </Card>
  );
}

// ── Thresholds Tab ───────────────────────────────────────

function ThresholdsTab({ deviceId }: { deviceId: string }) {
  const { data: thresholds, isLoading } = useDeviceThresholds(deviceId);
  const createOverride = useCreateThresholdOverride();
  const updateOverride = useUpdateThresholdOverride();
  const deleteOverride = useDeleteThresholdOverride();

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
            <p className="text-sm">No threshold variables for this device</p>
          </div>
        </CardContent>
      </Card>
    );
  }

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
                  <TableHead>Threshold</TableHead>
                  <TableHead>Default</TableHead>
                  <TableHead>App Value</TableHead>
                  <TableHead>Device Override</TableHead>
                  <TableHead>Effective</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <ThresholdRow
                    key={row.variable_id}
                    row={row}
                    onSaveOverride={(varId, value, existingId) => {
                      if (existingId) {
                        updateOverride.mutate({ id: existingId, value });
                      } else {
                        createOverride.mutate({
                          variable_id: varId,
                          device_id: deviceId,
                          value,
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

function formatDeviceThresholdValue(value: number | null | undefined, unit: string | null): string {
  if (value == null) return "\u2014";
  if (unit === "percent") return `${value}%`;
  if (unit === "ms") return `${value} ms`;
  if (unit === "seconds") return `${value}s`;
  if (unit === "dBm") return `${value} dBm`;
  if (unit === "pps") return `${value} pps`;
  if (unit === "bps") {
    if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)} Gbps`;
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} Mbps`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)} kbps`;
    return `${value} bps`;
  }
  if (unit === "bytes") {
    if (value >= 1_073_741_824) return `${(value / 1_073_741_824).toFixed(1)} GB`;
    if (value >= 1_048_576) return `${(value / 1_048_576).toFixed(1)} MB`;
    if (value >= 1_024) return `${(value / 1_024).toFixed(1)} KB`;
    return `${value} B`;
  }
  if (unit) return `${value} ${unit}`;
  return String(value);
}

function ThresholdRow({
  row,
  onSaveOverride,
  onDeleteOverride,
}: {
  row: DeviceThresholdRow;
  onSaveOverride: (varId: string, value: number, existingId?: string) => void;
  onDeleteOverride: (id: string) => void;
}) {
  const [editValue, setEditValue] = useState<string>("");
  const [editing, setEditing] = useState(false);

  const handleSave = () => {
    const val = parseFloat(editValue);
    if (isNaN(val) || !isFinite(val)) return;
    onSaveOverride(row.variable_id, val, row.device_override_id ?? undefined);
    setEditing(false);
  };

  const effectiveSource =
    row.device_value != null ? "device" :
    row.app_value != null ? "app" :
    "default";

  return (
    <TableRow>
      <TableCell className="font-medium text-zinc-100">
        {row.display_name || row.name}
      </TableCell>
      <TableCell className="text-zinc-400 font-mono text-sm">
        {formatDeviceThresholdValue(row.expression_default, row.unit)}
      </TableCell>
      <TableCell className="text-zinc-400 font-mono text-sm">
        {row.app_value != null ? (
          <span className="text-blue-400">{formatDeviceThresholdValue(row.app_value, row.unit)}</span>
        ) : "\u2014"}
      </TableCell>
      <TableCell>
        {editing ? (
          <div className="flex items-center gap-1">
            <Input
              className="w-20 h-7 text-xs"
              type="number"
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
              className={`text-sm cursor-pointer hover:text-brand-400 ${row.device_value != null ? "text-brand-400 font-medium" : "text-zinc-500"}`}
              onClick={() => {
                setEditValue(String(row.device_value ?? row.effective_value));
                setEditing(true);
              }}
            >
              {row.device_value != null ? formatDeviceThresholdValue(row.device_value, row.unit) : "\u2014"}
            </span>
            {row.device_override_id && (
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-1 text-zinc-500 hover:text-red-400"
                onClick={() => onDeleteOverride(row.device_override_id!)}
              >
                <X className="h-3 w-3" />
              </Button>
            )}
          </div>
        )}
      </TableCell>
      <TableCell>
        <span className={effectiveSource !== "default" ? "font-mono text-sm text-brand-400 font-medium" : "font-mono text-sm text-zinc-300"}>
          {formatDeviceThresholdValue(row.effective_value, row.unit)}
        </span>
        {effectiveSource === "device" && (
          <span className="ml-1.5 text-xs text-zinc-500">(device override)</span>
        )}
        {effectiveSource === "app" && (
          <span className="ml-1.5 text-xs text-zinc-500">(app value)</span>
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
          <TabTrigger value="events">
            <span className="flex items-center gap-1.5">
              <Zap className="h-3.5 w-3.5" />
              Events
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
        <TabsContent value="events">
          <EventsTab deviceId={deviceId} />
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
        <TabsContent value="history">
          <HistoryTab deviceId={deviceId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
