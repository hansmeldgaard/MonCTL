import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  Loader2,
  Package,
  ShieldCheck,
  ShieldOff,
  Trash2,
  Upload,
  Verified,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  usePythonModules,
  useNetworkStatus,
  useToggleModuleApproval,
  useToggleModuleVerify,
  useDeletePythonModule,
  useDeleteModuleVersion,
  usePythonModuleDetail,
  useAutoResolve,
} from "@/api/hooks.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { formatDate } from "@/lib/utils.ts";
import { WheelUploadDialog } from "@/components/WheelUploadDialog.tsx";
import { PyPIImportDialog } from "@/components/PyPIImportDialog.tsx";
import type { PythonModuleSummary } from "@/types/api.ts";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function NetworkBadge({ mode }: { mode: "offline" | "proxy" | "direct" }) {
  switch (mode) {
    case "direct":
      return (
        <Badge variant="success" className="gap-1">
          <Wifi className="h-3 w-3" /> Direct
        </Badge>
      );
    case "proxy":
      return (
        <Badge variant="info" className="gap-1">
          <Wifi className="h-3 w-3" /> Proxy
        </Badge>
      );
    case "offline":
      return (
        <Badge variant="default" className="gap-1">
          <WifiOff className="h-3 w-3" /> Offline
        </Badge>
      );
  }
}

