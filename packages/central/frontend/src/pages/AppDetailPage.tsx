import { useState, useCallback, useMemo, Fragment } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { formatDate, timeAgo } from "@/lib/utils.ts";
import {
  validateName,
  validateSemver,
  validateAlertWindow,
} from "@/lib/validation.ts";
import {
  ArrowLeft,
  AppWindow,
  Bell,
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  Copy,
  Layout,
  Loader2,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
  SlidersHorizontal,
  Star,
  Trash2,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Badge } from "@/components/ui/badge.tsx";
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
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { CodeEditor } from "@/components/CodeEditor.tsx";
import { DisplayTemplateEditor } from "@/components/DisplayTemplateEditor.tsx";
import { ModulePicker } from "@/components/ModulePicker.tsx";
import { VersionActions } from "@/components/VersionActions.tsx";
import {
  useAppDetail,
  useUpdateApp,
  useCreateAppVersion,
  useSetLatestVersion,
  useUpdateAppVersion,
  useDeleteAppVersion,
  useCloneAppVersion,
  useAlertDefinitions,
  useAlertMetrics,
  useCreateAlertDefinition,
  useDeleteAlertDefinition,
  useUpdateAlertDefinition,
  useInvertAlertDefinition,
  useDeleteAppConnector,
  useAssignConnectorToSlot,
  useConnectorDetail,
  useConnectors,
  useAppConfigKeys,
  useAppThresholds,
  useUpdateThresholdVariable,
  useCreateThresholdVariable,
  useDeleteThresholdVariable,
  useStartEligibilityTest,
  useEligibilityRuns,
  useEligibilityRunDetail,
  useAutoAssignEligible,
} from "@/api/hooks.ts";
import { apiGet } from "@/api/client.ts";
import type {
  AppAlertDefinition,
  DisplayTemplate,
  EligibilityOidCheck,
} from "@/types/api.ts";
import { X } from "lucide-react";
import { Select } from "@/components/ui/select.tsx";

interface VersionDetail {
  id: string;
  version: string;
  source_code: string | null;
  requirements: string[];
  entry_class: string | null;
  checksum: string;
  published_at: string | null;
  display_template: DisplayTemplate | null;
  volatile_keys?: string[];
  eligibility_oids?: EligibilityOidCheck[];
}

