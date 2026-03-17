import { useState } from "react";
import {
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
        <TableCell colSpan={6} className="py-4">
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
        <TableCell colSpan={6} className="py-3 text-center text-sm text-zinc-500">
          No versions
        </TableCell>
      </TableRow>
    );
  }

  return (
    <>
      {detail.versions.map((v) => (
        <TableRow key={v.id} className="bg-zinc-800/20">
          <TableCell className="pl-10">
            <span className="font-mono text-xs text-zinc-300">{v.version}</span>
          </TableCell>
          <TableCell>
            <span className="text-xs text-zinc-400">
              {v.dependencies.length > 0 ? `${v.dependencies.length} deps` : "--"}
            </span>
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

  const [uploadOpen, setUploadOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PythonModuleSummary | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setImportOpen(true)}
              className="gap-1.5"
            >
              <Download className="h-4 w-4" />
              Import from PyPI
            </Button>
          )}
          <Button size="sm" onClick={() => setUploadOpen(true)} className="gap-1.5">
            <Upload className="h-4 w-4" />
            Upload .whl
          </Button>
        </div>
      </div>

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
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Versions</TableHead>
                  <TableHead>Wheels</TableHead>
                  <TableHead>Approved</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-24"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {modules.map((m) => (
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
                  </>
                ))}
              </TableBody>
            </Table>
          )}
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