function ModuleVersionsRow({ moduleId }: { moduleId: string }) {
  const { data: detail, isLoading } = usePythonModuleDetail(moduleId);
  const toggleVerify = useToggleModuleVerify();
  const deleteVersion = useDeleteModuleVersion();
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; version: string } | null>(null);

  if (isLoading) {
    return (
      <TableRow>
        <TableCell colSpan={8} className="py-4">
          <div className="flex items-center justify-center">
            <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />
          </div>
        </TableCell>
      </TableRow>
    );
  }

  if (!detail || detail.versions.length === 0) {
    return (
      <TableRow>
        <TableCell colSpan={8} className="py-3 text-center text-sm text-zinc-500">
          No versions
        </TableCell>
      </TableRow>
    );
  }

  return (
    <>
      {detail.versions.map((v) => (
        <><TableRow key={v.id} className="bg-zinc-800/20">
          <TableCell className="pl-10">
            <span className="font-mono text-xs text-zinc-300">{v.version}</span>
          </TableCell>
          <TableCell>
            {v.dependencies.length === 0 ? (
              <span className="text-xs text-zinc-600">--</span>
            ) : (v.dep_missing ?? []).length === 0 ? (
              <Badge variant="success" className="gap-1 text-[10px]">
                <CheckCircle2 className="h-3 w-3" /> {v.dependencies.length} deps OK
              </Badge>
            ) : (
              <Badge variant="destructive" className="gap-1 text-[10px]">
                <AlertTriangle className="h-3 w-3" /> {(v.dep_missing ?? []).length}/{v.dependencies.length} missing
              </Badge>
            )}
          </TableCell>
          <TableCell>
            {v.is_verified ? (
              <Badge variant="success" className="gap-1 text-[10px]">
                <Verified className="h-3 w-3" /> Verified
              </Badge>
            ) : (
              <Badge variant="default" className="text-[10px]">Unverified</Badge>
            )}
          </TableCell>
          <TableCell>
            <div className="space-y-0.5">
              {v.wheel_files.map((w) => (
                <div key={w.id} className="flex items-center gap-2 text-xs">
                  <span className="font-mono text-zinc-400 truncate max-w-[200px]">
                    {w.filename}
                  </span>
                  <span className="text-zinc-600">{formatBytes(w.file_size)}</span>
                  <Badge variant="default" className="text-[9px]">
                    {w.python_tag}-{w.abi_tag}-{w.platform_tag}
                  </Badge>
                </div>
              ))}
              {v.wheel_files.length === 0 && (
                <span className="text-xs text-zinc-600">No wheels</span>
              )}
            </div>
          </TableCell>
          <TableCell>
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  toggleVerify.mutate({
                    moduleId,
                    versionId: v.id,
                    is_verified: !v.is_verified,
                  })
                }
                disabled={toggleVerify.isPending}
                title={v.is_verified ? "Unverify" : "Verify"}
              >
                <Verified className="h-3.5 w-3.5" />
              </Button>
              <button
                onClick={() => setDeleteTarget({ id: v.id, version: v.version })}
                className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                title="Delete version"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </TableCell>
        </TableRow>
        {v.dependencies.length > 0 && (
          <TableRow key={`${v.id}-deps`} className="bg-zinc-800/10">
            <TableCell colSpan={8} className="pl-14 py-2">
              <div className="text-xs space-y-1">
                <span className="font-semibold text-zinc-500 uppercase tracking-wider text-[10px]">Dependencies</span>
                <div className="flex flex-wrap gap-1.5">
                  {(v.dep_resolved ?? []).map((d: string) => (
                    <Badge key={d} variant="default" className="font-mono text-[10px] gap-1">
                      <CheckCircle2 className="h-2.5 w-2.5 text-green-500" /> {d}
                    </Badge>
                  ))}
                  {(v.dep_missing ?? []).map((d: string) => (
                    <Badge key={d} variant="destructive" className="font-mono text-[10px] gap-1">
                      <AlertTriangle className="h-2.5 w-2.5" /> {d}
                    </Badge>
                  ))}
                </div>
              </div>
            </TableCell>
          </TableRow>
        )}
        </>
      ))}

      {/* Delete Version Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Version"
      >
        <p className="text-sm text-zinc-400">
          Delete version{" "}
          <span className="font-semibold text-zinc-200">{deleteTarget?.version}</span> and
          its wheel files?
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={async () => {
              if (!deleteTarget) return;
              await deleteVersion.mutateAsync({
                moduleId,
                versionId: deleteTarget.id,
              });
              setDeleteTarget(null);
            }}
            disabled={deleteVersion.isPending}
          >
            {deleteVersion.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

export function PythonModulesPage() {
  const tz = useTimezone();
  const { data: modules, isLoading } = usePythonModules();
  const { data: network } = useNetworkStatus();
  const toggleApproval = useToggleModuleApproval();
  const deleteModule = useDeletePythonModule();

  const autoResolve = useAutoResolve();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PythonModuleSummary | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [resolveResult, setResolveResult] = useState<{ imported: number; failed: number; still_missing: number } | null>(null);

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteModule.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete module");
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Python Modules</h1>
            <p className="text-sm text-zinc-500">
              Manage Python wheel packages for collector apps.
            </p>
          </div>
          {network && <NetworkBadge mode={network.mode} />}
        </div>
        <div className="flex items-center gap-2">
          {network?.mode !== "offline" && (
            <>
              {modules && modules.some((m) => m.dep_missing > 0) && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={async () => {
                    setResolveResult(null);
                    try {
                      const res = await autoResolve.mutateAsync({});
                      setResolveResult({
                        imported: res.data.imported.length,
                        failed: res.data.failed.length,
                        still_missing: res.data.still_missing.length,
                      });
                    } catch { /* handled by mutation */ }
                  }}
                  disabled={autoResolve.isPending}
                  className="gap-1.5"
                >
                  {autoResolve.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4" />
                  )}
                  Auto-resolve All
                </Button>
              )}
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setImportOpen(true)}
                className="gap-1.5"
              >
                <Download className="h-4 w-4" />
                Import from PyPI
              </Button>
            </>
          )}
          <Button size="sm" onClick={() => setUploadOpen(true)} className="gap-1.5">
            <Upload className="h-4 w-4" />
            Upload .whl
          </Button>
        </div>
      </div>

      {/* Auto-resolve result banner */}
      {resolveResult && (
        <div className="flex items-center gap-3 rounded-md border border-zinc-700 bg-zinc-800/50 px-4 py-3">
          <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />
          <div className="text-sm">
            <span className="text-zinc-200">Auto-resolve complete:</span>{" "}
            <span className="text-green-400">{resolveResult.imported} imported</span>
            {resolveResult.failed > 0 && (
              <>, <span className="text-red-400">{resolveResult.failed} failed</span></>
            )}
            {resolveResult.still_missing > 0 && (
              <>, <span className="text-amber-400">{resolveResult.still_missing} still missing</span></>
            )}
          </div>
          <button
            onClick={() => setResolveResult(null)}
            className="ml-auto text-zinc-500 hover:text-zinc-300"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Modules Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="h-4 w-4" />
            Modules
            <Badge variant="default" className="ml-auto">
              {modules?.length ?? 0}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!modules || modules.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Package className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No Python modules registered</p>
              <p className="text-xs text-zinc-600 mt-1">
                Upload .whl files or import from PyPI to get started.
              </p>
            </div>
          ) : (() => {
            const topLevel = modules.filter((m) => m.is_dependency_of.length === 0);
            const depModules = modules.filter((m) => m.is_dependency_of.length > 0);

            return (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Versions</TableHead>
                  <TableHead>Wheels</TableHead>
                  <TableHead>Dependencies</TableHead>
                  <TableHead>Approved</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-24"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {topLevel.map((m) => {
                  // Find dep modules that belong to this top-level module
                  const childDeps = depModules.filter((d) =>
                    d.is_dependency_of.some((parent) => parent.toLowerCase().replace(/[-_.]+/g, "-") === m.name.toLowerCase().replace(/[-_.]+/g, "-"))
                  );
                  return (
                  <>
                    <TableRow key={m.id}>
                      <TableCell>
                        <button
                          onClick={() =>
                            setExpandedId((prev) => (prev === m.id ? null : m.id))
                          }
                          className="flex items-center gap-1.5 font-medium text-brand-400 hover:text-brand-300 transition-colors cursor-pointer"
                        >
                          {expandedId === m.id ? (
                            <ChevronDown className="h-3.5 w-3.5" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5" />
                          )}
                          <span className="font-mono">{m.name}</span>
                        </button>
                      </TableCell>
                      <TableCell className="text-zinc-400 text-sm max-w-[300px] truncate">
                        {m.description ?? (
                          <span className="text-zinc-600 italic">--</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="default">{m.version_count}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="default">{m.wheel_count}</Badge>
                      </TableCell>
                      <TableCell>
                        {m.dep_total === 0 ? (
                          <span className="text-xs text-zinc-600">None</span>
                        ) : m.dep_missing === 0 ? (
                          <Badge variant="success" className="gap-1 text-[10px]">
                            <CheckCircle2 className="h-3 w-3" /> Ready
                          </Badge>
                        ) : (
                          <Badge variant="destructive" className="gap-1 text-[10px]">
                            <AlertTriangle className="h-3 w-3" /> {m.dep_missing} missing
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {m.is_approved ? (
                          <Badge variant="success" className="gap-1">
                            <ShieldCheck className="h-3 w-3" /> Approved
                          </Badge>
                        ) : (
                          <Badge variant="default">Pending</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-zinc-500">
                        {formatDate(m.created_at, tz)}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              toggleApproval.mutate({
                                id: m.id,
                                is_approved: !m.is_approved,
                              })
                            }
                            disabled={toggleApproval.isPending}
                            title={m.is_approved ? "Revoke approval" : "Approve"}
                          >
                            {m.is_approved ? (
                              <ShieldOff className="h-3.5 w-3.5" />
                            ) : (
                              <ShieldCheck className="h-3.5 w-3.5" />
                            )}
                          </Button>
                          <button
                            onClick={() => setDeleteTarget(m)}
                            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </TableCell>
                    </TableRow>
                    {expandedId === m.id && (
                      <ModuleVersionsRow moduleId={m.id} />
                    )}
                    {/* Show child dependencies under this module when expanded */}
                    {expandedId === m.id && childDeps.length > 0 && (
                      <TableRow className="bg-zinc-900/40">
                        <TableCell colSpan={8} className="pl-10 py-3">
                          <div className="space-y-1.5">
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                              Installed Dependencies ({childDeps.length})
                            </span>
                            <div className="flex flex-wrap gap-1.5">
                              {childDeps.map((d) => (
                                <Badge key={d.id} variant="default" className="font-mono text-[10px] gap-1">
                                  <CheckCircle2 className="h-2.5 w-2.5 text-green-500" />
                                  {d.name}
                                  <span className="text-zinc-600">{d.version_count}v</span>
                                </Badge>
                              ))}
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </>
                  );
                })}
              </TableBody>
            </Table>
            );
          })()}
        </CardContent>
      </Card>

      {/* Upload Dialog */}
      <WheelUploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />

      {/* PyPI Import Dialog */}
      <PyPIImportDialog open={importOpen} onClose={() => setImportOpen(false)} />

      {/* Delete Module Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => {
          setDeleteTarget(null);
          setDeleteError(null);
        }}
        title="Delete Module"
      >
        <p className="text-sm text-zinc-400">
          Delete module{" "}
          <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span> and
          all its versions and wheel files?
        </p>
        {deleteError && <p className="text-sm text-red-400 mt-2">{deleteError}</p>}
        <DialogFooter>
          <Button
            variant="secondary"
            onClick={() => {
              setDeleteTarget(null);
              setDeleteError(null);
            }}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteModule.isPending}
          >
            {deleteModule.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
