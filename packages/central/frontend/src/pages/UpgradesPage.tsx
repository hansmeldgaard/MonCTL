import { useState, useRef } from "react";
import {
  ArrowUpCircle,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Loader2,
  Server,
  Package,
  Play,
  Trash2,
  Upload,
  XCircle,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  HardDrive,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import {
  useUpgradeStatus,
  useUploadUpgradeBundle,
  useDeleteUpgradePackage,
  useStartUpgrade,
  useUpgradeJobs,
  useCancelUpgradeJob,
  useOsUpdates,
  useCheckOsUpdatesNew,
  useDownloadOsPackages,
  useUploadOsPackage,
  useOsCachedPackages,
  useInstallOsOnNode,
} from "@/api/hooks.ts";
import { timeAgo, formatBytes } from "@/lib/utils.ts";
import type { UpgradeJob, UpgradeJobStep, OsInstallResult } from "@/types/api.ts";

// ── Status helpers ────────────────────────────────────────────────────────────

const jobStatusConfig: Record<string, { color: string; icon: typeof CheckCircle2 }> = {
  pending: { color: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30", icon: Clock },
  in_progress: { color: "bg-amber-500/15 text-amber-400 border-amber-500/30", icon: Loader2 },
  completed: { color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30", icon: CheckCircle2 },
  failed: { color: "bg-red-500/15 text-red-400 border-red-500/30", icon: XCircle },
  cancelled: { color: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30", icon: XCircle },
};

function JobStatusBadge({ status }: { status: string }) {
  const cfg = jobStatusConfig[status] ?? jobStatusConfig.pending;
  const Icon = cfg.icon;
  return (
    <Badge className={`${cfg.color} text-xs font-semibold`}>
      <Icon className={`mr-1 h-3 w-3 ${status === "in_progress" ? "animate-spin" : ""}`} />
      {status.replace(/_/g, " ")}
    </Badge>
  );
}

function StepStatusIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-red-400" />;
    case "in_progress":
      return <Loader2 className="h-4 w-4 text-amber-400 animate-spin" />;
    case "skipped":
      return <XCircle className="h-4 w-4 text-zinc-500" />;
    default:
      return <Clock className="h-4 w-4 text-zinc-500" />;
  }
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export function UpgradesPage() {
  const { data: status, isLoading: statusLoading } = useUpgradeStatus();
  const { data: jobs, isLoading: jobsLoading } = useUpgradeJobs();
  const uploadMutation = useUploadUpgradeBundle();
  const deleteMutation = useDeleteUpgradePackage();
  const startMutation = useStartUpgrade();
  const cancelMutation = useCancelUpgradeJob();
  const { data: osUpdatesByNode } = useOsUpdates();
  const checkOs = useCheckOsUpdatesNew();
  const downloadOs = useDownloadOsPackages();
  const uploadOs = useUploadOsPackage();
  const { data: cachedPackages } = useOsCachedPackages();
  const installOs = useInstallOsOnNode();

  const [selectedPkgId, setSelectedPkgId] = useState<string | null>(null);
  const [scope, setScope] = useState("all");
  const [strategy, setStrategy] = useState("rolling");
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [confirmStart, setConfirmStart] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const debInputRef = useRef<HTMLInputElement>(null);
  const [osSelectedPkgs, setOsSelectedPkgs] = useState<Record<string, Set<string>>>({});
  const [installResult, setInstallResult] = useState<{ hostname: string; result: OsInstallResult } | null>(null);

  const nodes = status?.nodes ?? [];
  const packages = status?.packages ?? [];
  const selectedPkg = packages.find((p) => p.id === selectedPkgId) ?? null;

  function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) uploadMutation.mutate(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleStartUpgrade() {
    if (!selectedPkgId) return;
    startMutation.mutate(
      { upgrade_package_id: selectedPkgId, scope, strategy },
      { onSuccess: () => { setConfirmStart(false); setSelectedPkgId(null); } },
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ArrowUpCircle className="h-7 w-7 text-brand-400" />
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Upgrades</h1>
          <p className="text-sm text-zinc-400">Manage system versions and orchestrate rolling upgrades</p>
        </div>
      </div>

      {/* ── System Status ─────────────────────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Server className="h-4 w-4 text-zinc-400" />
            System Nodes
          </CardTitle>
        </CardHeader>
        <CardContent>
          {statusLoading ? (
            <div className="flex items-center justify-center py-8 text-zinc-500">
              <Loader2 className="h-5 w-5 animate-spin mr-2" /> Loading...
            </div>
          ) : nodes.length === 0 ? (
            <p className="text-sm text-zinc-500 py-4 text-center">No nodes have reported version information yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Hostname</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>IP</TableHead>
                    <TableHead>MonCTL Version</TableHead>
                    <TableHead>OS</TableHead>
                    <TableHead>Kernel</TableHead>
                    <TableHead>Python</TableHead>
                    <TableHead>Last Reported</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {nodes.map((node) => (
                    <TableRow key={node.id}>
                      <TableCell className="font-mono text-xs">{node.hostname}</TableCell>
                      <TableCell>
                        <Badge className={node.role === "central"
                          ? "bg-brand-500/15 text-brand-400 border-brand-500/30 text-xs"
                          : "bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-xs"
                        }>
                          {node.role}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{node.ip || "\u2014"}</TableCell>
                      <TableCell className="font-mono text-xs">{node.monctl_version || "\u2014"}</TableCell>
                      <TableCell className="text-xs">{node.os_version || "\u2014"}</TableCell>
                      <TableCell className="font-mono text-xs">{node.kernel_version || "\u2014"}</TableCell>
                      <TableCell className="font-mono text-xs">{node.python_version || "\u2014"}</TableCell>
                      <TableCell className="text-xs text-zinc-400">
                        {node.last_reported_at ? timeAgo(node.last_reported_at) : "\u2014"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Upgrade Packages ──────────────────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Package className="h-4 w-4 text-zinc-400" />
              Upgrade Packages
            </CardTitle>
            <div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".tar.gz,.tgz,.zip"
                className="hidden"
                onChange={handleUpload}
              />
              <Button
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadMutation.isPending}
              >
                {uploadMutation.isPending ? (
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4 mr-1" />
                )}
                Upload Bundle
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {uploadMutation.isError && (
            <div className="mb-3 rounded-md bg-red-500/10 border border-red-500/30 p-3 text-sm text-red-400">
              <AlertTriangle className="inline h-4 w-4 mr-1" />
              Upload failed: {(uploadMutation.error as Error)?.message ?? "Unknown error"}
            </div>
          )}
          {packages.length === 0 ? (
            <p className="text-sm text-zinc-500 py-4 text-center">No upgrade packages uploaded yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Version</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Filename</TableHead>
                    <TableHead>Size</TableHead>
                    <TableHead>Components</TableHead>
                    <TableHead>Uploaded By</TableHead>
                    <TableHead>Uploaded</TableHead>
                    <TableHead className="w-20"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {packages.map((pkg) => (
                    <TableRow
                      key={pkg.id}
                      className={`cursor-pointer ${selectedPkgId === pkg.id ? "bg-brand-500/10" : ""}`}
                      onClick={() => setSelectedPkgId(selectedPkgId === pkg.id ? null : pkg.id)}
                    >
                      <TableCell className="font-mono text-xs font-semibold">{pkg.version}</TableCell>
                      <TableCell className="text-xs">{pkg.package_type}</TableCell>
                      <TableCell className="font-mono text-xs max-w-48 truncate">{pkg.filename}</TableCell>
                      <TableCell className="text-xs">{formatBytes(pkg.file_size)}</TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          {pkg.contains_central && (
                            <Badge className="bg-brand-500/15 text-brand-400 border-brand-500/30 text-[10px]">central</Badge>
                          )}
                          {pkg.contains_collector && (
                            <Badge className="bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-[10px]">collector</Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-zinc-400">{pkg.uploaded_by || "\u2014"}</TableCell>
                      <TableCell className="text-xs text-zinc-400">{timeAgo(pkg.created_at)}</TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0 text-zinc-500 hover:text-red-400"
                          onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(pkg.id); }}
                          disabled={deleteMutation.isPending}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          {selectedPkg?.changelog && (
            <div className="mt-3 rounded-md bg-zinc-800/50 border border-zinc-700 p-3">
              <p className="text-xs text-zinc-400 mb-1 font-semibold">Changelog</p>
              <pre className="text-xs text-zinc-300 whitespace-pre-wrap">{selectedPkg.changelog}</pre>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Start Upgrade ─────────────────────────────────────────────────── */}
      {selectedPkg && (
        <Card className="border-zinc-800 bg-zinc-900">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Play className="h-4 w-4 text-zinc-400" />
              Start Upgrade to {selectedPkg.version}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-end gap-4">
              <div className="space-y-1">
                <label className="text-xs text-zinc-400 font-medium">Scope</label>
                <Select value={scope} onChange={(e) => setScope(e.target.value)} className="w-40">
                  <option value="all">All nodes</option>
                  <option value="central">Central only</option>
                  <option value="collectors">Collectors only</option>
                </Select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-zinc-400 font-medium">Strategy</label>
                <Select value={strategy} onChange={(e) => setStrategy(e.target.value)} className="w-40">
                  <option value="rolling">Rolling</option>
                  <option value="all_at_once">All at once</option>
                </Select>
              </div>
              <div className="flex gap-2">
                {!confirmStart ? (
                  <Button onClick={() => setConfirmStart(true)} disabled={startMutation.isPending}>
                    <Play className="h-4 w-4 mr-1" />
                    Start Upgrade
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="destructive"
                      onClick={handleStartUpgrade}
                      disabled={startMutation.isPending}
                    >
                      {startMutation.isPending ? (
                        <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                      ) : (
                        <AlertTriangle className="h-4 w-4 mr-1" />
                      )}
                      Confirm Upgrade
                    </Button>
                    <Button variant="outline" onClick={() => setConfirmStart(false)}>
                      Cancel
                    </Button>
                  </>
                )}
              </div>
            </div>
            {startMutation.isError && (
              <div className="mt-3 rounded-md bg-red-500/10 border border-red-500/30 p-3 text-sm text-red-400">
                <AlertTriangle className="inline h-4 w-4 mr-1" />
                {(startMutation.error as Error)?.message ?? "Failed to start upgrade"}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Upgrade Jobs ──────────────────────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <RefreshCw className="h-4 w-4 text-zinc-400" />
            Upgrade Jobs
          </CardTitle>
        </CardHeader>
        <CardContent>
          {jobsLoading ? (
            <div className="flex items-center justify-center py-8 text-zinc-500">
              <Loader2 className="h-5 w-5 animate-spin mr-2" /> Loading...
            </div>
          ) : !jobs || jobs.length === 0 ? (
            <p className="text-sm text-zinc-500 py-4 text-center">No upgrade jobs have been created yet.</p>
          ) : (
            <div className="space-y-2">
              {jobs.map((job) => (
                <UpgradeJobCard
                  key={job.id}
                  job={job}
                  expanded={expandedJobId === job.id}
                  onToggle={() => setExpandedJobId(expandedJobId === job.id ? null : job.id)}
                  onCancel={() => cancelMutation.mutate(job.id)}
                  cancelling={cancelMutation.isPending}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── OS Updates ──────────────────────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <HardDrive className="h-4 w-4 text-zinc-400" />
              OS Updates
            </CardTitle>
            <div className="flex gap-2">
              <input
                ref={debInputRef}
                type="file"
                accept=".deb"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) uploadOs.mutate(file);
                  if (debInputRef.current) debInputRef.current.value = "";
                }}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => debInputRef.current?.click()}
                disabled={uploadOs.isPending}
              >
                {uploadOs.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Upload className="h-3 w-3 mr-1" />
                )}
                Upload .deb
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => checkOs.mutate()}
                disabled={checkOs.isPending}
              >
                {checkOs.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <RefreshCw className="h-3 w-3 mr-1" />
                )}
                Check All Nodes
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {checkOs.isError && (
            <div className="mb-3 rounded-md bg-red-500/10 border border-red-500/30 p-3 text-sm text-red-400">
              <AlertTriangle className="inline h-4 w-4 mr-1" />
              Check failed: {(checkOs.error as Error)?.message ?? "Unknown error"}
            </div>
          )}
          {uploadOs.isError && (
            <div className="mb-3 rounded-md bg-red-500/10 border border-red-500/30 p-3 text-sm text-red-400">
              <AlertTriangle className="inline h-4 w-4 mr-1" />
              Upload failed: {(uploadOs.error as Error)?.message ?? "Unknown error"}
            </div>
          )}

          {/* Per-node update cards */}
          {osUpdatesByNode && Object.keys(osUpdatesByNode).length > 0 ? (
            <div className="space-y-4 mb-6">
              {Object.entries(osUpdatesByNode).map(([hostname, updates]) => {
                const selected = osSelectedPkgs[hostname] ?? new Set<string>();
                const allSelected = updates.length > 0 && selected.size === updates.length;
                const togglePkg = (pkgName: string) => {
                  setOsSelectedPkgs((prev) => {
                    const s = new Set(prev[hostname] ?? []);
                    if (s.has(pkgName)) s.delete(pkgName);
                    else s.add(pkgName);
                    return { ...prev, [hostname]: s };
                  });
                };
                const toggleAll = () => {
                  setOsSelectedPkgs((prev) => {
                    if (allSelected) return { ...prev, [hostname]: new Set<string>() };
                    return { ...prev, [hostname]: new Set(updates.map((u) => u.package)) };
                  });
                };
                return (
                  <div key={hostname} className="border border-zinc-800 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Server className="h-3.5 w-3.5 text-zinc-500" />
                        <span className="text-sm font-medium">{hostname}</span>
                        <Badge variant="default" className="text-[10px]">
                          {updates.length} updates
                        </Badge>
                      </div>
                      <div className="flex gap-1.5">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-6 text-[10px]"
                          onClick={() => {
                            const names = Array.from(selected);
                            if (names.length > 0) downloadOs.mutate(names);
                          }}
                          disabled={selected.size === 0 || downloadOs.isPending}
                        >
                          {downloadOs.isPending ? (
                            <Loader2 className="h-3 w-3 animate-spin mr-1" />
                          ) : null}
                          Download Selected
                        </Button>
                        <Button
                          size="sm"
                          variant="default"
                          className="h-6 text-[10px]"
                          onClick={() => {
                            const names = Array.from(selected);
                            if (names.length === 0) return;
                            installOs.mutate(
                              { node_hostname: hostname, package_names: names },
                              {
                                onSuccess: (res) =>
                                  setInstallResult({ hostname, result: res.data }),
                              },
                            );
                          }}
                          disabled={selected.size === 0 || installOs.isPending}
                        >
                          {installOs.isPending ? (
                            <Loader2 className="h-3 w-3 animate-spin mr-1" />
                          ) : null}
                          Install Selected
                        </Button>
                      </div>
                    </div>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-8">
                            <input
                              type="checkbox"
                              checked={allSelected}
                              onChange={toggleAll}
                              className="accent-brand-500"
                            />
                          </TableHead>
                          <TableHead>Package</TableHead>
                          <TableHead>Current</TableHead>
                          <TableHead>New</TableHead>
                          <TableHead>Severity</TableHead>
                          <TableHead>Status</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {updates.map((u) => (
                          <TableRow key={u.id}>
                            <TableCell>
                              <input
                                type="checkbox"
                                checked={selected.has(u.package)}
                                onChange={() => togglePkg(u.package)}
                                className="accent-brand-500"
                              />
                            </TableCell>
                            <TableCell className="font-mono text-xs">{u.package}</TableCell>
                            <TableCell className="text-xs text-zinc-500">{u.current}</TableCell>
                            <TableCell className="text-xs">{u.new}</TableCell>
                            <TableCell>
                              <Badge
                                variant={u.severity === "security" ? "destructive" : "default"}
                                className="text-[10px]"
                              >
                                {u.severity}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              {u.is_downloaded && (
                                <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-[10px]">
                                  cached
                                </Badge>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-zinc-500 py-4 text-center mb-4">
              No OS updates detected. Click "Check All Nodes" to scan.
            </p>
          )}

          {/* Cached Packages */}
          <h4 className="text-sm font-medium text-zinc-400 mb-2">Cached Packages</h4>
          {cachedPackages && cachedPackages.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Package</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Arch</TableHead>
                  <TableHead>Filename</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Added</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cachedPackages.map((pkg) => (
                  <TableRow key={pkg.id}>
                    <TableCell className="font-mono text-xs">{pkg.package}</TableCell>
                    <TableCell className="text-xs">{pkg.version}</TableCell>
                    <TableCell className="text-xs text-zinc-500">{pkg.architecture}</TableCell>
                    <TableCell className="font-mono text-xs max-w-48 truncate">{pkg.filename}</TableCell>
                    <TableCell className="text-xs">{formatBytes(pkg.file_size)}</TableCell>
                    <TableCell className="text-xs text-zinc-500">{pkg.source}</TableCell>
                    <TableCell className="text-xs text-zinc-400">{timeAgo(pkg.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-xs text-zinc-600">No cached OS packages.</p>
          )}
        </CardContent>
      </Card>

      {/* ── Install Result Dialog ────────────────────────────────────────── */}
      {installResult && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-2xl rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-zinc-100">
                Install Result — {installResult.hostname}
              </h3>
              {installResult.result.success ? (
                <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-xs">
                  Success
                </Badge>
              ) : (
                <Badge className="bg-red-500/15 text-red-400 border-red-500/30 text-xs">
                  Failed (exit {installResult.result.returncode})
                </Badge>
              )}
            </div>
            {installResult.result.error && (
              <div className="mb-3 rounded-md bg-red-500/10 border border-red-500/30 p-2 text-xs text-red-400">
                {installResult.result.error}
              </div>
            )}
            <div className="rounded-md bg-zinc-950 border border-zinc-800 p-3 max-h-72 overflow-y-auto">
              <pre className="text-[11px] text-zinc-400 whitespace-pre-wrap font-mono">
                {installResult.result.output || "(no output)"}
              </pre>
            </div>
            <div className="mt-4 flex justify-end">
              <Button variant="outline" size="sm" onClick={() => setInstallResult(null)}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Upgrade Job Card ──────────────────────────────────────────────────────────

function UpgradeJobCard({
  job,
  expanded,
  onToggle,
  onCancel,
  cancelling,
}: {
  job: UpgradeJob;
  expanded: boolean;
  onToggle: () => void;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const isActive = job.status === "pending" || job.status === "in_progress";
  const completedSteps = job.steps.filter((s) => s.status === "completed").length;
  const totalSteps = job.steps.length;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-800/30">
      {/* Header row */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-zinc-800/50 transition-colors"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-zinc-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-zinc-500" />
          )}
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-semibold text-zinc-100">
                v{job.target_version}
              </span>
              <JobStatusBadge status={job.status} />
              <Badge className="bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-[10px]">
                {job.scope}
              </Badge>
              <Badge className="bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-[10px]">
                {job.strategy.replace(/_/g, " ")}
              </Badge>
            </div>
            <div className="flex items-center gap-3 mt-0.5 text-xs text-zinc-500">
              {job.started_by && <span>by {job.started_by}</span>}
              {job.started_at && <span>{timeAgo(job.started_at)}</span>}
              {totalSteps > 0 && (
                <span>
                  {completedSteps}/{totalSteps} steps
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isActive && (
            <Button
              variant="outline"
              size="sm"
              className="text-xs"
              onClick={(e) => { e.stopPropagation(); onCancel(); }}
              disabled={cancelling}
            >
              <XCircle className="h-3.5 w-3.5 mr-1" />
              Cancel
            </Button>
          )}
        </div>
      </div>

      {/* Error message */}
      {job.error_message && (
        <div className="mx-4 mb-3 rounded-md bg-red-500/10 border border-red-500/30 p-2 text-xs text-red-400">
          {job.error_message}
        </div>
      )}

      {/* Steps */}
      {expanded && job.steps.length > 0 && (
        <div className="border-t border-zinc-800 px-4 py-3">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead>Node</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Completed</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {job.steps
                .sort((a, b) => a.step_order - b.step_order)
                .map((step) => (
                  <StepRow key={step.id} step={step} />
                ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

// ── Step Row ──────────────────────────────────────────────────────────────────

function StepRow({ step }: { step: UpgradeJobStep }) {
  const [showLog, setShowLog] = useState(false);
  const hasDetails = !!(step.output_log || step.error_message);

  return (
    <>
      <TableRow>
        <TableCell className="text-xs text-zinc-500">{step.step_order}</TableCell>
        <TableCell className="font-mono text-xs">{step.node_hostname}</TableCell>
        <TableCell>
          <Badge className="bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-[10px]">
            {step.node_role}
          </Badge>
        </TableCell>
        <TableCell className="text-xs">{step.action}</TableCell>
        <TableCell>
          <div className="flex items-center gap-1.5">
            <StepStatusIcon status={step.status} />
            <span className="text-xs">{step.status.replace(/_/g, " ")}</span>
          </div>
        </TableCell>
        <TableCell className="text-xs text-zinc-400">
          {step.started_at ? timeAgo(step.started_at) : "\u2014"}
        </TableCell>
        <TableCell className="text-xs text-zinc-400">
          {step.completed_at ? timeAgo(step.completed_at) : "\u2014"}
        </TableCell>
        <TableCell>
          {hasDetails && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-xs text-zinc-400"
              onClick={() => setShowLog(!showLog)}
            >
              {showLog ? "Hide" : "Show"}
            </Button>
          )}
        </TableCell>
      </TableRow>
      {showLog && hasDetails && (
        <TableRow>
          <TableCell colSpan={8} className="p-0">
            <div className="mx-4 my-2 rounded-md bg-zinc-950 border border-zinc-800 p-3">
              {step.error_message && (
                <p className="text-xs text-red-400 mb-2">
                  <AlertTriangle className="inline h-3 w-3 mr-1" />
                  {step.error_message}
                </p>
              )}
              {step.output_log && (
                <pre className="text-[11px] text-zinc-400 whitespace-pre-wrap font-mono max-h-48 overflow-y-auto">
                  {step.output_log}
                </pre>
              )}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