export function AppDetailPage() {
  const { id } = useParams<{ id: string }>();
  const tz = useTimezone();
  const { data: app, isLoading } = useAppDetail(id);
  const updateApp = useUpdateApp();
  const createVersion = useCreateAppVersion();
  const setLatest = useSetLatestVersion();
  const updateVersion = useUpdateAppVersion();
  const deleteVersion = useDeleteAppVersion();
  const cloneVersion = useCloneAppVersion();

  const [activeTab, setActiveTab] = useState("overview");
  const isConfigApp = app?.target_table === "config";

  // Edit app state
  const [editOpen, setEditOpen] = useState(false);
  const editNameField = useField("", validateName);
  const [editDesc, setEditDesc] = useState("");
  const [editConfigSchema, setEditConfigSchema] = useState("");
  const [editVendorPrefix, setEditVendorPrefix] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  // New version state
  const [versionOpen, setVersionOpen] = useState(false);
  const versionField = useField("", validateSemver);
  const [versionCode, setVersionCode] = useState(
    "# New monitoring app\n\nclass MyCheck:\n    def run(self, config):\n        pass\n",
  );
  const [versionReqs, setVersionReqs] = useState("");
  const [versionEntry, setVersionEntry] = useState("");
  const [versionError, setVersionError] = useState<string | null>(null);
  const [newVersionTab, setNewVersionTab] = useState("code");
  const [newVersionTemplate, setNewVersionTemplate] =
    useState<DisplayTemplate | null>(null);
  const [versionVolatileKeys, setVersionVolatileKeys] = useState<string[]>([]);
  const [versionEligibilityOids, setVersionEligibilityOids] = useState<
    EligibilityOidCheck[]
  >([]);

  // Version detail viewer
  const [viewVersion, setViewVersion] = useState<VersionDetail | null>(null);
  const [loadingVersion, setLoadingVersion] = useState(false);

  // Edit version state
  const [editVersionTarget, setEditVersionTarget] =
    useState<VersionDetail | null>(null);
  const [editVersionCode, setEditVersionCode] = useState("");
  const [editVersionReqs, setEditVersionReqs] = useState("");
  const [editVersionEntry, setEditVersionEntry] = useState("");
  const [editVersionError, setEditVersionError] = useState<string | null>(null);
  const [editVersionVolatileKeys, setEditVersionVolatileKeys] = useState<
    string[]
  >([]);
  const [editVersionEligibilityOids, setEditVersionEligibilityOids] = useState<
    EligibilityOidCheck[]
  >([]);

  // Version dialog tab (for config apps)
  const [viewDialogTab, setViewDialogTab] = useState("code");
  const [editDialogTab, setEditDialogTab] = useState("code");

  // Delete version state
  const [deleteVersionTarget, setDeleteVersionTarget] = useState<{
    id: string;
    version: string;
  } | null>(null);
  const [deleteVersionError, setDeleteVersionError] = useState<string | null>(
    null,
  );

  // Connector binding state — slots are declared by the Poller source
  // (``required_connectors``) and pre-created on version upload. The
  // operator only picks which concrete Connector fills each slot.
  const assignConnector = useAssignConnectorToSlot();
  const deleteConnector = useDeleteAppConnector();
  const { data: connectorsResp } = useConnectors();
  const connectorsList = connectorsResp?.data ?? [];
  const [slotAssignError, setSlotAssignError] = useState<
    Record<string, string>
  >({});

  // Eligibility tab state
  const startEligTest = useStartEligibilityTest();
  const eligRunsQuery = useEligibilityRuns(id);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [eligFilter, setEligFilter] = useState<number | undefined>(undefined);
  const [eligPage, setEligPage] = useState(1);
  const eligDetailQuery = useEligibilityRunDetail(
    id,
    expandedRunId ?? undefined,
    eligFilter,
    eligPage,
  );
  const autoAssign = useAutoAssignEligible();

  async function handleEditApp(e: React.FormEvent) {
    e.preventDefault();
    if (!id) return;
    setEditError(null);
    if (!validateAll(editNameField)) return;
    let parsedSchema: Record<string, unknown> | undefined;
    if (editConfigSchema.trim()) {
      try {
        parsedSchema = JSON.parse(editConfigSchema.trim());
      } catch {
        setEditError("Config Schema is not valid JSON.");
        return;
      }
    }
    try {
      await updateApp.mutateAsync({
        id,
        data: {
          name: editNameField.value.trim(),
          description: editDesc.trim(),
          config_schema: parsedSchema ?? {},
          vendor_oid_prefix: editVendorPrefix.trim() || null,
        },
      });
      setEditOpen(false);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update");
    }
  }

  async function handleCreateVersion(e: React.FormEvent) {
    e.preventDefault();
    if (!id) return;
    setVersionError(null);
    if (!validateAll(versionField)) return;
    if (!versionCode.trim()) {
      setVersionError("Source code is required.");
      return;
    }
    try {
      await createVersion.mutateAsync({
        appId: id,
        data: {
          version: versionField.value.trim(),
          source_code: versionCode,
          requirements: versionReqs.trim()
            ? versionReqs
                .trim()
                .split("\n")
                .map((r) => r.trim())
                .filter(Boolean)
            : [],
          entry_class: versionEntry.trim() || undefined,
          display_template: newVersionTemplate ?? undefined,
          volatile_keys: isConfigApp ? versionVolatileKeys : undefined,
          eligibility_oids:
            versionEligibilityOids.length > 0
              ? versionEligibilityOids
              : undefined,
        },
      });
      versionField.reset();
      setVersionCode("");
      setVersionReqs("");
      setVersionEntry("");
      setNewVersionTemplate(null);
      setVersionVolatileKeys([]);
      setNewVersionTab("code");
      setVersionOpen(false);
    } catch (err) {
      setVersionError(
        err instanceof Error ? err.message : "Failed to create version",
      );
    }
  }

  async function handleEditVersion(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !editVersionTarget) return;
    setEditVersionError(null);
    try {
      await updateVersion.mutateAsync({
        appId: id,
        versionId: editVersionTarget.id,
        data: {
          source_code: editVersionCode,
          requirements: editVersionReqs.trim()
            ? editVersionReqs
                .trim()
                .split("\n")
                .map((r) => r.trim())
                .filter(Boolean)
            : [],
          entry_class: editVersionEntry.trim() || undefined,
          volatile_keys: isConfigApp ? editVersionVolatileKeys : undefined,
          eligibility_oids:
            editVersionEligibilityOids.length > 0
              ? editVersionEligibilityOids
              : [],
        },
      });
      setEditVersionTarget(null);
    } catch (err) {
      setEditVersionError(
        err instanceof Error ? err.message : "Failed to update version",
      );
    }
  }

  async function handleDeleteVersion() {
    if (!id || !deleteVersionTarget) return;
    setDeleteVersionError(null);
    try {
      await deleteVersion.mutateAsync({
        appId: id,
        versionId: deleteVersionTarget.id,
      });
      setDeleteVersionTarget(null);
    } catch (err) {
      setDeleteVersionError(
        err instanceof Error ? err.message : "Failed to delete version",
      );
    }
  }

  async function handleCloneVersion(versionId: string) {
    if (!id) return;
    try {
      await cloneVersion.mutateAsync({ appId: id, versionId });
    } catch {
      /* handled by React Query */
    }
  }

  async function openEditVersion(versionId: string) {
    if (!id) return;
    setLoadingVersion(true);
    setEditDialogTab("code");
    try {
      const res = await apiGet<VersionDetail>(
        `/apps/${id}/versions/${versionId}`,
      );
      const v = res.data;
      setEditVersionCode(v.source_code ?? "");
      setEditVersionReqs((v.requirements ?? []).join("\n"));
      setEditVersionEntry(v.entry_class ?? "");
      setEditVersionError(null);
      setEditVersionVolatileKeys(v.volatile_keys ?? []);
      setEditVersionEligibilityOids(v.eligibility_oids ?? []);
      setEditVersionTarget(v);
    } catch {
      // silent
    } finally {
      setLoadingVersion(false);
    }
  }

  async function loadVersion(versionId: string) {
    if (!id) return;
    setLoadingVersion(true);
    setViewDialogTab("code");
    try {
      const res = await apiGet<VersionDetail>(
        `/apps/${id}/versions/${versionId}`,
      );
      setViewVersion(res.data);
    } catch {
      // silent
    } finally {
      setLoadingVersion(false);
    }
  }

  const handleSaveDisplayTemplate = useCallback(
    async (versionId: string, template: DisplayTemplate) => {
      if (!id) return;
      await updateVersion.mutateAsync({
        appId: id,
        versionId,
        data: { display_template: template },
      });
      // Refresh view version data
      try {
        const res = await apiGet<VersionDetail>(
          `/apps/${id}/versions/${versionId}`,
        );
        setViewVersion(res.data);
      } catch {
        // silent
      }
    },
    [id, updateVersion],
  );

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!app) {
    return (
      <div className="space-y-4">
        <Link to="/apps">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4" /> Back to Apps
          </Button>
        </Link>
        <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
          <AppWindow className="mb-2 h-8 w-8 text-zinc-600" />
          <p className="text-sm">App not found</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="space-y-1.5">
        <Link to="/apps">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4" /> Back to Apps
          </Button>
        </Link>
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold text-zinc-100">{app.name}</h2>
          <Badge variant="info">{app.app_type}</Badge>
          <button
            onClick={() => {
              editNameField.reset(app.name);
              setEditDesc(app.description ?? "");
              setEditConfigSchema(
                app.config_schema
                  ? JSON.stringify(app.config_schema, null, 2)
                  : "",
              );
              setEditVendorPrefix(app.vendor_oid_prefix ?? "");
              setEditError(null);
              setEditOpen(true);
            }}
            className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
            title="Edit"
          >
            <Pencil className="h-4 w-4" />
          </button>
        </div>
        {app.description && (
          <p className="text-sm text-zinc-400">{app.description}</p>
        )}
      </div>

      <Tabs value={activeTab} onChange={setActiveTab}>
        <TabsList>
          <TabTrigger value="overview">Overview</TabTrigger>
          <TabTrigger value="versions">
            Versions ({app.versions.length})
          </TabTrigger>
          <TabTrigger value="alerts">Alerts</TabTrigger>
          <TabTrigger value="thresholds">Thresholds</TabTrigger>
          <TabTrigger value="eligibility">Eligibility</TabTrigger>
        </TabsList>

        <TabsContent value="overview">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <AppWindow className="h-4 w-4" /> App Details
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3 max-w-md">
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Name</span>
                  <span className="font-mono text-sm text-zinc-100">
                    {app.name}
                  </span>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Type</span>
                  <Badge variant="info">{app.app_type}</Badge>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Target Table</span>
                  <Badge variant="default" className="font-mono text-xs">
                    {app.target_table}
                  </Badge>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Versions</span>
                  <span className="text-sm text-zinc-100">
                    {app.versions.length}
                  </span>
                </div>
                {app.config_schema && (
                  <div className="rounded-md bg-zinc-800/50 px-4 py-3">
                    <span className="text-sm text-zinc-400 block mb-1">
                      Config Schema
                    </span>
                    <pre className="text-xs font-mono text-zinc-300 whitespace-pre-wrap">
                      {JSON.stringify(app.config_schema, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Required Connectors — slot-driven */}
          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Plug className="h-4 w-4" /> Required Connectors
              </CardTitle>
            </CardHeader>
            <CardContent>
              {app.connector_bindings && app.connector_bindings.length > 0 ? (
                <>
                  <p className="text-xs text-zinc-500 mb-3">
                    Slots declared by the app's Poller code (
                    <code className="text-zinc-400">required_connectors</code>).
                    Pick which concrete connector fills each slot.
                  </p>
                  <div className="space-y-2">
                    {app.connector_bindings.map((cb) => {
                      const matching = connectorsList.filter(
                        (c) => c.connector_type === cb.connector_type,
                      );
                      const err = slotAssignError[cb.connector_type];
                      if (cb.is_orphaned) {
                        return (
                          <div
                            key={cb.connector_type}
                            className="flex items-center justify-between rounded-md border border-amber-900/50 bg-amber-950/20 px-4 py-3"
                          >
                            <div className="flex items-center gap-3">
                              <Badge variant="warning" className="text-xs">
                                orphaned
                              </Badge>
                              <code className="text-xs text-zinc-300 bg-zinc-900 px-1.5 py-0.5 rounded">
                                {cb.connector_type}
                              </code>
                              <span className="text-xs text-zinc-500">
                                No longer declared by the current app version.
                              </span>
                            </div>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 px-2 text-zinc-500 hover:text-red-400"
                              onClick={() => {
                                if (id)
                                  deleteConnector.mutate({
                                    appId: id,
                                    connectorType: cb.connector_type,
                                  });
                              }}
                            >
                              <Trash2 className="h-3 w-3 mr-1" /> Remove
                            </Button>
                          </div>
                        );
                      }
                      return (
                        <div
                          key={cb.connector_type}
                          className="rounded-md bg-zinc-800/50 px-4 py-3 space-y-2"
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-zinc-500">type:</span>
                            <Badge variant="default" className="text-xs">
                              {cb.connector_type}
                            </Badge>
                            {cb.connector_id ? (
                              <Badge
                                variant="success"
                                className="text-xs ml-auto"
                              >
                                <Check className="h-2.5 w-2.5 mr-0.5" />
                                configured
                              </Badge>
                            ) : (
                              <Badge
                                variant="warning"
                                className="text-xs ml-auto"
                              >
                                needs connector
                              </Badge>
                            )}
                          </div>
                          <select
                            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100"
                            value={cb.connector_id ?? ""}
                            disabled={assignConnector.isPending}
                            onChange={(e) => {
                              const connectorId = e.target.value;
                              if (!id || !connectorId) return;
                              setSlotAssignError((prev) => {
                                const next = { ...prev };
                                delete next[cb.connector_type];
                                return next;
                              });
                              assignConnector.mutate(
                                {
                                  appId: id,
                                  connectorType: cb.connector_type,
                                  data: {
                                    connector_id: connectorId,
                                    connector_version_id: null,
                                  },
                                },
                                {
                                  onError: (mutErr: unknown) =>
                                    setSlotAssignError((prev) => ({
                                      ...prev,
                                      [cb.connector_type]:
                                        mutErr instanceof Error
                                          ? mutErr.message
                                          : String(mutErr),
                                    })),
                                },
                              );
                            }}
                          >
                            <option value="">
                              — Select a {cb.connector_type} connector —
                            </option>
                            {matching.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                                {c.description ? ` — ${c.description}` : ""}
                              </option>
                            ))}
                          </select>
                          {cb.connector_id && (
                            <SlotVersionPicker
                              connectorId={cb.connector_id}
                              versionId={cb.connector_version_id}
                              disabled={assignConnector.isPending}
                              onChange={(newVersionId) => {
                                if (!id || !cb.connector_id) return;
                                setSlotAssignError((prev) => {
                                  const next = { ...prev };
                                  delete next[cb.connector_type];
                                  return next;
                                });
                                assignConnector.mutate(
                                  {
                                    appId: id,
                                    connectorType: cb.connector_type,
                                    data: {
                                      connector_id: cb.connector_id,
                                      connector_version_id: newVersionId,
                                    },
                                  },
                                  {
                                    onError: (mutErr: unknown) =>
                                      setSlotAssignError((prev) => ({
                                        ...prev,
                                        [cb.connector_type]:
                                          mutErr instanceof Error
                                            ? mutErr.message
                                            : String(mutErr),
                                      })),
                                  },
                                );
                              }}
                            />
                          )}
                          {err && <p className="text-xs text-red-400">{err}</p>}
                        </div>
                      );
                    })}
                  </div>
                </>
              ) : (
                <p className="text-sm text-zinc-500">
                  This app declares no connector requirements. Upload a version
                  whose Poller class sets{" "}
                  <code className="text-zinc-400">required_connectors</code> to
                  add slots.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="versions">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Code2 className="h-4 w-4" /> Versions
                <Button
                  size="sm"
                  variant="secondary"
                  className="ml-auto gap-1.5"
                  onClick={() => {
                    versionField.reset();
                    setVersionCode("# New version\n");
                    setVersionReqs("");
                    setVersionEntry("");
                    setVersionError(null);
                    setNewVersionTab("code");
                    setNewVersionTemplate(null);
                    setVersionOpen(true);
                  }}
                >
                  <Plus className="h-4 w-4" /> New Version
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {app.versions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 text-zinc-500">
                  <Code2 className="mb-2 h-8 w-8 text-zinc-600" />
                  <p className="text-sm">No versions yet</p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Version</TableHead>
                      <TableHead>ID</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Published</TableHead>
                      <TableHead className="w-36"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {app.versions.map((v) => (
                      <TableRow key={v.id}>
                        <TableCell className="font-mono text-sm text-zinc-100">
                          {v.version}
                        </TableCell>
                        <TableCell className="font-mono text-xs text-zinc-500">
                          {v.id.slice(0, 8)}
                        </TableCell>
                        <TableCell>
                          {v.is_latest && (
                            <Badge variant="info" className="gap-1">
                              <Star className="h-3 w-3" /> Latest
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell
                          className="text-zinc-500 text-xs whitespace-nowrap"
                          title={
                            v.published_at ? formatDate(v.published_at, tz) : ""
                          }
                        >
                          {v.published_at ? timeAgo(v.published_at) : "—"}
                        </TableCell>
                        <TableCell>
                          <VersionActions
                            isLatest={v.is_latest}
                            onSetLatest={() =>
                              id &&
                              setLatest.mutate({ appId: id, versionId: v.id })
                            }
                            onView={() => loadVersion(v.id)}
                            onEdit={() => openEditVersion(v.id)}
                            onClone={() => handleCloneVersion(v.id)}
                            onDelete={() =>
                              setDeleteVersionTarget({
                                id: v.id,
                                version: v.version,
                              })
                            }
                            disabled={
                              loadingVersion ||
                              setLatest.isPending ||
                              cloneVersion.isPending
                            }
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="alerts">
          <AlertsTab appId={id!} app={app} />
        </TabsContent>

        <TabsContent value="thresholds">
          <ThresholdsTab appId={id!} />
        </TabsContent>
        <TabsContent value="eligibility">
          <EligibilityTab
            appId={id!}
            startTest={startEligTest}
            runsQuery={eligRunsQuery}
            expandedRunId={expandedRunId}
            setExpandedRunId={(rid) => {
              setExpandedRunId(rid);
              setEligFilter(undefined);
              setEligPage(1);
            }}
            detailQuery={eligDetailQuery}
            eligFilter={eligFilter}
            setEligFilter={(f) => {
              setEligFilter(f);
              setEligPage(1);
            }}
            eligPage={eligPage}
            setEligPage={setEligPage}
            autoAssign={autoAssign}
            appId2={id!}
          />
        </TabsContent>
      </Tabs>

      {/* Edit App Dialog */}
      <Dialog
        open={editOpen}
        onClose={() => setEditOpen(false)}
        title="Edit App"
      >
        <form onSubmit={handleEditApp} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="app-edit-name">Name</Label>
            <Input
              id="app-edit-name"
              value={editNameField.value}
              onChange={editNameField.onChange}
              onBlur={editNameField.onBlur}
              autoFocus
            />
            {editNameField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {editNameField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-edit-desc">Description</Label>
            <Input
              id="app-edit-desc"
              value={editDesc}
              onChange={(e) => setEditDesc(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-edit-schema">
              Config Schema{" "}
              <span className="font-normal text-zinc-500">
                (JSON, optional)
              </span>
            </Label>
            <textarea
              id="app-edit-schema"
              value={editConfigSchema}
              onChange={(e) => setEditConfigSchema(e.target.value)}
              placeholder='{"type": "object", "properties": { ... }}'
              rows={6}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 placeholder:text-zinc-600"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-edit-vendor">Vendor OID Prefix</Label>
            <p className="text-[11px] text-zinc-500">
              If set, auto-assign only to devices matching this sysObjectID
              prefix. Common: 1.3.6.1.4.1.9 (Cisco), 1.3.6.1.4.1.2636 (Juniper)
            </p>
            <Input
              id="app-edit-vendor"
              placeholder="1.3.6.1.4.1.9"
              value={editVendorPrefix}
              onChange={(e) => setEditVendorPrefix(e.target.value)}
            />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setEditOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={updateApp.isPending}>
              {updateApp.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}{" "}
              Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* New Version Dialog */}
      <Dialog
        open={versionOpen}
        onClose={() => setVersionOpen(false)}
        title="New Version"
        size="fullscreen"
      >
        {isConfigApp ? (
          <Tabs value={newVersionTab} onChange={setNewVersionTab}>
            <TabsList>
              <TabTrigger value="code">
                <span className="flex items-center gap-1.5">
                  <Code2 className="h-3.5 w-3.5" /> Code
                </span>
              </TabTrigger>
              <TabTrigger value="template">
                <span className="flex items-center gap-1.5">
                  <Layout className="h-3.5 w-3.5" /> Display Template
                </span>
              </TabTrigger>
            </TabsList>
            <TabsContent value="code">
              <NewVersionCodeForm
                versionField={versionField}
                versionCode={versionCode}
                setVersionCode={setVersionCode}
                versionReqs={versionReqs}
                setVersionReqs={setVersionReqs}
                versionEntry={versionEntry}
                setVersionEntry={setVersionEntry}
                versionError={versionError}
                onSubmit={handleCreateVersion}
                onCancel={() => setVersionOpen(false)}
                isPending={createVersion.isPending}
                volatileKeys={versionVolatileKeys}
                setVolatileKeys={setVersionVolatileKeys}
                eligibilityOids={versionEligibilityOids}
                setEligibilityOids={setVersionEligibilityOids}
                isConfigApp={true}
                appId={id!}
              />
            </TabsContent>
            <TabsContent value="template">
              <DisplayTemplateEditor
                appId={id!}
                initialTemplate={newVersionTemplate}
                onSave={async (tpl) => {
                  setNewVersionTemplate(tpl);
                  setNewVersionTab("code");
                }}
              />
            </TabsContent>
          </Tabs>
        ) : (
          <NewVersionCodeForm
            versionField={versionField}
            versionCode={versionCode}
            setVersionCode={setVersionCode}
            versionReqs={versionReqs}
            setVersionReqs={setVersionReqs}
            versionEntry={versionEntry}
            setVersionEntry={setVersionEntry}
            versionError={versionError}
            onSubmit={handleCreateVersion}
            onCancel={() => setVersionOpen(false)}
            isPending={createVersion.isPending}
            eligibilityOids={versionEligibilityOids}
            setEligibilityOids={setVersionEligibilityOids}
          />
        )}
      </Dialog>

      {/* View Version Dialog */}
      <Dialog
        open={!!viewVersion}
        onClose={() => setViewVersion(null)}
        title={`Version ${viewVersion?.version ?? ""}`}
        size="fullscreen"
      >
        {viewVersion &&
          (isConfigApp ? (
            <Tabs value={viewDialogTab} onChange={setViewDialogTab}>
              <TabsList>
                <TabTrigger value="code">
                  <span className="flex items-center gap-1.5">
                    <Code2 className="h-3.5 w-3.5" /> Code
                  </span>
                </TabTrigger>
                <TabTrigger value="template">
                  <span className="flex items-center gap-1.5">
                    <Layout className="h-3.5 w-3.5" /> Display Template
                  </span>
                </TabTrigger>
              </TabsList>
              <TabsContent value="code">
                <VersionCodeView version={viewVersion} />
              </TabsContent>
              <TabsContent value="template">
                <DisplayTemplateEditor
                  appId={id!}
                  versionId={viewVersion.id}
                  initialTemplate={viewVersion.display_template}
                  onSave={(tpl) =>
                    handleSaveDisplayTemplate(viewVersion.id, tpl)
                  }
                />
              </TabsContent>
            </Tabs>
          ) : (
            <VersionCodeView version={viewVersion} />
          ))}
        <DialogFooter>
          <Button
            size="sm"
            variant="secondary"
            className="gap-1.5"
            disabled={cloneVersion.isPending}
            onClick={() => {
              if (viewVersion) {
                handleCloneVersion(viewVersion.id);
                setViewVersion(null);
              }
            }}
          >
            <Copy className="h-4 w-4" /> Clone
          </Button>
          <Button variant="secondary" onClick={() => setViewVersion(null)}>
            Close
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Edit Version Dialog */}
      <Dialog
        open={!!editVersionTarget}
        onClose={() => setEditVersionTarget(null)}
        title={`Edit Version ${editVersionTarget?.version ?? ""}`}
        size="fullscreen"
      >
        {isConfigApp ? (
          <Tabs value={editDialogTab} onChange={setEditDialogTab}>
            <TabsList>
              <TabTrigger value="code">
                <span className="flex items-center gap-1.5">
                  <Code2 className="h-3.5 w-3.5" /> Code
                </span>
              </TabTrigger>
              <TabTrigger value="template">
                <span className="flex items-center gap-1.5">
                  <Layout className="h-3.5 w-3.5" /> Display Template
                </span>
              </TabTrigger>
            </TabsList>
            <TabsContent value="code">
              <EditVersionCodeForm
                editVersionCode={editVersionCode}
                setEditVersionCode={setEditVersionCode}
                editVersionReqs={editVersionReqs}
                setEditVersionReqs={setEditVersionReqs}
                editVersionEntry={editVersionEntry}
                setEditVersionEntry={setEditVersionEntry}
                editVersionError={editVersionError}
                onSubmit={handleEditVersion}
                onCancel={() => setEditVersionTarget(null)}
                isPending={updateVersion.isPending}
                volatileKeys={editVersionVolatileKeys}
                setVolatileKeys={setEditVersionVolatileKeys}
                eligibilityOids={editVersionEligibilityOids}
                setEligibilityOids={setEditVersionEligibilityOids}
                isConfigApp={true}
                appId={id!}
              />
            </TabsContent>
            <TabsContent value="template">
              {editVersionTarget && (
                <DisplayTemplateEditor
                  appId={id!}
                  versionId={editVersionTarget.id}
                  initialTemplate={editVersionTarget.display_template}
                  onSave={(tpl) =>
                    handleSaveDisplayTemplate(editVersionTarget.id, tpl)
                  }
                />
              )}
            </TabsContent>
          </Tabs>
        ) : (
          <EditVersionCodeForm
            editVersionCode={editVersionCode}
            setEditVersionCode={setEditVersionCode}
            editVersionReqs={editVersionReqs}
            setEditVersionReqs={setEditVersionReqs}
            editVersionEntry={editVersionEntry}
            setEditVersionEntry={setEditVersionEntry}
            editVersionError={editVersionError}
            onSubmit={handleEditVersion}
            onCancel={() => setEditVersionTarget(null)}
            isPending={updateVersion.isPending}
            eligibilityOids={editVersionEligibilityOids}
            setEligibilityOids={setEditVersionEligibilityOids}
          />
        )}
      </Dialog>

      {/* Delete Version Dialog */}
      <Dialog
        open={!!deleteVersionTarget}
        onClose={() => {
          setDeleteVersionTarget(null);
          setDeleteVersionError(null);
        }}
        title="Delete Version"
      >
        <p className="text-sm text-zinc-400">
          Delete version{" "}
          <span className="font-semibold text-zinc-200">
            {deleteVersionTarget?.version}
          </span>
          ?
        </p>
        {deleteVersionError && (
          <p className="text-sm text-red-400 mt-2">{deleteVersionError}</p>
        )}
        <DialogFooter>
          <Button
            variant="secondary"
            onClick={() => {
              setDeleteVersionTarget(null);
              setDeleteVersionError(null);
            }}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDeleteVersion}
            disabled={deleteVersion.isPending}
          >
            {deleteVersion.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

// ── Helper components extracted for View/Edit dialogs ────

function VersionCodeView({ version }: { version: VersionDetail }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-md bg-zinc-800/50 px-3 py-2">
          <span className="text-zinc-500">Entry Class:</span>{" "}
          <span className="text-zinc-200 font-mono">
            {version.entry_class ?? "\u2014"}
          </span>
        </div>
        <div className="rounded-md bg-zinc-800/50 px-3 py-2">
          <span className="text-zinc-500">Checksum:</span>{" "}
          <span className="text-zinc-200 font-mono text-xs">
            {version.checksum?.slice(0, 12)}...
          </span>
        </div>
      </div>
      {version.requirements && version.requirements.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1">
            Requirements
          </p>
          <div className="flex flex-wrap gap-1">
            {version.requirements.map((r, i) => (
              <Badge key={i} variant="default" className="font-mono text-xs">
                {r}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {version.source_code && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1">
            Source Code
          </p>
          <CodeEditor
            value={version.source_code}
            readOnly
            height="calc(100vh - 300px)"
          />
        </div>
      )}
    </div>
  );
}

function SlotVersionPicker({
  connectorId,
  versionId,
  disabled,
  onChange,
}: {
  connectorId: string;
  versionId: string | null;
  disabled: boolean;
  onChange: (versionId: string | null) => void;
}) {
  const { data: detail, isLoading } = useConnectorDetail(connectorId);
  const versions = detail?.versions ?? [];
  const latest = versions.find((v) => v.is_latest);
  const currentValue = versionId ?? "";
  return (
    <select
      className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100"
      value={currentValue}
      disabled={disabled || isLoading}
      onChange={(e) => {
        const v = e.target.value;
        onChange(v === "" ? null : v);
      }}
    >
      <option value="">Latest{latest ? ` (${latest.version})` : ""}</option>
      {versions.map((v) => (
        <option key={v.id} value={v.id}>
          {v.version}
          {v.is_latest ? " — latest" : ""}
        </option>
      ))}
    </select>
  );
}

function VolatileKeyPicker({
  appId,
  keys,
  setKeys,
}: {
  appId: string;
  keys: string[];
  setKeys: (v: string[]) => void;
}) {
  const [customInput, setCustomInput] = useState("");
  const { data: configKeys } = useAppConfigKeys(appId);

  const allKeys = useMemo(() => {
    const detected = configKeys?.all_keys ?? [];
    const extra = keys.filter((k) => !detected.includes(k));
    const merged = [...new Set([...detected, ...extra])];
    // Sort: volatile keys first, then alphabetical
    return merged.sort((a, b) => {
      const aVol = keys.includes(a);
      const bVol = keys.includes(b);
      if (aVol !== bVol) return aVol ? -1 : 1;
      return a.localeCompare(b);
    });
  }, [configKeys, keys]);

  const toggleKey = useCallback(
    (key: string) => {
      if (keys.includes(key)) {
        setKeys(keys.filter((k) => k !== key));
      } else {
        setKeys([...keys, key]);
      }
    },
    [keys, setKeys],
  );

  return (
    <div className="space-y-2">
      <Label className="text-sm">Volatile Keys</Label>
      <p className="text-xs text-zinc-500">
        Keys excluded from change detection. Volatile keys change every poll
        cycle and won't create change history entries.
      </p>

      <div className="border border-zinc-800 rounded-lg max-h-[300px] overflow-auto">
        {allKeys.map((key) => (
          <div
            key={key}
            className="flex items-center justify-between px-3 py-1.5 border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/30"
          >
            <span className="font-mono text-xs text-zinc-300">{key}</span>
            <input
              type="checkbox"
              checked={keys.includes(key)}
              onChange={() => toggleKey(key)}
              className="accent-brand-500 cursor-pointer"
            />
          </div>
        ))}
        {allKeys.length === 0 && (
          <p className="text-xs text-zinc-600 py-4 text-center">
            No config keys detected yet. Run the app once to populate.
          </p>
        )}
      </div>

      <div className="flex gap-2">
        <Input
          placeholder="Add custom key..."
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && customInput.trim()) {
              e.preventDefault();
              if (!keys.includes(customInput.trim())) {
                setKeys([...keys, customInput.trim()]);
              }
              setCustomInput("");
            }
          }}
          className="text-xs"
        />
      </div>
    </div>
  );
}

function EditVersionCodeForm({
  editVersionCode,
  setEditVersionCode,
  editVersionReqs,
  setEditVersionReqs,
  editVersionEntry,
  setEditVersionEntry,
  editVersionError,
  onSubmit,
  onCancel,
  isPending,
  volatileKeys,
  setVolatileKeys,
  eligibilityOids,
  setEligibilityOids,
  isConfigApp,
  appId,
}: {
  editVersionCode: string;
  setEditVersionCode: (v: string) => void;
  editVersionReqs: string;
  setEditVersionReqs: (v: string) => void;
  editVersionEntry: string;
  setEditVersionEntry: (v: string) => void;
  editVersionError: string | null;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
  isPending: boolean;
  volatileKeys?: string[];
  setVolatileKeys?: (v: string[]) => void;
  eligibilityOids?: EligibilityOidCheck[];
  setEligibilityOids?: (v: EligibilityOidCheck[]) => void;
  isConfigApp?: boolean;
  appId?: string;
}) {
  const reqsList = useMemo(
    () =>
      editVersionReqs.trim()
        ? editVersionReqs.trim().split("\n").filter(Boolean)
        : [],
    [editVersionReqs],
  );

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="edit-ver-entry">
          Entry Class{" "}
          <span className="font-normal text-zinc-500">(optional)</span>
        </Label>
        <Input
          id="edit-ver-entry"
          placeholder="e.g. Poller"
          value={editVersionEntry}
          onChange={(e) => setEditVersionEntry(e.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <Label>Source Code (Python)</Label>
        <CodeEditor
          value={editVersionCode}
          onChange={setEditVersionCode}
          height="calc(100vh - 300px)"
        />
      </div>
      <div className="space-y-1.5">
        <Label>Requirements</Label>
        <ModulePicker
          value={reqsList}
          onChange={(reqs) => setEditVersionReqs(reqs.join("\n"))}
        />
      </div>
      {isConfigApp && volatileKeys && setVolatileKeys && appId && (
        <VolatileKeyPicker
          appId={appId}
          keys={volatileKeys}
          setKeys={setVolatileKeys}
        />
      )}
      {eligibilityOids && setEligibilityOids && (
        <EligibilityOidsEditor
          value={eligibilityOids}
          onChange={setEligibilityOids}
        />
      )}
      {editVersionError && (
        <p className="text-sm text-red-400">{editVersionError}</p>
      )}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={isPending}>
          {isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save
        </Button>
      </DialogFooter>
    </form>
  );
}

function NewVersionCodeForm({
  versionField,
  versionCode,
  setVersionCode,
  versionReqs,
  setVersionReqs,
  versionEntry,
  setVersionEntry,
  versionError,
  onSubmit,
  onCancel,
  isPending,
  volatileKeys,
  setVolatileKeys,
  eligibilityOids,
  setEligibilityOids,
  isConfigApp,
  appId,
}: {
  versionField: {
    value: string;
    onChange: (
      e: React.ChangeEvent<
        HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
      >,
    ) => void;
    onBlur: () => void;
    error: string | null;
  };
  versionCode: string;
  setVersionCode: (v: string) => void;
  versionReqs: string;
  setVersionReqs: (v: string) => void;
  versionEntry: string;
  setVersionEntry: (v: string) => void;
  versionError: string | null;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
  isPending: boolean;
  volatileKeys?: string[];
  setVolatileKeys?: (v: string[]) => void;
  eligibilityOids?: EligibilityOidCheck[];
  setEligibilityOids?: (v: EligibilityOidCheck[]) => void;
  isConfigApp?: boolean;
  appId?: string;
}) {
  const reqsList = useMemo(
    () =>
      versionReqs.trim() ? versionReqs.trim().split("\n").filter(Boolean) : [],
    [versionReqs],
  );

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="ver-string">Version</Label>
          <Input
            id="ver-string"
            placeholder="e.g. 1.1.0"
            value={versionField.value}
            onChange={versionField.onChange}
            onBlur={versionField.onBlur}
            autoFocus
          />
          {versionField.error && (
            <p className="text-xs text-red-400 mt-0.5">{versionField.error}</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ver-entry">
            Entry Class{" "}
            <span className="font-normal text-zinc-500">(optional)</span>
          </Label>
          <Input
            id="ver-entry"
            placeholder="e.g. MyCheck"
            value={versionEntry}
            onChange={(e) => setVersionEntry(e.target.value)}
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label>Source Code (Python)</Label>
        <CodeEditor
          value={versionCode}
          onChange={setVersionCode}
          height="calc(100vh - 300px)"
        />
      </div>
      <div className="space-y-1.5">
        <Label>Requirements</Label>
        <ModulePicker
          value={reqsList}
          onChange={(reqs) => setVersionReqs(reqs.join("\n"))}
        />
      </div>
      {isConfigApp && volatileKeys && setVolatileKeys && appId && (
        <VolatileKeyPicker
          appId={appId}
          keys={volatileKeys}
          setKeys={setVolatileKeys}
        />
      )}
      {eligibilityOids && setEligibilityOids && (
        <EligibilityOidsEditor
          value={eligibilityOids}
          onChange={setEligibilityOids}
        />
      )}
      {versionError && <p className="text-sm text-red-400">{versionError}</p>}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={isPending}>
          {isPending && <Loader2 className="h-4 w-4 animate-spin" />} Create
          Version
        </Button>
      </DialogFooter>
    </form>
  );
}

// ── Eligibility Tab ─────────────────────────────────────

function EligibilityTab({
  appId,
  startTest,
  runsQuery,
  expandedRunId,
  setExpandedRunId,
  detailQuery,
  eligFilter,
  setEligFilter,
  eligPage,
  setEligPage,
  autoAssign,
  appId2,
}: {
  appId: string;
  startTest: ReturnType<typeof useStartEligibilityTest>;
  runsQuery: ReturnType<typeof useEligibilityRuns>;
  expandedRunId: string | null;
  setExpandedRunId: (id: string | null) => void;
  detailQuery: ReturnType<typeof useEligibilityRunDetail>;
  eligFilter: number | undefined;
  setEligFilter: (f: number | undefined) => void;
  eligPage: number;
  setEligPage: (p: number) => void;
  autoAssign: ReturnType<typeof useAutoAssignEligible>;
  appId2: string;
}) {
  const runs = runsQuery.data?.data ?? [];
  const detail = detailQuery.data?.data;
  const hasRunning = runs.some((r) => r.status === "running");
  const tz = useTimezone();

  // Bulk selection state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deviceSearch, setDeviceSearch] = useState("");

  // Filter displayed devices by search
  const visibleDevices = useMemo(() => {
    const devices = detail?.devices ?? [];
    if (!deviceSearch) return devices;
    const q = deviceSearch.toLowerCase();
    return devices.filter(
      (d) =>
        d.device_name.toLowerCase().includes(q) ||
        d.device_address.toLowerCase().includes(q),
    );
  }, [detail?.devices, deviceSearch]);

  // Eligible (non-already-assigned) device IDs on current page for select-all
  const selectableIds = useMemo(
    () =>
      visibleDevices
        .filter((d) => d.eligible === 1 && !d.already_assigned)
        .map((d) => d.device_id),
    [visibleDevices],
  );
  const allSelected =
    selectableIds.length > 0 &&
    selectableIds.every((id) => selectedIds.has(id));

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        selectableIds.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        selectableIds.forEach((id) => next.add(id));
        return next;
      });
    }
  };

  // Reset selection when expanding a different run
  const handleExpand = (runId: string | null) => {
    setSelectedIds(new Set());
    setDeviceSearch("");
    setExpandedRunId(runId);
  };

  const statusBadge = (run: {
    status: string;
    tested: number;
    total_devices: number;
  }) => {
    if (run.status === "running") {
      const pct =
        run.total_devices > 0
          ? Math.round((run.tested / run.total_devices) * 100)
          : 0;
      return (
        <div className="flex items-center gap-2">
          <Badge className="bg-blue-500/15 text-blue-400 border-blue-500/30">
            <Loader2 className="h-3 w-3 animate-spin mr-1" />
            {run.tested}/{run.total_devices}
          </Badge>
          <div className="w-16 h-1.5 rounded-full bg-zinc-800">
            <div
              className="h-1.5 rounded-full bg-blue-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-[10px] text-zinc-500">{pct}%</span>
        </div>
      );
    }
    if (run.status === "completed")
      return (
        <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30">
          completed
        </Badge>
      );
    return (
      <Badge className="bg-red-500/15 text-red-400 border-red-500/30">
        failed
      </Badge>
    );
  };

  const eligLabel = (e: number) => {
    if (e === 1) return <span className="text-emerald-400">Eligible</span>;
    if (e === 0) return <span className="text-red-400">Ineligible</span>;
    return <span className="text-zinc-500">Error</span>;
  };

  const selectedCount = selectedIds.size;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-zinc-500">
          Find eligible devices via vendor match (instant) or live SNMP OID
          probing.
        </p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={startTest.isPending || hasRunning}
            onClick={() => startTest.mutate({ appId, mode: "probe" })}
          >
            {startTest.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            )}
            Probe OIDs
          </Button>
          <Button
            size="sm"
            disabled={startTest.isPending || hasRunning}
            onClick={() => startTest.mutate({ appId, mode: "instant" })}
          >
            {startTest.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
            ) : (
              <SlidersHorizontal className="h-3.5 w-3.5 mr-1.5" />
            )}
            Find Eligible
          </Button>
        </div>
      </div>

      {runs.length === 0 ? (
        <div className="flex h-32 flex-col items-center justify-center gap-2 text-zinc-500">
          <SlidersHorizontal className="h-6 w-6" />
          <p className="text-sm">No eligibility tests have been run yet.</p>
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs py-1 w-8" />
              <TableHead className="text-xs py-1">Time</TableHead>
              <TableHead className="text-xs py-1">Status</TableHead>
              <TableHead className="text-xs py-1">Eligible</TableHead>
              <TableHead className="text-xs py-1">Ineligible</TableHead>
              <TableHead className="text-xs py-1">Error</TableHead>
              <TableHead className="text-xs py-1">Duration</TableHead>
              <TableHead className="text-xs py-1">By</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((run) => {
              const isExpanded = expandedRunId === run.run_id;
              return (
                <Fragment key={run.run_id}>
                  <TableRow
                    className="cursor-pointer hover:bg-zinc-800/50"
                    onClick={() => handleExpand(isExpanded ? null : run.run_id)}
                  >
                    <TableCell className="py-1.5 px-2">
                      {isExpanded ? (
                        <ChevronDown className="h-3.5 w-3.5 text-zinc-500" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 text-zinc-500" />
                      )}
                    </TableCell>
                    <TableCell className="py-1.5 text-xs text-zinc-400">
                      {run.started_at ? formatDate(run.started_at, tz) : "—"}
                    </TableCell>
                    <TableCell className="py-1.5">{statusBadge(run)}</TableCell>
                    <TableCell className="py-1.5 text-xs font-mono text-emerald-400">
                      {run.eligible}
                    </TableCell>
                    <TableCell className="py-1.5 text-xs font-mono text-red-400">
                      {run.ineligible}
                    </TableCell>
                    <TableCell className="py-1.5 text-xs font-mono text-zinc-500">
                      {run.unreachable}
                    </TableCell>
                    <TableCell className="py-1.5 text-xs text-zinc-500">
                      {run.duration_ms
                        ? `${(run.duration_ms / 1000).toFixed(1)}s`
                        : "—"}
                    </TableCell>
                    <TableCell className="py-1.5 text-xs text-zinc-500">
                      {run.triggered_by}
                    </TableCell>
                  </TableRow>
                  {isExpanded && (
                    <TableRow>
                      <TableCell
                        colSpan={8}
                        className="bg-zinc-900/50 px-4 py-3"
                      >
                        {/* Filter + search + assign bar */}
                        <div className="flex flex-wrap gap-2 mb-3 items-center">
                          {[
                            { label: "All", value: undefined },
                            { label: "Eligible", value: 1 },
                            { label: "Ineligible", value: 0 },
                            { label: "Error", value: 2 },
                          ].map((f) => (
                            <Button
                              key={f.label}
                              size="sm"
                              variant={
                                eligFilter === f.value ? "default" : "outline"
                              }
                              onClick={() => {
                                setEligFilter(f.value);
                                setEligPage(1);
                              }}
                              className="h-6 text-xs"
                            >
                              {f.label}
                            </Button>
                          ))}
                          <span className="text-xs text-zinc-500 self-center ml-1">
                            {detail?.meta.total ?? 0} devices
                          </span>
                          <Input
                            placeholder="Search devices..."
                            value={deviceSearch}
                            onChange={(e) => setDeviceSearch(e.target.value)}
                            className="h-6 text-xs w-44 ml-2"
                          />
                          {run.status === "completed" && run.eligible > 0 && (
                            <Button
                              size="sm"
                              className="ml-auto h-6 text-xs"
                              disabled={autoAssign.isPending}
                              onClick={(e) => {
                                e.stopPropagation();
                                autoAssign.mutate({
                                  appId: appId2,
                                  runId: run.run_id,
                                  deviceIds:
                                    selectedCount > 0
                                      ? [...selectedIds]
                                      : undefined,
                                });
                              }}
                            >
                              {autoAssign.isPending ? (
                                <Loader2 className="h-3 w-3 animate-spin mr-1" />
                              ) : (
                                <Plus className="h-3 w-3 mr-1" />
                              )}
                              {selectedCount > 0
                                ? `Assign ${selectedCount} selected`
                                : `Auto-assign ${run.eligible} eligible`}
                            </Button>
                          )}
                          {autoAssign.isSuccess &&
                            autoAssign.variables?.runId === run.run_id && (
                              <span className="text-xs text-emerald-400 ml-2">
                                {autoAssign.data?.data?.created ?? 0} assigned
                              </span>
                            )}
                        </div>
                        {/* Device results table with checkboxes */}
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="text-[11px] py-1 w-8 px-2">
                                <input
                                  type="checkbox"
                                  checked={allSelected}
                                  onChange={toggleSelectAll}
                                  className="accent-emerald-500 h-3 w-3 cursor-pointer"
                                  title="Select all eligible on this page"
                                />
                              </TableHead>
                              <TableHead className="text-[11px] py-1">
                                Device
                              </TableHead>
                              <TableHead className="text-[11px] py-1">
                                Address
                              </TableHead>
                              <TableHead className="text-[11px] py-1">
                                Result
                              </TableHead>
                              <TableHead className="text-[11px] py-1">
                                Details
                              </TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {visibleDevices.map((d) => {
                              const selectable =
                                d.eligible === 1 && !d.already_assigned;
                              return (
                                <TableRow
                                  key={d.device_id}
                                  className={
                                    selectedIds.has(d.device_id)
                                      ? "bg-emerald-500/5"
                                      : ""
                                  }
                                >
                                  <TableCell className="py-1 px-2">
                                    <input
                                      type="checkbox"
                                      checked={selectedIds.has(d.device_id)}
                                      onChange={() => toggleSelect(d.device_id)}
                                      disabled={!selectable}
                                      className="accent-emerald-500 h-3 w-3 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                                    />
                                  </TableCell>
                                  <TableCell className="py-1 text-xs font-mono text-zinc-200">
                                    {d.device_name}
                                  </TableCell>
                                  <TableCell className="py-1 text-xs font-mono text-zinc-400">
                                    {d.device_address}
                                  </TableCell>
                                  <TableCell className="py-1 text-xs">
                                    {d.already_assigned ? (
                                      <span className="text-zinc-500">
                                        Assigned
                                      </span>
                                    ) : (
                                      eligLabel(d.eligible)
                                    )}
                                  </TableCell>
                                  <TableCell className="py-1 text-xs text-zinc-500">
                                    {d.reason ||
                                      (d.eligible === 1
                                        ? "All checks passed"
                                        : "")}
                                  </TableCell>
                                </TableRow>
                              );
                            })}
                            {visibleDevices.length === 0 && (
                              <TableRow>
                                <TableCell
                                  colSpan={5}
                                  className="py-3 text-center text-xs text-zinc-500"
                                >
                                  {detailQuery.isLoading
                                    ? "Loading..."
                                    : deviceSearch
                                      ? "No matches"
                                      : "No results"}
                                </TableCell>
                              </TableRow>
                            )}
                          </TableBody>
                        </Table>
                        {/* Selection summary + pagination */}
                        <div className="flex items-center justify-between mt-2 text-xs text-zinc-500">
                          <span>
                            {selectedCount > 0 && (
                              <span className="text-emerald-400 mr-3">
                                {selectedCount} selected
                              </span>
                            )}
                            Page {eligPage} of{" "}
                            {Math.max(
                              1,
                              Math.ceil((detail?.meta.total ?? 0) / 25),
                            )}
                          </span>
                          {(detail?.meta.total ?? 0) > 25 && (
                            <div className="flex gap-1">
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-6"
                                disabled={eligPage <= 1}
                                onClick={() => setEligPage(eligPage - 1)}
                              >
                                Prev
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-6"
                                disabled={
                                  eligPage >=
                                  Math.ceil((detail?.meta.total ?? 0) / 25)
                                }
                                onClick={() => setEligPage(eligPage + 1)}
                              >
                                Next
                              </Button>
                            </div>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

// ── Eligibility OIDs Editor ─────────────────────────────

function EligibilityOidsEditor({
  value,
  onChange,
}: {
  value: EligibilityOidCheck[];
  onChange: (v: EligibilityOidCheck[]) => void;
}) {
  return (
    <div className="space-y-2">
      <Label>Eligibility OIDs</Label>
      <p className="text-[11px] text-zinc-500">
        OID checks that must pass before auto-assigning via discovery. Leave
        empty for no requirements.
      </p>
      {value.map((entry, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input
            placeholder="1.3.6.1.4.1.9.9.168.1.1.1.0"
            value={entry.oid}
            onChange={(e) => {
              const u = [...value];
              u[i] = { ...u[i], oid: e.target.value };
              onChange(u);
            }}
            className="flex-1"
          />
          <Select
            value={entry.check}
            onChange={(e) => {
              const u = [...value];
              const check = e.target.value as "exists" | "equals";
              u[i] =
                check === "exists"
                  ? { oid: u[i].oid, check }
                  : { ...u[i], check };
              onChange(u);
            }}
            className="w-28"
          >
            <option value="exists">Exists</option>
            <option value="equals">Equals</option>
          </Select>
          {entry.check === "equals" && (
            <Input
              placeholder="Expected value"
              value={entry.value || ""}
              onChange={(e) => {
                const u = [...value];
                u[i] = { ...u[i], value: e.target.value };
                onChange(u);
              }}
              className="w-48"
            />
          )}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onChange(value.filter((_, j) => j !== i))}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onChange([...value, { oid: "", check: "exists" }])}
      >
        <Plus className="mr-1.5 h-3 w-3" /> Add OID Check
      </Button>
    </div>
  );
}

// ── Thresholds Tab ──────────────────────────────────────

const BUILT_IN_UNITS = [
  { value: "percent", label: "percent (%)" },
  { value: "ms", label: "ms (milliseconds)" },
  { value: "seconds", label: "seconds (s)" },
  { value: "bytes", label: "bytes (B)" },
  { value: "count", label: "count" },
  { value: "ratio", label: "ratio (0\u20131)" },
  { value: "dBm", label: "dBm (signal strength)" },
  { value: "pps", label: "pps (packets/sec)" },
  { value: "bps", label: "bps (bitrate)" },
];

function UnitSelector({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  const isCustom =
    value != null &&
    value !== "" &&
    !BUILT_IN_UNITS.some((u) => u.value === value);
  const [showCustom, setShowCustom] = useState(isCustom);
  const [customValue, setCustomValue] = useState(isCustom ? (value ?? "") : "");

  return (
    <div className="space-y-1">
      <select
        value={showCustom ? "__custom__" : (value ?? "")}
        onChange={(e) => {
          const sel = e.target.value;
          if (sel === "__custom__") {
            setShowCustom(true);
            onChange(customValue || null);
          } else {
            setShowCustom(false);
            setCustomValue("");
            onChange(sel || null);
          }
        }}
        className="rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-100"
      >
        <option value="">None</option>
        {BUILT_IN_UNITS.map((u) => (
          <option key={u.value} value={u.value}>
            {u.label}
          </option>
        ))}
        <option value="__custom__">Custom\u2026</option>
      </select>
      {showCustom && (
        <Input
          autoFocus
          placeholder="e.g. RPM, \u00b0C, req/s"
          value={customValue}
          onChange={(e) => {
            setCustomValue(e.target.value);
            onChange(e.target.value || null);
          }}
          className="h-7 text-xs"
        />
      )}
    </div>
  );
}

function formatThresholdValue(
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

function ThresholdsTab({ appId }: { appId: string }) {
  const { data: variables, isLoading } = useAppThresholds(appId);
  const { data: definitionsResp } = useAlertDefinitions(appId);
  const definitions = definitionsResp?.data ?? [];
  const updateVar = useUpdateThresholdVariable();
  const createVar = useCreateThresholdVariable();
  const deleteVar = useDeleteThresholdVariable();

  // Editing states
  const [editingDefault, setEditingDefault] = useState<string | null>(null);
  const [defaultDraft, setDefaultDraft] = useState("");
  const [editingAppValue, setEditingAppValue] = useState<string | null>(null);
  const [appValueDraft, setAppValueDraft] = useState("");

  // Create form
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDefault, setNewDefault] = useState("");
  const [newUnit, setNewUnit] = useState<string | null>(null);
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Build a map: variable name -> list of definitions that reference the variable
  const variableUsage = useMemo(() => {
    const usage: Record<
      string,
      { definition_id: string; definition_name: string }[]
    > = {};
    if (variables && definitions) {
      for (const v of variables) {
        const refs: { definition_id: string; definition_name: string }[] = [];
        for (const d of definitions) {
          const tiers = d.severity_tiers ?? [];
          const re = new RegExp(`(?:>|<|>=|<=|==|!=)\\s*${v.name}\\b`);
          if (
            tiers.some((t) => t.expression != null && re.test(t.expression))
          ) {
            refs.push({ definition_id: d.id, definition_name: d.name });
          }
        }
        usage[v.id] = refs;
      }
    }
    return usage;
  }, [variables, definitions]);

  if (isLoading)
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
      </div>
    );

  const handleSaveDefault = (varId: string) => {
    const val = parseFloat(defaultDraft);
    if (!isNaN(val) && isFinite(val)) {
      updateVar.mutate({ appId, varId, default_value: val });
    }
    setEditingDefault(null);
  };

  const handleSaveAppValue = (varId: string) => {
    const val = parseFloat(appValueDraft);
    if (!isNaN(val) && isFinite(val)) {
      updateVar.mutate({ appId, varId, app_value: val });
    }
    setEditingAppValue(null);
  };

  const handleResetAppValue = (varId: string) => {
    updateVar.mutate({ appId, varId, clear_app_value: true });
  };

  const handleCreate = () => {
    setCreateError(null);
    const name = newName.trim();
    if (!name) {
      setCreateError("Name is required");
      return;
    }
    if (!/^[a-z][a-z0-9_]*$/.test(name)) {
      setCreateError(
        "Name must be lowercase alphanumeric with underscores, starting with a letter",
      );
      return;
    }
    const defaultVal = parseFloat(newDefault);
    if (isNaN(defaultVal) || !isFinite(defaultVal)) {
      setCreateError("Default value must be a valid number");
      return;
    }
    createVar.mutate(
      {
        appId,
        name,
        default_value: defaultVal,
        display_name: newDisplayName.trim() || undefined,
        description: newDescription.trim() || undefined,
        unit: newUnit || undefined,
      },
      {
        onSuccess: () => {
          setCreating(false);
          setNewName("");
          setNewDefault("");
          setNewUnit(null);
          setNewDisplayName("");
          setNewDescription("");
          setCreateError(null);
        },
        onError: (err: unknown) => {
          setCreateError(
            err instanceof Error ? err.message : "Failed to create variable",
          );
        },
      },
    );
  };

  const handleDelete = (varId: string) => {
    deleteVar.mutate(
      { appId, varId },
      {
        onSuccess: () => setConfirmDeleteId(null),
      },
    );
  };

  const isEmpty = !variables || variables.length === 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4" />
          Threshold Variables{" "}
          {variables && variables.length > 0 ? `(${variables.length})` : ""}
          <Button
            size="sm"
            variant="secondary"
            className="ml-auto gap-1.5"
            onClick={() => {
              setCreating(true);
              setCreateError(null);
            }}
          >
            <Plus className="h-3 w-3" /> New Variable
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isEmpty && !creating ? (
          <div className="py-8 text-center">
            <SlidersHorizontal className="h-8 w-8 text-zinc-600 mx-auto mb-2" />
            <p className="text-sm text-zinc-500">
              No threshold variables defined.
            </p>
            <p className="text-xs text-zinc-600 mt-1">
              Variables are auto-created when alert definitions use $variable
              syntax, or create one manually.
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Default</TableHead>
                <TableHead>App Value</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead>Used By</TableHead>
                <TableHead className="w-24"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {variables?.map((v) => {
                const usedBy = variableUsage[v.id] ?? [];
                const isReferenced = usedBy.length > 0;
                return (
                  <TableRow key={v.id}>
                    <TableCell className="font-medium text-zinc-100">
                      <span className="font-mono text-sm">{v.name}</span>
                      {v.display_name && (
                        <span className="text-zinc-400 text-xs ml-2">
                          ({v.display_name})
                        </span>
                      )}
                      {v.description && (
                        <p className="text-xs text-zinc-500 mt-0.5">
                          {v.description}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>
                      {editingDefault === v.id ? (
                        <div className="flex items-center gap-1">
                          <Input
                            autoFocus
                            type="number"
                            value={defaultDraft}
                            onChange={(e) => setDefaultDraft(e.target.value)}
                            className="w-24 h-7 text-sm font-mono"
                            onKeyDown={(e) => {
                              if (e.key === "Enter") handleSaveDefault(v.id);
                              if (e.key === "Escape") setEditingDefault(null);
                            }}
                            onBlur={() => handleSaveDefault(v.id)}
                          />
                          <span className="text-xs text-zinc-400">
                            {v.unit || ""}
                          </span>
                        </div>
                      ) : (
                        <button
                          className="font-mono text-sm text-zinc-300 hover:text-zinc-100 flex items-center gap-1 group"
                          onClick={() => {
                            setEditingDefault(v.id);
                            setDefaultDraft(String(v.default_value));
                          }}
                        >
                          {formatThresholdValue(v.default_value, v.unit)}
                          <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-50" />
                        </button>
                      )}
                    </TableCell>
                    <TableCell>
                      {editingAppValue === v.id ? (
                        <div className="flex items-center gap-1">
                          <Input
                            autoFocus
                            type="number"
                            value={appValueDraft}
                            onChange={(e) => setAppValueDraft(e.target.value)}
                            className="w-24 h-7 text-sm font-mono"
                            onKeyDown={(e) => {
                              if (e.key === "Enter") handleSaveAppValue(v.id);
                              if (e.key === "Escape") setEditingAppValue(null);
                            }}
                            onBlur={() => handleSaveAppValue(v.id)}
                          />
                          <span className="text-xs text-zinc-400">
                            {v.unit || ""}
                          </span>
                        </div>
                      ) : v.app_value != null ? (
                        <div className="flex items-center gap-2">
                          <button
                            className="font-mono text-sm text-brand-400 hover:text-brand-300 flex items-center gap-1 group"
                            onClick={() => {
                              setEditingAppValue(v.id);
                              setAppValueDraft(String(v.app_value));
                            }}
                          >
                            {formatThresholdValue(v.app_value, v.unit)}
                            <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-50" />
                          </button>
                          <button
                            className="text-xs text-zinc-500 hover:text-zinc-300"
                            onClick={() => handleResetAppValue(v.id)}
                          >
                            Reset
                          </button>
                        </div>
                      ) : (
                        <button
                          className="text-zinc-500 hover:text-zinc-300 flex items-center gap-1 group text-sm"
                          onClick={() => {
                            setEditingAppValue(v.id);
                            setAppValueDraft("");
                          }}
                        >
                          <span>{"\u2014"}</span>
                          <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-50" />
                        </button>
                      )}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-xs">
                      {v.unit || "\u2014"}
                    </TableCell>
                    <TableCell>
                      {usedBy.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {usedBy.map((u) => (
                            <Badge
                              key={u.definition_id}
                              variant="default"
                              className="text-xs"
                            >
                              {u.definition_name}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-zinc-600">Unused</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {confirmDeleteId === v.id ? (
                          <div className="flex items-center gap-1">
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => handleDelete(v.id)}
                              disabled={deleteVar.isPending}
                            >
                              Confirm
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setConfirmDeleteId(null)}
                            >
                              Cancel
                            </Button>
                          </div>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-zinc-500 hover:text-red-400"
                            title={
                              isReferenced
                                ? `Cannot delete: used by ${usedBy.map((u) => u.definition_name).join(", ")}`
                                : "Delete variable"
                            }
                            disabled={isReferenced}
                            onClick={() => setConfirmDeleteId(v.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
              {creating && (
                <TableRow>
                  <TableCell>
                    <div className="space-y-1">
                      <Input
                        placeholder="variable_name"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        className="h-7 text-sm font-mono"
                        autoFocus
                      />
                      <Input
                        placeholder="Display name (optional)"
                        value={newDisplayName}
                        onChange={(e) => setNewDisplayName(e.target.value)}
                        className="h-7 text-xs"
                      />
                      <Input
                        placeholder="Description (optional)"
                        value={newDescription}
                        onChange={(e) => setNewDescription(e.target.value)}
                        className="h-7 text-xs text-zinc-400"
                      />
                    </div>
                  </TableCell>
                  <TableCell>
                    <Input
                      type="number"
                      placeholder="Default"
                      value={newDefault}
                      onChange={(e) => setNewDefault(e.target.value)}
                      className="w-24 h-7 text-sm"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleCreate();
                        if (e.key === "Escape") setCreating(false);
                      }}
                    />
                  </TableCell>
                  <TableCell />
                  <TableCell>
                    <UnitSelector value={newUnit} onChange={setNewUnit} />
                  </TableCell>
                  <TableCell />
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button
                        size="sm"
                        onClick={handleCreate}
                        disabled={createVar.isPending}
                      >
                        {createVar.isPending ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Check className="h-3.5 w-3.5" />
                        )}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setCreating(false);
                          setCreateError(null);
                        }}
                      >
                        Cancel
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
        {createError && (
          <p className="text-sm text-red-400 mt-2">{createError}</p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Alerts Tab ──────────────────────────────────────────

function AlertsTab({
  appId,
  app,
}: {
  appId: string;
  app: {
    target_table?: string;
    versions: Array<{ id: string; version: string; is_latest: boolean }>;
  };
}) {
  const navigate = useNavigate();
  const { data: definitionsResp, isLoading } = useAlertDefinitions(appId);
  const definitions = definitionsResp?.data ?? [];
  const { data: metrics } = useAlertMetrics(appId);
  const { data: variables } = useAppThresholds(appId);
  const createDef = useCreateAlertDefinition();
  const updateDef = useUpdateAlertDefinition();
  const deleteDef = useDeleteAlertDefinition();
  const invertDef = useInvertAlertDefinition();

  // Form state — used for both create and edit
  const [formMode, setFormMode] = useState<"closed" | "create" | "edit">(
    "closed",
  );
  const [editId, setEditId] = useState<string | null>(null);
  const formNameField = useField("", validateName);
  // Single-expression form state kept for UI compatibility. On submit
  // we wrap it into a one-tier severity_tiers list. Existing multi-tier
  // defs are flagged read-only (form blocked) so operators can inspect
  // them but must use the API for structural edits.
  const [formExpression, setFormExpression] = useState("");
  const [formSeverity, setFormSeverity] = useState<
    "info" | "warning" | "critical" | "emergency"
  >("warning");
  const [formMultiTier, setFormMultiTier] = useState(false);
  const formWindowField = useField("5m", validateAlertWindow);
  const [formEnabled, setFormEnabled] = useState(true);
  const [formMessageTemplate, setFormMessageTemplate] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const openCreate = (prefill?: {
    name?: string;
    expression?: string;
    window?: string;
  }) => {
    setFormMode("create");
    setEditId(null);
    formNameField.reset(prefill?.name ?? "");
    setFormExpression(prefill?.expression ?? "");
    setFormSeverity("warning");
    setFormMultiTier(false);
    formWindowField.reset(prefill?.window ?? "5m");
    setFormEnabled(true);
    setFormMessageTemplate("");
    setFormError(null);
  };

  // Inline editing happens on the dedicated /alerts/definitions/:id page.
  // The inline form here is used only for quick creation on this app.

  const closeForm = () => {
    setFormMode("closed");
    setEditId(null);
    formNameField.reset();
    formWindowField.reset("5m");
    setFormError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (formMultiTier) {
      setFormError(
        "Multi-tier definitions are read-only in the UI for now — edit via API.",
      );
      return;
    }
    if (!validateAll(formNameField, formWindowField)) return;
    // Build a minimal two-tier def: healthy recovery + the one severity
    // the inline form configures. Full multi-tier edits happen on the
    // dedicated detail page.
    const fallbackMsg =
      formMessageTemplate || `${formNameField.value} on {device_name}`;
    const tiers = [
      {
        severity: "healthy",
        expression: null,
        message_template: `${formNameField.value} on {device_name} recovered`,
      },
      {
        severity: formSeverity,
        expression: formExpression,
        message_template: fallbackMsg,
      },
    ];
    try {
      if (formMode === "edit" && editId) {
        await updateDef.mutateAsync({
          id: editId,
          name: formNameField.value,
          severity_tiers: tiers,
          window: formWindowField.value,
          enabled: formEnabled,
        });
      } else {
        await createDef.mutateAsync({
          app_id: appId,
          name: formNameField.value,
          severity_tiers: tiers,
          window: formWindowField.value,
          enabled: formEnabled,
        });
      }
      closeForm();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Operation failed");
    }
  };

  const handleRecovery = async (defnId: string) => {
    try {
      const res = await invertDef.mutateAsync(defnId);
      const d = res.data;
      openCreate({
        name: d.suggested_name,
        expression: d.inverted_expression,
        window: d.window,
      });
    } catch {
      /* noop */
    }
  };

  const isPending = createDef.isPending || updateDef.isPending;

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bell className="h-4 w-4" /> Alert Definitions
          <Button
            size="sm"
            variant="secondary"
            className="ml-auto"
            onClick={() => openCreate()}
          >
            <Plus className="h-3.5 w-3.5" /> New Alert
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {formMode !== "closed" && (
          <form
            onSubmit={handleSubmit}
            className="mb-6 space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4"
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium text-zinc-500 uppercase tracking-wide">
                {formMode === "edit" ? "Edit Alert" : "New Alert"}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="alert-name">Name</Label>
                <Input
                  id="alert-name"
                  value={formNameField.value}
                  onChange={formNameField.onChange}
                  onBlur={formNameField.onBlur}
                  required
                />
                {formNameField.error && (
                  <p className="text-xs text-red-400 mt-0.5">
                    {formNameField.error}
                  </p>
                )}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="alert-expr">Expression</Label>
              <Input
                id="alert-expr"
                value={formExpression}
                onChange={(e) => setFormExpression(e.target.value)}
                placeholder="e.g. avg(rtt_ms) > 100"
                className="font-mono text-sm"
                required
              />
              {metrics && metrics.length > 0 && (
                <div className="rounded-md border border-zinc-800 bg-zinc-900 p-3 space-y-2">
                  <p className="text-xs text-zinc-500 font-medium">
                    Available metrics — click to insert
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {metrics.map((m) => (
                      <button
                        key={m.name}
                        type="button"
                        className="inline-flex items-center gap-1 rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs font-mono text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100 cursor-pointer transition-colors"
                        onClick={() => {
                          const fn = m.type === "string" ? "" : "avg";
                          const snippet =
                            m.type === "string"
                              ? `${m.name} != ''`
                              : `${fn}(${m.name}) > `;
                          setFormExpression((prev) =>
                            prev ? `${prev} AND ${snippet}` : snippet,
                          );
                        }}
                        title={m.description}
                      >
                        <span
                          className={
                            m.type === "string"
                              ? "text-amber-400"
                              : "text-brand-400"
                          }
                        >
                          {m.type === "string" ? "Aa" : "#"}
                        </span>
                        {m.name}
                      </button>
                    ))}
                  </div>
                  <p className="text-[10px] text-zinc-600 leading-tight">
                    Functions:{" "}
                    <span className="font-mono text-zinc-500">avg</span>,{" "}
                    <span className="font-mono text-zinc-500">max</span>,{" "}
                    <span className="font-mono text-zinc-500">min</span>,{" "}
                    <span className="font-mono text-zinc-500">sum</span>,{" "}
                    <span className="font-mono text-zinc-500">count</span>,{" "}
                    <span className="font-mono text-zinc-500">last</span>
                    {" · "}Operators:{" "}
                    <span className="font-mono text-zinc-500">{">"}</span>,{" "}
                    <span className="font-mono text-zinc-500">{"<"}</span>,{" "}
                    <span className="font-mono text-zinc-500">{">="}</span>,{" "}
                    <span className="font-mono text-zinc-500">{"<="}</span>,{" "}
                    <span className="font-mono text-zinc-500">==</span>,{" "}
                    <span className="font-mono text-zinc-500">!=</span>
                    {" · "}Combine:{" "}
                    <span className="font-mono text-zinc-500">AND</span>,{" "}
                    <span className="font-mono text-zinc-500">OR</span>
                    {" · "}Thresholds:{" "}
                    <span className="font-mono text-zinc-500">name</span>
                    {app.target_table === "config" && (
                      <>
                        {" "}
                        · String:{" "}
                        <span className="font-mono text-zinc-500">CHANGED</span>
                        ,{" "}
                        <span className="font-mono text-zinc-500">
                          IN ('a', 'b')
                        </span>
                      </>
                    )}
                  </p>
                </div>
              )}
              {/* Available threshold variables */}
              {variables && variables.length > 0 && (
                <div className="rounded-md border border-amber-500/20 bg-zinc-900 p-3 space-y-2">
                  <p className="text-xs text-amber-400/70 font-medium">
                    Available thresholds — click to insert
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {variables.map((v) => (
                      <button
                        key={v.id}
                        type="button"
                        className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-zinc-800 px-2 py-1 text-xs font-mono text-amber-300 hover:bg-amber-500/10 hover:text-amber-200 cursor-pointer transition-colors"
                        onClick={() => {
                          setFormExpression((prev) =>
                            prev ? `${prev}${v.name}` : v.name,
                          );
                        }}
                      >
                        {v.name}
                        <span className="text-zinc-500 text-[10px] ml-0.5">
                          ({v.default_value}
                          {v.unit === "percent"
                            ? "%"
                            : v.unit === "ms"
                              ? "ms"
                              : ""}
                          )
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {/* Show resolved threshold variables */}
              {formExpression && variables && variables.length > 0 && (
                <div className="mt-2 space-y-0.5">
                  {variables
                    .filter((v) => {
                      const regex = new RegExp(
                        `(?<![a-z_])${v.name}(?![a-z0-9_(])`,
                        "i",
                      );
                      return regex.test(formExpression);
                    })
                    .map((v) => (
                      <div
                        key={v.id}
                        className="flex items-center gap-1.5 text-xs"
                      >
                        <span className="text-emerald-500 font-mono">ok</span>
                        <span className="text-amber-400 font-mono">
                          {v.name}
                        </span>
                        <span className="text-zinc-500">&rarr;</span>
                        <span className="text-zinc-300">
                          {v.display_name || v.name}
                        </span>
                        <span className="text-zinc-500">=</span>
                        <span className="text-zinc-200 font-medium">
                          {v.default_value}
                          {v.unit === "percent"
                            ? "%"
                            : v.unit === "ms"
                              ? " ms"
                              : ""}
                        </span>
                      </div>
                    ))}
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="alert-window">Window</Label>
                <select
                  id="alert-window"
                  value={formWindowField.value}
                  onChange={(e) => formWindowField.setValue(e.target.value)}
                  className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100"
                >
                  <option value="30s">30s</option>
                  <option value="1m">1m</option>
                  <option value="5m">5m</option>
                  <option value="15m">15m</option>
                  <option value="1h">1h</option>
                  <option value="6h">6h</option>
                  <option value="1d">1d</option>
                </select>
              </div>
              {formMode === "edit" && (
                <div className="space-y-1.5">
                  <Label>Enabled</Label>
                  <button
                    type="button"
                    onClick={() => setFormEnabled(!formEnabled)}
                    className={`w-full rounded-md border px-3 py-2 text-sm text-left cursor-pointer ${
                      formEnabled
                        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                        : "border-zinc-700 bg-zinc-800 text-zinc-500"
                    }`}
                  >
                    {formEnabled ? "Enabled" : "Disabled"}
                  </button>
                </div>
              )}
            </div>
            {/* Message Template */}
            <div className="space-y-1.5">
              <Label htmlFor="alert-template">
                Message Template{" "}
                <span className="font-normal text-zinc-600">(optional)</span>
              </Label>
              <textarea
                id="alert-template"
                value={formMessageTemplate}
                onChange={(e) => setFormMessageTemplate(e.target.value)}
                placeholder="{device_name} {if_name}: {in_utilization_pct}% > {$in_utilization_pct_threshold}%"
                className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 font-mono resize-y min-h-[2.5rem] focus:outline-none focus:ring-2 focus:ring-brand-500"
                rows={2}
              />
              {/* Variable badges */}
              <div className="flex flex-wrap gap-1 mt-1">
                {[
                  {
                    label: "{device_name}",
                    cls: "text-cyan-400 border-cyan-500/30",
                  },
                  {
                    label: "{if_name}",
                    cls: "text-cyan-400 border-cyan-500/30",
                  },
                  { label: "{value}", cls: "text-zinc-300 border-zinc-600" },
                  {
                    label: "{fire_count}",
                    cls: "text-zinc-300 border-zinc-600",
                  },
                  {
                    label: "{alert_name}",
                    cls: "text-zinc-300 border-zinc-600",
                  },
                ].map(({ label, cls }) => (
                  <button
                    key={label}
                    type="button"
                    className={`rounded border bg-zinc-900 px-1.5 py-0.5 text-[10px] font-mono cursor-pointer hover:bg-zinc-800 transition-colors ${cls}`}
                    onClick={() =>
                      setFormMessageTemplate((prev) => prev + label)
                    }
                  >
                    {label}
                  </button>
                ))}
                {/* Metric variables from expression */}
                {metrics
                  ?.filter((m) => {
                    const re = new RegExp(`\\b${m.name}\\b`);
                    return m.type !== "string" && re.test(formExpression);
                  })
                  .map((m) => (
                    <button
                      key={`m-${m.name}`}
                      type="button"
                      className="rounded border border-brand-500/30 bg-zinc-900 px-1.5 py-0.5 text-[10px] font-mono text-brand-400 cursor-pointer hover:bg-zinc-800 transition-colors"
                      onClick={() =>
                        setFormMessageTemplate((prev) => prev + `{${m.name}}`)
                      }
                    >
                      {`{${m.name}}`}
                    </button>
                  ))}
                {/* Threshold variables */}
                {variables
                  ?.filter((v) => {
                    const re = new RegExp(
                      `(?<![a-z_])${v.name}(?![a-z0-9_(])`,
                      "i",
                    );
                    return re.test(formExpression);
                  })
                  .map((v) => (
                    <button
                      key={`t-${v.id}`}
                      type="button"
                      className="rounded border border-amber-500/30 bg-zinc-900 px-1.5 py-0.5 text-[10px] font-mono text-amber-400 cursor-pointer hover:bg-zinc-800 transition-colors"
                      onClick={() =>
                        setFormMessageTemplate((prev) => prev + `{$${v.name}}`)
                      }
                    >
                      {`{$${v.name}}`}
                    </button>
                  ))}
              </div>
              {/* Live preview */}
              {formMessageTemplate && (
                <div className="rounded border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs">
                  <span className="text-zinc-600 text-[10px] uppercase tracking-wider">
                    Preview:{" "}
                  </span>
                  <span className="text-zinc-300">
                    {formMessageTemplate
                      .replace(/\{device_name\}/g, "switch-01")
                      .replace(/\{if_name\}/g, "Gi0/1")
                      .replace(/\{component\}/g, "CPU")
                      .replace(/\{entity_key\}/g, "device|iface")
                      .replace(/\{value\}/g, "83.2")
                      .replace(/\{fire_count\}/g, "5")
                      .replace(
                        /\{alert_name\}/g,
                        formNameField.value || "Alert",
                      )
                      .replace(/\{(\$[^}]+)\}/g, (_, name) => {
                        const v = variables?.find((v) => `$${v.name}` === name);
                        return v ? String(v.default_value) : name;
                      })
                      .replace(/\{([^}]+)\}/g, (match, name) => {
                        const m = metrics?.find((m) => m.name === name);
                        return m ? "50" : match;
                      })}
                  </span>
                </div>
              )}
            </div>
            {formError && <p className="text-sm text-red-400">{formError}</p>}
            <div className="flex gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={closeForm}
              >
                Cancel
              </Button>
              <Button type="submit" size="sm" disabled={isPending}>
                {isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {formMode === "edit" ? "Save" : "Create"}
              </Button>
            </div>
          </form>
        )}

        {!definitions || definitions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
            <Bell className="mb-2 h-8 w-8 text-zinc-600" />
            <p className="text-sm">No alert definitions for this app</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Expression</TableHead>
                <TableHead>Window</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead className="w-24"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {definitions.map((defn: AppAlertDefinition) => (
                <TableRow
                  key={defn.id}
                  className={`cursor-pointer ${editId === defn.id ? "bg-zinc-800/50" : "hover:bg-zinc-800/30"}`}
                  onClick={() => navigate(`/alerts/definitions/${defn.id}`)}
                >
                  <TableCell className="font-medium text-zinc-100">
                    {defn.name}
                  </TableCell>
                  <TableCell className="text-zinc-400 font-mono text-xs max-w-xs">
                    <div className="space-y-0.5">
                      {(defn.severity_tiers ?? []).map((t, i) => (
                        <div key={i} className="flex items-center gap-1.5">
                          <span
                            className={`inline-flex items-center rounded px-1 text-[10px] uppercase font-semibold ${
                              t.severity === "critical"
                                ? "bg-red-600 text-white"
                                : t.severity === "warning"
                                  ? "bg-orange-600 text-white"
                                  : t.severity === "info"
                                    ? "bg-sky-600 text-white"
                                    : "bg-zinc-600 text-white"
                            }`}
                          >
                            {t.severity}
                          </span>
                          <span className="truncate">{t.expression}</span>
                        </div>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-zinc-400">{defn.window}</TableCell>
                  <TableCell>
                    <Badge variant={defn.enabled ? "success" : "default"}>
                      {defn.enabled ? "On" : "Off"}
                    </Badge>
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <div className="flex gap-0.5">
                      {(() => {
                        const topExpr =
                          (defn.severity_tiers ?? []).slice(-1)[0]
                            ?.expression ?? "";
                        return (
                          !/\bCHANGED\b/.test(topExpr) || /[><=!]/.test(topExpr)
                        );
                      })() && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-zinc-500 hover:text-brand-400"
                          title="Create Recovery Alert"
                          disabled={invertDef.isPending}
                          onClick={() => handleRecovery(defn.id)}
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-zinc-500 hover:text-red-400"
                        onClick={() => deleteDef.mutate(defn.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
