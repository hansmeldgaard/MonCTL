import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bug,
  FileText,
  ListChecks,
  Loader2,
  Pencil,
  Pin,
  Plus,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { SearchableSelect } from "@/components/ui/searchable-select.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { IntervalInput, formatInterval } from "@/components/IntervalInput";
import { CredentialCell } from "@/components/CredentialCell.tsx";
import { DebugRunDialog } from "@/components/DebugRunDialog.tsx";
import { ApplyTemplateDialog } from "@/components/ApplyTemplateDialog.tsx";
import { SchemaConfigFields } from "@/components/SchemaConfigFields.tsx";
import {
  useAppDetail,
  useApps,
  useCollectors,
  useCreateAssignment,
  useCredentials,
  useDeleteAssignment,
  useDevice,
  useDeviceAssignments,
  useUpdateAssignment,
} from "@/api/hooks.ts";
import { apiGet } from "@/api/client.ts";
import type { DeviceAssignment } from "@/types/api.ts";
import { usePermissions } from "@/hooks/usePermissions";

const ROLE_COLORS: Record<string, string> = {
  availability: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  latency: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  interface: "bg-purple-500/15 text-purple-400 border-purple-500/30",
};

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

export function AssignmentsTab({ deviceId }: { deviceId: string }) {
  const { data: device } = useDevice(deviceId);
  const { data: assignments, isLoading } = useDeviceAssignments(deviceId);
  const deleteAssignment = useDeleteAssignment();
  const { canEdit } = usePermissions();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [applyTemplateOpen, setApplyTemplateOpen] = useState(false);
  const [debugAssignment, setDebugAssignment] = useState<{
    id: string;
    appName: string;
  } | null>(null);

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
                  {canEdit("device") && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 w-6 p-0 text-brand-400 hover:text-brand-300"
                      onClick={() =>
                        setDebugAssignment({ id: a.id, appName: a.app.name })
                      }
                      title="Debug Run — run this app once and see the full output"
                    >
                      <Bug className="h-3 w-3" />
                    </Button>
                  )}
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

      <DebugRunDialog
        open={!!debugAssignment}
        onClose={() => setDebugAssignment(null)}
        deviceId={deviceId}
        assignmentId={debugAssignment?.id ?? ""}
        appName={debugAssignment?.appName ?? ""}
        deviceName={device?.name ?? ""}
      />
    </div>
  );
}
