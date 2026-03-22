import { useState, useCallback, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName, validateSemver, validateAlertWindow } from "@/lib/validation.ts";
import { ArrowLeft, AppWindow, Bell, Code2, Copy, Layout, Loader2, Pencil, Plug, Plus, RefreshCw, Star, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Tabs, TabsList, TabTrigger, TabsContent } from "@/components/ui/tabs.tsx";
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
  useAddAppConnector,
  useDeleteAppConnector,
  useConnectors,
  useAppConfigKeys,
} from "@/api/hooks.ts";
import { apiGet } from "@/api/client.ts";
import type { AppAlertDefinition, DisplayTemplate } from "@/types/api.ts";

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
}

export function AppDetailPage() {
  const { id } = useParams<{ id: string }>();
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
  const [editError, setEditError] = useState<string | null>(null);

  // New version state
  const [versionOpen, setVersionOpen] = useState(false);
  const versionField = useField("", validateSemver);
  const [versionCode, setVersionCode] = useState("# New monitoring app\n\nclass MyCheck:\n    def run(self, config):\n        pass\n");
  const [versionReqs, setVersionReqs] = useState("");
  const [versionEntry, setVersionEntry] = useState("");
  const [versionError, setVersionError] = useState<string | null>(null);
  const [newVersionTab, setNewVersionTab] = useState("code");
  const [newVersionTemplate, setNewVersionTemplate] = useState<DisplayTemplate | null>(null);
  const [versionVolatileKeys, setVersionVolatileKeys] = useState<string[]>([]);

  // Version detail viewer
  const [viewVersion, setViewVersion] = useState<VersionDetail | null>(null);
  const [loadingVersion, setLoadingVersion] = useState(false);

  // Edit version state
  const [editVersionTarget, setEditVersionTarget] = useState<VersionDetail | null>(null);
  const [editVersionCode, setEditVersionCode] = useState("");
  const [editVersionReqs, setEditVersionReqs] = useState("");
  const [editVersionEntry, setEditVersionEntry] = useState("");
  const [editVersionError, setEditVersionError] = useState<string | null>(null);
  const [editVersionVolatileKeys, setEditVersionVolatileKeys] = useState<string[]>([]);

  // Version dialog tab (for config apps)
  const [viewDialogTab, setViewDialogTab] = useState("code");
  const [editDialogTab, setEditDialogTab] = useState("code");

  // Delete version state
  const [deleteVersionTarget, setDeleteVersionTarget] = useState<{ id: string; version: string } | null>(null);
  const [deleteVersionError, setDeleteVersionError] = useState<string | null>(null);

  // Connector binding state
  const addConnector = useAddAppConnector();
  const deleteConnector = useDeleteAppConnector();
  const { data: connectorsResp } = useConnectors();
  const connectorsList = connectorsResp?.data ?? [];
  const [connBindOpen, setConnBindOpen] = useState(false);
  const [connBindAlias, setConnBindAlias] = useState("");
  const [connBindConnectorId, setConnBindConnectorId] = useState("");
  const [connBindError, setConnBindError] = useState<string | null>(null);

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
        setEditError("Config Schema is not valid JSON."); return;
      }
    }
    try {
      await updateApp.mutateAsync({ id, data: { name: editNameField.value.trim(), description: editDesc.trim(), config_schema: parsedSchema ?? {} } });
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
    if (!versionCode.trim()) { setVersionError("Source code is required."); return; }
    try {
      await createVersion.mutateAsync({
        appId: id,
        data: {
          version: versionField.value.trim(),
          source_code: versionCode,
          requirements: versionReqs.trim() ? versionReqs.trim().split("\n").map((r) => r.trim()).filter(Boolean) : [],
          entry_class: versionEntry.trim() || undefined,
          display_template: newVersionTemplate ?? undefined,
          volatile_keys: isConfigApp ? versionVolatileKeys : undefined,
        },
      });
      versionField.reset(); setVersionCode(""); setVersionReqs(""); setVersionEntry(""); setNewVersionTemplate(null); setVersionVolatileKeys([]); setNewVersionTab("code"); setVersionOpen(false);
    } catch (err) {
      setVersionError(err instanceof Error ? err.message : "Failed to create version");
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
          requirements: editVersionReqs.trim() ? editVersionReqs.trim().split("\n").map((r) => r.trim()).filter(Boolean) : [],
          entry_class: editVersionEntry.trim() || undefined,
          volatile_keys: isConfigApp ? editVersionVolatileKeys : undefined,
        },
      });
      setEditVersionTarget(null);
    } catch (err) {
      setEditVersionError(err instanceof Error ? err.message : "Failed to update version");
    }
  }

  async function handleDeleteVersion() {
    if (!id || !deleteVersionTarget) return;
    setDeleteVersionError(null);
    try {
      await deleteVersion.mutateAsync({ appId: id, versionId: deleteVersionTarget.id });
      setDeleteVersionTarget(null);
    } catch (err) {
      setDeleteVersionError(err instanceof Error ? err.message : "Failed to delete version");
    }
  }

  async function handleCloneVersion(versionId: string) {
    if (!id) return;
    try {
      await cloneVersion.mutateAsync({ appId: id, versionId });
    } catch { /* handled by React Query */ }
  }

  async function openEditVersion(versionId: string) {
    if (!id) return;
    setLoadingVersion(true);
    setEditDialogTab("code");
    try {
      const res = await apiGet<VersionDetail>(`/apps/${id}/versions/${versionId}`);
      const v = res.data;
      setEditVersionCode(v.source_code ?? "");
      setEditVersionReqs((v.requirements ?? []).join("\n"));
      setEditVersionEntry(v.entry_class ?? "");
      setEditVersionError(null);
      setEditVersionVolatileKeys(v.volatile_keys ?? []);
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
      const res = await apiGet<VersionDetail>(`/apps/${id}/versions/${versionId}`);
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
        const res = await apiGet<VersionDetail>(`/apps/${id}/versions/${versionId}`);
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
          <Button variant="ghost" size="sm"><ArrowLeft className="h-4 w-4" /> Back to Apps</Button>
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
          <Button variant="ghost" size="sm"><ArrowLeft className="h-4 w-4" /> Back to Apps</Button>
        </Link>
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold text-zinc-100">{app.name}</h2>
          <Badge variant="info">{app.app_type}</Badge>
          <button
            onClick={() => { editNameField.reset(app.name); setEditDesc(app.description ?? ""); setEditConfigSchema(app.config_schema ? JSON.stringify(app.config_schema, null, 2) : ""); setEditError(null); setEditOpen(true); }}
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
          <TabTrigger value="versions">Versions ({app.versions.length})</TabTrigger>
          <TabTrigger value="alerts">Alerts</TabTrigger>
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
                  <span className="font-mono text-sm text-zinc-100">{app.name}</span>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Type</span>
                  <Badge variant="info">{app.app_type}</Badge>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Target Table</span>
                  <Badge variant="default" className="font-mono text-xs">{app.target_table}</Badge>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Versions</span>
                  <span className="text-sm text-zinc-100">{app.versions.length}</span>
                </div>
                {app.config_schema && (
                  <div className="rounded-md bg-zinc-800/50 px-4 py-3">
                    <span className="text-sm text-zinc-400 block mb-1">Config Schema</span>
                    <pre className="text-xs font-mono text-zinc-300 whitespace-pre-wrap">
                      {JSON.stringify(app.config_schema, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Required Connectors */}
          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Plug className="h-4 w-4" /> Required Connectors
                <Button size="sm" variant="secondary" className="ml-auto gap-1.5" onClick={() => { setConnBindAlias(""); setConnBindConnectorId(""); setConnBindError(null); setConnBindOpen(true); }}>
                  <Plus className="h-3 w-3" /> Add Connector
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {app.connector_bindings && app.connector_bindings.length > 0 ? (
                <div className="space-y-2">
                  {app.connector_bindings.map((cb) => (
                    <div key={cb.alias} className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                      <div className="flex items-center gap-3">
                        <Badge variant="info" className="text-xs gap-1">
                          <Plug className="h-2.5 w-2.5" />
                          {cb.connector_name || cb.alias}
                        </Badge>
                        <code className="text-xs text-zinc-400 bg-zinc-900 px-1.5 py-0.5 rounded">
                          alias: {cb.alias}
                        </code>
                      </div>
                      <div className="flex items-center gap-2">
                        {cb.use_latest ? (
                          <Badge variant="success" className="text-xs">latest</Badge>
                        ) : (
                          <Badge variant="default" className="text-xs">pinned</Badge>
                        )}
                        <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-zinc-500 hover:text-red-400" onClick={() => { if (id) deleteConnector.mutate({ appId: id, alias: cb.alias }); }}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-zinc-500">No connectors bound. Click "Add Connector" to bind one.</p>
              )}
            </CardContent>
          </Card>

          {/* Add Connector Binding Dialog */}
          {connBindOpen && (
            <Dialog open onClose={() => setConnBindOpen(false)} title="Add Connector Binding">
              <div className="space-y-4">
                <div>
                  <Label>Alias</Label>
                  <Input placeholder='e.g. "snmp"' value={connBindAlias} onChange={e => setConnBindAlias(e.target.value)} />
                  <p className="text-xs text-zinc-500 mt-1">The alias your app code uses to reference this connector (e.g. context.connectors["snmp"])</p>
                </div>
                <div>
                  <Label>Connector</Label>
                  <select className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100" value={connBindConnectorId} onChange={e => setConnBindConnectorId(e.target.value)}>
                    <option value="">Select a connector...</option>
                    {connectorsList?.map(c => (
                      <option key={c.id} value={c.id}>{c.name} — {c.description}</option>
                    ))}
                  </select>
                </div>
                {connBindError && <p className="text-sm text-red-400">{connBindError}</p>}
              </div>
              <DialogFooter>
                <Button variant="secondary" onClick={() => setConnBindOpen(false)}>Cancel</Button>
                <Button onClick={() => {
                  if (!connBindAlias.trim() || !connBindConnectorId) {
                    setConnBindError("Alias and connector are required");
                    return;
                  }
                  if (!id) return;
                  addConnector.mutate({ appId: id, data: { alias: connBindAlias.trim(), connector_id: connBindConnectorId, use_latest: true } }, {
                    onSuccess: () => setConnBindOpen(false),
                    onError: (err: unknown) => setConnBindError(err instanceof Error ? err.message : String(err)),
                  });
                }} disabled={addConnector.isPending}>
                  {addConnector.isPending ? "Adding..." : "Add"}
                </Button>
              </DialogFooter>
            </Dialog>
          )}
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
                  onClick={() => { versionField.reset(); setVersionCode("# New version\n"); setVersionReqs(""); setVersionEntry(""); setVersionError(null); setNewVersionTab("code"); setNewVersionTemplate(null); setVersionOpen(true); }}
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
                      <TableHead className="w-40"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {app.versions.map((v) => (
                      <TableRow key={v.id}>
                        <TableCell className="font-mono text-sm text-zinc-100">{v.version}</TableCell>
                        <TableCell className="font-mono text-xs text-zinc-500">{v.id.slice(0, 8)}</TableCell>
                        <TableCell>
                          {v.is_latest && (
                            <Badge variant="info" className="gap-1">
                              <Star className="h-3 w-3" /> Latest
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="flex items-center gap-1">
                          {!v.is_latest && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => id && setLatest.mutate({ appId: id, versionId: v.id })}
                              disabled={setLatest.isPending}
                              title="Set as Latest"
                            >
                              <Star className="h-3.5 w-3.5" /> Set Latest
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => loadVersion(v.id)}
                            disabled={loadingVersion}
                          >
                            <Code2 className="h-3.5 w-3.5" /> View
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => openEditVersion(v.id)}
                            disabled={loadingVersion}
                          >
                            <Pencil className="h-3.5 w-3.5" /> Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="gap-1"
                            disabled={cloneVersion.isPending}
                            onClick={() => handleCloneVersion(v.id)}
                            title="Clone version"
                          >
                            <Copy className="h-3.5 w-3.5" />
                          </Button>
                          <button
                            onClick={() => setDeleteVersionTarget({ id: v.id, version: v.version })}
                            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                            title="Delete version"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
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
      </Tabs>

      {/* Edit App Dialog */}
      <Dialog open={editOpen} onClose={() => setEditOpen(false)} title="Edit App">
        <form onSubmit={handleEditApp} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="app-edit-name">Name</Label>
            <Input id="app-edit-name" value={editNameField.value} onChange={editNameField.onChange} onBlur={editNameField.onBlur} autoFocus />
            {editNameField.error && <p className="text-xs text-red-400 mt-0.5">{editNameField.error}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-edit-desc">Description</Label>
            <Input id="app-edit-desc" value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-edit-schema">Config Schema <span className="font-normal text-zinc-500">(JSON, optional)</span></Label>
            <textarea
              id="app-edit-schema"
              value={editConfigSchema}
              onChange={(e) => setEditConfigSchema(e.target.value)}
              placeholder='{"type": "object", "properties": { ... }}'
              rows={6}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 placeholder:text-zinc-600"
            />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={updateApp.isPending}>
              {updateApp.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* New Version Dialog */}
      <Dialog open={versionOpen} onClose={() => setVersionOpen(false)} title="New Version" size="fullscreen">
        {isConfigApp ? (
          <Tabs value={newVersionTab} onChange={setNewVersionTab}>
            <TabsList>
              <TabTrigger value="code">
                <span className="flex items-center gap-1.5"><Code2 className="h-3.5 w-3.5" /> Code</span>
              </TabTrigger>
              <TabTrigger value="template">
                <span className="flex items-center gap-1.5"><Layout className="h-3.5 w-3.5" /> Display Template</span>
              </TabTrigger>
            </TabsList>
            <TabsContent value="code">
              <NewVersionCodeForm
                versionField={versionField}
                versionCode={versionCode} setVersionCode={setVersionCode}
                versionReqs={versionReqs} setVersionReqs={setVersionReqs}
                versionEntry={versionEntry} setVersionEntry={setVersionEntry}
                versionError={versionError}
                onSubmit={handleCreateVersion}
                onCancel={() => setVersionOpen(false)}
                isPending={createVersion.isPending}
                volatileKeys={versionVolatileKeys} setVolatileKeys={setVersionVolatileKeys}
                isConfigApp={true}
                appId={id!}
              />
            </TabsContent>
            <TabsContent value="template">
              <DisplayTemplateEditor
                appId={id!}
                initialTemplate={newVersionTemplate}
                onSave={async (tpl) => { setNewVersionTemplate(tpl); setNewVersionTab("code"); }}
              />
            </TabsContent>
          </Tabs>
        ) : (
          <NewVersionCodeForm
            versionField={versionField}
            versionCode={versionCode} setVersionCode={setVersionCode}
            versionReqs={versionReqs} setVersionReqs={setVersionReqs}
            versionEntry={versionEntry} setVersionEntry={setVersionEntry}
            versionError={versionError}
            onSubmit={handleCreateVersion}
            onCancel={() => setVersionOpen(false)}
            isPending={createVersion.isPending}
          />
        )}
      </Dialog>

      {/* View Version Dialog */}
      <Dialog open={!!viewVersion} onClose={() => setViewVersion(null)} title={`Version ${viewVersion?.version ?? ""}`} size="fullscreen">
        {viewVersion && (
          isConfigApp ? (
            <Tabs value={viewDialogTab} onChange={setViewDialogTab}>
              <TabsList>
                <TabTrigger value="code">
                  <span className="flex items-center gap-1.5"><Code2 className="h-3.5 w-3.5" /> Code</span>
                </TabTrigger>
                <TabTrigger value="template">
                  <span className="flex items-center gap-1.5"><Layout className="h-3.5 w-3.5" /> Display Template</span>
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
                  onSave={(tpl) => handleSaveDisplayTemplate(viewVersion.id, tpl)}
                />
              </TabsContent>
            </Tabs>
          ) : (
            <VersionCodeView version={viewVersion} />
          )
        )}
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
          <Button variant="secondary" onClick={() => setViewVersion(null)}>Close</Button>
        </DialogFooter>
      </Dialog>

      {/* Edit Version Dialog */}
      <Dialog open={!!editVersionTarget} onClose={() => setEditVersionTarget(null)} title={`Edit Version ${editVersionTarget?.version ?? ""}`} size="fullscreen">
        {isConfigApp ? (
          <Tabs value={editDialogTab} onChange={setEditDialogTab}>
            <TabsList>
              <TabTrigger value="code">
                <span className="flex items-center gap-1.5"><Code2 className="h-3.5 w-3.5" /> Code</span>
              </TabTrigger>
              <TabTrigger value="template">
                <span className="flex items-center gap-1.5"><Layout className="h-3.5 w-3.5" /> Display Template</span>
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
                volatileKeys={editVersionVolatileKeys} setVolatileKeys={setEditVersionVolatileKeys}
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
                  onSave={(tpl) => handleSaveDisplayTemplate(editVersionTarget.id, tpl)}
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
          />
        )}
      </Dialog>

      {/* Delete Version Dialog */}
      <Dialog open={!!deleteVersionTarget} onClose={() => { setDeleteVersionTarget(null); setDeleteVersionError(null); }} title="Delete Version">
        <p className="text-sm text-zinc-400">
          Delete version <span className="font-semibold text-zinc-200">{deleteVersionTarget?.version}</span>?
        </p>
        {deleteVersionError && <p className="text-sm text-red-400 mt-2">{deleteVersionError}</p>}
        <DialogFooter>
          <Button variant="secondary" onClick={() => { setDeleteVersionTarget(null); setDeleteVersionError(null); }}>Cancel</Button>
          <Button variant="destructive" onClick={handleDeleteVersion} disabled={deleteVersion.isPending}>
            {deleteVersion.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
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
          <span className="text-zinc-200 font-mono">{version.entry_class ?? "\u2014"}</span>
        </div>
        <div className="rounded-md bg-zinc-800/50 px-3 py-2">
          <span className="text-zinc-500">Checksum:</span>{" "}
          <span className="text-zinc-200 font-mono text-xs">{version.checksum?.slice(0, 12)}...</span>
        </div>
      </div>
      {version.requirements && version.requirements.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1">Requirements</p>
          <div className="flex flex-wrap gap-1">
            {version.requirements.map((r, i) => (
              <Badge key={i} variant="default" className="font-mono text-xs">{r}</Badge>
            ))}
          </div>
        </div>
      )}
      {version.source_code && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1">Source Code</p>
          <CodeEditor value={version.source_code} readOnly height="calc(100vh - 300px)" />
        </div>
      )}
    </div>
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

  const toggleKey = useCallback((key: string) => {
    if (keys.includes(key)) {
      setKeys(keys.filter((k) => k !== key));
    } else {
      setKeys([...keys, key]);
    }
  }, [keys, setKeys]);

  return (
    <div className="space-y-2">
      <Label className="text-sm">Volatile Keys</Label>
      <p className="text-xs text-zinc-500">
        Keys excluded from change detection. Volatile keys change every poll cycle and won't create change history entries.
      </p>

      <div className="border border-zinc-800 rounded-lg max-h-[300px] overflow-auto">
        {allKeys.map((key) => (
          <div key={key} className="flex items-center justify-between px-3 py-1.5 border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/30">
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
          <p className="text-xs text-zinc-600 py-4 text-center">No config keys detected yet. Run the app once to populate.</p>
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
  volatileKeys, setVolatileKeys,
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
  volatileKeys?: string[]; setVolatileKeys?: (v: string[]) => void;
  isConfigApp?: boolean;
  appId?: string;
}) {
  const reqsList = useMemo(
    () => editVersionReqs.trim() ? editVersionReqs.trim().split("\n").filter(Boolean) : [],
    [editVersionReqs],
  );

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="edit-ver-entry">Entry Class <span className="font-normal text-zinc-500">(optional)</span></Label>
        <Input id="edit-ver-entry" placeholder="e.g. Poller" value={editVersionEntry} onChange={(e) => setEditVersionEntry(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Label>Source Code (Python)</Label>
        <CodeEditor value={editVersionCode} onChange={setEditVersionCode} height="calc(100vh - 300px)" />
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
      {editVersionError && <p className="text-sm text-red-400">{editVersionError}</p>}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={isPending}>
          {isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save
        </Button>
      </DialogFooter>
    </form>
  );
}

function NewVersionCodeForm({
  versionField,
  versionCode, setVersionCode,
  versionReqs, setVersionReqs,
  versionEntry, setVersionEntry,
  versionError,
  onSubmit,
  onCancel,
  isPending,
  volatileKeys, setVolatileKeys,
  isConfigApp,
  appId,
}: {
  versionField: { value: string; onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => void; onBlur: () => void; error: string | null };
  versionCode: string; setVersionCode: (v: string) => void;
  versionReqs: string; setVersionReqs: (v: string) => void;
  versionEntry: string; setVersionEntry: (v: string) => void;
  versionError: string | null;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
  isPending: boolean;
  volatileKeys?: string[]; setVolatileKeys?: (v: string[]) => void;
  isConfigApp?: boolean;
  appId?: string;
}) {
  const reqsList = useMemo(
    () => versionReqs.trim() ? versionReqs.trim().split("\n").filter(Boolean) : [],
    [versionReqs],
  );

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="ver-string">Version</Label>
          <Input id="ver-string" placeholder="e.g. 1.1.0" value={versionField.value} onChange={versionField.onChange} onBlur={versionField.onBlur} autoFocus />
          {versionField.error && <p className="text-xs text-red-400 mt-0.5">{versionField.error}</p>}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ver-entry">Entry Class <span className="font-normal text-zinc-500">(optional)</span></Label>
          <Input id="ver-entry" placeholder="e.g. MyCheck" value={versionEntry} onChange={(e) => setVersionEntry(e.target.value)} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label>Source Code (Python)</Label>
        <CodeEditor value={versionCode} onChange={setVersionCode} height="calc(100vh - 300px)" />
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
      {versionError && <p className="text-sm text-red-400">{versionError}</p>}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={isPending}>
          {isPending && <Loader2 className="h-4 w-4 animate-spin" />} Create Version
        </Button>
      </DialogFooter>
    </form>
  );
}


// ── Alerts Tab ──────────────────────────────────────────

function AlertsTab({ appId, app }: { appId: string; app: { target_table?: string; versions: Array<{ id: string; version: string; is_latest: boolean }> } }) {
  const { data: definitionsResp, isLoading } = useAlertDefinitions(appId);
  const definitions = definitionsResp?.data ?? [];
  const { data: metrics } = useAlertMetrics(appId);
  const createDef = useCreateAlertDefinition();
  const updateDef = useUpdateAlertDefinition();
  const deleteDef = useDeleteAlertDefinition();
  const invertDef = useInvertAlertDefinition();

  // Form state — used for both create and edit
  const [formMode, setFormMode] = useState<"closed" | "create" | "edit">("closed");
  const [editId, setEditId] = useState<string | null>(null);
  const formNameField = useField("", validateName);
  const [formExpression, setFormExpression] = useState("");
  const formWindowField = useField("5m", validateAlertWindow);
  const [formSeverity, setFormSeverity] = useState("warning");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);

  const latestVersion = app.versions.find((v) => v.is_latest) ?? app.versions[0];

  const openCreate = (prefill?: { name?: string; expression?: string; window?: string; severity?: string }) => {
    setFormMode("create");
    setEditId(null);
    formNameField.reset(prefill?.name ?? "");
    setFormExpression(prefill?.expression ?? "");
    formWindowField.reset(prefill?.window ?? "5m");
    setFormSeverity(prefill?.severity ?? "warning");
    setFormEnabled(true);
    setFormError(null);
  };

  const openEdit = (defn: AppAlertDefinition) => {
    setFormMode("edit");
    setEditId(defn.id);
    formNameField.reset(defn.name);
    setFormExpression(defn.expression);
    formWindowField.reset(defn.window);
    setFormSeverity(defn.severity);
    setFormEnabled(defn.enabled);
    setFormError(null);
  };

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
    if (!validateAll(formNameField, formWindowField)) return;
    try {
      if (formMode === "edit" && editId) {
        await updateDef.mutateAsync({
          id: editId,
          name: formNameField.value,
          expression: formExpression,
          window: formWindowField.value,
          severity: formSeverity,
          enabled: formEnabled,
        });
      } else {
        if (!latestVersion) {
          setFormError("No versions found. Create a version first.");
          return;
        }
        await createDef.mutateAsync({
          app_id: appId,
          app_version_id: latestVersion.id,
          name: formNameField.value,
          expression: formExpression,
          window: formWindowField.value,
          severity: formSeverity,
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
        severity: d.severity,
      });
    } catch { /* noop */ }
  };

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
          <Button size="sm" variant="secondary" className="ml-auto" onClick={() => openCreate()}>
            <Plus className="h-3.5 w-3.5" /> New Alert
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {formMode !== "closed" && (
          <form onSubmit={handleSubmit} className="mb-6 space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium text-zinc-500 uppercase tracking-wide">
                {formMode === "edit" ? "Edit Alert" : "New Alert"}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="alert-name">Name</Label>
                <Input id="alert-name" value={formNameField.value} onChange={formNameField.onChange} onBlur={formNameField.onBlur} required />
                {formNameField.error && <p className="text-xs text-red-400 mt-0.5">{formNameField.error}</p>}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="alert-severity">Severity</Label>
                <select
                  id="alert-severity"
                  value={formSeverity}
                  onChange={(e) => setFormSeverity(e.target.value)}
                  className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100"
                >
                  <option value="info">Info</option>
                  <option value="recovery">Recovery</option>
                  <option value="warning">Warning</option>
                  <option value="critical">Critical</option>
                  <option value="emergency">Emergency</option>
                </select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="alert-expr">Expression</Label>
              <Input
                id="alert-expr"
                value={formExpression}
                onChange={(e) => setFormExpression(e.target.value)}
                placeholder='e.g. avg(rtt_ms) > 100'
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
                          const snippet = m.type === "string"
                            ? `${m.name} != ''`
                            : `${fn}(${m.name}) > `;
                          setFormExpression((prev) =>
                            prev ? `${prev} AND ${snippet}` : snippet
                          );
                        }}
                        title={m.description}
                      >
                        <span className={m.type === "string" ? "text-amber-400" : "text-brand-400"}>
                          {m.type === "string" ? "Aa" : "#"}
                        </span>
                        {m.name}
                      </button>
                    ))}
                  </div>
                  <p className="text-[10px] text-zinc-600 leading-tight">
                    Functions: <span className="font-mono text-zinc-500">avg</span>, <span className="font-mono text-zinc-500">max</span>, <span className="font-mono text-zinc-500">min</span>, <span className="font-mono text-zinc-500">sum</span>, <span className="font-mono text-zinc-500">count</span>, <span className="font-mono text-zinc-500">last</span>
                    {" · "}Operators: <span className="font-mono text-zinc-500">{">"}</span>, <span className="font-mono text-zinc-500">{"<"}</span>, <span className="font-mono text-zinc-500">{">="}</span>, <span className="font-mono text-zinc-500">{"<="}</span>, <span className="font-mono text-zinc-500">==</span>, <span className="font-mono text-zinc-500">!=</span>
                    {" · "}Combine: <span className="font-mono text-zinc-500">AND</span>, <span className="font-mono text-zinc-500">OR</span>
                    {app.target_table === "config" && (
                      <> · String: <span className="font-mono text-zinc-500">CHANGED</span>, <span className="font-mono text-zinc-500">IN ('a', 'b')</span></>
                    )}
                  </p>
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
            {formError && <p className="text-sm text-red-400">{formError}</p>}
            <div className="flex gap-2">
              <Button type="button" variant="secondary" size="sm" onClick={closeForm}>Cancel</Button>
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
                <TableHead>Severity</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead className="w-24"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {definitions.map((defn: AppAlertDefinition) => (
                <TableRow
                  key={defn.id}
                  className={`cursor-pointer ${editId === defn.id ? "bg-zinc-800/50" : "hover:bg-zinc-800/30"}`}
                  onClick={() => openEdit(defn)}
                >
                  <TableCell className="font-medium text-zinc-100">{defn.name}</TableCell>
                  <TableCell className="text-zinc-400 font-mono text-xs max-w-xs truncate">{defn.expression}</TableCell>
                  <TableCell className="text-zinc-400">{defn.window}</TableCell>
                  <TableCell>
                    <Badge variant={severityVariant(defn.severity)}>{defn.severity}</Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={defn.enabled ? "success" : "default"}>
                      {defn.enabled ? "On" : "Off"}
                    </Badge>
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <div className="flex gap-0.5">
                      {(!/\bCHANGED\b/.test(defn.expression) || /[><=!]/.test(defn.expression)) && (
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
