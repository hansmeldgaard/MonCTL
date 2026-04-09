import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName, validateAddress } from "@/lib/validation.ts";
import {
  Activity,
  AlertTriangle,
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
  Search,
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
import { IntervalInput, formatInterval } from "@/components/IntervalInput";
import { InterfaceToggleCell } from "@/components/InterfaceToggleCell";
import { InterfaceToggleBulkHead } from "@/components/InterfaceToggleBulkHead";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { SearchableSelect } from "@/components/ui/searchable-select.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  Tabs,
  TabsList,
  TabTrigger,
  TabsContent,
} from "@/components/ui/tabs.tsx";
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
import {
  TimeRangePicker,
  rangeToTimestamps,
} from "@/components/TimeRangePicker.tsx";
import type {
  TimeRangeValue,
  TimeRangePreset,
} from "@/components/TimeRangePicker.tsx";
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
  useDeviceCategories,
  useInterfaceLatest,
  useMultiInterfaceHistory,
  useRefreshInterfaceMetadata,
  useInterfaceMetadata,
  useUpdateInterfaceSettings,
  useBulkUpdateInterfaceSettings,
  useAppDetail,
  useApps,
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
  usePollConfigNow,
  useUpdateInterfacePreferences,
  useDeviceAlertLog,
  useDeviceActiveEvents,
  useDeviceClearedEvents,
  useAcknowledgeEvents,
  useClearEvents,
  useDiscoverDevice,
  useDeviceTypes,
  useResolveTemplates,
  useAutoApplyTemplates,
  useDeviceInterfaceRules,
  useSetDeviceInterfaceRules,
  useEvaluateInterfaceRules,
} from "@/api/hooks.ts";
import { apiGet } from "@/api/client.ts";
import { useAuth } from "@/hooks/useAuth.tsx";
import type {
  Device as DeviceModel,
  DeviceAssignment,
  DeviceThresholdRow,
  ConfigDiffEntry,
  AlertLogEntry,
  MonitoringEvent,
  ResolvedTemplateResult,
  InterfaceRule,
  InterfaceRecord,
} from "@/types/api.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import { SchemaConfigFields } from "@/components/SchemaConfigFields.tsx";
import { ConfigDataRenderer } from "@/components/ConfigDataRenderer.tsx";
import { ApplyTemplateDialog } from "@/components/ApplyTemplateDialog.tsx";
import { PerformanceChart } from "@/components/PerformanceChart.tsx";
import {
  MultiInterfaceChart,
  formatTraffic,
} from "@/components/InterfaceTrafficChart.tsx";
import type {
  TrafficUnit,
  ChartMetric,
  ChartMode,
} from "@/components/InterfaceTrafficChart.tsx";
import { CredentialCell } from "@/components/CredentialCell.tsx";
import { DeviceIcon, categoryIconUrl } from "@/components/DeviceIcon.tsx";
import { RuleFormDialog } from "@/pages/DiscoveryRulesPage.tsx";
import { timeAgo, formatDate, formatUptime } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

// ── Default time range ────────────────────────────────────

const DEFAULT_RANGE: TimeRangeValue = { type: "preset", preset: "24h" };

// ── Add Assignment Dialog ────────────────────────────────

interface AddAssignmentDialogProps {
  deviceId: string;
  deviceCollectorGroupId: string | null;
  deviceCollectorGroupName: string | null;
  deviceCredentials?: Record<
    string,
    { id: string; name: string; credential_type: string }
  >;
  open: boolean;
  onClose: () => void;
}

