import { useState, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateSemver } from "@/lib/validation.ts";
import { ArrowLeft, Code2, Copy, Loader2, Pencil, Plug, Plus, Star } from "lucide-react";
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
import { ModulePicker } from "@/components/ModulePicker.tsx";
import { VersionActions } from "@/components/VersionActions.tsx";
import {
  useConnectorDetail,
  useUpdateConnector,
  useCreateConnectorVersion,
  useSetConnectorLatest,
  useUpdateConnectorVersion,
  useDeleteConnectorVersion,
  useCloneConnectorVersion,
} from "@/api/hooks.ts";
import { apiGet } from "@/api/client.ts";
import type { ConnectorVersionDetail } from "@/types/api.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

export function ConnectorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: connector, isLoading } = useConnectorDetail(id);
  const updateConnector = useUpdateConnector();
  const createVersion = useCreateConnectorVersion();
  const setLatest = useSetConnectorLatest();
  const updateVersion = useUpdateConnectorVersion();
  const deleteVersion = useDeleteConnectorVersion();
  const cloneVersion = useCloneConnectorVersion();
  const tz = useTimezone();

  const [activeTab, setActiveTab] = useState("overview");

  // Edit connector state
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  // New version state
  const [versionOpen, setVersionOpen] = useState(false);
  const versionField = useField("", validateSemver);
  const [versionCode, setVersionCode] = useState("# New connector\n\nclass MyConnector:\n    def connect(self, config):\n        pass\n");
  const [versionReqs, setVersionReqs] = useState("");
  const [versionEntry, setVersionEntry] = useState("");
  const [versionError, setVersionError] = useState<string | null>(null);

  // Version detail viewer
  const [viewVersion, setViewVersion] = useState<ConnectorVersionDetail | null>(null);
  const [loadingVersion, setLoadingVersion] = useState(false);

  // Edit version state
  const [editVersionTarget, setEditVersionTarget] = useState<ConnectorVersionDetail | null>(null);
  const [editVersionCode, setEditVersionCode] = useState("");
  const [editVersionReqs, setEditVersionReqs] = useState("");
  const [editVersionEntry, setEditVersionEntry] = useState("");
  const [editVersionError, setEditVersionError] = useState<string | null>(null);

  // Delete version state
  const [deleteVersionTarget, setDeleteVersionTarget] = useState<{ id: string; version: string } | null>(null);
  const [deleteVersionError, setDeleteVersionError] = useState<string | null>(null);

  async function handleEditConnector(e: React.FormEvent) {
    e.preventDefault();
    if (!id) return;
    setEditError(null);
    try {
      await updateConnector.mutateAsync({ id, data: { name: editName.trim(), description: editDesc.trim() } });
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
        connectorId: id,
        data: {
          version: versionField.value.trim(),
          source_code: versionCode,
          requirements: versionReqs.trim() ? versionReqs.trim().split("\n").map((r) => r.trim()).filter(Boolean) : [],
          entry_class: versionEntry.trim() || undefined,
        },
      });
      versionField.reset(); setVersionCode(""); setVersionReqs(""); setVersionEntry(""); setVersionOpen(false);
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
        connectorId: id,
        versionId: editVersionTarget.id,
        data: {
          source_code: editVersionCode,
          requirements: editVersionReqs.trim() ? editVersionReqs.trim().split("\n").map((r) => r.trim()).filter(Boolean) : [],
          entry_class: editVersionEntry.trim() || undefined,
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
      await deleteVersion.mutateAsync({ connectorId: id, versionId: deleteVersionTarget.id });
      setDeleteVersionTarget(null);
    } catch (err) {
      setDeleteVersionError(err instanceof Error ? err.message : "Failed to delete version");
    }
  }

  async function handleCloneVersion(versionId: string) {
    if (!id) return;
    try {
      await cloneVersion.mutateAsync({ connectorId: id, versionId });
    } catch { /* handled by React Query */ }
  }

  async function openEditVersion(versionId: string) {
    if (!id) return;
    setLoadingVersion(true);
    try {
      const res = await apiGet<ConnectorVersionDetail>(`/connectors/${id}/versions/${versionId}`);
      const v = res.data;
      setEditVersionCode(v.source_code ?? "");
      setEditVersionReqs((v.requirements ?? []).join("\n"));
      setEditVersionEntry(v.entry_class ?? "");
      setEditVersionError(null);
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
    try {
      const res = await apiGet<ConnectorVersionDetail>(`/connectors/${id}/versions/${versionId}`);
      setViewVersion(res.data);
    } catch {
      // silent
    } finally {
      setLoadingVersion(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  if (!connector) {
    return (
      <div className="space-y-4">
        <Link to="/connectors">
          <Button variant="ghost" size="sm"><ArrowLeft className="h-4 w-4" /> Back to Connectors</Button>
        </Link>
        <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
          <Plug className="mb-2 h-8 w-8 text-zinc-600" />
          <p className="text-sm">Connector not found</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="space-y-1.5">
        <Link to="/connectors">
          <Button variant="ghost" size="sm"><ArrowLeft className="h-4 w-4" /> Back to Connectors</Button>
        </Link>
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold text-zinc-100">{connector.name}</h2>
          <Badge variant="info">{connector.connector_type}</Badge>
          {connector.is_builtin && <Badge variant="success">built-in</Badge>}
          <button
            onClick={() => { setEditName(connector.name); setEditDesc(connector.description ?? ""); setEditError(null); setEditOpen(true); }}
            className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
            title="Edit"
          >
            <Pencil className="h-4 w-4" />
          </button>
        </div>
        {connector.description && (
          <p className="text-sm text-zinc-400">{connector.description}</p>
        )}
      </div>

      <Tabs value={activeTab} onChange={setActiveTab}>
        <TabsList>
          <TabTrigger value="overview">Overview</TabTrigger>
          <TabTrigger value="versions">Versions ({connector.versions.length})</TabTrigger>
        </TabsList>

        <TabsContent value="overview">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Plug className="h-4 w-4" /> Connector Details
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3 max-w-md">
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Name</span>
                  <span className="font-mono text-sm text-zinc-100">{connector.name}</span>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Type</span>
                  <Badge variant="info">{connector.connector_type}</Badge>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Built-in</span>
                  <span className="text-sm text-zinc-100">{connector.is_builtin ? "Yes" : "No"}</span>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Versions</span>
                  <span className="text-sm text-zinc-100">{connector.versions.length}</span>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Description</span>
                  <span className="text-sm text-zinc-100">{connector.description || "\u2014"}</span>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Created</span>
                  <span className="text-sm text-zinc-100">{formatDate(connector.created_at, tz)}</span>
                </div>
                <div className="flex items-center justify-between rounded-md bg-zinc-800/50 px-4 py-3">
                  <span className="text-sm text-zinc-400">Updated</span>
                  <span className="text-sm text-zinc-100">{formatDate(connector.updated_at, tz)}</span>
                </div>
              </div>
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
                  onClick={() => { versionField.reset(); setVersionCode("# New connector version\n"); setVersionReqs(""); setVersionEntry(""); setVersionError(null); setVersionOpen(true); }}
                >
                  <Plus className="h-4 w-4" /> New Version
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {connector.versions.length === 0 ? (
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
                      <TableHead className="w-36"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {connector.versions.map((v) => (
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
                        <TableCell>
                          <VersionActions
                            isLatest={v.is_latest}
                            onSetLatest={() => id && setLatest.mutate({ connectorId: id, versionId: v.id })}
                            onView={() => loadVersion(v.id)}
                            onEdit={() => openEditVersion(v.id)}
                            onClone={() => handleCloneVersion(v.id)}
                            onDelete={() => setDeleteVersionTarget({ id: v.id, version: v.version })}
                            disabled={loadingVersion || setLatest.isPending || cloneVersion.isPending}
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
      </Tabs>

      {/* Edit Connector Dialog */}
      <Dialog open={editOpen} onClose={() => setEditOpen(false)} title="Edit Connector">
        <form onSubmit={handleEditConnector} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="conn-edit-name">Name</Label>
            <Input id="conn-edit-name" value={editName} onChange={(e) => setEditName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="conn-edit-desc">Description</Label>
            <Input id="conn-edit-desc" value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={updateConnector.isPending}>
              {updateConnector.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* New Version Dialog */}
      <Dialog open={versionOpen} onClose={() => setVersionOpen(false)} title="New Version" size="fullscreen">
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
      </Dialog>

      {/* View Version Dialog */}
      <Dialog open={!!viewVersion} onClose={() => setViewVersion(null)} title={`Version ${viewVersion?.version ?? ""}`} size="fullscreen">
        {viewVersion && (
          <VersionCodeView version={viewVersion} />
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

// ── Helper components ────────────────────────────────────

function VersionCodeView({ version }: { version: ConnectorVersionDetail }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-md bg-zinc-800/50 px-3 py-2">
          <span className="text-zinc-500">Entry Class:</span>{" "}
          <span className="text-zinc-200 font-mono">{version.entry_class ?? "\u2014"}</span>
        </div>
        <div className="rounded-md bg-zinc-800/50 px-3 py-2">
          <span className="text-zinc-500">Checksum:</span>{" "}
          <span className="text-zinc-200 font-mono text-xs">{version.checksum ? `${version.checksum.slice(0, 12)}...` : "\u2014"}</span>
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
}) {
  const reqsList = useMemo(
    () => editVersionReqs.trim() ? editVersionReqs.trim().split("\n").filter(Boolean) : [],
    [editVersionReqs],
  );

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="edit-ver-entry">Entry Class <span className="font-normal text-zinc-500">(optional)</span></Label>
        <Input id="edit-ver-entry" placeholder="e.g. MyConnector" value={editVersionEntry} onChange={(e) => setEditVersionEntry(e.target.value)} />
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
}: {
  versionField: { value: string; onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => void; onBlur: () => void; error: string | null };
  versionCode: string; setVersionCode: (v: string) => void;
  versionReqs: string; setVersionReqs: (v: string) => void;
  versionEntry: string; setVersionEntry: (v: string) => void;
  versionError: string | null;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
  isPending: boolean;
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
          <Input id="ver-string" placeholder="e.g. 1.0.0" value={versionField.value} onChange={versionField.onChange} onBlur={versionField.onBlur} autoFocus />
          {versionField.error && <p className="text-xs text-red-400 mt-0.5">{versionField.error}</p>}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ver-entry">Entry Class <span className="font-normal text-zinc-500">(optional)</span></Label>
          <Input id="ver-entry" placeholder="e.g. MyConnector" value={versionEntry} onChange={(e) => setVersionEntry(e.target.value)} />
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
