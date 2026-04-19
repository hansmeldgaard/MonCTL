import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
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
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
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
import { usePermissions } from "@/hooks/usePermissions.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import { formatTime } from "@/lib/utils.ts";
import { WheelUploadDialog } from "@/components/WheelUploadDialog.tsx";
import { PyPIImportDialog } from "@/components/PyPIImportDialog.tsx";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";
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

/** Modal showing per-version wheel files + dependency state for a
 *  module. Replaces the previous in-table expanded-row UI so the
 *  parent list can use FlexTable (which doesn't support row
 *  expansion). */
function ModuleDetailDialog({
  module,
  childDeps,
  onClose,
}: {
  module: PythonModuleSummary;
  childDeps: PythonModuleSummary[];
  onClose: () => void;
}) {
  const { isAdmin } = usePermissions();
  const { data: detail, isLoading } = usePythonModuleDetail(module.id);
  const toggleVerify = useToggleModuleVerify();
  const deleteVersion = useDeleteModuleVersion();
  const [deleteTarget, setDeleteTarget] = useState<{
    id: string;
    version: string;
  } | null>(null);

  return (
    <Dialog open onClose={onClose} title={module.name} size="lg">
      <div className="space-y-4 max-h-[70vh] overflow-y-auto">
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
          </div>
        )}
        {!isLoading && detail && detail.versions.length === 0 && (
          <p className="text-sm text-zinc-500 py-4 text-center">No versions</p>
        )}
        {detail?.versions.map((v) => (
          <div
            key={v.id}
            className="rounded border border-zinc-800 bg-zinc-900/40 p-3"
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="font-mono text-sm text-zinc-200">
                {v.version}
              </span>
              {v.is_verified ? (
                <Badge variant="success" className="gap-1 text-[10px]">
                  <Verified className="h-3 w-3" /> Verified
                </Badge>
              ) : (
                <Badge variant="default" className="text-[10px]">
                  Unverified
                </Badge>
              )}
              {v.dependencies.length === 0 ? (
                <span className="text-xs text-zinc-600">no deps</span>
              ) : (v.dep_missing ?? []).length === 0 ? (
                <Badge variant="success" className="gap-1 text-[10px]">
                  <CheckCircle2 className="h-3 w-3" /> {v.dependencies.length}{" "}
                  deps OK
                </Badge>
              ) : (
                <Badge variant="destructive" className="gap-1 text-[10px]">
                  <AlertTriangle className="h-3 w-3" />{" "}
                  {(v.dep_missing ?? []).length}/{v.dependencies.length} missing
                </Badge>
              )}
              {isAdmin && (
                <div className="ml-auto flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      toggleVerify.mutate({
                        moduleId: module.id,
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
                    onClick={() =>
                      setDeleteTarget({ id: v.id, version: v.version })
                    }
                    className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                    title="Delete version"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
            <div className="space-y-1 text-xs">
              {v.wheel_files.map((w) => (
                <div key={w.id} className="flex items-center gap-2">
                  <span className="font-mono text-zinc-400 truncate max-w-[300px]">
                    {w.filename}
                  </span>
                  <span className="text-zinc-600">
                    {formatBytes(w.file_size)}
                  </span>
                  <Badge variant="default" className="text-[9px]">
                    {w.python_tag}-{w.abi_tag}-{w.platform_tag}
                  </Badge>
                </div>
              ))}
              {v.wheel_files.length === 0 && (
                <span className="text-zinc-600">No wheels</span>
              )}
            </div>
            {v.dependencies.length > 0 && (
              <div className="mt-2 space-y-1">
                <span className="text-[10px] uppercase tracking-wider text-zinc-500">
                  Dependencies
                </span>
                <div className="flex flex-wrap gap-1">
                  {(v.dep_resolved ?? []).map((d: string) => (
                    <Badge
                      key={d}
                      variant="default"
                      className="font-mono text-[10px] gap-1"
                    >
                      <CheckCircle2 className="h-2.5 w-2.5 text-green-500" />
                      {d}
                    </Badge>
                  ))}
                  {(v.dep_missing ?? []).map((d: string) => (
                    <Badge
                      key={d}
                      variant="destructive"
                      className="font-mono text-[10px] gap-1"
                    >
                      <AlertTriangle className="h-2.5 w-2.5" />
                      {d}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}

        {childDeps.length > 0 && (
          <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Installed Dependencies ({childDeps.length})
            </span>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {childDeps.map((d) => (
                <Badge
                  key={d.id}
                  variant="default"
                  className="font-mono text-[10px] gap-1"
                >
                  <CheckCircle2 className="h-2.5 w-2.5 text-green-500" />
                  {d.name}
                  <span className="text-zinc-600">{d.version_count}v</span>
                </Badge>
              ))}
            </div>
          </div>
        )}
      </div>

      <DialogFooter>
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      </DialogFooter>

      {/* Delete Version Dialog (nested) */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Version"
      >
        <p className="text-sm text-zinc-400">
          Delete version{" "}
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.version}
          </span>{" "}
          and its wheel files?
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
                moduleId: module.id,
                versionId: deleteTarget.id,
              });
              setDeleteTarget(null);
            }}
            disabled={deleteVersion.isPending}
          >
            {deleteVersion.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </Dialog>
  );
}

export function PythonModulesPage() {
  const { isAdmin } = usePermissions();
  const tz = useTimezone();
  const { mode } = useTimeDisplayMode();
  const { compact } = useDisplayPreferences();
  const { data: response, isLoading } = usePythonModules({
    limit: 500,
    offset: 0,
  });
  const modules = response?.data ?? [];
  const { data: network } = useNetworkStatus();
  const toggleApproval = useToggleModuleApproval();
  const deleteModule = useDeletePythonModule();

  const autoResolve = useAutoResolve();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [detailModule, setDetailModule] = useState<PythonModuleSummary | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<PythonModuleSummary | null>(
    null,
  );
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [resolveResult, setResolveResult] = useState<{
    imported: number;
    failed: number;
    still_missing: number;
  } | null>(null);

  // Split top-level modules from those that exist only as dependencies
  // of another. The detail dialog still surfaces the children when you
  // click into a parent.
  const topLevel = useMemo(
    () => modules.filter((m) => m.is_dependency_of.length === 0),
    [modules],
  );
  const depModules = useMemo(
    () => modules.filter((m) => m.is_dependency_of.length > 0),
    [modules],
  );
  const childDepsFor = (m: PythonModuleSummary) =>
    depModules.filter((d) =>
      d.is_dependency_of.some(
        (parent) =>
          parent.toLowerCase().replace(/[-_.]+/g, "-") ===
          m.name.toLowerCase().replace(/[-_.]+/g, "-"),
      ),
    );

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteModule.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete module",
      );
    }
  }

  // ── Client-side sort / filter / FlexTable ────────────────────────
  const [sortBy, setSortBy] = useState("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const handleSort = (col: string) => {
    if (col === sortBy) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(col);
      setSortDir("asc");
    }
  };
  const sortedTopLevel = useMemo(() => {
    const copy = [...topLevel];
    const getter: Record<string, (m: PythonModuleSummary) => string | number> =
      {
        name: (m) => m.name,
        description: (m) => m.description ?? "",
        version_count: (m) => m.version_count,
        wheel_count: (m) => m.wheel_count,
        dep_missing: (m) => m.dep_missing,
        is_approved: (m) => (m.is_approved ? 1 : 0),
        created_at: (m) =>
          m.created_at ? new Date(m.created_at).getTime() : 0,
      };
    const g = getter[sortBy];
    if (!g) return copy;
    return copy.sort((a, b) => {
      const av = g(a);
      const bv = g(b);
      if (typeof av === "number" && typeof bv === "number")
        return sortDir === "asc" ? av - bv : bv - av;
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
  }, [topLevel, sortBy, sortDir]);

  const columns = useMemo<FlexColumnDef<PythonModuleSummary>[]>(
    () => [
      {
        key: "name",
        label: "Name",
        defaultWidth: 200,
        cell: (m) => (
          <button
            onClick={() => setDetailModule(m)}
            className="flex items-center gap-1.5 font-medium text-brand-400 hover:text-brand-300 transition-colors cursor-pointer"
          >
            <span className="font-mono">{m.name}</span>
          </button>
        ),
      },
      {
        key: "description",
        label: "Description",
        defaultWidth: 280,
        cellClassName: "text-zinc-400 text-sm max-w-[300px] truncate",
        cell: (m) =>
          m.description ?? <span className="text-zinc-600 italic">--</span>,
      },
      {
        key: "version_count",
        label: "Versions",
        filterable: false,
        defaultWidth: 100,
        cell: (m) => <Badge variant="default">{m.version_count}</Badge>,
      },
      {
        key: "wheel_count",
        label: "Wheels",
        filterable: false,
        defaultWidth: 100,
        cell: (m) => <Badge variant="default">{m.wheel_count}</Badge>,
      },
      {
        key: "dep_missing",
        label: "Dependencies",
        filterable: false,
        defaultWidth: 140,
        cell: (m) =>
          m.dep_total === 0 ? (
            <span className="text-xs text-zinc-600">None</span>
          ) : m.dep_missing === 0 ? (
            <Badge variant="success" className="gap-1 text-[10px]">
              <CheckCircle2 className="h-3 w-3" /> Ready
            </Badge>
          ) : (
            <Badge variant="destructive" className="gap-1 text-[10px]">
              <AlertTriangle className="h-3 w-3" /> {m.dep_missing} missing
            </Badge>
          ),
      },
      {
        key: "is_approved",
        label: "Approved",
        filterable: false,
        defaultWidth: 110,
        cell: (m) =>
          m.is_approved ? (
            <Badge variant="success" className="gap-1">
              <ShieldCheck className="h-3 w-3" /> Approved
            </Badge>
          ) : (
            <Badge variant="default">Pending</Badge>
          ),
      },
      {
        key: "created_at",
        label: "Created",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (m) => formatTime(m.created_at, mode, tz),
      },
      {
        key: "__actions",
        label: "",
        pickerLabel: "Actions",
        sortable: false,
        filterable: false,
        defaultWidth: 110,
        cell: (m) =>
          isAdmin ? (
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
          ) : null,
      },
    ],
    [isAdmin, mode, tz, toggleApproval],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<PythonModuleSummary>("python-modules", columns);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">
              Python Modules
            </h1>
            <p className="text-sm text-zinc-500">
              Manage Python wheel packages for collector apps.
            </p>
          </div>
          {network && <NetworkBadge mode={network.mode} />}
        </div>
        {isAdmin && (
          <div className="flex items-center gap-2">
            {network?.mode !== "offline" && (
              <>
                {modules.some((m) => m.dep_missing > 0) && (
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
                      } catch {
                        /* handled by mutation */
                      }
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
            <Button
              size="sm"
              onClick={() => setUploadOpen(true)}
              className="gap-1.5"
            >
              <Upload className="h-4 w-4" />
              Upload .whl
            </Button>
          </div>
        )}
      </div>

      {resolveResult && (
        <div className="flex items-center gap-3 rounded-md border border-zinc-700 bg-zinc-800/50 px-4 py-3">
          <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />
          <div className="text-sm">
            <span className="text-zinc-200">Auto-resolve complete:</span>{" "}
            <span className="text-green-400">
              {resolveResult.imported} imported
            </span>
            {resolveResult.failed > 0 && (
              <>
                ,{" "}
                <span className="text-red-400">
                  {resolveResult.failed} failed
                </span>
              </>
            )}
            {resolveResult.still_missing > 0 && (
              <>
                ,{" "}
                <span className="text-amber-400">
                  {resolveResult.still_missing} still missing
                </span>
              </>
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

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="h-4 w-4" />
            Modules
            <Badge variant="default" className="ml-2">
              {topLevel.length}
            </Badge>
            <div className="ml-auto">
              <DisplayMenu
                columns={columns}
                configMap={configMap}
                onToggleHidden={setHidden}
                onReset={reset}
              />
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {modules.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Package className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No Python modules registered</p>
              <p className="text-xs text-zinc-600 mt-1">
                Upload .whl files or import from PyPI to get started.
              </p>
            </div>
          ) : (
            <div
              className={
                compact
                  ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
                  : ""
              }
            >
              <FlexTable<PythonModuleSummary>
                orderedVisibleColumns={orderedVisibleColumns}
                configMap={configMap}
                onOrderChange={setOrder}
                onWidthChange={setWidth}
                rows={sortedTopLevel}
                rowKey={(m) => m.id}
                sortBy={sortBy}
                sortDir={sortDir}
                onSort={handleSort}
                filters={{}}
                onFilterChange={() => {}}
                emptyState="No modules"
              />
            </div>
          )}
        </CardContent>
      </Card>

      <WheelUploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
      />

      <PyPIImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
      />

      {detailModule && (
        <ModuleDetailDialog
          module={detailModule}
          childDeps={childDepsFor(detailModule)}
          onClose={() => setDetailModule(null)}
        />
      )}

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
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.name}
          </span>{" "}
          and all its versions and wheel files?
        </p>
        {deleteError && (
          <p className="text-sm text-red-400 mt-2">{deleteError}</p>
        )}
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
            {deleteModule.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