function AddAssignmentDialog({
  deviceId,
  deviceCollectorGroupId,
  deviceCollectorGroupName,
  deviceCredentials,
  open,
  onClose,
}: AddAssignmentDialogProps) {
  const { data: appsResp } = useApps();
  const apps = appsResp?.data ?? [];
  const { data: credentials } = useCredentials();
  const [selectedAppId, setSelectedAppId] = useState("");
  const { data: appDetail } = useAppDetail(selectedAppId || undefined);
  const createAssignment = useCreateAssignment();

  const [scheduleType, setScheduleType] = useState("interval");
  const [scheduleValue, setScheduleValue] = useState("60");
  const [cronValue, setCronValue] = useState("*/5 * * * *");
  const [versionMode, setVersionMode] = useState<"latest" | "pinned">("latest");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [selectedCredentialId, setSelectedCredentialId] = useState("");
  const [pinToCollector, setPinToCollector] = useState(false);
  const [pinnedCollectorId, setPinnedCollectorId] = useState("");
  const { data: groupCollectors } = useCollectors(
    pinToCollector && deviceCollectorGroupId
      ? { group_id: deviceCollectorGroupId }
      : undefined,
  );
  const [configText, setConfigText] = useState("{}");
  const [parsedConfig, setParsedConfig] = useState<Record<string, unknown>>({});
  const [configError, setConfigError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // Vendor compatibility check
  const { data: vendorCheck } = useQuery({
    queryKey: ["vendor-check", selectedAppId, deviceId],
    queryFn: () =>
      apiGet<{ match: boolean | null; warning: string | null }>(
        `/apps/${selectedAppId}/vendor-check/${deviceId}`,
      ),
    enabled: !!selectedAppId && !!deviceId,
  });
  const vc = vendorCheck?.data;

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
    setScheduleValue("60");
    setCronValue("*/5 * * * *");
    setConfigText("{}");
    setParsedConfig({});
    setConfigError(null);
    setFormError(null);
  }

  function handleClose() {
    reset();
    onClose();
  }

  const hasSchemaFields =
    appDetail?.config_schema &&
    Object.keys(
      (appDetail.config_schema as { properties?: Record<string, unknown> })
        .properties ?? {},
    ).length > 0;

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
      const secs = Number(scheduleValue);
      if (isNaN(secs) || secs < 10 || secs > 604800) {
        setFormError("Interval must be between 10s and 7d");
        return;
      }
    } else if (scheduleType === "cron") {
      const parts = cronValue.trim().split(/\s+/);
      if (parts.length < 5) {
        setFormError(
          "Cron expression must have at least 5 fields: min hour day month weekday",
        );
        return;
      }
    }

    if (!selectedAppId) {
      setFormError("App is required.");
      return;
    }

    if (!deviceCollectorGroupId) {
      setFormError(
        "Device must be assigned to a collector group before adding assignments.",
      );
      return;
    }

    const latestVersion = appDetail?.versions?.find((v) => v.is_latest);
    if (!latestVersion && versionMode === "latest") {
      setFormError("The selected app has no latest version.");
      return;
    }

    const versionId =
      versionMode === "latest" ? latestVersion!.id : selectedVersionId;
    if (!versionId) {
      setFormError("Select a version.");
      return;
    }

    try {
      await createAssignment.mutateAsync({
        app_id: selectedAppId,
        app_version_id: versionId,
        collector_id:
          pinToCollector && pinnedCollectorId ? pinnedCollectorId : null,
        device_id: deviceId,
        schedule_type: scheduleType,
        schedule_value: scheduleType === "interval" ? scheduleValue : cronValue,
        config,
        use_latest: versionMode === "latest",
        credential_id: selectedCredentialId || null,
      });
      reset();
      onClose();
    } catch (err) {
      setFormError(
        err instanceof Error ? err.message : "Failed to create assignment",
      );
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} title="Add App Assignment">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="aa-app">App</Label>
          <SearchableSelect
            id="aa-app"
            value={selectedAppId}
            onChange={setSelectedAppId}
            options={(apps ?? []).map((a) => ({ value: a.id, label: a.name }))}
            placeholder="Select app..."
          />
          {vc?.match === false && vc.warning && (
            <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5 mt-1.5">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
              <p className="text-xs text-amber-200">{vc.warning}</p>
            </div>
          )}
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
                      (currently{" "}
                      {appDetail.versions.find((v) => v.is_latest)!.version})
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
                      {v.version}
                      {v.is_latest ? " (latest)" : ""}
                    </option>
                  ))}
                </Select>
              )}
            </div>
          )}
          {appDetail && appDetail.versions.length === 0 && (
            <p className="text-xs text-red-400 mt-1">
              No versions — publish a version first
            </p>
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
              This device is not assigned to a collector group. Assign it to a
              group in Settings before adding apps.
            </p>
          )}
        </div>

        {/* Credential */}
        <div className="space-y-1.5">
          <Label htmlFor="aa-credential">
            Credential{" "}
            <span className="font-normal text-zinc-500">(optional)</span>
          </Label>
          <Select
            id="aa-credential"
            value={selectedCredentialId}
            onChange={(e) => setSelectedCredentialId(e.target.value)}
          >
            <option value="">Device default</option>
            {(credentials ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.credential_type})
              </option>
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
                onChange={(e) => {
                  setPinToCollector(e.target.checked);
                  if (!e.target.checked) setPinnedCollectorId("");
                }}
                className="accent-brand-500 cursor-pointer"
              />
              <Label
                htmlFor="pin-collector"
                className="text-sm text-zinc-400 font-normal cursor-pointer"
              >
                Pin to a specific collector
              </Label>
            </div>
            {pinToCollector && (
              <>
                <Select
                  value={pinnedCollectorId}
                  onChange={(e) => setPinnedCollectorId(e.target.value)}
                >
                  <option value="">Select collector...</option>
                  {(groupCollectors ?? []).map(
                    (c: { id: string; name: string; status: string }) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                        {c.status !== "ACTIVE" ? ` (${c.status})` : ""}
                      </option>
                    ),
                  )}
                </Select>
                <p className="text-xs text-zinc-500">
                  This assignment will only run on the selected collector. If
                  the collector goes down, the assignment pauses until it
                  recovers.
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
              onChange={(e) => setScheduleType(e.target.value)}
            >
              <option value="interval">Interval</option>
              <option value="cron">Cron expression</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="aa-sched-val">
              {scheduleType === "interval" ? "Interval" : "Cron"}
            </Label>
            {scheduleType === "interval" ? (
              <IntervalInput
                id="aa-sched-val"
                value={scheduleValue}
                onChange={setScheduleValue}
              />
            ) : (
              <Input
                id="aa-sched-val"
                value={cronValue}
                onChange={(e) => setCronValue(e.target.value)}
                placeholder="*/5 * * * *"
              />
            )}
            <p className="text-xs text-zinc-500">
              {scheduleType === "interval"
                ? "How often to run"
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
                deviceCredentials={deviceCredentials}
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
                    try {
                      setParsedConfig(JSON.parse(e.target.value || "{}"));
                    } catch {
                      /* typing */
                    }
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
            {createAssignment.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
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
  deviceCredentials?: Record<
    string,
    { id: string; name: string; credential_type: string }
  >;
  open: boolean;
  onClose: () => void;
}

function EditAssignmentDialog({
  assignment,
  deviceCollectorGroupId,
  deviceCredentials,
  open,
  onClose,
}: EditAssignmentDialogProps) {
  const updateAssignment = useUpdateAssignment();
  const { data: appDetail } = useAppDetail(assignment?.app.id);
  const { data: credentials } = useCredentials();

  const [scheduleType, setScheduleType] = useState("interval");
  const [editScheduleValue, setEditScheduleValue] = useState("60");
  const [editCronValue, setEditCronValue] = useState("*/5 * * * *");
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
    pinToCollector && deviceCollectorGroupId
      ? { group_id: deviceCollectorGroupId }
      : undefined,
  );

  useEffect(() => {
    if (assignment) {
      setScheduleType(assignment.schedule_type);
      if (assignment.schedule_type === "interval") {
        setEditScheduleValue(assignment.schedule_value);
      } else {
        setEditCronValue(assignment.schedule_value);
      }
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

  const editHasSchemaFields =
    appDetail?.config_schema &&
    Object.keys(
      (appDetail.config_schema as { properties?: Record<string, unknown> })
        .properties ?? {},
    ).length > 0;

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
      const secs = Number(editScheduleValue);
      if (isNaN(secs) || secs < 10 || secs > 604800) {
        setFormError("Interval must be between 10s and 7d");
        return;
      }
    } else if (scheduleType === "cron") {
      const parts = editCronValue.trim().split(/\s+/);
      if (parts.length < 5) {
        setFormError(
          "Cron expression must have at least 5 fields: min hour day month weekday",
        );
        return;
      }
    }

    const latestVersion = appDetail?.versions?.find((v) => v.is_latest);
    const versionId =
      versionMode === "latest" ? latestVersion?.id : selectedVersionId;
    if (!versionId) {
      setFormError(
        versionMode === "latest"
          ? "No latest version available."
          : "Select a version.",
      );
      return;
    }

    if (pinToCollector && !pinnedCollectorId) {
      setFormError(
        "Select a collector or uncheck 'Pin to a specific collector'.",
      );
      return;
    }

    try {
      await updateAssignment.mutateAsync({
        id: assignment.id,
        data: {
          schedule_type: scheduleType,
          schedule_value:
            scheduleType === "interval" ? editScheduleValue : editCronValue,
          config,
          enabled,
          app_version_id: versionId,
          use_latest: versionMode === "latest",
          credential_id: selectedCredentialId || null,
          collector_id:
            pinToCollector && pinnedCollectorId ? pinnedCollectorId : null,
        },
      });
      onClose();
    } catch (err) {
      setFormError(
        err instanceof Error ? err.message : "Failed to update assignment",
      );
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Edit Assignment — ${assignment?.app.name ?? ""}`}
    >
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
                    (currently{" "}
                    {appDetail.versions.find((v) => v.is_latest)!.version})
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
                    {v.version}
                    {v.is_latest ? " (latest)" : ""}
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
              <option value="interval">Interval</option>
              <option value="cron">Cron expression</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ea-sched-val">
              {scheduleType === "interval" ? "Interval" : "Cron"}
            </Label>
            {scheduleType === "interval" ? (
              <IntervalInput
                id="ea-sched-val"
                value={editScheduleValue}
                onChange={setEditScheduleValue}
              />
            ) : (
              <Input
                id="ea-sched-val"
                value={editCronValue}
                onChange={(e) => setEditCronValue(e.target.value)}
                placeholder="*/5 * * * *"
              />
            )}
            <p className="text-xs text-zinc-500">
              {scheduleType === "interval"
                ? "How often to run"
                : "Standard cron: min hour day month weekday"}
            </p>
          </div>
        </div>

        {/* Credential */}
        <div className="space-y-1.5">
          <Label htmlFor="ea-credential">
            Credential{" "}
            <span className="font-normal text-zinc-500">(optional)</span>
          </Label>
          <Select
            id="ea-credential"
            value={selectedCredentialId}
            onChange={(e) => setSelectedCredentialId(e.target.value)}
          >
            <option value="">Device default</option>
            {(credentials ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.credential_type})
              </option>
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
                onChange={(e) => {
                  setPinToCollector(e.target.checked);
                  if (!e.target.checked) setPinnedCollectorId("");
                }}
                className="accent-brand-500 cursor-pointer"
              />
              <Label
                htmlFor="edit-pin-collector"
                className="text-sm text-zinc-400 font-normal cursor-pointer"
              >
                Pin to a specific collector
              </Label>
            </div>
            {pinToCollector && (
              <>
                <Select
                  value={pinnedCollectorId}
                  onChange={(e) => setPinnedCollectorId(e.target.value)}
                >
                  <option value="">Select collector...</option>
                  {(groupCollectors ?? []).map(
                    (c: { id: string; name: string; status: string }) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                        {c.status !== "ACTIVE" ? ` (${c.status})` : ""}
                      </option>
                    ),
                  )}
                </Select>
                <p className="text-xs text-zinc-500">
                  This assignment will only run on the selected collector. If
                  the collector goes down, the assignment pauses until it
                  recovers.
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
                deviceCredentials={deviceCredentials}
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
                    try {
                      setParsedConfig(JSON.parse(e.target.value || "{}"));
                    } catch {
                      /* typing */
                    }
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
            {updateAssignment.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
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
  const [baseRange, setBaseRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const [isZoomed, setIsZoomed] = useState(false);
  const { fromTs, toTs } = useMemo(
    () => rangeToTimestamps(timeRange),
    [timeRange],
  );
  const { data: deviceResults } = useDeviceResults(deviceId);
  const { data: history, isLoading: histLoading } = useAvailabilityHistory(
    deviceId,
    fromTs,
    toTs,
    5000,
  );
  const handleChartZoom = useCallback(
    (fromMs: number, toMs: number) => {
      if (!isZoomed) setBaseRange(timeRange);
      setTimeRange({
        type: "absolute",
        fromTs: new Date(fromMs).toISOString(),
        toTs: new Date(toMs).toISOString(),
      });
      setIsZoomed(true);
    },
    [isZoomed, timeRange],
  );
  const handleResetZoom = useCallback(() => {
    setTimeRange(baseRange);
    setIsZoomed(false);
  }, [baseRange]);
  const handleTimeRangeChange = useCallback((v: TimeRangeValue) => {
    setTimeRange(v);
    setBaseRange(v);
    setIsZoomed(false);
  }, []);

  // ── Staleness detection ───────────────────────────────────
  const STALE_THRESHOLD_MS = 15 * 60 * 1000; // 15 minutes
  const staleSince = useMemo(() => {
    if (!deviceResults?.checks?.length) return null;
    // Only consider availability/latency checks for staleness — other apps
    // (config, performance) have their own tabs and should not drive this indicator.
    const monitoringChecks = deviceResults.checks.filter(
      (c: any) => c.role === "availability" || c.role === "latency",
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
            </span>{" "}
            ({timeAgo(staleSince.toISOString())}). Check collector connectivity
            and assignment status.
          </span>
        </div>
      )}

      {/* Chart header + time picker */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-zinc-400">
            Availability &amp; Latency
          </h3>
          {isZoomed && (
            <button
              onClick={handleResetZoom}
              className="text-xs text-brand-400 hover:text-brand-300 cursor-pointer"
            >
              Reset zoom
            </button>
          )}
        </div>
        <TimeRangePicker
          value={timeRange}
          onChange={handleTimeRangeChange}
          timezone={tz}
        />
      </div>

      {/* Chart card */}
      <Card>
        <CardContent className="pt-4">
          {histLoading ? (
            <div className="flex h-48 items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            </div>
          ) : (
            <AvailabilityChart
              results={history ?? []}
              fromTs={fromTs}
              toTs={toTs}
              timezone={tz}
              onZoom={handleChartZoom}
            />
          )}
        </CardContent>
      </Card>

      {/* Events placeholder */}
      <Card>
        <CardHeader>
          <CardTitle className="text-zinc-400 text-sm">
            Events &amp; Alerts
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-8 text-zinc-600">
            <p className="text-sm">
              Event log and alert history coming in a future update.
            </p>
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
  const [baseRange, setBaseRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const [isZoomed, setIsZoomed] = useState(false);
  const { fromTs, toTs } = useMemo(
    () => rangeToTimestamps(timeRange),
    [timeRange],
  );
  const handleChartZoom = useCallback(
    (fromMs: number, toMs: number) => {
      if (!isZoomed) setBaseRange(timeRange);
      setTimeRange({
        type: "absolute",
        fromTs: new Date(fromMs).toISOString(),
        toTs: new Date(toMs).toISOString(),
      });
      setIsZoomed(true);
    },
    [isZoomed, timeRange],
  );
  const handleResetZoom = useCallback(() => {
    setTimeRange(baseRange);
    setIsZoomed(false);
  }, [baseRange]);
  const handleTimeRangeChange = useCallback((v: TimeRangeValue) => {
    setTimeRange(v);
    setBaseRange(v);
    setIsZoomed(false);
  }, []);

  const { data: summary, isLoading: summaryLoading } =
    usePerformanceSummary(deviceId);

  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);
  const [selectedComponentType, setSelectedComponentType] = useState<
    string | null
  >(null);
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
  const currentCT =
    currentApp && selectedComponentType
      ? currentApp.component_types[selectedComponentType]
      : null;
  const availableComponents = currentCT?.components ?? [];
  const availableMetrics = currentCT?.metric_names ?? [];

  const { data: perfData, isLoading: dataLoading } = usePerformanceHistory(
    deviceId,
    fromTs,
    toTs,
    selectedAppId,
    selectedComponentType,
    selectedComponents.length ? selectedComponents : null,
    5000,
  );

  const filteredComponents = useMemo(() => {
    if (!componentFilter) return availableComponents;
    const q = componentFilter.toLowerCase();
    return availableComponents.filter((c) => c.toLowerCase().includes(q));
  }, [availableComponents, componentFilter]);

  const toggleComponent = (comp: string) => {
    setSelectedComponents((prev) =>
      prev.includes(comp) ? prev.filter((c) => c !== comp) : [...prev, comp],
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
    setSelectedComponents((prev) =>
      prev.filter((c) => !filteredComponents.includes(c)),
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-zinc-300">
            Performance Metrics
          </h3>
          {isZoomed && (
            <button
              onClick={handleResetZoom}
              className="text-xs text-brand-400 hover:text-brand-300 cursor-pointer"
            >
              Reset zoom
            </button>
          )}
        </div>
        <TimeRangePicker value={timeRange} onChange={handleTimeRangeChange} />
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
              <p className="text-sm text-zinc-500">
                No performance data collected for this device yet.
              </p>
              <p className="text-xs text-zinc-700 mt-1">
                Assign a performance monitoring app to start collecting metrics.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="flex gap-4">
          {/* Sidebar */}
          <div className="w-64 shrink-0 space-y-3">
            <Card>
              <CardHeader className="py-2 px-3">
                <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">
                  App
                </CardTitle>
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

            {currentApp &&
              Object.keys(currentApp.component_types).length > 1 && (
                <Card>
                  <CardHeader className="py-2 px-3">
                    <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">
                      Type
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="px-3 pb-3 space-y-1">
                    {Object.keys(currentApp.component_types)
                      .sort()
                      .map((ct) => (
                        <button
                          key={ct}
                          onClick={() => {
                            setSelectedComponentType(ct);
                            const entry = currentApp.component_types[ct];
                            setSelectedMetric(entry.metric_names[0] ?? null);
                            setSelectedComponents(
                              entry.components.slice(0, 10),
                            );
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
                  <CardTitle className="text-zinc-400 text-xs uppercase tracking-wide">
                    Metric
                  </CardTitle>
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
                      Components ({selectedComponents.length}/
                      {availableComponents.length})
                    </CardTitle>
                    <div className="flex gap-1">
                      <button
                        onClick={selectAll}
                        className="text-[10px] text-zinc-500 hover:text-zinc-300 px-1 cursor-pointer"
                      >
                        All
                      </button>
                      <button
                        onClick={selectNone}
                        className="text-[10px] text-zinc-500 hover:text-zinc-300 px-1 cursor-pointer"
                      >
                        None
                      </button>
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
                      <p className="text-xs text-zinc-600 px-1 py-2">
                        No match
                      </p>
                    ) : (
                      filteredComponents.map((comp) => (
                        <label
                          key={comp}
                          className="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-zinc-800 cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={selectedComponents.includes(comp)}
                            onChange={() => toggleComponent(comp)}
                            className="accent-brand-500 h-3.5 w-3.5"
                          />
                          <span className="text-xs text-zinc-400 font-mono truncate">
                            {comp}
                          </span>
                        </label>
                      ))
                    )}
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
                    unit={
                      selectedMetric.includes("pct")
                        ? "%"
                        : selectedMetric.includes("_ms")
                          ? "ms"
                          : selectedMetric.includes("_bytes")
                            ? "B"
                            : ""
                    }
                    title={`${selectedComponentType ?? ""} — ${selectedMetric ?? ""}`}
                    onZoom={handleChartZoom}
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
  const { data: configTemplates } = useDeviceConfigTemplates(deviceId);
  const { data: assignments } = useDeviceAssignments(deviceId);
  const [configView, setConfigView] = useState<
    "current" | "changes" | "compare"
  >("current");
  const [selectedConfigApp, setSelectedConfigApp] = useState<string | null>(
    null,
  );
  const pollNow = usePollConfigNow();
  const qc = useQueryClient();

  // Poll now visual state
  const [pollStatus, setPollStatus] = useState<"idle" | "polling" | "done">(
    "idle",
  );
  const [pollRequestedAt, setPollRequestedAt] = useState<number | null>(null);
  const {
    data: configRows,
    isLoading,
    dataUpdatedAt,
  } = useDeviceConfigData(deviceId);

  // Aggressively refetch while poll is pending
  useEffect(() => {
    if (!pollRequestedAt) return;
    let tries = 0;
    const iv = setInterval(() => {
      tries++;
      qc.invalidateQueries({ queryKey: ["device-config-data", deviceId] });
      if (tries >= 15) {
        clearInterval(iv);
        setPollRequestedAt(null);
        setPollStatus("idle");
      }
    }, 2000);
    return () => clearInterval(iv);
  }, [pollRequestedAt, deviceId, qc]);

  // Detect when data actually refreshed after poll
  useEffect(() => {
    if (pollRequestedAt && dataUpdatedAt > pollRequestedAt) {
      setPollRequestedAt(null);
      setPollStatus("done");
      setTimeout(() => setPollStatus("idle"), 2500);
    }
  }, [dataUpdatedAt, pollRequestedAt]);

  // Changelog — server-side filters + sort
  const [changelogPage, setChangelogPage] = useState(0);
  const [filterKey, setFilterKey] = useState("");
  const [filterComponent, setFilterComponent] = useState("");
  const [filterValue, setFilterValue] = useState("");
  const [changeSortCol, setChangeSortCol] = useState<
    "time" | "component" | "key" | "value"
  >("time");
  const [changeSortDir, setChangeSortDir] = useState<"asc" | "desc">("desc");
  const PAGE_SIZE = 50;
  const { data: changelogResp } = useConfigChangelog(deviceId, {
    app_id: selectedConfigApp ?? undefined,
    config_key: filterKey || undefined,
    component: filterComponent || undefined,
    value: filterValue || undefined,
    limit: PAGE_SIZE,
    offset: changelogPage * PAGE_SIZE,
  });
  const changelog = changelogResp?.data ?? [];
  const changelogMeta = (changelogResp as unknown as Record<string, unknown>)
    ?.meta as { total?: number; count?: number } | undefined;

  // Diff dialog for single key
  const [diffKey, setDiffKey] = useState<string | null>(null);
  const { data: diffResp } = useConfigDiff(
    deviceId,
    diffKey ?? "",
    selectedConfigApp ?? undefined,
    20,
  );
  const diffRows = diffResp?.data ?? [];

  // Compare view
  const { data: timestamps } = useConfigChangeTimestamps(deviceId, {
    app_id: selectedConfigApp ?? undefined,
  });
  const tsData = timestamps?.data ?? [];
  const [compareTimeA, setCompareTimeA] = useState<string | null>(null);
  const [compareTimeB, setCompareTimeB] = useState<string | null>(null);
  const { data: compareResult } = useConfigCompare(
    deviceId,
    compareTimeA,
    compareTimeB,
    selectedConfigApp ?? undefined,
  );

  // Auto-set compare timestamps when data loads
  useEffect(() => {
    if (tsData.length >= 2 && !compareTimeA && !compareTimeB) {
      setCompareTimeA(tsData[1].change_time);
      setCompareTimeB(tsData[0].change_time);
    }
  }, [tsData, compareTimeA, compareTimeB]);

  // Group by app_id for sidebar and current view
  const configApps = useMemo(() => {
    const apps = new Map<
      string,
      {
        appName: string;
        data: Record<string, string>;
        lastCollected: string | null;
        intervalSeconds: number | null;
        scheduleHuman: string | null;
      }
    >();
    // Build a map of app_id -> schedule info from assignments
    const scheduleByAppId = new Map<
      string,
      { intervalSeconds: number | null; scheduleHuman: string }
    >();
    for (const a of assignments ?? []) {
      scheduleByAppId.set(a.app.id, {
        intervalSeconds:
          a.schedule_type === "interval" ? Number(a.schedule_value) : null,
        scheduleHuman:
          a.schedule_human ??
          (a.schedule_type === "interval"
            ? `every ${formatInterval(Number(a.schedule_value))}`
            : a.schedule_value),
      });
    }
    for (const row of configRows ?? []) {
      const appId = String(row.app_id ?? "unknown");
      const key = String(row.config_key ?? "");
      const value = String(row.config_value ?? "");
      const appName = String(row.app_name ?? appId);
      const executedAt = String(row.executed_at ?? "");
      if (!apps.has(appId)) {
        const sched = scheduleByAppId.get(appId);
        apps.set(appId, {
          appName,
          data: {},
          lastCollected: null,
          intervalSeconds: sched?.intervalSeconds ?? null,
          scheduleHuman: sched?.scheduleHuman ?? null,
        });
      }
      const entry = apps.get(appId)!;
      if (!(key in entry.data)) {
        entry.data[key] = value;
      }
      if (
        executedAt &&
        (!entry.lastCollected || executedAt > entry.lastCollected)
      ) {
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

  // Reset changelog page + filters when switching apps
  useEffect(() => {
    setChangelogPage(0);
    setFilterKey("");
    setFilterComponent("");
    setFilterValue("");
  }, [selectedConfigApp]);

  // Reset page when filters change
  useEffect(() => {
    setChangelogPage(0);
  }, [filterKey, filterComponent, filterValue]);

  function handleChangeSort(col: string) {
    if (changeSortCol === col)
      setChangeSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setChangeSortCol(col as typeof changeSortCol);
      setChangeSortDir("asc");
    }
  }

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
            Config apps will populate structured data here once they have been
            assigned and executed.
          </p>
        </CardContent>
      </Card>
    );
  }

  const selectedAppData = selectedConfigApp
    ? configApps.get(selectedConfigApp)
    : null;

  return (
    <div className="flex gap-4">
      {/* Left sidebar — app selector */}
      <div className="w-48 shrink-0">
        <Card>
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-xs text-zinc-500 uppercase tracking-wide">
              Apps
            </CardTitle>
          </CardHeader>
          <CardContent className="p-1.5 space-y-0.5">
            {[...configApps.entries()]
              .sort(([, a], [, b]) =>
                a.appName.toLowerCase().localeCompare(b.appName.toLowerCase()),
              )
              .map(([appId, { appName }]) => (
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
                {selectedAppData.lastCollected &&
                  (() => {
                    const ageSec =
                      (Date.now() -
                        new Date(selectedAppData.lastCollected).getTime()) /
                      1000;
                    const interval = selectedAppData.intervalSeconds;
                    const missedPolls = interval ? ageSec / interval : 0;
                    const statusColor = !interval
                      ? "bg-zinc-700 text-zinc-300"
                      : missedPolls <= 1.5
                        ? "bg-emerald-900/60 text-emerald-400 border border-emerald-700/50"
                        : missedPolls <= 2.5
                          ? "bg-amber-900/60 text-amber-400 border border-amber-700/50"
                          : "bg-red-900/60 text-red-400 border border-red-700/50";
                    return (
                      <span className="ml-auto flex items-center gap-2">
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded ${statusColor}`}
                          title={`Last polled: ${formatDate(selectedAppData.lastCollected, tz)}`}
                        >
                          {timeAgo(selectedAppData.lastCollected)}
                        </span>
                        {selectedAppData.scheduleHuman && (
                          <span className="text-xs text-zinc-500 font-normal">
                            ↻ {selectedAppData.scheduleHuman}
                          </span>
                        )}
                        {(() => {
                          const selectedAssignment = (assignments ?? []).find(
                            (a) => a.app.id === selectedConfigApp,
                          );
                          if (!selectedAssignment) return null;
                          const isPolling = pollStatus === "polling";
                          const isDone = pollStatus === "done";
                          return (
                            <button
                              onClick={() => {
                                if (isPolling) return;
                                const now = Date.now();
                                setPollRequestedAt(now);
                                setPollStatus("polling");
                                pollNow.mutate(
                                  {
                                    deviceId,
                                    assignmentId: selectedAssignment.id,
                                  },
                                  {
                                    onError: () => {
                                      setPollStatus("idle");
                                      setPollRequestedAt(null);
                                    },
                                  },
                                );
                              }}
                              disabled={isPolling}
                              title={
                                isPolling
                                  ? "Polling..."
                                  : isDone
                                    ? "Done!"
                                    : "Poll now"
                              }
                              className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded transition-colors disabled:opacity-60 ${
                                isDone
                                  ? "text-emerald-400 bg-emerald-900/30"
                                  : isPolling
                                    ? "text-brand-400 bg-brand-900/30"
                                    : "text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700/50"
                              }`}
                            >
                              {isDone ? (
                                <>
                                  <Check className="h-3 w-3" /> Done
                                </>
                              ) : isPolling ? (
                                <>
                                  <RefreshCw className="h-3 w-3 animate-spin" />{" "}
                                  Polling...
                                </>
                              ) : (
                                <RefreshCw className="h-3.5 w-3.5" />
                              )}
                            </button>
                          );
                        })()}
                      </span>
                    );
                  })()}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ConfigDataRenderer
                template={
                  selectedConfigApp &&
                  configTemplates?.[selectedConfigApp]?.display_template?.html
                    ? {
                        html: configTemplates[selectedConfigApp]
                          .display_template!.html,
                        css:
                          configTemplates[selectedConfigApp].display_template!
                            .css ?? undefined,
                        key_mappings:
                          configTemplates[selectedConfigApp].display_template!
                            .key_mappings ?? [],
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
                  <p className="text-sm text-zinc-500">
                    No configuration changes detected.
                  </p>
                  <p className="text-xs text-zinc-600 mt-1 max-w-sm mx-auto">
                    Changes will appear here automatically when config values on
                    this device change between poll cycles.
                  </p>
                </div>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <FilterableSortHead
                          col="time"
                          label="Time"
                          sortBy={changeSortCol}
                          sortDir={changeSortDir}
                          onSort={handleChangeSort}
                          filterable={false}
                        />
                        <FilterableSortHead
                          col="component"
                          label="Component"
                          sortBy={changeSortCol}
                          sortDir={changeSortDir}
                          onSort={handleChangeSort}
                          filterValue={filterComponent}
                          onFilterChange={setFilterComponent}
                          filterable={true}
                        />
                        <FilterableSortHead
                          col="key"
                          label="Key"
                          sortBy={changeSortCol}
                          sortDir={changeSortDir}
                          onSort={handleChangeSort}
                          filterValue={filterKey}
                          onFilterChange={setFilterKey}
                          filterable={true}
                        />
                        <FilterableSortHead
                          col="value"
                          label="Value"
                          sortBy={changeSortCol}
                          sortDir={changeSortDir}
                          onSort={handleChangeSort}
                          filterValue={filterValue}
                          onFilterChange={setFilterValue}
                          filterable={true}
                        />
                        <TableHead className="w-16">Diff</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {changelog.map((row, i) => (
                        <TableRow
                          key={`${row.executed_at}-${row.config_key}-${i}`}
                        >
                          <TableCell
                            className="text-xs text-zinc-400 whitespace-nowrap"
                            title={formatDate(row.executed_at, tz)}
                          >
                            {timeAgo(row.executed_at)}
                          </TableCell>
                          <TableCell className="text-xs font-mono text-zinc-500">
                            {row.component
                              ? `${row.component_type}/${row.component}`
                              : "—"}
                          </TableCell>
                          <TableCell className="text-xs font-mono">
                            {row.config_key}
                          </TableCell>
                          <TableCell
                            className="text-xs font-mono max-w-[250px] truncate"
                            title={row.config_value}
                          >
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
                        {Math.min(
                          (changelogPage + 1) * PAGE_SIZE,
                          changelogMeta?.total ?? 0,
                        )}{" "}
                        of {changelogMeta?.total}
                      </span>
                      <div className="flex gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-2 text-xs"
                          disabled={changelogPage === 0}
                          onClick={() => setChangelogPage((p) => p - 1)}
                        >
                          Prev
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-2 text-xs"
                          disabled={
                            (changelogPage + 1) * PAGE_SIZE >=
                            (changelogMeta?.total ?? 0)
                          }
                          onClick={() => setChangelogPage((p) => p + 1)}
                        >
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
                  <p className="text-sm text-zinc-500">
                    No changes to compare yet.
                  </p>
                  <p className="text-xs text-zinc-600 mt-1 max-w-sm mx-auto">
                    The comparison view requires at least two different
                    configuration snapshots. Changes will become available once
                    config values on this device change between poll cycles.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center gap-3 flex-wrap">
                    {(() => {
                      const groups = new Map<string, typeof tsData>();
                      for (const ts of tsData) {
                        const label = new Intl.DateTimeFormat("en-GB", {
                          timeZone: tz || undefined,
                          weekday: "short",
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        }).format(new Date(ts.change_time));
                        if (!groups.has(label)) groups.set(label, []);
                        groups.get(label)!.push(ts);
                      }
                      const renderOption = (ts: (typeof tsData)[0]) => (
                        <option key={ts.change_time} value={ts.change_time}>
                          {new Date(ts.change_time).toLocaleTimeString(
                            "en-GB",
                            {
                              timeZone: tz || undefined,
                              hour: "2-digit",
                              minute: "2-digit",
                            },
                          )}{" "}
                          ({ts.change_count} keys)
                        </option>
                      );
                      const renderSelect = (
                        value: string,
                        onChange: (v: string) => void,
                      ) => (
                        <select
                          value={value}
                          onChange={(e) => onChange(e.target.value)}
                          className="bg-zinc-900 border border-zinc-700 rounded-md text-xs text-zinc-200 px-2 py-1 min-w-[220px] focus:outline-none focus:ring-1 focus:ring-brand-500"
                        >
                          {[...groups.entries()].map(([date, group]) => (
                            <optgroup key={date} label={date}>
                              {group.map(renderOption)}
                            </optgroup>
                          ))}
                        </select>
                      );
                      return (
                        <>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-zinc-500">
                              Before:
                            </span>
                            {renderSelect(compareTimeA ?? "", setCompareTimeA)}
                          </div>
                          <span className="text-zinc-600">vs</span>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-zinc-500">
                              After:
                            </span>
                            {renderSelect(compareTimeB ?? "", setCompareTimeB)}
                          </div>
                        </>
                      );
                    })()}
                  </div>

                  {compareResult &&
                    (() => {
                      const added = compareResult.changes.filter(
                        (d) => d.change_type === "added",
                      );
                      const removed = compareResult.changes.filter(
                        (d) => d.change_type === "removed",
                      );
                      const modified = compareResult.changes.filter(
                        (d) => d.change_type === "modified",
                      );
                      const unchangedList = compareResult.unchanged ?? [];

                      const renderDiffRow = (d: ConfigDiffEntry, i: number) => {
                        const rowBg =
                          d.change_type === "added"
                            ? "bg-emerald-950/20"
                            : d.change_type === "removed"
                              ? "bg-red-950/20"
                              : d.change_type === "modified"
                                ? "bg-amber-950/20"
                                : "";
                        const statusIcon =
                          d.change_type === "added"
                            ? "+"
                            : d.change_type === "removed"
                              ? "\u2212"
                              : d.change_type === "modified"
                                ? "~"
                                : "=";
                        const statusColor =
                          d.change_type === "added"
                            ? "text-emerald-400"
                            : d.change_type === "removed"
                              ? "text-red-400"
                              : d.change_type === "modified"
                                ? "text-amber-400"
                                : "text-zinc-600";

                        return (
                          <TableRow
                            key={`${d.component_type}-${d.component}-${d.config_key}-${i}`}
                            className={rowBg}
                          >
                            <TableCell
                              className={`text-sm font-bold w-8 text-center ${statusColor}`}
                            >
                              {statusIcon}
                            </TableCell>
                            <TableCell className="text-xs font-mono">
                              {d.config_key}
                            </TableCell>
                            <TableCell
                              className="text-xs font-mono max-w-[250px] truncate"
                              title={d.value_a ?? ""}
                            >
                              {d.change_type === "added" ? (
                                <span className="text-zinc-600">&mdash;</span>
                              ) : (
                                <span
                                  className={
                                    d.change_type === "removed" ||
                                    d.change_type === "modified"
                                      ? "text-red-400"
                                      : "text-zinc-400"
                                  }
                                >
                                  {d.value_a}
                                </span>
                              )}
                            </TableCell>
                            <TableCell
                              className="text-xs font-mono max-w-[250px] truncate"
                              title={d.value_b ?? ""}
                            >
                              {d.change_type === "removed" ? (
                                <span className="text-zinc-600">&mdash;</span>
                              ) : (
                                <span
                                  className={
                                    d.change_type === "added" ||
                                    d.change_type === "modified"
                                      ? "text-emerald-400"
                                      : "text-zinc-400"
                                  }
                                >
                                  {d.value_b}
                                </span>
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
                              <Badge variant="success" className="text-[10px]">
                                +{added.length} added
                              </Badge>
                            )}
                            {removed.length > 0 && (
                              <Badge
                                variant="destructive"
                                className="text-[10px]"
                              >
                                &minus;{removed.length} removed
                              </Badge>
                            )}
                            {modified.length > 0 && (
                              <Badge variant="warning" className="text-[10px]">
                                ~{modified.length} changed
                              </Badge>
                            )}
                            {unchangedList.length > 0 && (
                              <Badge variant="default" className="text-[10px]">
                                {unchangedList.length} unchanged
                              </Badge>
                            )}
                          </div>

                          {compareResult.changes.length === 0 &&
                          unchangedList.length === 0 ? (
                            <p className="text-sm text-zinc-500 py-4 text-center">
                              No configuration data found for the selected
                              timestamps.
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
                                {unchangedList.length} unchanged key
                                {unchangedList.length !== 1 ? "s" : ""}
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
          <Dialog
            open
            onClose={() => setDiffKey(null)}
            title={`History: ${diffKey}`}
          >
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
                      const changed =
                        !prevRow || prevRow.config_hash !== row.config_hash;
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
              <Button
                variant="outline"
                size="sm"
                onClick={() => setDiffKey(null)}
              >
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

function RetentionOverrideSelect({
  label,
  systemDefault,
  value,
  options,
  onChange,
}: {
  label: string;
  systemDefault: string;
  value: string | undefined;
  options: number[];
  onChange: (v: string | undefined) => void;
}) {
  const isOverridden = value != null && value !== "";
  function fmtDays(d: number): string {
    if (d >= 730) return `${Math.round(d / 365)} years`;
    if (d >= 365) return "1 year";
    return `${d} days`;
  }
  return (
    <div className="space-y-0.5">
      <span className="text-xs text-zinc-600">{label}</span>
      <Select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        className={isOverridden ? "border-brand-500/50" : ""}
      >
        <option value="">
          System default ({fmtDays(Number(systemDefault))})
        </option>
        {options.map((o) => (
          <option key={o} value={String(o)}>
            {fmtDays(o)}
          </option>
        ))}
      </Select>
    </div>
  );
}

function RetentionOverrideTriple({
  rawKey,
  hourlyKey,
  dailyKey,
  overrides,
  systemSettings,
  onChange,
  rawOptions,
  hourlyOptions,
  dailyOptions,
  rawDefault,
  hourlyDefault,
  dailyDefault,
}: {
  rawKey: string;
  hourlyKey: string;
  dailyKey: string;
  overrides: Record<string, string>;
  systemSettings: Record<string, string>;
  onChange: (key: string, value: string | undefined) => void;
  rawOptions: number[];
  hourlyOptions: number[];
  dailyOptions: number[];
  rawDefault: string;
  hourlyDefault: string;
  dailyDefault: string;
}) {
  return (
    <div className="grid grid-cols-3 gap-4">
      <RetentionOverrideSelect
        label="Raw"
        systemDefault={systemSettings[rawKey] ?? rawDefault}
        value={overrides[rawKey]}
        options={rawOptions}
        onChange={(v) => onChange(rawKey, v)}
      />
      <RetentionOverrideSelect
        label="Hourly rollup"
        systemDefault={systemSettings[hourlyKey] ?? hourlyDefault}
        value={overrides[hourlyKey]}
        options={hourlyOptions}
        onChange={(v) => onChange(hourlyKey, v)}
      />
      <RetentionOverrideSelect
        label="Daily rollup"
        systemDefault={systemSettings[dailyKey] ?? dailyDefault}
        value={overrides[dailyKey]}
        options={dailyOptions}
        onChange={(v) => onChange(dailyKey, v)}
      />
    </div>
  );
}

function RetentionTab({ deviceId }: { deviceId: string }) {
  const { data: device } = useDevice(deviceId);
  const { data: systemSettings } = useSystemSettings();
  const updateDevice = useUpdateDevice();

  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [modified, setModified] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (device?.retention_overrides) {
      setOverrides(device.retention_overrides);
      setModified(false);
    }
  }, [device]);

  function handleChange(key: string, value: string | undefined) {
    setOverrides((prev) => {
      const next = { ...prev };
      if (value == null || value === "") {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
    setModified(true);
  }

  async function handleSave() {
    setSaving(true);
    try {
      await updateDevice.mutateAsync({
        id: deviceId,
        data: { retention_overrides: overrides },
      });
      setModified(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  if (!device || !systemSettings) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-400">
          Override system-wide retention for this device. Empty fields inherit
          the system default.
        </p>
        <div className="flex items-center gap-2">
          {saved && <span className="text-sm text-emerald-400">Saved.</span>}
          {modified && (
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Save
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Database className="h-4 w-4" /> Interface Data
          </CardTitle>
        </CardHeader>
        <CardContent>
          <RetentionOverrideTriple
            rawKey="interface_raw_retention_days"
            hourlyKey="interface_hourly_retention_days"
            dailyKey="interface_daily_retention_days"
            overrides={overrides}
            systemSettings={systemSettings}
            onChange={handleChange}
            rawOptions={[3, 7, 14, 30, 60, 90]}
            hourlyOptions={[30, 60, 90, 180, 365]}
            dailyOptions={[180, 365, 730, 1095, 1825]}
            rawDefault="7"
            hourlyDefault="90"
            dailyDefault="730"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Database className="h-4 w-4" /> Performance Data
          </CardTitle>
        </CardHeader>
        <CardContent>
          <RetentionOverrideTriple
            rawKey="perf_raw_retention_days"
            hourlyKey="perf_hourly_retention_days"
            dailyKey="perf_daily_retention_days"
            overrides={overrides}
            systemSettings={systemSettings}
            onChange={handleChange}
            rawOptions={[3, 7, 14, 30, 60, 90]}
            hourlyOptions={[30, 60, 90, 180, 365]}
            dailyOptions={[180, 365, 730, 1095, 1825]}
            rawDefault="7"
            hourlyDefault="90"
            dailyDefault="730"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Activity className="h-4 w-4" /> Availability & Latency
          </CardTitle>
          <p className="text-xs text-zinc-600">
            Ping, port, and HTTP check data. Keep daily rollups for years of
            device health history.
          </p>
        </CardHeader>
        <CardContent>
          <RetentionOverrideTriple
            rawKey="avail_raw_retention_days"
            hourlyKey="avail_hourly_retention_days"
            dailyKey="avail_daily_retention_days"
            overrides={overrides}
            systemSettings={systemSettings}
            onChange={handleChange}
            rawOptions={[7, 14, 30, 60, 90]}
            hourlyOptions={[90, 180, 365, 730]}
            dailyOptions={[365, 730, 1095, 1825, 2555]}
            rawDefault="30"
            hourlyDefault="365"
            dailyDefault="1825"
          />
        </CardContent>
      </Card>
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

type IfaceSortKey =
  | "status"
  | "if_index"
  | "if_name"
  | "if_alias"
  | "speed"
  | "in_traffic"
  | "out_traffic"
  | "in_errors"
  | "out_errors"
  | "last_polled";

const METRIC_TYPES = ["traffic", "errors", "discards", "status"] as const;

function parseMetrics(poll_metrics: string): Set<string> {
  if (poll_metrics === "all") return new Set(METRIC_TYPES);
  return new Set(poll_metrics.split(",").filter(Boolean));
}

function serializeMetrics(set: Set<string>): string {
  if (METRIC_TYPES.every((m) => set.has(m))) return "all";
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

type IfaceStatusFilter = "all" | "up" | "down" | "monitored";

function InterfacesTab({ deviceId }: { deviceId: string }) {
  const { user } = useAuth();
  const { data: interfaces, isLoading } = useInterfaceLatest(deviceId);
  const { data: metadata } = useInterfaceMetadata(deviceId);
  const updateSettings = useUpdateInterfaceSettings();
  const bulkUpdate = useBulkUpdateInterfaceSettings();
  const refreshMeta = useRefreshInterfaceMetadata();
  const [refreshQueuedAt, setRefreshQueuedAt] = useState<number | null>(null);
  const [refreshDone, setRefreshDone] = useState(false);
  const [showRulesPanel, setShowRulesPanel] = useState(false);
  const { data: rules } = useDeviceInterfaceRules(deviceId);

  // Detect metadata update after refresh was queued
  useEffect(() => {
    if (!refreshQueuedAt || !metadata?.length) return;
    const maxUpdated = Math.max(
      ...metadata.map((m) =>
        m.updated_at ? new Date(m.updated_at).getTime() : 0,
      ),
    );
    if (maxUpdated > refreshQueuedAt) {
      setRefreshDone(true);
      setRefreshQueuedAt(null);
    }
  }, [refreshQueuedAt, metadata]);

  // Auto-hide "Metadata refreshed" after 3 seconds
  useEffect(() => {
    if (!refreshDone) return;
    const t = setTimeout(() => setRefreshDone(false), 3000);
    return () => clearTimeout(t);
  }, [refreshDone]);

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
    (user?.iface_traffic_unit as TrafficUnit) ?? "auto",
  );
  const [chartMetric, setChartMetric] = useState<ChartMetric>(
    (user?.iface_chart_metric as ChartMetric) ?? "traffic",
  );
  const [chartMode, setChartMode] = useState<ChartMode>("overlaid");
  const [statusFilter, setStatusFilter] = useState<IfaceStatusFilter>(() => {
    const saved = user?.iface_status_filter;
    // "unmonitored" was renamed to "monitored" — treat old saved value as "all"
    if (
      saved === "unmonitored" ||
      !["all", "up", "down", "monitored"].includes(saved ?? "")
    )
      return "all";
    return (saved as IfaceStatusFilter) ?? "all";
  });
  const [filterName, setFilterName] = useState("");
  const [filterAlias, setFilterAlias] = useState("");
  const [filterOperStatus, setFilterOperStatus] = useState<string>("");
  const [filterSpeed, setFilterSpeed] = useState<string>("");
  const [baseRange, setBaseRange] = useState<TimeRangeValue>(timeRange);
  const [isZoomed, setIsZoomed] = useState(false);
  const handleChartZoom = useCallback(
    (fromMs: number, toMs: number) => {
      if (!isZoomed) setBaseRange(timeRange);
      setTimeRange({
        type: "absolute",
        fromTs: new Date(fromMs).toISOString(),
        toTs: new Date(toMs).toISOString(),
      });
      setIsZoomed(true);
    },
    [isZoomed, timeRange],
  );
  const handleResetZoom = useCallback(() => {
    setTimeRange(baseRange);
    setIsZoomed(false);
  }, [baseRange]);
  const tz = useTimezone();
  const { data: monitoring } = useDeviceMonitoring(deviceId);
  const { fromTs, toTs } = useMemo(
    () => rangeToTimestamps(timeRange),
    [timeRange],
  );

  // Build metadata lookup
  const metaMap = useMemo(() => {
    const m = new Map<
      string,
      {
        polling_enabled: boolean;
        alerting_enabled: boolean;
        poll_metrics: string;
        rules_managed: boolean;
      }
    >();
    for (const meta of metadata ?? []) {
      m.set(meta.id, {
        polling_enabled: meta.polling_enabled,
        alerting_enabled: meta.alerting_enabled,
        poll_metrics: meta.poll_metrics ?? "all",
        rules_managed: meta.rules_managed,
      });
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

  // Build the interface list from metadata (PostgreSQL) as the primary source,
  // enriched with ClickHouse data where available. This ensures all discovered
  // interfaces are visible even if they haven't been polled yet (e.g. newly
  // discovered interfaces or those with polling_enabled=false).
  const validInterfaces = useMemo((): InterfaceRecord[] => {
    const chMap = new Map<string, InterfaceRecord>();
    for (const iface of interfaces ?? []) {
      chMap.set(iface.interface_id, iface);
    }
    return (metadata ?? []).map((meta) => {
      const ch = chMap.get(meta.id);
      if (ch) return ch;
      // Metadata-only — synthesize a placeholder row with no polling data
      return {
        interface_id: meta.id,
        if_index: meta.current_if_index,
        if_name: meta.if_name,
        if_alias: meta.if_alias || "",
        if_speed_mbps: meta.if_speed_mbps || 0,
        if_admin_status: "",
        if_oper_status: "unknown",
        in_octets: 0,
        out_octets: 0,
        in_errors: 0,
        out_errors: 0,
        in_discards: 0,
        out_discards: 0,
        in_unicast_pkts: 0,
        out_unicast_pkts: 0,
        in_rate_bps: 0,
        out_rate_bps: 0,
        in_utilization_pct: 0,
        out_utilization_pct: 0,
        poll_interval_sec: 0,
        counter_bits: 64,
        state: 3,
        executed_at: "",
        assignment_id: "",
        collector_id: "",
        app_id: "",
        device_id: meta.device_id,
        collector_name: "",
        device_name: "",
        app_name: "",
        tenant_id: "",
      } satisfies InterfaceRecord;
    });
  }, [interfaces, metadata]);

  // Dynamic filter options
  const availableOperStatuses = useMemo(
    () => [...new Set(validInterfaces.map((i) => i.if_oper_status))].sort(),
    [validInterfaces],
  );
  const availableSpeeds = useMemo(
    () =>
      [...new Set(validInterfaces.map((i) => i.if_speed_mbps))]
        .filter(Boolean)
        .sort((a, b) => a - b),
    [validInterfaces],
  );

  // Filter
  const filtered = useMemo(() => {
    let data = validInterfaces;
    // Status badge filter
    if (statusFilter === "up")
      data = data.filter((i) => i.if_oper_status === "up" && !isUnmonitored(i));
    else if (statusFilter === "down")
      data = data.filter(
        (i) =>
          i.if_oper_status !== "up" &&
          i.if_oper_status !== "unknown" &&
          !isUnmonitored(i),
      );
    else if (statusFilter === "monitored")
      data = data.filter((i) => !isUnmonitored(i));
    // Column filters
    if (filterName)
      data = data.filter((i) => matchesTextFilter(i.if_name, filterName));
    if (filterAlias)
      data = data.filter((i) =>
        matchesTextFilter(i.if_alias || "", filterAlias),
      );
    if (filterOperStatus)
      data = data.filter((i) => i.if_oper_status === filterOperStatus);
    if (filterSpeed)
      data = data.filter((i) => i.if_speed_mbps === Number(filterSpeed));
    return data;
  }, [
    validInterfaces,
    statusFilter,
    filterName,
    filterAlias,
    filterOperStatus,
    filterSpeed,
    isUnmonitored,
  ]);

  // Sort
  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      switch (sortKey) {
        case "status":
          return (
            (a.if_oper_status === "up" ? 0 : 1) -
            (b.if_oper_status === "up" ? 0 : 1)
          );
        case "if_index":
          return (a.if_index - b.if_index) * dir;
        case "if_name":
          return a.if_name.localeCompare(b.if_name) * dir;
        case "if_alias":
          return (a.if_alias || "").localeCompare(b.if_alias || "") * dir;
        case "speed":
          return (a.if_speed_mbps - b.if_speed_mbps) * dir;
        case "in_traffic":
          return (a.in_rate_bps - b.in_rate_bps) * dir;
        case "out_traffic":
          return (a.out_rate_bps - b.out_rate_bps) * dir;
        case "in_errors":
          return (a.in_errors - b.in_errors) * dir;
        case "out_errors":
          return (a.out_errors - b.out_errors) * dir;
        case "last_polled":
          return a.executed_at.localeCompare(b.executed_at) * dir;
        default:
          return 0;
      }
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const toggleSort = (key: IfaceSortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  // Selection helpers
  const filteredIds = useMemo(
    () => new Set(filtered.map((i) => i.interface_id)),
    [filtered],
  );
  const allFilteredSelected =
    filtered.length > 0 &&
    filtered.every((i) => selectedIds.has(i.interface_id));
  const someFilteredSelected = filtered.some((i) =>
    selectedIds.has(i.interface_id),
  );
  const activeSelectedCount = [...selectedIds].filter((id) =>
    filteredIds.has(id),
  ).length;

  const toggleSelectAll = () => {
    if (allFilteredSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const i of filtered) next.delete(i.interface_id);
        return next;
      });
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const i of filtered) next.add(i.interface_id);
        return next;
      });
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Multi-interface chart data
  const chartInterfaceIds = useMemo(() => {
    return [...selectedIds]
      .filter((id) => filteredIds.has(id))
      .slice(0, MAX_CHART_INTERFACES);
  }, [selectedIds, filteredIds]);
  const showMultiChart = chartInterfaceIds.length > 0;
  const tooManySelected = activeSelectedCount > MAX_CHART_INTERFACES;

  const { data: multiHistory } = useMultiInterfaceHistory(
    deviceId,
    fromTs,
    toTs,
    showMultiChart ? chartInterfaceIds : [],
  );

  // Bulk metric toggle for selected interfaces
  const bulkToggleMetric = (metric: string, enable: boolean) => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return;
    for (const id of ids) {
      const meta = metaMap.get(id);
      const current = parseMetrics(meta?.poll_metrics ?? "all");
      if (enable) current.add(metric);
      else current.delete(metric);
      updateSettings.mutate({
        deviceId,
        interfaceId: id,
        data: { poll_metrics: serializeMetrics(current) },
      });
    }
  };

  const selectedHaveMetric = (metric: string): boolean | "mixed" => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map((id) =>
      parseMetrics(metaMap.get(id)?.poll_metrics ?? "all").has(metric),
    );
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const selectedHavePolling = (): boolean | "mixed" => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map((id) => metaMap.get(id)?.polling_enabled ?? true);
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const selectedHaveAlerting = (): boolean | "mixed" => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return false;
    const states = ids.map((id) => metaMap.get(id)?.alerting_enabled ?? true);
    if (states.every(Boolean)) return true;
    if (states.some(Boolean)) return "mixed";
    return false;
  };

  const bulkTogglePolling = (enable: boolean) => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return;
    bulkUpdate.mutate({
      deviceId,
      data: { interface_ids: ids, polling_enabled: enable },
    });
  };

  const bulkToggleAlerting = (enable: boolean) => {
    const ids = [...selectedIds].filter((id) => filteredIds.has(id));
    if (ids.length === 0) return;
    bulkUpdate.mutate({
      deviceId,
      data: { interface_ids: ids, alerting_enabled: enable },
    });
  };

  const SortHead = ({
    col,
    children,
  }: {
    col: IfaceSortKey;
    children: React.ReactNode;
  }) => (
    <TableHead
      className="cursor-pointer select-none"
      onClick={() => toggleSort(col)}
    >
      <span className="flex items-center gap-1">
        {children}
        {sortKey === col ? (
          sortDir === "asc" ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 text-zinc-600" />
        )}
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

  if (!interfaces?.length && !metadata?.length) {
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center justify-center text-zinc-500">
            <Network className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No interface data collected yet.</p>
            <p className="text-xs text-zinc-600 mt-1">
              Assign an interface poller app to this device to start collecting
              data.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const upCount = validInterfaces.filter(
    (i) => i.if_oper_status === "up" && !isUnmonitored(i),
  ).length;
  const downCount = validInterfaces.filter(
    (i) => i.if_oper_status !== "up" && !isUnmonitored(i),
  ).length;
  const monitoredCount = validInterfaces.filter(
    (i) => !isUnmonitored(i),
  ).length;

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
    setBaseRange(next);
    setIsZoomed(false);
    if (
      next.type === "preset" &&
      ["1h", "6h", "24h", "7d", "30d"].includes(next.preset)
    ) {
      updateIfacePrefs.mutate({ iface_time_range: next.preset as any });
    }
  };
  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2 text-sm flex-wrap">
          <span className="text-zinc-500">Interfaces:</span>
          {[
            {
              value: "all" as const,
              count: validInterfaces.length,
              label: "all",
              cls: "bg-zinc-700 text-zinc-200 border-zinc-600",
            },
            {
              value: "up" as const,
              count: upCount,
              label: "up",
              cls: "bg-green-900/60 text-green-400 border-green-700",
            },
            {
              value: "down" as const,
              count: downCount,
              label: "down",
              cls: "bg-red-900/60 text-red-400 border-red-700",
            },
            {
              value: "monitored" as const,
              count: monitoredCount,
              label: "monitored",
              cls: "bg-brand-900/60 text-brand-400 border-brand-700",
            },
          ].map(({ value, count, label, cls }) => (
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
          {activeSelectedCount > 0 && (
            <Badge variant="default">{activeSelectedCount} selected</Badge>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs gap-1"
          disabled={refreshMeta.isPending}
          onClick={() => {
            setRefreshQueuedAt(Date.now());
            setRefreshDone(false);
            refreshMeta.mutate(deviceId);
          }}
        >
          {refreshMeta.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <RefreshCw className="h-3 w-3" />
          )}
          Refresh Metadata
        </Button>
        <Button
          variant={showRulesPanel ? "default" : "outline"}
          size="sm"
          className="h-7 text-xs gap-1"
          onClick={() => setShowRulesPanel((p) => !p)}
        >
          <Settings2 className="h-3 w-3" />
          Interface Rules
          {(rules?.length ?? 0) > 0 && (
            <Badge variant="info" className="ml-0.5 text-[10px] px-1 py-0">
              {rules!.length}
            </Badge>
          )}
        </Button>
        {refreshQueuedAt && !refreshDone && (
          <span className="text-xs text-emerald-400">Queued</span>
        )}
        {refreshDone && (
          <span className="text-xs text-emerald-400">Metadata refreshed</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Select
            value={trafficUnit}
            onChange={(e) => handleTrafficUnit(e.target.value as TrafficUnit)}
            className="h-7 text-xs w-24"
          >
            <option value="auto">Auto</option>
            <option value="kbps">Kbps</option>
            <option value="mbps">Mbps</option>
            <option value="gbps">Gbps</option>
            <option value="pct">% util</option>
          </Select>
          <Select
            value={chartMetric}
            onChange={(e) => handleChartMetric(e.target.value as ChartMetric)}
            className="h-7 text-xs w-28"
          >
            <option value="traffic">Traffic</option>
            <option value="errors">Errors</option>
            <option value="discards">Discards</option>
          </Select>
          <TimeRangePicker
            value={timeRange}
            onChange={handleTimeRange}
            timezone={tz}
          />
          {isZoomed && (
            <button
              onClick={handleResetZoom}
              className="text-xs text-brand-400 hover:text-brand-300 cursor-pointer"
            >
              Reset zoom
            </button>
          )}
        </div>
      </div>

      {/* Interface rules (collapsible panel) */}
      {showRulesPanel && <InterfaceRulesCard deviceId={deviceId} />}

      {/* Multi-interface chart */}
      {showMultiChart && multiHistory ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-zinc-400 flex items-center gap-2 flex-wrap">
              <span>
                {chartMetric === "traffic"
                  ? "Traffic"
                  : chartMetric === "errors"
                    ? "Errors"
                    : "Discards"}
                {" \u2014 "}
                {chartInterfaceIds.length} interface
                {chartInterfaceIds.length > 1 ? "s" : ""}
              </span>
              <div className="ml-auto flex items-center gap-2">
                <div className="flex items-center gap-0.5 border border-zinc-700 rounded px-0.5">
                  <button
                    onClick={() => setChartMode("overlaid")}
                    className={`px-1.5 py-0.5 text-xs rounded ${chartMode === "overlaid" ? "bg-zinc-700 text-zinc-200" : "text-zinc-500"}`}
                  >
                    Overlay
                  </button>
                  <button
                    onClick={() => setChartMode("stacked")}
                    className={`px-1.5 py-0.5 text-xs rounded ${chartMode === "stacked" ? "bg-zinc-700 text-zinc-200" : "text-zinc-500"}`}
                  >
                    Stacked
                  </button>
                </div>
                <button
                  onClick={() => setSelectedIds(new Set())}
                  className="text-zinc-600 hover:text-zinc-300"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MultiInterfaceChart
              interfaceIds={chartInterfaceIds}
              interfaceNames={chartInterfaceIds.map(
                (id) =>
                  interfaces?.find((i) => i.interface_id === id)?.if_name ?? id,
              )}
              historyPerInterface={multiHistory}
              metric={chartMetric}
              unit={trafficUnit}
              mode={chartMode}
              timezone={tz}
              onZoom={handleChartZoom}
            />
          </CardContent>
        </Card>
      ) : tooManySelected ? (
        <Card>
          <CardContent className="py-3">
            <p className="text-sm text-zinc-400 text-center">
              Select up to {MAX_CHART_INTERFACES} interfaces to show the chart.
              Currently {activeSelectedCount} selected.
            </p>
          </CardContent>
        </Card>
      ) : null}

      {/* Interface table */}
      <Card>
        <CardContent className="pt-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead
                  className="w-10"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    checked={allFilteredSelected}
                    ref={(el) => {
                      if (el)
                        el.indeterminate =
                          !allFilteredSelected && someFilteredSelected;
                    }}
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
                  onToggleMetric={(metric, enable) =>
                    bulkToggleMetric(metric, enable)
                  }
                />
              </TableRow>
              {/* Filter row */}
              <TableRow className="bg-zinc-900/50">
                <TableCell />
                <TableCell>
                  {availableOperStatuses.length > 1 && (
                    <Select
                      value={filterOperStatus}
                      onChange={(e) => setFilterOperStatus(e.target.value)}
                      className="h-6 text-[10px] w-full"
                    >
                      <option value="">All</option>
                      {availableOperStatuses.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </Select>
                  )}
                </TableCell>
                <TableCell />
                <TableCell>
                  <ClearableInput
                    placeholder="Filter..."
                    value={filterName}
                    onChange={(e) => setFilterName(e.target.value)}
                    onClear={() => setFilterName("")}
                    className="h-6 text-[10px]"
                  />
                </TableCell>
                <TableCell>
                  <ClearableInput
                    placeholder="Filter..."
                    value={filterAlias}
                    onChange={(e) => setFilterAlias(e.target.value)}
                    onClear={() => setFilterAlias("")}
                    className="h-6 text-[10px]"
                  />
                </TableCell>
                <TableCell>
                  {availableSpeeds.length > 1 && (
                    <Select
                      value={filterSpeed}
                      onChange={(e) => setFilterSpeed(e.target.value)}
                      className="h-6 text-[10px] w-full"
                    >
                      <option value="">All</option>
                      {availableSpeeds.map((s) => (
                        <option key={s} value={String(s)}>
                          {formatSpeed(s)}
                        </option>
                      ))}
                    </Select>
                  )}
                </TableCell>
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell />
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
                    className={`cursor-pointer transition-colors ${isSelected ? "bg-zinc-800/70" : "hover:bg-zinc-800/50"} ${unmonitored ? "opacity-40" : ""}`}
                    onClick={() => toggleSelect(iface.interface_id)}
                  >
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(iface.interface_id)}
                        className="accent-brand-500 cursor-pointer"
                      />
                    </TableCell>
                    <TableCell>
                      <div
                        className={`h-2.5 w-2.5 rounded-full ${iface.if_oper_status === "up" ? "bg-emerald-500" : iface.if_oper_status === "down" ? "bg-red-500" : "bg-zinc-600"}`}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-500">
                      {iface.if_index}
                    </TableCell>
                    <TableCell className="font-medium text-zinc-100">
                      <span className="flex items-center gap-1.5">
                        {iface.if_name}
                        {iface.counter_bits === 32 && (
                          <span
                            className="inline-flex items-center rounded px-1 py-0.5 text-[10px] font-medium leading-none bg-amber-500/15 text-amber-400 border border-amber-500/30"
                            title="32-bit SNMP counters — may wrap on high-speed links"
                          >
                            32-bit
                          </span>
                        )}
                      </span>
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {iface.if_alias || "\u2014"}
                    </TableCell>
                    <TableCell className="text-zinc-300 text-sm">
                      {formatSpeed(iface.if_speed_mbps)}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-cyan-400">
                      {iface.in_rate_bps > 0
                        ? formatTraffic(
                            iface.in_rate_bps,
                            trafficUnit,
                            iface.if_speed_mbps,
                          )
                        : "\u2014"}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-indigo-400">
                      {iface.out_rate_bps > 0
                        ? formatTraffic(
                            iface.out_rate_bps,
                            trafficUnit,
                            iface.if_speed_mbps,
                          )
                        : "\u2014"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      <span
                        className={
                          iface.in_errors > 0
                            ? "text-amber-400"
                            : "text-zinc-600"
                        }
                      >
                        {iface.in_errors.toLocaleString()}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      <span
                        className={
                          iface.out_errors > 0
                            ? "text-amber-400"
                            : "text-zinc-600"
                        }
                      >
                        {iface.out_errors.toLocaleString()}
                      </span>
                    </TableCell>
                    <TableCell className="text-zinc-500 text-xs">
                      {iface.executed_at ? timeAgo(iface.executed_at) : "—"}
                    </TableCell>
                    <TableCell
                      className="text-center"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center gap-1 justify-center">
                        <InterfaceToggleCell
                          state={{
                            polling_enabled: pollingOn,
                            alerting_enabled: alertingOn,
                            traffic: metrics.has("traffic"),
                            errors: metrics.has("errors"),
                            discards: metrics.has("discards"),
                            status: metrics.has("status"),
                          }}
                          onTogglePolling={() =>
                            updateSettings.mutate({
                              deviceId,
                              interfaceId: iface.interface_id,
                              data: { polling_enabled: !pollingOn },
                            })
                          }
                          onToggleAlerting={() =>
                            updateSettings.mutate({
                              deviceId,
                              interfaceId: iface.interface_id,
                              data: { alerting_enabled: !alertingOn },
                            })
                          }
                          onToggleMetric={toggleMetric}
                        />
                        {meta?.rules_managed && (
                          <span
                            className="text-[9px] font-bold text-brand-400 leading-none"
                            title="Managed by interface rule"
                          >
                            R
                          </span>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
              {sorted.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={12}
                    className="text-center py-8 text-zinc-500 text-sm"
                  >
                    {statusFilter === "monitored"
                      ? "No monitored interfaces."
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

// ── Interface Rules Card ──────────────────────────────────

const MATCH_TYPE_OPTIONS = [
  { value: "glob", label: "Glob" },
  { value: "regex", label: "Regex" },
  { value: "exact", label: "Exact" },
];
const NUMERIC_OP_OPTIONS = [
  { value: "eq", label: "=" },
  { value: "gt", label: ">" },
  { value: "lt", label: "<" },
  { value: "gte", label: "≥" },
  { value: "lte", label: "≤" },
];
const METRICS_OPTIONS = [
  { value: "all", label: "All metrics" },
  { value: "none", label: "None" },
  { value: "traffic,status", label: "Traffic + Status" },
  { value: "traffic", label: "Traffic only" },
  { value: "traffic,errors", label: "Traffic + Errors" },
  { value: "traffic,errors,discards,status", label: "All (explicit)" },
];

function emptyRule(): InterfaceRule {
  return {
    name: "",
    match: { if_alias: { pattern: "*", type: "glob" } },
    settings: {
      polling_enabled: true,
      alerting_enabled: true,
      poll_metrics: "all",
    },
    priority: 10,
  };
}

function InterfaceRulesCard({ deviceId }: { deviceId: string }) {
  const { data: rules } = useDeviceInterfaceRules(deviceId);
  const setRules = useSetDeviceInterfaceRules();
  const evaluate = useEvaluateInterfaceRules();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<InterfaceRule[]>([]);
  const [evalResult, setEvalResult] = useState<{
    matched: number;
    changed: number;
    total: number;
  } | null>(null);

  const startEdit = () => {
    const base: InterfaceRule[] =
      rules && rules.length > 0
        ? JSON.parse(JSON.stringify(rules))
        : [emptyRule()];
    // Normalize settings so all fields are explicit — prevents checkbox ?? fallback from hiding missing values
    const normalized = base.map((r) => ({
      ...r,
      settings: {
        polling_enabled: r.settings.polling_enabled ?? true,
        alerting_enabled: r.settings.alerting_enabled ?? true,
        poll_metrics: r.settings.poll_metrics ?? "all",
      },
    }));
    setDraft(normalized);
    setEditing(true);
    setEvalResult(null);
  };
  const cancel = () => {
    setEditing(false);
    setEvalResult(null);
  };

  const save = () => {
    setRules.mutate(
      { deviceId, data: { interface_rules: draft, apply_now: false } },
      {
        onSuccess: () => setEditing(false),
      },
    );
  };

  const runEvaluate = (force: boolean) => {
    evaluate.mutate(
      { deviceId, force },
      {
        onSuccess: (res) => {
          const d = (
            res as { data: { matched: number; changed: number; total: number } }
          ).data;
          setEvalResult(d);
        },
      },
    );
  };

  const addRule = () => setDraft([...draft, emptyRule()]);
  const removeRule = (i: number) =>
    setDraft(draft.filter((_, idx) => idx !== i));
  const updateRule = (i: number, rule: InterfaceRule) => {
    const next = [...draft];
    next[i] = rule;
    setDraft(next);
  };

  const hasRules = (rules?.length ?? 0) > 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-zinc-400 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Interface Rules
            {hasRules && !editing && (
              <Badge variant="info">
                {rules!.length} rule{rules!.length !== 1 ? "s" : ""}
              </Badge>
            )}
          </span>
          <div className="flex items-center gap-2">
            {!editing && hasRules && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs gap-1"
                  disabled={evaluate.isPending}
                  onClick={() => runEvaluate(false)}
                >
                  {evaluate.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Zap className="h-3 w-3" />
                  )}
                  Evaluate
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs gap-1"
                  disabled={evaluate.isPending}
                  onClick={() => runEvaluate(true)}
                >
                  Force
                </Button>
              </>
            )}
            <Button
              variant={editing ? "secondary" : "outline"}
              size="sm"
              className="h-7 text-xs gap-1"
              onClick={editing ? cancel : startEdit}
            >
              {editing ? (
                <>
                  <X className="h-3 w-3" /> Cancel
                </>
              ) : (
                <>
                  <Pencil className="h-3 w-3" />{" "}
                  {hasRules ? "Edit" : "Add Rules"}
                </>
              )}
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {evalResult && (
          <div className="mb-3 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            Evaluated {evalResult.total} interfaces — {evalResult.matched}{" "}
            matched, {evalResult.changed} changed.
          </div>
        )}

        {!editing && !hasRules && (
          <p className="text-sm text-zinc-500">
            No interface rules configured. Rules auto-configure interface
            monitoring based on name, alias, or speed.
          </p>
        )}

        {!editing && hasRules && (
          <div className="space-y-1.5">
            {rules!.map((rule, i) => (
              <div
                key={i}
                className="flex items-center gap-3 rounded-md border border-zinc-800 px-3 py-2"
              >
                <span className="text-xs font-medium text-zinc-200 min-w-0 truncate">
                  {rule.name}
                </span>
                <span className="ml-auto text-[10px] text-zinc-500 shrink-0">
                  prio {rule.priority}
                </span>
                <div className="flex items-center gap-1.5">
                  {Object.entries(rule.match).map(([field, spec]) => (
                    <Badge
                      key={field}
                      variant="default"
                      className="text-[10px]"
                    >
                      {field}:{" "}
                      {(
                        spec as {
                          pattern?: string;
                          op?: string;
                          value?: number;
                        }
                      ).pattern ??
                        `${(spec as { op: string }).op} ${(spec as { value: number }).value}`}
                    </Badge>
                  ))}
                </div>
                <div className="flex items-center gap-1">
                  {rule.settings.polling_enabled != null && (
                    <span
                      className={`h-2 w-2 rounded-full ${rule.settings.polling_enabled ? "bg-brand-500" : "bg-zinc-700"}`}
                      title={`Poll: ${rule.settings.polling_enabled ? "on" : "off"}`}
                    />
                  )}
                  {rule.settings.alerting_enabled != null && (
                    <span
                      className={`h-2 w-2 rounded-full ${rule.settings.alerting_enabled ? "bg-amber-500" : "bg-zinc-700"}`}
                      title={`Alert: ${rule.settings.alerting_enabled ? "on" : "off"}`}
                    />
                  )}
                  {rule.settings.poll_metrics && (
                    <span className="text-[10px] text-zinc-500">
                      {rule.settings.poll_metrics}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {editing && (
          <div className="space-y-3">
            {draft.map((rule, i) => (
              <InterfaceRuleEditor
                key={i}
                rule={rule}
                onChange={(r) => updateRule(i, r)}
                onRemove={() => removeRule(i)}
              />
            ))}
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="gap-1"
                onClick={addRule}
              >
                <Plus className="h-3.5 w-3.5" /> Add Rule
              </Button>
              <Button
                type="button"
                size="sm"
                className="gap-1"
                onClick={save}
                disabled={setRules.isPending}
              >
                {setRules.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                Save Rules
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function InterfaceRuleEditor({
  rule,
  onChange,
  onRemove,
}: {
  rule: InterfaceRule;
  onChange: (r: InterfaceRule) => void;
  onRemove: () => void;
}) {
  const matchFields = Object.keys(rule.match);
  const hasSpeed = "if_speed_mbps" in rule.match;

  const updateMatch = (field: string, spec: Record<string, unknown>) => {
    onChange({ ...rule, match: { ...rule.match, [field]: spec } });
  };

  const removeMatchField = (field: string) => {
    const next = { ...rule.match };
    delete (next as Record<string, unknown>)[field];
    onChange({ ...rule, match: next });
  };

  const addMatchField = (field: string) => {
    if (field === "if_speed_mbps") {
      onChange({
        ...rule,
        match: { ...rule.match, if_speed_mbps: { op: "gte", value: 1000 } },
      });
    } else {
      onChange({
        ...rule,
        match: { ...rule.match, [field]: { pattern: "*", type: "glob" } },
      });
    }
  };

  return (
    <div className="rounded-md border border-zinc-700 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Input
          value={rule.name}
          onChange={(e) => onChange({ ...rule, name: e.target.value })}
          placeholder="Rule name"
          className="h-7 text-xs flex-1"
        />
        <div className="flex items-center gap-1">
          <label className="text-[10px] text-zinc-500">Priority</label>
          <Input
            type="number"
            value={rule.priority}
            onChange={(e) =>
              onChange({ ...rule, priority: parseInt(e.target.value, 10) || 0 })
            }
            className="h-7 text-xs w-16"
            min={0}
          />
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Match conditions */}
      <div className="space-y-1.5">
        <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
          Match (all must match)
        </span>
        {matchFields.map((field) => {
          const spec = (rule.match as Record<string, Record<string, unknown>>)[
            field
          ];
          if (field === "if_speed_mbps") {
            return (
              <div key={field} className="flex items-center gap-1.5">
                <span className="text-xs text-zinc-400 w-24 shrink-0">
                  {field}
                </span>
                <Select
                  value={String(spec.op ?? "gte")}
                  onChange={(e) =>
                    updateMatch(field, { ...spec, op: e.target.value })
                  }
                  className="h-7 text-xs w-16"
                >
                  {NUMERIC_OP_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
                <Input
                  type="number"
                  value={(spec.value as number) ?? 0}
                  onChange={(e) =>
                    updateMatch(field, {
                      ...spec,
                      value: parseInt(e.target.value, 10) || 0,
                    })
                  }
                  className="h-7 text-xs w-24"
                />
                <span className="text-[10px] text-zinc-600">Mbps</span>
                <button
                  type="button"
                  onClick={() => removeMatchField(field)}
                  className="text-zinc-600 hover:text-red-400 cursor-pointer"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            );
          }
          return (
            <div key={field} className="flex items-center gap-1.5">
              <span className="text-xs text-zinc-400 w-24 shrink-0">
                {field}
              </span>
              <Select
                value={String(spec.type ?? "glob")}
                onChange={(e) =>
                  updateMatch(field, { ...spec, type: e.target.value })
                }
                className="h-7 text-xs w-20"
              >
                {MATCH_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
              <Input
                value={String(spec.pattern ?? "")}
                onChange={(e) =>
                  updateMatch(field, { ...spec, pattern: e.target.value })
                }
                placeholder="Pattern..."
                className="h-7 text-xs flex-1"
              />
              <button
                type="button"
                onClick={() => removeMatchField(field)}
                className="text-zinc-600 hover:text-red-400 cursor-pointer"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          );
        })}
        {/* Add match field */}
        <div className="flex items-center gap-1">
          {["if_alias", "if_name", "if_descr"]
            .filter((f) => !(f in rule.match))
            .map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => addMatchField(f)}
                className="text-[10px] text-zinc-600 hover:text-brand-400 border border-zinc-800 hover:border-brand-500/30 rounded px-1.5 py-0.5 cursor-pointer transition-colors"
              >
                + {f}
              </button>
            ))}
          {!hasSpeed && (
            <button
              type="button"
              onClick={() => addMatchField("if_speed_mbps")}
              className="text-[10px] text-zinc-600 hover:text-brand-400 border border-zinc-800 hover:border-brand-500/30 rounded px-1.5 py-0.5 cursor-pointer transition-colors"
            >
              + if_speed_mbps
            </button>
          )}
        </div>
      </div>

      {/* Settings */}
      <div className="space-y-1.5">
        <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
          Settings
        </span>
        <div className="flex items-center gap-4 flex-wrap">
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={rule.settings.polling_enabled ?? true}
              onChange={(e) =>
                onChange({
                  ...rule,
                  settings: {
                    ...rule.settings,
                    polling_enabled: e.target.checked,
                  },
                })
              }
              className="accent-brand-500"
            />
            <span className="text-zinc-300">Polling</span>
          </label>
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={rule.settings.alerting_enabled ?? true}
              onChange={(e) =>
                onChange({
                  ...rule,
                  settings: {
                    ...rule.settings,
                    alerting_enabled: e.target.checked,
                  },
                })
              }
              className="accent-amber-500"
            />
            <span className="text-zinc-300">Alerting</span>
          </label>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-zinc-400">Metrics:</span>
            <Select
              value={rule.settings.poll_metrics ?? "all"}
              onChange={(e) =>
                onChange({
                  ...rule,
                  settings: { ...rule.settings, poll_metrics: e.target.value },
                })
              }
              className="h-7 text-xs w-44"
            >
              {METRICS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </div>
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

// SchemaConfigFields extracted to @/components/SchemaConfigFields.tsx

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
  const systemDefaultInterval =
    systemSettings?.interface_poll_interval_seconds ?? "300";

  // Fetch config_schema for selected apps
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
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
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

            {/* ── Interface Polling ─────────────────────── */}
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

// ── Tab: Assignments ──────────────────────────────────────

const ROLE_COLORS: Record<string, string> = {
  availability: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  latency: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  interface: "bg-purple-500/15 text-purple-400 border-purple-500/30",
};

// formatInterval is imported from @/components/IntervalInput

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
          <Button
            size="sm"
            variant="secondary"
            className="mt-2 gap-1.5"
            onClick={() => setAddOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" /> Assign App
          </Button>
        </div>
        <AddAssignmentDialog
          deviceId={deviceId}
          deviceCollectorGroupId={device?.collector_group_id ?? null}
          deviceCollectorGroupName={device?.collector_group_name ?? null}
          deviceCredentials={device?.credentials}
          open={addOpen}
          onClose={() => setAddOpen(false)}
        />
      </div>
    );
  }

  const editing = editingId
    ? assignments.find((a) => a.id === editingId)
    : null;
  const deleting = deleteConfirmId
    ? assignments.find((a) => a.id === deleteConfirmId)
    : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-500">
          {assignments.length} assignment{assignments.length !== 1 ? "s" : ""}
        </p>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setApplyTemplateOpen(true)}
            className="gap-1.5"
          >
            <FileText className="h-3.5 w-3.5" /> Apply Template
          </Button>
          <Button
            size="sm"
            onClick={() => setAddOpen(true)}
            className="gap-1.5"
          >
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
              <TableCell className="py-1.5 font-mono text-sm">
                {a.app.name}
              </TableCell>
              <TableCell className="py-1.5">
                <div className="flex items-center gap-1">
                  <Badge variant="default" className="text-[10px]">
                    v{a.app.version}
                  </Badge>
                  {a.use_latest && (
                    <Badge
                      variant="default"
                      className="text-[10px] text-zinc-500 border-zinc-700"
                    >
                      latest
                    </Badge>
                  )}
                </div>
              </TableCell>
              <TableCell className="py-1.5">
                {a.role ? (
                  <Badge
                    className={`text-[10px] ${ROLE_COLORS[a.role] ?? "bg-zinc-500/15 text-zinc-400 border-zinc-500/30"}`}
                  >
                    {a.role}
                  </Badge>
                ) : (
                  <span className="text-zinc-600 text-xs">{"\u2014"}</span>
                )}
              </TableCell>
              <TableCell className="py-1.5 text-xs font-mono text-zinc-400">
                {a.schedule_type === "interval"
                  ? formatInterval(Number(a.schedule_value))
                  : a.schedule_value}
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
                <Badge
                  variant={a.enabled ? "success" : "default"}
                  className="text-[10px]"
                >
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
        <Dialog
          open={!!deleteConfirmId}
          onClose={() => setDeleteConfirmId(null)}
          title="Delete Assignment"
        >
          <p className="text-sm text-zinc-300 mb-4">
            Are you sure you want to delete the{" "}
            <span className="font-mono font-semibold">{deleting.app.name}</span>{" "}
            assignment? This will stop monitoring and delete associated data.
          </p>
          <DialogFooter>
            <Button
              variant="secondary"
              onClick={() => setDeleteConfirmId(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={async () => {
                await deleteAssignment.mutateAsync(deleting.id);
                setDeleteConfirmId(null);
              }}
              disabled={deleteAssignment.isPending}
            >
              {deleteAssignment.isPending && (
                <Loader2 className="h-4 w-4 animate-spin mr-1" />
              )}
              Delete
            </Button>
          </DialogFooter>
        </Dialog>
      )}

      {/* Edit dialog uses the existing EditAssignmentDialog */}
      <EditAssignmentDialog
        assignment={editing ?? null}
        deviceCollectorGroupId={device?.collector_group_id ?? null}
        deviceCredentials={device?.credentials}
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
  const { data: deviceCategories } = useDeviceCategories();
  const { data: allDeviceTypes } = useDeviceTypes({ limit: 500 });
  const deviceTypes = allDeviceTypes?.data ?? [];
  const { data: tenants } = useTenants();
  const { data: collectorGroups } = useCollectorGroups();
  const { data: allCredentials } = useCredentials();
  const { data: credentialTypes } = useCredentialTypes();
  const updateDevice = useUpdateDevice();

  // Device fields
  const settingsNameField = useField("", validateName);
  const settingsAddressField = useField("", validateAddress);
  const [deviceCategory, setDeviceCategory] = useState("");
  const [deviceTypeId, setDeviceTypeId] = useState("");
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

  // Initialize form fields when device loads
  useEffect(() => {
    if (device) {
      settingsNameField.reset(device.name);
      settingsAddressField.reset(device.address);
      setDeviceCategory(device.device_category);
      setDeviceTypeId(device.device_type_id ?? "");
      setTenantId(device.tenant_id ?? "");
      setCollectorGroupId(device.collector_group_id ?? "");
      setLabels(device.labels ?? {});
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

      {/* Credentials */}
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

      {/* SNMP Discovery */}
      <DiscoveryCard deviceId={deviceId} device={device} />

      {/* Monitoring Configuration */}
      <MonitoringCard deviceId={deviceId} device={device} />
    </div>
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

  // --- Discovery polling state ---
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

  // Fast-poll device while waiting for discovery result
  useEffect(() => {
    if (discoveryPhase !== "polling") return;
    const iv = setInterval(() => {
      qc.invalidateQueries({ queryKey: ["device", deviceId] });
    }, 2000);
    return () => clearInterval(iv);
  }, [discoveryPhase, deviceId, qc]);

  // Detect when discovered_at changes → discovery complete
  useEffect(() => {
    if (discoveryPhase !== "polling") return;
    if (discovered && discovered !== preDiscoverAt.current) {
      setDiscoveryPhase("done");
    }
  }, [discoveryPhase, discovered]);

  // Timeout after 60s
  useEffect(() => {
    if (discoveryPhase !== "polling") return;
    const t = setTimeout(() => setDiscoveryPhase("timeout"), 60_000);
    return () => clearTimeout(t);
  }, [discoveryPhase]);

  // Auto-dismiss done / timeout messages
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

  // Show "Create Device Type" when sysObjectID is known
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
              // Re-discover so device gets linked to new type
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
          sortDir === "asc" ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )
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
  const toggle = useCallback(
    (field: string) => {
      if (field === sortBy) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortBy(field);
        setSortDir("desc");
      }
    },
    [sortBy],
  );
  return { sortBy, sortDir, toggle };
}

// ── Tab: Checks (Live + History) ─────────────────────────

function ChecksTab({ deviceId }: { deviceId: string }) {
  const tz = useTimezone();
  const [mode, setMode] = useState<"live" | "history">("live");

  // Live mode data
  const { data: deviceResults, isLoading: liveLoading } =
    useDeviceResults(deviceId);

  // History mode data + state
  const [range, setRange] = useState<TimeRangeValue>({
    type: "preset",
    preset: "24h",
  });
  const { fromTs: from } = useMemo(() => rangeToTimestamps(range), [range]);
  const { data: history, isLoading: histLoading } = useDeviceHistory(
    deviceId,
    from,
    null,
    500,
  );
  const { sortBy, sortDir, toggle: onSort } = useSort("executed_at");
  const [filterApp, setFilterApp] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterCollector, setFilterCollector] = useState("");

  const records = history ?? [];

  const appNames = useMemo(
    () => [...new Set(records.map((r) => r.app_name).filter(Boolean))].sort(),
    [records],
  );
  const statuses = useMemo(
    () => [...new Set(records.map((r) => r.state_name).filter(Boolean))].sort(),
    [records],
  );
  const collectors = useMemo(
    () =>
      [...new Set(records.map((r) => r.collector_name).filter(Boolean))].sort(),
    [records],
  );

  const filtered = useMemo(() => {
    let data = records;
    if (filterApp) data = data.filter((r) => r.app_name === filterApp);
    if (filterStatus) data = data.filter((r) => r.state_name === filterStatus);
    if (filterCollector)
      data = data.filter((r) => r.collector_name === filterCollector);
    return [...data].sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case "app_name":
          cmp = (a.app_name ?? "").localeCompare(b.app_name ?? "");
          break;
        case "started_at":
          cmp = (a.started_at ?? "").localeCompare(b.started_at ?? "");
          break;
        case "executed_at":
          cmp = a.executed_at.localeCompare(b.executed_at);
          break;
        case "duration":
          cmp = (a.execution_time_ms ?? 0) - (b.execution_time_ms ?? 0);
          break;
        case "collector":
          cmp = (a.collector_name ?? "").localeCompare(b.collector_name ?? "");
          break;
        case "status":
          cmp = (a.state_name ?? "").localeCompare(b.state_name ?? "");
          break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [records, filterApp, filterStatus, filterCollector, sortBy, sortDir]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Checks
            {mode === "live" && deviceResults && (
              <Badge variant="default" className="ml-1 text-xs">
                {deviceResults.checks.length}
              </Badge>
            )}
            {mode === "history" && (
              <span className="text-zinc-500 font-normal text-xs ml-1">
                ({filtered.length}
                {filtered.length !== records.length
                  ? ` of ${records.length}`
                  : ""}{" "}
                results)
              </span>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            {/* Mode toggle */}
            <div className="flex rounded-md border border-zinc-700 overflow-hidden text-xs">
              <button
                onClick={() => setMode("live")}
                className={`px-3 py-1.5 transition-colors ${mode === "live" ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}
              >
                Live
              </button>
              <button
                onClick={() => setMode("history")}
                className={`px-3 py-1.5 transition-colors ${mode === "history" ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}
              >
                History
              </button>
            </div>
            {mode === "history" && (
              <TimeRangePicker
                value={range}
                onChange={setRange}
                timezone={tz}
              />
            )}
          </div>
        </div>
        {/* History filters */}
        {mode === "history" && (
          <div className="flex items-center gap-2 pt-2">
            <Select
              value={filterApp}
              onChange={(e) => setFilterApp(e.target.value)}
              className="w-40 text-xs"
            >
              <option value="">All Apps</option>
              {appNames.map((n) => (
                <option key={n} value={n!}>
                  {n}
                </option>
              ))}
            </Select>
            <Select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="w-36 text-xs"
            >
              <option value="">All Statuses</option>
              {statuses.map((s) => (
                <option key={s} value={s!}>
                  {s}
                </option>
              ))}
            </Select>
            <Select
              value={filterCollector}
              onChange={(e) => setFilterCollector(e.target.value)}
              className="w-40 text-xs"
            >
              <option value="">All Collectors</option>
              {collectors.map((c) => (
                <option key={c} value={c!}>
                  {c}
                </option>
              ))}
            </Select>
            {(filterApp || filterStatus || filterCollector) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setFilterApp("");
                  setFilterStatus("");
                  setFilterCollector("");
                }}
              >
                <X className="h-3 w-3" /> Clear
              </Button>
            )}
          </div>
        )}
      </CardHeader>
      <CardContent>
        {mode === "live" ? (
          liveLoading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
          ) : !deviceResults || deviceResults.checks.length === 0 ? (
            <p className="text-sm text-zinc-500 py-8 text-center">
              No checks configured. Add apps on the Settings tab.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>State</TableHead>
                  <TableHead>App</TableHead>
                  <TableHead>Output</TableHead>
                  <TableHead>Latency</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Collector</TableHead>
                  <TableHead>Executed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {deviceResults.checks.map((check) => (
                  <TableRow key={check.assignment_id}>
                    <TableCell>
                      <StatusBadge state={check.state_name} />
                    </TableCell>
                    <TableCell className="font-medium text-zinc-200">
                      {check.app_name}
                    </TableCell>
                    <TableCell
                      className="max-w-[240px] truncate text-zinc-400 text-sm"
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
                    <TableCell className="font-mono text-xs text-zinc-300">
                      {check.execution_time_ms != null
                        ? `${Math.round(check.execution_time_ms)}ms`
                        : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {check.collector_name ?? "—"}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm">
                      {timeAgo(check.executed_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )
        ) : histLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-zinc-500 py-8 text-center">
            No results match the current filters.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <SortableHead
                  label="Status"
                  field="status"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <SortableHead
                  label="App"
                  field="app_name"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <TableHead>Output</TableHead>
                <TableHead>Latency</TableHead>
                <SortableHead
                  label="Duration"
                  field="duration"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <SortableHead
                  label="Started"
                  field="started_at"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <SortableHead
                  label="Completed"
                  field="executed_at"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
                <SortableHead
                  label="Collector"
                  field="collector"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={onSort}
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((r, i) => {
                const startedAt = r.started_at ? new Date(r.started_at) : null;
                const executedAt = new Date(r.executed_at);
                const durationMs =
                  r.execution_time_ms ??
                  (startedAt
                    ? executedAt.getTime() - startedAt.getTime()
                    : null);
                const latency =
                  r.rtt_ms != null
                    ? `${r.rtt_ms}ms`
                    : r.response_time_ms != null
                      ? `${r.response_time_ms}ms`
                      : "—";
                return (
                  <TableRow key={`${r.assignment_id}-${i}`}>
                    <TableCell>
                      <StatusBadge state={r.state_name} />
                    </TableCell>
                    <TableCell className="font-medium text-zinc-200">
                      {r.app_name ?? "—"}
                    </TableCell>
                    <TableCell
                      className="max-w-[200px] truncate text-zinc-400 text-sm"
                      title={r.output ?? ""}
                    >
                      {r.output || "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm font-mono">
                      {latency}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-300">
                      {durationMs != null ? `${Math.round(durationMs)}ms` : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-xs">
                      {startedAt
                        ? formatDate(startedAt.toISOString(), tz)
                        : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-xs">
                      {formatDate(r.executed_at, tz)}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {r.collector_name ?? "—"}
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
    <span
      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium ${variants[severity] ?? variants.warning}`}
    >
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
          <button
            key={t}
            onClick={() => setSubTab(t)}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${subTab === t ? "bg-zinc-700 text-white" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"}`}
          >
            {t === "active" ? "Active" : "History"}
          </button>
        ))}
      </div>
      {subTab === "active" ? (
        <DeviceActiveAlerts deviceId={deviceId} />
      ) : (
        <DeviceAlertHistory deviceId={deviceId} />
      )}
    </div>
  );
}

function DeviceActiveAlerts({ deviceId }: { deviceId: string }) {
  const { pageSize, scrollMode } = useTablePreferences();
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
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: response,
    isLoading,
    isFetching,
  } = useAlertInstances({
    device_id: deviceId,
    ...listState.params,
  });
  const instances = (response as any)?.data ?? response ?? [];
  const meta = (response as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: instances.length,
    total: instances.length,
  };
  const updateInstance = useUpdateAlertInstance();

  if (isLoading)
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );

  if (!instances || instances.length === 0) {
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center justify-center text-zinc-500">
            <Bell className="h-10 w-10 mb-3 text-zinc-600" />
            <p className="text-sm">No alert definitions for this device</p>
            <p className="text-xs text-zinc-600 mt-1">
              Alert definitions are created on apps and automatically applied
              when assigned
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const firing = instances.filter((i: any) => i.state === "firing");

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-4 w-4" /> Active Alerts
            {firing.length > 0 && (
              <Badge variant="destructive" className="ml-1.5 text-xs">
                {firing.length} firing
              </Badge>
            )}
          </CardTitle>
          <span className="text-xs text-zinc-500">{meta.total} total</span>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <FilterableSortHead
                col="state"
                label="State"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="definition_name"
                label="Alert"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.definition_name}
                onFilterChange={(v) =>
                  listState.setFilter("definition_name", v)
                }
              />
              <FilterableSortHead
                col="app_name"
                label="App"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.app_name}
                onFilterChange={(v) => listState.setFilter("app_name", v)}
              />
              <FilterableSortHead
                col="entity_key"
                label="Entity"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.entity_key}
                onFilterChange={(v) => listState.setFilter("entity_key", v)}
              />
              <FilterableSortHead
                col="current_value"
                label="Value"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="fire_count"
                label="Fires"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="started_firing_at"
                label="Since"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <TableHead className="w-16">Enabled</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {instances.map((inst: any) => (
              <TableRow
                key={inst.id}
                className={inst.state === "firing" ? "bg-red-500/5" : ""}
              >
                <TableCell>
                  <Badge
                    variant={
                      inst.state === "firing"
                        ? "destructive"
                        : inst.state === "resolved"
                          ? "warning"
                          : "success"
                    }
                  >
                    {inst.state === "firing"
                      ? "ACTIVE"
                      : inst.state === "resolved"
                        ? "CLEARED"
                        : inst.state.toUpperCase()}
                  </Badge>
                </TableCell>
                <TableCell className="font-medium">
                  {inst.definition_name ?? "\u2014"}
                  {inst.entity_labels?.if_name && (
                    <span className="ml-1.5 text-xs text-zinc-500">
                      ({inst.entity_labels.if_name})
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-zinc-400 text-sm">
                  {inst.app_name ?? "\u2014"}
                </TableCell>
                <TableCell className="text-zinc-400 text-xs font-mono">
                  {inst.entity_labels?.if_name ||
                    inst.entity_labels?.component ||
                    inst.entity_key ||
                    "\u2014"}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {inst.current_value != null
                    ? Number(inst.current_value).toFixed(2)
                    : "\u2014"}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {inst.fire_count ?? 0}
                </TableCell>
                <TableCell className="text-xs text-zinc-400">
                  {inst.started_firing_at
                    ? timeAgo(inst.started_firing_at)
                    : "\u2014"}
                </TableCell>
                <TableCell className="text-center">
                  <button
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${inst.enabled ? "bg-brand-500" : "bg-zinc-600"}`}
                    onClick={() =>
                      updateInstance.mutate({
                        id: inst.id,
                        enabled: !inst.enabled,
                      })
                    }
                  >
                    <span
                      className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${inst.enabled ? "translate-x-4.5" : "translate-x-0.5"}`}
                    />
                  </button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <PaginationBar
          page={listState.page}
          pageSize={listState.pageSize}
          total={meta.total}
          count={meta.count}
          onPageChange={listState.setPage}
          scrollMode={listState.scrollMode}
          sentinelRef={listState.sentinelRef}
          isFetching={isFetching}
          onLoadMore={listState.loadMore}
        />
      </CardContent>
    </Card>
  );
}

function DeviceAlertHistory({ deviceId }: { deviceId: string }) {
  const [actionFilter, setActionFilter] = useState<string | undefined>(
    undefined,
  );
  const { pageSize, scrollMode } = useTablePreferences();
  const listState = useListState({
    columns: [
      { key: "definition_name", label: "Alert" },
      { key: "message", label: "Message" },
      { key: "occurred_at", label: "Time", filterable: false },
    ],
    defaultSortBy: "occurred_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });

  const {
    data: response,
    isLoading,
    isFetching,
  } = useDeviceAlertLog(deviceId, listState.params, { action: actionFilter });
  const logEntries = (response as any)?.data ?? [];
  const meta = (response as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-4 w-4" /> Alert History
            <Badge variant="default" className="ml-1.5 text-xs">
              {meta.total}
            </Badge>
          </CardTitle>
          <div className="flex items-center gap-1 text-xs">
            {(
              [
                { val: undefined, label: "All", cls: "" },
                {
                  val: "fire",
                  label: "Fires",
                  cls: "bg-red-500/20 text-red-400",
                },
                {
                  val: "clear",
                  label: "Clears",
                  cls: "bg-green-500/20 text-green-400",
                },
              ] as const
            ).map(({ val, label, cls }) => (
              <button
                key={label}
                onClick={() => setActionFilter(val)}
                className={`px-2 py-0.5 rounded ${actionFilter === val ? cls || "bg-zinc-700 text-white" : "text-zinc-400 hover:text-zinc-200"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-brand-500" />
          </div>
        ) : logEntries.length === 0 ? (
          <p className="text-sm text-zinc-500 text-center py-8">
            No alert history for this device
          </p>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">Action</TableHead>
                  <FilterableSortHead
                    col="definition_name"
                    label="Alert"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterValue={listState.filters.definition_name}
                    onFilterChange={(v) =>
                      listState.setFilter("definition_name", v)
                    }
                  />
                  <TableHead>Entity</TableHead>
                  <TableHead>Value</TableHead>
                  <FilterableSortHead
                    col="message"
                    label="Message"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterValue={listState.filters.message}
                    onFilterChange={(v) => listState.setFilter("message", v)}
                    sortable={false}
                  />
                  <FilterableSortHead
                    col="occurred_at"
                    label="Time"
                    sortBy={listState.sortBy}
                    sortDir={listState.sortDir}
                    onSort={listState.handleSort}
                    filterable={false}
                  />
                </TableRow>
              </TableHeader>
              <TableBody>
                {logEntries.map((entry: AlertLogEntry, idx: number) => (
                  <TableRow
                    key={`${entry.definition_id}-${entry.occurred_at}-${idx}`}
                    className={
                      entry.action === "fire"
                        ? "bg-red-500/5"
                        : "bg-green-500/5"
                    }
                  >
                    <TableCell>
                      <Badge
                        variant={
                          entry.action === "fire" ? "destructive" : "success"
                        }
                      >
                        {entry.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-medium">
                      {entry.definition_name}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-xs font-mono">
                      {entry.entity_key || "\u2014"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {entry.current_value != null
                        ? Number(entry.current_value).toFixed(2)
                        : "\u2014"}
                    </TableCell>
                    <TableCell
                      className="text-xs text-zinc-400 max-w-[200px] truncate"
                      title={entry.message}
                    >
                      {entry.message || "\u2014"}
                    </TableCell>
                    <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                      {timeAgo(entry.occurred_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <PaginationBar
              page={listState.page}
              pageSize={listState.pageSize}
              total={meta.total}
              count={meta.count}
              onPageChange={listState.setPage}
              scrollMode={listState.scrollMode}
              sentinelRef={listState.sentinelRef}
              isFetching={isFetching}
              onLoadMore={listState.loadMore}
            />
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
          <button
            key={t}
            onClick={() => setSubTab(t)}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${subTab === t ? "bg-zinc-700 text-white" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"}`}
          >
            {t === "active" ? "Active" : "Cleared"}
          </button>
        ))}
      </div>
      {subTab === "active" ? (
        <DeviceActiveEvents deviceId={deviceId} />
      ) : (
        <DeviceClearedEvents deviceId={deviceId} />
      )}
    </div>
  );
}

function DeviceActiveEvents({ deviceId }: { deviceId: string }) {
  const { pageSize, scrollMode } = useTablePreferences();
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
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: response,
    isLoading,
    isFetching,
  } = useDeviceActiveEvents(deviceId, listState.params);
  const events = (response as any)?.data ?? [];
  const meta = (response as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const ackMut = useAcknowledgeEvents();
  const clearMut = useClearEvents();

  const toggle = (id: string) =>
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const toggleAll = () =>
    selected.size === events.length
      ? setSelected(new Set())
      : setSelected(new Set(events.map((e: any) => e.id)));

  if (isLoading)
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
          </div>
        </CardContent>
      </Card>
    );
  if (events.length === 0)
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center justify-center text-zinc-500">
            <Zap className="h-10 w-10 mb-3 text-zinc-600" />
            <p className="text-sm">No active events for this device</p>
          </div>
        </CardContent>
      </Card>
    );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-4 w-4" /> Active Events ({meta.total})
          </CardTitle>
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={ackMut.isPending}
                onClick={async () => {
                  await ackMut.mutateAsync([...selected]);
                  setSelected(new Set());
                }}
              >
                <Check className="h-3.5 w-3.5" /> Acknowledge ({selected.size})
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={clearMut.isPending}
                onClick={async () => {
                  await clearMut.mutateAsync([...selected]);
                  setSelected(new Set());
                }}
              >
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
              <TableHead className="w-10">
                <input
                  type="checkbox"
                  checked={selected.size === events.length && events.length > 0}
                  onChange={toggleAll}
                  className="accent-brand-500 cursor-pointer"
                />
              </TableHead>
              <FilterableSortHead
                col="severity"
                label="Severity"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="source"
                label="Source"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.source}
                onFilterChange={(v) => listState.setFilter("source", v)}
              />
              <FilterableSortHead
                col="policy_name"
                label="Policy"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.policy_name}
                onFilterChange={(v) => listState.setFilter("policy_name", v)}
                sortable={false}
              />
              <FilterableSortHead
                col="message"
                label="Message"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.message}
                onFilterChange={(v) => listState.setFilter("message", v)}
                sortable={false}
              />
              <TableHead>State</TableHead>
              <FilterableSortHead
                col="occurred_at"
                label="Occurred"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((evt: MonitoringEvent) => (
              <TableRow key={evt.id}>
                <TableCell>
                  <input
                    type="checkbox"
                    checked={selected.has(evt.id)}
                    onChange={() => toggle(evt.id)}
                    className="accent-brand-500 cursor-pointer"
                  />
                </TableCell>
                <TableCell>
                  <SeverityBadge severity={evt.severity} />
                </TableCell>
                <TableCell className="text-xs text-zinc-400">
                  {evt.source}
                </TableCell>
                <TableCell className="text-xs">{evt.policy_name}</TableCell>
                <TableCell
                  className="text-xs text-zinc-300 max-w-[300px] truncate"
                  title={evt.message}
                >
                  {evt.message}
                </TableCell>
                <TableCell>
                  <Badge
                    variant={
                      evt.state === "acknowledged" ? "warning" : "default"
                    }
                  >
                    {evt.state}
                  </Badge>
                </TableCell>
                <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                  {timeAgo(evt.occurred_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <PaginationBar
          page={listState.page}
          pageSize={listState.pageSize}
          total={meta.total}
          count={meta.count}
          onPageChange={listState.setPage}
          scrollMode={listState.scrollMode}
          sentinelRef={listState.sentinelRef}
          isFetching={isFetching}
          onLoadMore={listState.loadMore}
        />
      </CardContent>
    </Card>
  );
}

function DeviceClearedEvents({ deviceId }: { deviceId: string }) {
  const { pageSize, scrollMode } = useTablePreferences();
  const listState = useListState({
    columns: [
      { key: "severity", label: "Severity", filterable: false },
      { key: "source", label: "Source" },
      { key: "policy_name", label: "Policy", sortable: false },
      { key: "occurred_at", label: "Occurred", filterable: false },
    ],
    defaultSortBy: "occurred_at",
    defaultSortDir: "desc",
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: response,
    isLoading,
    isFetching,
  } = useDeviceClearedEvents(deviceId, listState.params);
  const events = (response as any)?.data ?? [];
  const meta = (response as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };

  if (isLoading)
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
          </div>
        </CardContent>
      </Card>
    );
  if (events.length === 0)
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center justify-center text-zinc-500">
            <Zap className="h-10 w-10 mb-3 text-zinc-600" />
            <p className="text-sm">No cleared events for this device</p>
          </div>
        </CardContent>
      </Card>
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="h-4 w-4" /> Cleared Events ({meta.total})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <FilterableSortHead
                col="severity"
                label="Severity"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <FilterableSortHead
                col="source"
                label="Source"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.source}
                onFilterChange={(v) => listState.setFilter("source", v)}
              />
              <FilterableSortHead
                col="policy_name"
                label="Policy"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterValue={listState.filters.policy_name}
                onFilterChange={(v) => listState.setFilter("policy_name", v)}
                sortable={false}
              />
              <TableHead>Message</TableHead>
              <FilterableSortHead
                col="occurred_at"
                label="Occurred"
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filterable={false}
              />
              <TableHead>Cleared</TableHead>
              <TableHead>Cleared By</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((evt: MonitoringEvent) => (
              <TableRow key={evt.id}>
                <TableCell>
                  <SeverityBadge severity={evt.severity} />
                </TableCell>
                <TableCell className="text-xs text-zinc-400">
                  {evt.source}
                </TableCell>
                <TableCell className="text-xs">{evt.policy_name}</TableCell>
                <TableCell
                  className="text-xs text-zinc-300 max-w-[300px] truncate"
                  title={evt.message}
                >
                  {evt.message}
                </TableCell>
                <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                  {timeAgo(evt.occurred_at)}
                </TableCell>
                <TableCell className="text-xs text-zinc-400 whitespace-nowrap">
                  {evt.cleared_at ? timeAgo(evt.cleared_at) : "\u2014"}
                </TableCell>
                <TableCell className="text-xs text-zinc-400">
                  {evt.cleared_by ||
                    (evt.event_type === "alert_resolved" ? "auto" : "\u2014")}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <PaginationBar
          page={listState.page}
          pageSize={listState.pageSize}
          total={meta.total}
          count={meta.count}
          onPageChange={listState.setPage}
          scrollMode={listState.scrollMode}
          sentinelRef={listState.sentinelRef}
          isFetching={isFetching}
          onLoadMore={listState.loadMore}
        />
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

  const grouped = thresholds.reduce<Record<string, DeviceThresholdRow[]>>(
    (acc, row) => {
      const key = row.app_name || "Unknown";
      if (!acc[key]) acc[key] = [];
      acc[key].push(row);
      return acc;
    },
    {},
  );

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

function formatDeviceThresholdValue(
  value: number | null | undefined,
  unit: string | null,
): string {
  if (value == null) return "\u2014";
  if (unit === "percent") return `${value}%`;
  if (unit === "ms") return `${value} ms`;
  if (unit === "seconds") return `${value}s`;
  if (unit === "dBm") return `${value} dBm`;
  if (unit === "pps") return `${value} pps`;
  if (unit === "bps") {
    if (value >= 1_000_000_000)
      return `${(value / 1_000_000_000).toFixed(1)} Gbps`;
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} Mbps`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)} kbps`;
    return `${value} bps`;
  }
  if (unit === "bytes") {
    if (value >= 1_073_741_824)
      return `${(value / 1_073_741_824).toFixed(1)} GB`;
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
    row.device_value != null
      ? "device"
      : row.app_value != null
        ? "app"
        : "default";

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
          <span className="text-blue-400">
            {formatDeviceThresholdValue(row.app_value, row.unit)}
          </span>
        ) : (
          "\u2014"
        )}
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
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-1"
              onClick={handleSave}
            >
              <Save className="h-3 w-3" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-1"
              onClick={() => setEditing(false)}
            >
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
              {row.device_value != null
                ? formatDeviceThresholdValue(row.device_value, row.unit)
                : "\u2014"}
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
        <span
          className={
            effectiveSource !== "default"
              ? "font-mono text-sm text-brand-400 font-medium"
              : "font-mono text-sm text-zinc-300"
          }
        >
          {formatDeviceThresholdValue(row.effective_value, row.unit)}
        </span>
        {effectiveSource === "device" && (
          <span className="ml-1.5 text-xs text-zinc-500">
            (device override)
          </span>
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
  const { data: deviceResults, isLoading: resultsLoading } =
    useDeviceResults(id);
  const { data: device, isLoading: deviceLoading } = useDevice(id);
  const { data: allCategories } = useDeviceCategories();
  const [activeTab, setActiveTab] = useState("overview");

  // Auto-assign templates
  const resolveTemplates = useResolveTemplates();
  const autoApplyTemplates = useAutoApplyTemplates();
  const [autoAssignPreview, setAutoAssignPreview] =
    useState<ResolvedTemplateResult | null>(null);

  // Extract uptime from performance checks (snmp_uptime app)
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

  // Use device data as primary source, deviceResults as supplement
  const deviceName = device?.name ?? deviceResults?.device_name ?? "Unknown";
  const deviceAddress = device?.address ?? deviceResults?.device_address ?? "";
  const deviceCategory =
    device?.device_category ?? deviceResults?.device_category ?? "";
  const dc = (allCategories ?? []).find((c) => c.name === deviceCategory);
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

      {/* Auto-Assign Preview Dialog */}
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
          <TabTrigger value="checks">
            <span className="flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5" />
              Checks
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
        <TabsContent value="checks">
          <ChecksTab deviceId={deviceId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
