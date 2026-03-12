import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, AppWindow, Code2, Loader2, Pencil, Plus, Star, Trash2 } from "lucide-react";
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
import {
  useAppDetail,
  useUpdateApp,
  useCreateAppVersion,
  useSetLatestVersion,
  useUpdateAppVersion,
  useDeleteAppVersion,
} from "@/api/hooks.ts";
import { apiGet } from "@/api/client.ts";

interface VersionDetail {
  id: string;
  version: string;
  source_code: string | null;
  requirements: string[];
  entry_class: string | null;
  checksum: string;
  published_at: string | null;
}

export function AppDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: app, isLoading } = useAppDetail(id);
  const updateApp = useUpdateApp();
  const createVersion = useCreateAppVersion();
  const setLatest = useSetLatestVersion();
  const updateVersion = useUpdateAppVersion();
  const deleteVersion = useDeleteAppVersion();

  const [activeTab, setActiveTab] = useState("overview");

  // Edit app state
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  // New version state
  const [versionOpen, setVersionOpen] = useState(false);
  const [versionString, setVersionString] = useState("");
  const [versionCode, setVersionCode] = useState("# New monitoring app\n\nclass MyCheck:\n    def run(self, config):\n        pass\n");
  const [versionReqs, setVersionReqs] = useState("");
  const [versionEntry, setVersionEntry] = useState("");
  const [versionError, setVersionError] = useState<string | null>(null);

  // Version detail viewer
  const [viewVersion, setViewVersion] = useState<VersionDetail | null>(null);
  const [loadingVersion, setLoadingVersion] = useState(false);

  // Edit version state
  const [editVersionTarget, setEditVersionTarget] = useState<VersionDetail | null>(null);
  const [editVersionCode, setEditVersionCode] = useState("");
  const [editVersionReqs, setEditVersionReqs] = useState("");
  const [editVersionEntry, setEditVersionEntry] = useState("");
  const [editVersionError, setEditVersionError] = useState<string | null>(null);

  // Delete version state
  const [deleteVersionTarget, setDeleteVersionTarget] = useState<{ id: string; version: string } | null>(null);
  const [deleteVersionError, setDeleteVersionError] = useState<string | null>(null);

  async function handleEditApp(e: React.FormEvent) {
    e.preventDefault();
    if (!id) return;
    setEditError(null);
    try {
      await updateApp.mutateAsync({ id, data: { name: editName.trim(), description: editDesc.trim() } });
      setEditOpen(false);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update");
    }
  }

  async function handleCreateVersion(e: React.FormEvent) {
    e.preventDefault();
    if (!id) return;
    setVersionError(null);
    if (!versionString.trim()) { setVersionError("Version is required."); return; }
    if (!versionCode.trim()) { setVersionError("Source code is required."); return; }
    try {
      await createVersion.mutateAsync({
        appId: id,
        data: {
          version: versionString.trim(),
          source_code: versionCode,
          requirements: versionReqs.trim() ? versionReqs.trim().split("\n").map((r) => r.trim()).filter(Boolean) : [],
          entry_class: versionEntry.trim() || undefined,
        },
      });
      setVersionString(""); setVersionCode(""); setVersionReqs(""); setVersionEntry(""); setVersionOpen(false);
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

  async function openEditVersion(versionId: string) {
    if (!id) return;
    setLoadingVersion(true);
    try {
      const res = await apiGet<VersionDetail>(`/apps/${id}/versions/${versionId}`);
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
      const res = await apiGet<VersionDetail>(`/apps/${id}/versions/${versionId}`);
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
            onClick={() => { setEditName(app.name); setEditDesc(app.description ?? ""); setEditError(null); setEditOpen(true); }}
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
                  onClick={() => { setVersionString(""); setVersionCode("# New version\n"); setVersionReqs(""); setVersionEntry(""); setVersionError(null); setVersionOpen(true); }}
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
      </Tabs>

      {/* Edit App Dialog */}
      <Dialog open={editOpen} onClose={() => setEditOpen(false)} title="Edit App">
        <form onSubmit={handleEditApp} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="app-edit-name">Name</Label>
            <Input id="app-edit-name" value={editName} onChange={(e) => setEditName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-edit-desc">Description</Label>
            <Input id="app-edit-desc" value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
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
      <Dialog open={versionOpen} onClose={() => setVersionOpen(false)} title="New Version" size="xl">
        <form onSubmit={handleCreateVersion} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="ver-string">Version</Label>
              <Input id="ver-string" placeholder="e.g. 1.1.0" value={versionString} onChange={(e) => setVersionString(e.target.value)} autoFocus />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ver-entry">Entry Class <span className="font-normal text-zinc-500">(optional)</span></Label>
              <Input id="ver-entry" placeholder="e.g. MyCheck" value={versionEntry} onChange={(e) => setVersionEntry(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Source Code (Python)</Label>
            <CodeEditor value={versionCode} onChange={setVersionCode} height="500px" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ver-reqs">Requirements <span className="font-normal text-zinc-500">(one per line)</span></Label>
            <textarea
              id="ver-reqs"
              value={versionReqs}
              onChange={(e) => setVersionReqs(e.target.value)}
              placeholder="requests>=2.28&#10;pyyaml"
              rows={3}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 placeholder:text-zinc-600"
            />
          </div>
          {versionError && <p className="text-sm text-red-400">{versionError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setVersionOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createVersion.isPending}>
              {createVersion.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Create Version
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* View Version Dialog */}
      <Dialog open={!!viewVersion} onClose={() => setViewVersion(null)} title={`Version ${viewVersion?.version ?? ""}`} size="xl">
        {viewVersion && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-md bg-zinc-800/50 px-3 py-2">
                <span className="text-zinc-500">Entry Class:</span>{" "}
                <span className="text-zinc-200 font-mono">{viewVersion.entry_class ?? "—"}</span>
              </div>
              <div className="rounded-md bg-zinc-800/50 px-3 py-2">
                <span className="text-zinc-500">Checksum:</span>{" "}
                <span className="text-zinc-200 font-mono text-xs">{viewVersion.checksum?.slice(0, 12)}...</span>
              </div>
            </div>
            {viewVersion.requirements && viewVersion.requirements.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1">Requirements</p>
                <div className="flex flex-wrap gap-1">
                  {viewVersion.requirements.map((r, i) => (
                    <Badge key={i} variant="default" className="font-mono text-xs">{r}</Badge>
                  ))}
                </div>
              </div>
            )}
            {viewVersion.source_code && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1">Source Code</p>
                <CodeEditor value={viewVersion.source_code} readOnly height="500px" />
              </div>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="secondary" onClick={() => setViewVersion(null)}>Close</Button>
        </DialogFooter>
      </Dialog>

      {/* Edit Version Dialog */}
      <Dialog open={!!editVersionTarget} onClose={() => setEditVersionTarget(null)} title={`Edit Version ${editVersionTarget?.version ?? ""}`} size="xl">
        <form onSubmit={handleEditVersion} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="edit-ver-entry">Entry Class <span className="font-normal text-zinc-500">(optional)</span></Label>
            <Input id="edit-ver-entry" placeholder="e.g. Poller" value={editVersionEntry} onChange={(e) => setEditVersionEntry(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Source Code (Python)</Label>
            <CodeEditor value={editVersionCode} onChange={setEditVersionCode} height="500px" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-ver-reqs">Requirements <span className="font-normal text-zinc-500">(one per line)</span></Label>
            <textarea
              id="edit-ver-reqs"
              value={editVersionReqs}
              onChange={(e) => setEditVersionReqs(e.target.value)}
              placeholder="requests>=2.28&#10;pyyaml"
              rows={3}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 placeholder:text-zinc-600"
            />
          </div>
          {editVersionError && <p className="text-sm text-red-400">{editVersionError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditVersionTarget(null)}>Cancel</Button>
            <Button type="submit" disabled={updateVersion.isPending}>
              {updateVersion.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save
            </Button>
          </DialogFooter>
        </form>
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
