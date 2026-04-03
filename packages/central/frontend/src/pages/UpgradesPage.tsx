import { useState, useRef, useMemo } from "react";
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
  SkipForward,
  ListOrdered,
  Search,
  Download,
  Check,
  ArrowUp,
  HelpCircle,
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
  useCheckOsUpdatesNew,
  useDownloadOsPackages,
  useUploadOsPackage,
  useOsInstallJobs,
  useStartOsInstallJob,
  useApproveOsInstallJob,
  useCancelOsInstallJob,
  useDeleteOsInstallJob,
  usePackageInventory,
  useCollectInventory,
  useRestartNodes,
} from "@/api/hooks.ts";
import { timeAgo, formatBytes } from "@/lib/utils.ts";
import type { UpgradeJob, UpgradeJobStep, OsInstallJob, OsInstallJobStep, PackageInventoryItem } from "@/types/api.ts";

// ── Status helpers ────────────────────────────────────────────────────────────

const jobStatusConfig: Record<string, { color: string; icon: typeof CheckCircle2 }> = {
  pending: { color: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30", icon: Clock },
  in_progress: { color: "bg-amber-500/15 text-amber-400 border-amber-500/30", icon: Loader2 },
  completed: { color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30", icon: CheckCircle2 },
  failed: { color: "bg-red-500/15 text-red-400 border-red-500/30", icon: XCircle },
  cancelled: { color: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30", icon: XCircle },
};

const installJobStatusConfig: Record<string, { color: string; icon: typeof CheckCircle2 }> = {
  pending: { color: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30", icon: Clock },
  running: { color: "bg-amber-500/15 text-amber-400 border-amber-500/30", icon: Loader2 },
  awaiting_approval: { color: "bg-blue-500/15 text-blue-400 border-blue-500/30", icon: Clock },
  completed: { color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30", icon: CheckCircle2 },
  failed: { color: "bg-red-500/15 text-red-400 border-red-500/30", icon: XCircle },
  cancelled: { color: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30", icon: XCircle },
};

function InstallJobStatusBadge({ status }: { status: string }) {
  const cfg = installJobStatusConfig[status] ?? installJobStatusConfig.pending;
  const Icon = cfg.icon;
  return (
    <Badge className={`${cfg.color} text-xs font-semibold`}>
      <Icon className={`mr-1 h-3 w-3 ${status === "running" ? "animate-spin" : ""}`} />
      {status.replace(/_/g, " ")}
    </Badge>
  );
}

function InstallStepStatusIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-red-400" />;
    case "running":
      return <Loader2 className="h-4 w-4 text-amber-400 animate-spin" />;
    case "skipped":
      return <SkipForward className="h-4 w-4 text-zinc-500" />;
    default:
      return <Clock className="h-4 w-4 text-zinc-500" />;
  }
}

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
  const checkOs = useCheckOsUpdatesNew();
  const downloadOs = useDownloadOsPackages();
  const uploadOs = useUploadOsPackage();
  const { data: osInstallJobs } = useOsInstallJobs();
  const startInstallJob = useStartOsInstallJob();
  const approveInstallJob = useApproveOsInstallJob();
  const cancelInstallJob = useCancelOsInstallJob();
  const deleteInstallJob = useDeleteOsInstallJob();
  const restartNodes = useRestartNodes();

  const [selectedPkgId, setSelectedPkgId] = useState<string | null>(null);
  const [scope, setScope] = useState("all");
  const [strategy, setStrategy] = useState("rolling");
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [confirmStart, setConfirmStart] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const debInputRef = useRef<HTMLInputElement>(null);
  const [expandedInstallJobId, setExpandedInstallJobId] = useState<string | null>(null);

  // Package inventory state
  const { data: packageInventory } = usePackageInventory();
  const collectInventory = useCollectInventory();
  const [pkgSearch, setPkgSearch] = useState("");
  const [selectedPkgs, setSelectedPkgs] = useState<Set<string>>(new Set());
  const [expandedPkg, setExpandedPkg] = useState<string | null>(null);
  const [expandedNodeSearch, setExpandedNodeSearch] = useState("");
  const [showAllNodes, setShowAllNodes] = useState(false);

  // Install preview state
  const [showInstallPreview, setShowInstallPreview] = useState(false);
  const [installStrategy, setInstallStrategy] = useState("rolling");

  // System Nodes selection state (for restart)
  const [selectedNodes, setSelectedNodes] = useState<Set<string>>(new Set());

  const nodes = status?.nodes ?? [];
  const packages = status?.packages ?? [];
  const selectedPkg = packages.find((p) => p.id === selectedPkgId) ?? null;

  // Compute install plan from selected packages
  const installPlan = useMemo(() => {
    if (selectedPkgs.size === 0 || !packageInventory) return null;
    const pkgItems = packageInventory.filter((p) => selectedPkgs.has(p.package_name));
    // Build node→packages map (only nodes that need updates)
    const nodeMap = new Map<string, { hostname: string; role: string; packages: string[] }>();
    for (const pkg of pkgItems) {
      for (const node of pkg.nodes) {
        if (node.status === "installed") continue;
        if (!nodeMap.has(node.hostname)) {
          nodeMap.set(node.hostname, { hostname: node.hostname, role: node.role, packages: [] });
        }
        nodeMap.get(node.hostname)!.packages.push(pkg.package_name);
      }
    }
    const rebootPkgs = pkgItems.filter((p) => p.requires_reboot).map((p) => p.package_name);
    return {
      packageNames: pkgItems.map((p) => p.package_name),
      nodes: Array.from(nodeMap.values()).sort((a, b) => a.hostname.localeCompare(b.hostname)),
      rebootPkgs,
    };
  }, [selectedPkgs, packageInventory]);

  function handleStartInstallJob() {
    if (!installPlan || installPlan.packageNames.length === 0) return;
    startInstallJob.mutate(
      {
        package_names: installPlan.packageNames,
        scope: "all",
        strategy: installStrategy,
        restart_policy: "none",
      },
      {
        onSuccess: () => {
          setShowInstallPreview(false);
          setInstallStrategy("rolling");
          setSelectedPkgs(new Set());
        },
      },
    );
  }

  // Nodes that have reboot_required and are selected
  const rebootableSelectedNodes = useMemo(() => {
    return nodes.filter((n) => selectedNodes.has(n.hostname) && n.reboot_required);
  }, [nodes, selectedNodes]);

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
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Server className="h-4 w-4 text-zinc-400" />
              System Nodes
            </CardTitle>
            {rebootableSelectedNodes.length > 0 && (
              <Button
                size="sm"
                onClick={() => {
                  restartNodes.mutate(
                    { node_hostnames: Array.from(selectedNodes).filter((h) => nodes.find((n) => n.hostname === h)?.reboot_required), strategy: "rolling" },
                  );
                }}
                disabled={restartNodes.isPending}
              >
                {restartNodes.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <RefreshCw className="h-3 w-3 mr-1" />
                )}
                Rolling Restart Selected ({rebootableSelectedNodes.length})
              </Button>
            )}
          </div>
          {restartNodes.isError && (
            <div className="mt-2 rounded-md bg-red-500/10 border border-red-500/30 p-2 text-xs text-red-400">
              <AlertTriangle className="inline h-3 w-3 mr-1" />
              {(restartNodes.error as Error)?.message ?? "Failed to restart nodes"}
            </div>
          )}
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
                    <TableHead className="w-8">
                      <input
                        type="checkbox"
                        checked={nodes.length > 0 && nodes.every((n) => selectedNodes.has(n.hostname))}
                        onChange={() => {
                          if (nodes.every((n) => selectedNodes.has(n.hostname))) {
                            setSelectedNodes(new Set());
                          } else {
                            setSelectedNodes(new Set(nodes.map((n) => n.hostname)));
                          }
                        }}
                        className="accent-brand-500"
                      />
                    </TableHead>
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
                      <TableCell>
                        <input
                          type="checkbox"
                          checked={selectedNodes.has(node.hostname)}
                          onChange={() => {
                            setSelectedNodes((prev) => {
                              const next = new Set(prev);
                              if (next.has(node.hostname)) next.delete(node.hostname);
                              else next.add(node.hostname);
                              return next;
                            });
                          }}
                          className="accent-brand-500"
                        />
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        <div className="flex items-center gap-1.5">
                          {node.hostname}
                          {node.reboot_required && (
                            <Badge className="bg-amber-500/15 text-amber-300 border-amber-500/30 text-[10px]" title="Reboot required">
                              <RefreshCw className="h-2.5 w-2.5 mr-0.5" />
                              reboot
                            </Badge>
                          )}
                        </div>
                      </TableCell>
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

      {/* ── OS Package Manager ────────────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Package className="h-4 w-4 text-zinc-400" />
              OS Package Manager
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
                onClick={() => checkOs.mutate()}
                disabled={checkOs.isPending}
              >
                {checkOs.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <RefreshCw className="h-3 w-3 mr-1" />
                )}
                Scan for Updates
              </Button>
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
                onClick={() => collectInventory.mutate()}
                disabled={collectInventory.isPending}
              >
                {collectInventory.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <RefreshCw className="h-3 w-3 mr-1" />
                )}
                Collect Inventory
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

          {/* Search */}
          <div className="relative mb-4">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
            <input
              type="text"
              value={pkgSearch}
              onChange={(e) => setPkgSearch(e.target.value)}
              placeholder="Filter packages..."
              className="w-full rounded-md border border-zinc-700 bg-zinc-800/50 py-1.5 pl-9 pr-3 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>

          {/* Package table */}
          {(() => {
            const filtered = (packageInventory ?? []).filter(
              (p) => !pkgSearch || p.package_name.toLowerCase().includes(pkgSearch.toLowerCase()),
            );
            const allFilteredSelected =
              filtered.length > 0 && filtered.every((p) => selectedPkgs.has(p.package_name));
            return (
              <>
                {filtered.length === 0 ? (
                  <p className="text-sm text-zinc-500 py-4 text-center">
                    {pkgSearch
                      ? "No packages match the filter."
                      : 'No package inventory yet. Click "Collect Inventory" to scan nodes.'}
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-8">
                            <input
                              type="checkbox"
                              checked={allFilteredSelected}
                              onChange={() => {
                                if (allFilteredSelected) {
                                  setSelectedPkgs(new Set());
                                } else {
                                  setSelectedPkgs(new Set(filtered.map((p) => p.package_name)));
                                }
                              }}
                              className="accent-brand-500"
                            />
                          </TableHead>
                          <TableHead>Package</TableHead>
                          <TableHead>New Version</TableHead>
                          <TableHead>Severity</TableHead>
                          <TableHead>Progress</TableHead>
                          <TableHead className="w-10"></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filtered.map((pkg) => {
                          const isExpanded = expandedPkg === pkg.package_name;
                          const pct =
                            pkg.total_nodes > 0
                              ? Math.round((pkg.installed_count / pkg.total_nodes) * 100)
                              : 0;
                          return (
                            <>
                              <TableRow
                                key={pkg.package_name}
                                className={`cursor-pointer ${isExpanded ? "bg-zinc-800/50" : ""}`}
                                onClick={() =>
                                  setExpandedPkg(isExpanded ? null : pkg.package_name)
                                }
                              >
                                <TableCell onClick={(e) => e.stopPropagation()}>
                                  <input
                                    type="checkbox"
                                    checked={selectedPkgs.has(pkg.package_name)}
                                    onChange={() => {
                                      setSelectedPkgs((prev) => {
                                        const next = new Set(prev);
                                        if (next.has(pkg.package_name))
                                          next.delete(pkg.package_name);
                                        else next.add(pkg.package_name);
                                        return next;
                                      });
                                    }}
                                    className="accent-brand-500"
                                  />
                                </TableCell>
                                <TableCell className="font-mono text-xs">{pkg.package_name}</TableCell>
                                <TableCell className="font-mono text-xs">{pkg.new_version}</TableCell>
                                <TableCell>
                                  <div className="flex items-center gap-1.5">
                                    <Badge
                                      className={
                                        pkg.severity === "security"
                                          ? "bg-red-500/15 text-red-400 border-red-500/30 text-[10px]"
                                          : "bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-[10px]"
                                      }
                                    >
                                      {pkg.severity}
                                    </Badge>
                                    {pkg.requires_reboot && (
                                      <span title="Requires reboot after install">
                                        <RefreshCw className="h-3 w-3 text-amber-400" />
                                      </span>
                                    )}
                                  </div>
                                </TableCell>
                                <TableCell>
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs text-zinc-400">
                                      {pkg.installed_count}/{pkg.total_nodes}
                                    </span>
                                    <div className="w-16 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
                                      <div
                                        className="h-full bg-emerald-500 rounded-full"
                                        style={{ width: `${pct}%` }}
                                      />
                                    </div>
                                  </div>
                                </TableCell>
                                <TableCell>
                                  {isExpanded ? (
                                    <ChevronDown className="h-4 w-4 text-zinc-500" />
                                  ) : (
                                    <ChevronRight className="h-4 w-4 text-zinc-500" />
                                  )}
                                </TableCell>
                              </TableRow>
                              {isExpanded && (
                                <TableRow key={`${pkg.package_name}-detail`}>
                                  <TableCell colSpan={6} className="p-0">
                                    <PackageNodeDetail
                                      pkg={pkg}
                                      nodeSearch={expandedNodeSearch}
                                      setNodeSearch={setExpandedNodeSearch}
                                      showAll={showAllNodes}
                                      setShowAll={setShowAllNodes}
                                    />
                                  </TableCell>
                                </TableRow>
                              )}
                            </>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                )}

                {/* Selected actions bar */}
                {selectedPkgs.size > 0 && (
                  <div className="mt-3 flex items-center gap-3 rounded-lg border border-zinc-700 bg-zinc-800/50 px-4 py-2.5">
                    <span className="text-sm text-zinc-300">
                      {selectedPkgs.size} package{selectedPkgs.size !== 1 ? "s" : ""} selected
                    </span>
                    <div className="flex-1" />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => downloadOs.mutate(Array.from(selectedPkgs))}
                      disabled={downloadOs.isPending}
                    >
                      {downloadOs.isPending ? (
                        <Loader2 className="h-3 w-3 animate-spin mr-1" />
                      ) : (
                        <Download className="h-3 w-3 mr-1" />
                      )}
                      Download Selected
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => setShowInstallPreview(true)}
                    >
                      <ListOrdered className="h-3 w-3 mr-1" />
                      Install Selected...
                    </Button>
                  </div>
                )}
              </>
            );
          })()}
        </CardContent>
      </Card>

      {/* ── Install Preview Dialog ─────────────────────────────────────── */}
      {showInstallPreview && installPlan && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-8">
          <div className="w-full max-w-4xl max-h-[85vh] flex flex-col rounded-lg border border-zinc-700 bg-zinc-900 shadow-xl">
            <div className="p-6 pb-0">
              <h3 className="text-base font-semibold text-zinc-100 mb-4">Install Plan</h3>
            </div>

            <div className="flex-1 overflow-y-auto px-6 pb-2">
            {/* Package list */}
            <div className="mb-4">
              <p className="text-xs text-zinc-500 mb-1">
                Packages ({installPlan.packageNames.length}):
              </p>
              <p className="text-sm text-zinc-200 font-mono">
                {installPlan.packageNames.join(", ")}
              </p>
            </div>

            {/* Nodes table */}
            {installPlan.nodes.length > 0 ? (
              <div className="mb-4 overflow-x-auto rounded-md border border-zinc-800">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Node</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Packages</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {installPlan.nodes.map((node) => (
                      <TableRow key={node.hostname}>
                        <TableCell className="font-mono text-xs">{node.hostname}</TableCell>
                        <TableCell>
                          <Badge className={node.role === "central"
                            ? "bg-brand-500/15 text-brand-400 border-brand-500/30 text-[10px]"
                            : "bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-[10px]"
                          }>
                            {node.role}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-zinc-300 font-mono">
                          {node.packages.join(", ")}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <div className="mb-4 rounded-md bg-emerald-500/10 border border-emerald-500/30 p-3 text-sm text-emerald-400">
                <CheckCircle2 className="inline h-4 w-4 mr-1" />
                All selected packages are already installed on all nodes.
              </div>
            )}

            {/* Reboot warning */}
            {installPlan.rebootPkgs.length > 0 && (
              <div className="mb-4 rounded-md bg-amber-500/15 border border-amber-500/30 p-3 text-sm text-amber-300">
                <AlertTriangle className="inline h-4 w-4 mr-1" />
                {installPlan.rebootPkgs.join(", ")} require{installPlan.rebootPkgs.length === 1 ? "s" : ""} a
                reboot after installation. You can restart nodes after installation from the System Nodes section.
              </div>
            )}

            {/* Strategy */}
            <div className="mb-4 space-y-1">
              <label className="text-xs text-zinc-400 font-medium">Strategy</label>
              <Select value={installStrategy} onChange={(e) => setInstallStrategy(e.target.value)} className="w-48">
                <option value="rolling">Rolling</option>
                <option value="test_first">Test First</option>
              </Select>
            </div>

            </div>{/* end scrollable area */}

            <div className="p-6 pt-3 border-t border-zinc-800">
            {startInstallJob.isError && (
              <div className="mb-3 rounded-md bg-red-500/10 border border-red-500/30 p-2 text-xs text-red-400">
                <AlertTriangle className="inline h-3 w-3 mr-1" />
                {(startInstallJob.error as Error)?.message ?? "Failed to start install job"}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setShowInstallPreview(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleStartInstallJob}
                disabled={startInstallJob.isPending || installPlan.nodes.length === 0}
              >
                {startInstallJob.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5 mr-1" />
                )}
                Start Install
              </Button>
            </div>
            </div>{/* end footer */}
          </div>
        </div>
      )}

      {/* ── OS Install Jobs ─────────────────────────────────────────────── */}
      {osInstallJobs && osInstallJobs.length > 0 && (
        <Card className="border-zinc-800 bg-zinc-900">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <ListOrdered className="h-4 w-4 text-zinc-400" />
              OS Install Jobs
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {[...osInstallJobs].sort((a, b) => {
                const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
                const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
                return tb - ta;
              }).map((job) => (
                <OsInstallJobCard
                  key={job.id}
                  job={job}
                  expanded={expandedInstallJobId === job.id}
                  onToggle={() => setExpandedInstallJobId(expandedInstallJobId === job.id ? null : job.id)}
                  onApprove={() => approveInstallJob.mutate(job.id)}
                  onCancel={() => cancelInstallJob.mutate(job.id)}
                  onDelete={() => deleteInstallJob.mutate(job.id)}
                  approving={approveInstallJob.isPending}
                  cancelling={cancelInstallJob.isPending}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

    </div>
  );
}

// ── Package Node Detail (expanded row) ───────────────────────────────────────

function PackageNodeDetail({
  pkg,
  nodeSearch,
  setNodeSearch,
  showAll,
  setShowAll,
}: {
  pkg: PackageInventoryItem;
  nodeSearch: string;
  setNodeSearch: (v: string) => void;
  showAll: boolean;
  setShowAll: (v: boolean) => void;
}) {
  const NODE_LIMIT = 25;
  const filtered = pkg.nodes.filter(
    (n) => !nodeSearch || n.hostname.toLowerCase().includes(nodeSearch.toLowerCase()),
  );
  const displayed = showAll ? filtered : filtered.slice(0, NODE_LIMIT);
  const hasMore = filtered.length > NODE_LIMIT && !showAll;

  return (
    <div className="mx-4 my-3 rounded-md border border-zinc-800 bg-zinc-800/30 p-3">
      {/* Search within nodes */}
      {pkg.nodes.length > 10 && (
        <div className="relative mb-3">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-600" />
          <input
            type="text"
            value={nodeSearch}
            onChange={(e) => setNodeSearch(e.target.value)}
            placeholder="Filter by hostname..."
            className="w-64 rounded border border-zinc-700 bg-zinc-900/50 py-1 pl-7 pr-2 text-xs text-zinc-300 placeholder:text-zinc-600 focus:border-brand-500 focus:outline-none"
          />
        </div>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Hostname</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Current Version</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {displayed.map((node) => (
            <TableRow key={node.hostname}>
              <TableCell className="font-mono text-xs">{node.hostname}</TableCell>
              <TableCell>
                <Badge
                  className={
                    node.role === "central"
                      ? "bg-brand-500/15 text-brand-400 border-brand-500/30 text-[10px]"
                      : "bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-[10px]"
                  }
                >
                  {node.role}
                </Badge>
              </TableCell>
              <TableCell className="font-mono text-xs text-zinc-400">{node.current_version}</TableCell>
              <TableCell>
                {node.status === "installed" ? (
                  <div className="flex items-center gap-1.5">
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="text-xs text-emerald-400">installed</span>
                  </div>
                ) : node.status === "pending" ? (
                  <div className="flex items-center gap-1.5">
                    <ArrowUp className="h-3.5 w-3.5 text-amber-400" />
                    <span className="text-xs text-amber-400">pending</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <HelpCircle className="h-3.5 w-3.5 text-zinc-500" />
                    <span className="text-xs text-zinc-500">unknown</span>
                  </div>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {hasMore && (
        <button
          className="mt-2 text-xs text-brand-400 hover:text-brand-300"
          onClick={() => setShowAll(true)}
        >
          Show all {filtered.length} nodes
        </button>
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

// ── OS Install Job Card ──────────────────────────────────────────────────────

function OsInstallJobCard({
  job,
  expanded,
  onToggle,
  onApprove,
  onCancel,
  onDelete,
  approving,
  cancelling,
}: {
  job: OsInstallJob;
  expanded: boolean;
  onToggle: () => void;
  onApprove: () => void;
  onCancel: () => void;
  onDelete: () => void;
  approving: boolean;
  cancelling: boolean;
}) {
  const isActive = job.status === "pending" || job.status === "running" || job.status === "awaiting_approval";
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
                {job.package_names.length} pkg{job.package_names.length !== 1 ? "s" : ""}
              </span>
              <InstallJobStatusBadge status={job.status} />
              <Badge className="bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-[10px]">
                {job.scope}
              </Badge>
              <Badge className="bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-[10px]">
                {job.strategy.replace(/_/g, " ")}
              </Badge>
              <Badge className="bg-zinc-500/15 text-zinc-400 border-zinc-500/30 text-[10px]">
                {job.restart_policy === "none" ? "no restart" : job.restart_policy.replace(/_/g, " ") + " restart"}
              </Badge>
            </div>
            <div className="flex items-center gap-3 mt-0.5 text-xs text-zinc-500">
              {job.started_by && <span>by {job.started_by}</span>}
              {job.started_at ? <span>started {timeAgo(job.started_at)}</span> : job.created_at && <span>created {timeAgo(job.created_at)}</span>}
              {totalSteps > 0 && (
                <span>
                  {completedSteps}/{totalSteps} steps
                </span>
              )}
              {job.completed_at && <span>completed {timeAgo(job.completed_at)}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {job.status === "awaiting_approval" && (
            <Button
              size="sm"
              className="text-xs"
              onClick={(e) => { e.stopPropagation(); onApprove(); }}
              disabled={approving}
            >
              {approving ? (
                <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              )}
              Approve & Continue
            </Button>
          )}
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
          {!isActive && (
            <Button
              variant="outline"
              size="sm"
              className="text-xs text-zinc-500 hover:text-red-400"
              onClick={(e) => { e.stopPropagation(); onDelete(); }}
            >
              <Trash2 className="h-3.5 w-3.5" />
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
      {expanded && (
        <div className="border-t border-zinc-800 px-4 py-3">
          {/* Package list */}
          <div className="mb-3">
            <p className="text-xs text-zinc-500 mb-1">Packages:</p>
            <p className="text-xs text-zinc-300 font-mono">{job.package_names.join(", ")}</p>
          </div>

          {job.steps.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">#</TableHead>
                  <TableHead>Node</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Test</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Completed</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...job.steps]
                  .sort((a, b) => a.step_order - b.step_order)
                  .map((step) => (
                    <OsInstallStepRow key={step.id} step={step} />
                  ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-xs text-zinc-600 py-2">No steps yet.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── OS Install Step Row ──────────────────────────────────────────────────────

function OsInstallStepRow({ step }: { step: OsInstallJobStep }) {
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
        <TableCell className="text-xs">{step.action.replace(/_/g, " ")}</TableCell>
        <TableCell>
          <div className="flex items-center gap-1.5">
            <InstallStepStatusIcon status={step.status} />
            <span className="text-xs">{step.status.replace(/_/g, " ")}</span>
          </div>
        </TableCell>
        <TableCell>
          {step.is_test_node && (
            <Badge className="bg-blue-500/15 text-blue-400 border-blue-500/30 text-[10px]">
              test
            </Badge>
          )}
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
          <TableCell colSpan={9} className="p-0">
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
