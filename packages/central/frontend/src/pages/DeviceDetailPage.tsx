import { useState, useEffect, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  BarChart2,
  Layout,
  Loader2,
  Monitor,
  Plus,
  Save,
  Settings2,
  Tag,
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
import { TimeRangePicker, rangeToTimestamps } from "@/components/TimeRangePicker.tsx";
import type { TimeRangeValue } from "@/components/TimeRangePicker.tsx";
import {
  useCollectorGroups,
  useCollectors,
  useCreateAssignment,
  useCredentials,
  useDeleteAssignment,
  useDevice,
  useDeviceAssignments,
  useDeviceHistory,
  useDeviceMonitoring,
  useDeviceResults,
  useDeviceTypes,
  useAppDetail,
  useApps,
  useSnmpOids,
  useTenants,
  useUpdateDevice,
  useUpdateDeviceMonitoring,
} from "@/api/hooks.ts";
import type { Device as DeviceType } from "@/types/api.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";

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
  const [configText, setConfigText] = useState("{}");
  const [configError, setConfigError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

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

  function reset() {
    setSelectedAppId(apps?.[0]?.id ?? "");
    setCollectorId(collectors?.[0]?.id ?? "");
    setRoutingMode(deviceCollectorGroupId ? "group" : "specific");
    setScheduleType("interval");
    setScheduleValue("60");
    setConfigText("{}");
    setConfigError(null);
    setFormError(null);
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setConfigError(null);

    let config: Record<string, unknown> = {};
    try {
      config = JSON.parse(configText);
    } catch {
      setConfigError("Invalid JSON");
      return;
    }

    if (!selectedAppId) {
      setFormError("App is required.");
      return;
    }

    if (routingMode === "specific" && !collectorId) {
      setFormError("Select a collector or switch to collector group routing.");
      return;
    }

    const latestVersion = appDetail?.versions?.[0];
    if (!latestVersion) {
      setFormError("The selected app has no published versions.");
      return;
    }

    try {
      await createAssignment.mutateAsync({
        app_id: selectedAppId,
        app_version_id: latestVersion.id,
        collector_id: routingMode === "specific" ? collectorId : null,
        device_id: deviceId,
        schedule_type: scheduleType,
        schedule_value: scheduleValue,
        config,
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
          {appDetail && (
            <p className="text-xs text-zinc-500">
              Latest version:{" "}
              {appDetail.versions.length > 0
                ? <span className="text-zinc-300">{appDetail.versions[0].version}</span>
                : <span className="text-red-400">none — publish a version first</span>}
            </p>
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
          <Label htmlFor="aa-config">
            Config <span className="font-normal text-zinc-500">(JSON)</span>
          </Label>
          <textarea
            id="aa-config"
            rows={4}
            value={configText}
            onChange={(e) => setConfigText(e.target.value)}
            className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 font-mono text-xs text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 resize-none"
            placeholder="{}"
          />
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

// ── Tab 1: Overview ──────────────────────────────────────

function OverviewTab({ deviceId }: { deviceId: string }) {
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
        <TimeRangePicker value={timeRange} onChange={setTimeRange} />
      </div>

      {/* Chart card */}
      <Card>
        <CardContent className="pt-4">
          {histLoading ? (
            <div className="flex h-48 items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            </div>
          ) : (
            <AvailabilityChart results={history ?? []} fromTs={fromTs} toTs={toTs} />
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
  const [timeRange, setTimeRange] = useState<TimeRangeValue>(DEFAULT_RANGE);
  const { fromTs, toTs } = useMemo(() => rangeToTimestamps(timeRange), [timeRange]);
  const { data: history, isLoading } = useDeviceHistory(deviceId, fromTs, toTs, 1000);
  const tableHistory = history ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-zinc-400">Check History</h3>
        <TimeRangePicker value={timeRange} onChange={setTimeRange} />
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
                ({tableHistory.length} results)
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>State</TableHead>
                  <TableHead>Check</TableHead>
                  <TableHead>Availability</TableHead>
                  <TableHead>Latency</TableHead>
                  <TableHead>Output</TableHead>
                  <TableHead>Executed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tableHistory.slice(0, 500).map((r, idx) => (
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
                      {formatDate(r.executed_at)}
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

function ConfigurationTab() {
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="py-12 flex flex-col items-center gap-3 text-zinc-600">
          <Wrench className="h-8 w-8 text-zinc-700" />
          <p className="text-sm text-zinc-500">Configuration data will be populated by monitoring apps.</p>
          <p className="text-xs text-zinc-700 text-center max-w-sm">
            Apps can report structured configuration data (serial numbers, CPU/RAM info, module inventory, etc.)
            that will be displayed here once implemented.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Monitoring Config Card ────────────────────────────────

const APP_TYPE_OPTIONS = [
  { value: "", label: "None" },
  { value: "ping_check", label: "Ping (ICMP)" },
  { value: "port_check", label: "Port Check (TCP)" },
  { value: "snmp_check", label: "SNMP" },
];

const INTERVAL_OPTIONS = [
  { value: "30", label: "30 seconds" },
  { value: "60", label: "60 seconds" },
  { value: "120", label: "2 minutes" },
  { value: "300", label: "5 minutes" },
];

function MonitoringCard({ deviceId, device }: { deviceId: string; device: DeviceType | undefined }) {
  const { data: monitoring, isLoading: monLoading } = useDeviceMonitoring(deviceId);
  const { data: snmpOids } = useSnmpOids();
  const { data: credentials } = useCredentials();
  const updateMonitoring = useUpdateDeviceMonitoring();

  const [availabilityAppType, setAvailabilityAppType] = useState("");
  const [availabilityPort, setAvailabilityPort] = useState("");
  const [availabilityOid, setAvailabilityOid] = useState("");
  const [availabilityCredential, setAvailabilityCredential] = useState("");
  const [latencyAppType, setLatencyAppType] = useState("");
  const [latencyPort, setLatencyPort] = useState("");
  const [latencyOid, setLatencyOid] = useState("");
  const [latencyCredential, setLatencyCredential] = useState("");
  const [intervalSeconds, setIntervalSeconds] = useState("60");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Sync state when monitoring data loads
  useEffect(() => {
    if (!monitoring) return;
    const av = monitoring.availability;
    const la = monitoring.latency;
    setAvailabilityAppType(av?.app_type ?? "");
    setAvailabilityPort(av?.port != null ? String(av.port) : "");
    setAvailabilityOid(av?.oid ?? "");
    setAvailabilityCredential(av?.credential_name ?? "");
    setLatencyAppType(la?.app_type ?? "");
    setLatencyPort(la?.port != null ? String(la.port) : "");
    setLatencyOid(la?.oid ?? "");
    setLatencyCredential(la?.credential_name ?? "");
    // Use the interval from availability if set, otherwise latency, otherwise default
    const interval = av?.interval_seconds ?? la?.interval_seconds ?? 60;
    setIntervalSeconds(String(interval));
  }, [monitoring]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaveError(null);
    setSaveSuccess(false);

    const makeCheck = (appType: string, port: string, oid: string, cred: string) => {
      if (!appType) return null;
      return {
        app_type: appType,
        port: appType === "port_check" && port ? parseInt(port, 10) : null,
        oid: appType === "snmp_check" ? oid || null : null,
        credential_name: appType === "snmp_check" ? cred || null : null,
        interval_seconds: parseInt(intervalSeconds, 10),
      };
    };

    try {
      await updateMonitoring.mutateAsync({
        id: deviceId,
        data: {
          availability: makeCheck(availabilityAppType, availabilityPort, availabilityOid, availabilityCredential),
          latency: makeCheck(latencyAppType, latencyPort, latencyOid, latencyCredential),
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
          <form onSubmit={handleSave} className="space-y-5 max-w-md">
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
            <div className="space-y-3">
              <Label>Availability Check</Label>
              <Select
                value={availabilityAppType}
                onChange={(e) => setAvailabilityAppType(e.target.value)}
                disabled={!hasGroup}
              >
                {APP_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
              {availabilityAppType === "port_check" && (
                <div className="space-y-1.5">
                  <Label htmlFor="av-port">TCP Port</Label>
                  <Input
                    id="av-port"
                    type="number"
                    min={1}
                    max={65535}
                    placeholder="e.g. 22, 80, 443"
                    value={availabilityPort}
                    onChange={(e) => setAvailabilityPort(e.target.value)}
                  />
                </div>
              )}
              {availabilityAppType === "snmp_check" && (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="av-oid">SNMP OID</Label>
                    <Select
                      id="av-oid"
                      value={availabilityOid}
                      onChange={(e) => setAvailabilityOid(e.target.value)}
                    >
                      <option value="">— Select OID —</option>
                      {(snmpOids ?? []).map((o) => (
                        <option key={o.id} value={o.oid}>{o.name} ({o.oid})</option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="av-cred">SNMP Credential</Label>
                    <Select
                      id="av-cred"
                      value={availabilityCredential}
                      onChange={(e) => setAvailabilityCredential(e.target.value)}
                    >
                      <option value="">— Select credential —</option>
                      {(credentials ?? [])
                        .filter((c) => c.credential_type.startsWith("snmp"))
                        .map((c) => (
                          <option key={c.id} value={c.name}>{c.name}</option>
                        ))}
                    </Select>
                  </div>
                </div>
              )}
            </div>

            {/* Latency check */}
            <div className="space-y-3">
              <Label>Latency Check</Label>
              <Select
                value={latencyAppType}
                onChange={(e) => setLatencyAppType(e.target.value)}
                disabled={!hasGroup}
              >
                {APP_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
              {latencyAppType === "port_check" && (
                <div className="space-y-1.5">
                  <Label htmlFor="la-port">TCP Port</Label>
                  <Input
                    id="la-port"
                    type="number"
                    min={1}
                    max={65535}
                    placeholder="e.g. 22, 80, 443"
                    value={latencyPort}
                    onChange={(e) => setLatencyPort(e.target.value)}
                  />
                </div>
              )}
              {latencyAppType === "snmp_check" && (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="la-oid">SNMP OID</Label>
                    <Select
                      id="la-oid"
                      value={latencyOid}
                      onChange={(e) => setLatencyOid(e.target.value)}
                    >
                      <option value="">— Select OID —</option>
                      {(snmpOids ?? []).map((o) => (
                        <option key={o.id} value={o.oid}>{o.name} ({o.oid})</option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="la-cred">SNMP Credential</Label>
                    <Select
                      id="la-cred"
                      value={latencyCredential}
                      onChange={(e) => setLatencyCredential(e.target.value)}
                    >
                      <option value="">— Select credential —</option>
                      {(credentials ?? [])
                        .filter((c) => c.credential_type.startsWith("snmp"))
                        .map((c) => (
                          <option key={c.id} value={c.name}>{c.name}</option>
                        ))}
                    </Select>
                  </div>
                </div>
              )}
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

// ── Tab 4: Settings ──────────────────────────────────────

function SettingsTab({ deviceId }: { deviceId: string }) {
  const { data: device, isLoading: deviceLoading } = useDevice(deviceId);
  const { data: deviceTypes } = useDeviceTypes();
  const { data: tenants } = useTenants();
  const { data: collectorGroups } = useCollectorGroups();
  const { data: assignments } = useDeviceAssignments(deviceId);
  const deleteAssignment = useDeleteAssignment();
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
  const [newLabelKey, setNewLabelKey] = useState("");
  const [newLabelValue, setNewLabelValue] = useState("");
  const [labelError, setLabelError] = useState<string | null>(null);

  // Assignment dialogs
  const [addOpen, setAddOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

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

  function handleAddLabel() {
    setLabelError(null);
    const key = newLabelKey.trim();
    const val = newLabelValue.trim();
    if (!key) {
      setLabelError("Label key cannot be empty.");
      return;
    }
    setLabels((prev) => ({ ...prev, [key]: val }));
    setNewLabelKey("");
    setNewLabelValue("");
  }

  function handleRemoveLabel(key: string) {
    setLabels((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  async function handleDeleteAssignment() {
    if (!deleteTarget) return;
    try {
      await deleteAssignment.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      // silently ignore
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
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 max-w-md">
            {/* Existing labels */}
            {Object.keys(labels).length > 0 ? (
              <div className="rounded-md border border-zinc-800 divide-y divide-zinc-800">
                {Object.entries(labels).map(([key, val]) => (
                  <div key={key} className="flex items-center gap-2 px-3 py-2">
                    <span className="text-xs font-mono text-zinc-300 flex-1">
                      <span className="text-zinc-400">{key}</span>
                      <span className="text-zinc-600 mx-1">=</span>
                      <span className="text-zinc-200">{val}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => handleRemoveLabel(key)}
                      className="rounded p-0.5 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                      title={`Remove label "${key}"`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-zinc-600">No labels set.</p>
            )}

            {/* Add new label row */}
            <div className="flex items-center gap-2">
              <Input
                placeholder="key"
                value={newLabelKey}
                onChange={(e) => setNewLabelKey(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAddLabel(); } }}
                className="flex-1 font-mono text-xs"
              />
              <Input
                placeholder="value"
                value={newLabelValue}
                onChange={(e) => setNewLabelValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAddLabel(); } }}
                className="flex-1 font-mono text-xs"
              />
              <Button type="button" size="sm" variant="secondary" onClick={handleAddLabel}>
                <Plus className="h-3.5 w-3.5" />
                Add
              </Button>
            </div>
            {labelError && <p className="text-xs text-red-400">{labelError}</p>}

            <p className="text-xs text-zinc-600">
              Labels are saved along with device settings. Click "Save Changes" above to persist.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Monitoring Configuration */}
      <MonitoringCard deviceId={deviceId} device={device} />

      {/* Assigned Apps */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Assigned Apps
            <Button
              size="sm"
              variant="secondary"
              className="ml-auto gap-1.5"
              onClick={() => setAddOpen(true)}
            >
              <Plus className="h-4 w-4" />
              Add App
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!assignments || assignments.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-zinc-600">
              <p className="text-sm">No apps assigned to this device.</p>
              <Button
                size="sm"
                variant="secondary"
                className="mt-3 gap-1.5"
                onClick={() => setAddOpen(true)}
              >
                <Plus className="h-4 w-4" />
                Assign first app
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>App</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Schedule</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-12"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {assignments.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium text-zinc-200">{a.app.name}</TableCell>
                    <TableCell className="text-zinc-500 font-mono text-xs">{a.app.version}</TableCell>
                    <TableCell className="text-zinc-400 text-sm">{a.schedule_human}</TableCell>
                    <TableCell>
                      <Badge variant={a.enabled ? "success" : "default"}>
                        {a.enabled ? "enabled" : "disabled"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <button
                        onClick={() => setDeleteTarget({ id: a.id, name: a.app.name })}
                        className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                        title="Remove"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <AddAssignmentDialog
        deviceId={deviceId}
        deviceCollectorGroupId={device?.collector_group_id ?? null}
        deviceCollectorGroupName={device?.collector_group_name ?? null}
        open={addOpen}
        onClose={() => setAddOpen(false)}
      />

      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Remove App Assignment"
      >
        <p className="text-sm text-zinc-400">
          Remove{" "}
          <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>
          {" "}from this device? The app will stop running on the next collector heartbeat.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button
            variant="destructive"
            onClick={handleDeleteAssignment}
            disabled={deleteAssignment.isPending}
          >
            {deleteAssignment.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Remove
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────

export function DeviceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: deviceResults, isLoading } = useDeviceResults(id);
  const { data: device } = useDevice(id);
  const { data: collectors } = useCollectors();
  const [activeTab, setActiveTab] = useState("overview");

  // Resolve the active collector name from the most recent check result
  const activeCollectorId = deviceResults?.checks?.[0]?.collector_id ?? null;
  const activeCollectorName = activeCollectorId
    ? (collectors?.find((c) => c.id === activeCollectorId)?.name ?? null)
    : null;

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!deviceResults) {
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
          <p className="text-sm">Device not found or no data available</p>
        </div>
      </div>
    );
  }

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
            {deviceResults.device_name}
          </h2>
          <Badge
            variant={
              deviceResults.up === true
                ? "success"
                : deviceResults.up === false
                  ? "destructive"
                  : "default"
            }
          >
            {deviceResults.up === true ? "UP" : deviceResults.up === false ? "DOWN" : "UNKNOWN"}
          </Badge>
        </div>
        <div className="flex items-center gap-3 text-sm text-zinc-500">
          <span className="font-mono">{deviceResults.device_address}</span>
          <Badge variant="info">{deviceResults.device_type}</Badge>
          {device?.tenant_name && (
            <span className="text-xs text-zinc-500">
              tenant: <span className="text-zinc-300">{device.tenant_name}</span>
            </span>
          )}
          {device?.collector_group_name && (
            <span className="text-xs text-zinc-500">
              collector group: <span className="text-zinc-300">{device.collector_group_name}</span>
              {activeCollectorName && (
                <span className="text-zinc-500"> via <span className="text-zinc-300">{activeCollectorName}</span></span>
              )}
            </span>
          )}
          {!device?.collector_group_name && activeCollectorName && (
            <span className="text-xs text-zinc-500">
              via <span className="text-zinc-300">{activeCollectorName}</span>
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
          <TabTrigger value="configuration">
            <span className="flex items-center gap-1.5">
              <Wrench className="h-3.5 w-3.5" />
              Configuration
            </span>
          </TabTrigger>
          <TabTrigger value="settings">
            <span className="flex items-center gap-1.5">
              <Settings2 className="h-3.5 w-3.5" />
              Settings
            </span>
          </TabTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab deviceId={deviceResults.device_id} />
        </TabsContent>
        <TabsContent value="performance">
          <PerformanceTab deviceId={deviceResults.device_id} />
        </TabsContent>
        <TabsContent value="configuration">
          <ConfigurationTab />
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab deviceId={deviceResults.device_id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
