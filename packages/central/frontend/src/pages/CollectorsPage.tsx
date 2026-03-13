import { useState } from "react";
import {
  Cpu,
  Layers,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  CheckCircle2,
  XCircle,
  Clock,
  HeartPulse,
  AlertTriangle,
  CircleOff,
  Minus,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
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
  useCollectors,
  useCollectorGroups,
  useCreateCollectorGroup,
  useUpdateCollectorGroup,
  useDeleteCollectorGroup,
  useUpdateCollector,
  useDeleteCollector,
  useApproveCollector,
  useRejectCollector,
  useRegistrationTokens,
  useCreateRegistrationToken,
  useDeleteRegistrationToken,
} from "@/api/hooks.ts";
import type { Collector, CollectorGroup, RegistrationToken } from "@/types/api.ts";
import { timeAgo, formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

// ── Status indicator helper ───────────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  const cls =
    status === "ACTIVE"
      ? "bg-emerald-500 animate-pulse-dot"
      : status === "PENDING"
        ? "bg-amber-500 animate-pulse-dot"
        : status === "REJECTED"
          ? "bg-red-500"
          : "bg-zinc-500"; // DOWN or unknown
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${cls}`} title={status} />;
}

// ── Pending Collectors Section ────────────────────────────────────────────────

function PendingCollectorsCard() {
  const { data: collectors } = useCollectors();
  const { data: groups } = useCollectorGroups();
  const approveCollector = useApproveCollector();
  const rejectCollector = useRejectCollector();

  const [approveTarget, setApproveTarget] = useState<Collector | null>(null);
  const [approveGroupId, setApproveGroupId] = useState("");
  const [approveError, setApproveError] = useState<string | null>(null);

  const [rejectTarget, setRejectTarget] = useState<Collector | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const pending = collectors?.filter((c) => c.status === "PENDING") ?? [];

  if (pending.length === 0) return null;

  async function handleApprove(e: React.FormEvent) {
    e.preventDefault();
    if (!approveTarget) return;
    setApproveError(null);
    if (!approveGroupId) {
      setApproveError("Please select a collector group.");
      return;
    }
    try {
      await approveCollector.mutateAsync({ id: approveTarget.id, group_id: approveGroupId });
      setApproveTarget(null);
      setApproveGroupId("");
    } catch (err) {
      setApproveError(err instanceof Error ? err.message : "Failed to approve collector");
    }
  }

  async function handleReject() {
    if (!rejectTarget) return;
    try {
      await rejectCollector.mutateAsync({
        id: rejectTarget.id,
        reason: rejectReason.trim() || undefined,
      });
      setRejectTarget(null);
      setRejectReason("");
    } catch { /* silent */ }
  }

  return (
    <>
      <Card className="border-amber-500/30 bg-amber-500/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-amber-400">
            <Clock className="h-4 w-4" />
            Pending Approval
            <Badge variant="default" className="ml-auto bg-amber-500/20 text-amber-400">
              {pending.length}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Hostname</TableHead>
                <TableHead>IP Address</TableHead>
                <TableHead>Fingerprint</TableHead>
                <TableHead>Registered</TableHead>
                <TableHead className="w-32"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pending.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium text-zinc-100">{c.hostname ?? c.name}</TableCell>
                  <TableCell className="font-mono text-xs text-zinc-400">
                    {c.ip_addresses && c.ip_addresses.length > 0
                      ? c.ip_addresses.join(", ")
                      : <span className="italic text-zinc-600">—</span>}
                  </TableCell>
                  <TableCell>
                    {c.fingerprint ? (
                      <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs font-mono text-zinc-300">
                        {c.fingerprint}
                      </code>
                    ) : (
                      <span className="italic text-zinc-600 text-xs">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-zinc-500 text-sm">
                    {c.registered_at ? timeAgo(c.registered_at) : timeAgo(c.last_seen_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button
                        size="sm"
                        variant="secondary"
                        className="gap-1 text-emerald-400 hover:text-emerald-300 h-7 text-xs"
                        onClick={() => {
                          setApproveTarget(c);
                          setApproveGroupId("");
                          setApproveError(null);
                        }}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        className="gap-1 text-red-400 hover:text-red-300 h-7 text-xs"
                        onClick={() => {
                          setRejectTarget(c);
                          setRejectReason("");
                        }}
                      >
                        <XCircle className="h-3.5 w-3.5" />
                        Reject
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Approve Dialog */}
      <Dialog open={!!approveTarget} onClose={() => setApproveTarget(null)} title="Approve Collector">
        <form onSubmit={handleApprove} className="space-y-4">
          <p className="text-sm text-zinc-400">
            Approve collector{" "}
            <span className="font-semibold text-zinc-200">{approveTarget?.hostname ?? approveTarget?.name}</span>
            {approveTarget?.fingerprint && (
              <>
                {" "}with fingerprint{" "}
                <code className="rounded bg-zinc-800 px-1 py-0.5 text-xs font-mono text-zinc-300">
                  {approveTarget.fingerprint}
                </code>
              </>
            )}
            ?
          </p>
          <div className="space-y-1.5">
            <Label htmlFor="approve-group">Assign to Collector Group</Label>
            <select
              id="approve-group"
              value={approveGroupId}
              onChange={(e) => setApproveGroupId(e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500"
              autoFocus
            >
              <option value="">— Select group —</option>
              {(groups ?? []).map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          </div>
          {approveError && <p className="text-sm text-red-400">{approveError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setApproveTarget(null)}>Cancel</Button>
            <Button type="submit" disabled={approveCollector.isPending}>
              {approveCollector.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Approve
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Reject Dialog */}
      <Dialog open={!!rejectTarget} onClose={() => setRejectTarget(null)} title="Reject Collector">
        <div className="space-y-4">
          <p className="text-sm text-zinc-400">
            Reject collector{" "}
            <span className="font-semibold text-zinc-200">{rejectTarget?.hostname ?? rejectTarget?.name}</span>?
          </p>
          <div className="space-y-1.5">
            <Label htmlFor="reject-reason">
              Reason <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <textarea
              id="reject-reason"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="e.g. Unknown device, not authorized"
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500 min-h-[80px] resize-y"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setRejectTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleReject} disabled={rejectCollector.isPending}>
            {rejectCollector.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Reject
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Group Health Indicator ────────────────────────────────────────────────────

function GroupHealthBadge({ health }: { health: { status: string; message: string } }) {
  const cfg = {
    healthy:  { icon: HeartPulse,    cls: "text-emerald-400 bg-emerald-500/10", label: "Healthy" },
    degraded: { icon: AlertTriangle, cls: "text-amber-400 bg-amber-500/10",     label: "Degraded" },
    critical: { icon: XCircle,       cls: "text-red-400 bg-red-500/10",         label: "Critical" },
    empty:    { icon: Minus,         cls: "text-zinc-500 bg-zinc-500/10",       label: "Empty" },
  }[health.status] ?? { icon: CircleOff, cls: "text-zinc-500 bg-zinc-500/10", label: health.status };

  const Icon = cfg.icon;

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${cfg.cls}`} title={health.message}>
      <Icon className="h-3.5 w-3.5" />
      {cfg.label}
    </span>
  );
}

// ── Collector Groups Section ──────────────────────────────────────────────────

function CollectorGroupsCard() {
  const { data: groups, isLoading } = useCollectorGroups();
  const { data: collectors } = useCollectors();
  const createGroup = useCreateCollectorGroup();
  const updateGroup = useUpdateCollectorGroup();
  const deleteGroup = useDeleteCollectorGroup();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<CollectorGroup | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<CollectorGroup | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    try {
      await createGroup.mutateAsync({ name: addName.trim(), description: addDesc.trim() || undefined });
      setAddName(""); setAddDesc(""); setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create group");
    }
  }

  function openEdit(g: CollectorGroup) {
    setEditTarget(g);
    setEditName(g.name);
    setEditDesc(g.description ?? "");
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    if (!editName.trim()) { setEditError("Name is required."); return; }
    try {
      await updateGroup.mutateAsync({
        id: editTarget.id,
        data: { name: editName.trim(), description: editDesc.trim() || undefined },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update group");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteGroup.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch { /* silent */ }
  }

  // Count collectors per group from the collectors list
  const countByGroup = (groupId: string) =>
    collectors?.filter((c) => c.group_id === groupId).length ?? 0;

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Layers className="h-4 w-4" />
            Collector Groups
            <Badge variant="default" className="ml-auto">
              {groups?.length ?? 0}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
          ) : !groups || groups.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-zinc-500">
              <Layers className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No collector groups defined</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Health</TableHead>
                  <TableHead className="text-right">Collectors</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.map((g) => {
                  const cnt = countByGroup(g.id);
                  return (
                    <TableRow key={g.id}>
                      <TableCell className="font-medium text-zinc-100">{g.name}</TableCell>
                      <TableCell className="text-zinc-400 text-sm">
                        {g.description ?? <span className="italic text-zinc-600">—</span>}
                      </TableCell>
                      <TableCell>
                        <GroupHealthBadge health={g.health} />
                      </TableCell>
                      <TableCell className="text-right text-zinc-400 text-sm">{cnt}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => openEdit(g)}
                            className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                            title="Edit"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => setDeleteTarget(g)}
                            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}

          <div className="mt-4 flex justify-end border-t border-zinc-800 pt-4">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => { setAddName(""); setAddDesc(""); setAddError(null); setAddOpen(true); }}
              className="gap-1.5"
            >
              <Plus className="h-4 w-4" />
              New Group
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Add Group Dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="New Collector Group">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="cg-name">Name</Label>
            <Input
              id="cg-name"
              placeholder="e.g. EU-West"
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cg-desc">
              Description <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="cg-desc"
              placeholder="Short description"
              value={addDesc}
              onChange={(e) => setAddDesc(e.target.value)}
            />
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createGroup.isPending}>
              {createGroup.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Group Dialog */}
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title="Edit Collector Group">
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="cg-edit-name">Name</Label>
            <Input
              id="cg-edit-name"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cg-edit-desc">Description</Label>
            <Input
              id="cg-edit-desc"
              value={editDesc}
              onChange={(e) => setEditDesc(e.target.value)}
            />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditTarget(null)}>Cancel</Button>
            <Button type="submit" disabled={updateGroup.isPending}>
              {updateGroup.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Group Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete Collector Group">
        <p className="text-sm text-zinc-400">
          Delete group{" "}
          <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?
          Collectors in this group will be unassigned. Devices targeting this group
          will lose their group assignment.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteGroup.isPending}>
            {deleteGroup.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Collectors Section ────────────────────────────────────────────────────────

function EditCollectorDialog({
  collector,
  groups,
  onClose,
}: {
  collector: Collector;
  groups: CollectorGroup[];
  onClose: () => void;
}) {
  const updateCollector = useUpdateCollector();
  const [name, setName] = useState(collector.name);
  const [groupId, setGroupId] = useState(collector.group_id ?? "");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await updateCollector.mutateAsync({
        id: collector.id,
        data: { name: name.trim(), group_id: groupId || "" },
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update collector");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="col-name">Name</Label>
        <Input
          id="col-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="col-group">Collector Group</Label>
        <select
          id="col-group"
          value={groupId}
          onChange={(e) => setGroupId(e.target.value)}
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          <option value="">— No group —</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>{g.name}</option>
          ))}
        </select>
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={updateCollector.isPending}>
          {updateCollector.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Save
        </Button>
      </DialogFooter>
    </form>
  );
}

function CollectorsCard() {
  const { data: collectors, isLoading } = useCollectors();
  const { data: groups } = useCollectorGroups();
  const deleteCollector = useDeleteCollector();

  const [editTarget, setEditTarget] = useState<Collector | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Collector | null>(null);

  // Exclude PENDING from main table (they have their own card)
  const nonPending = collectors?.filter((c) => c.status !== "PENDING") ?? [];
  const online = nonPending.filter((c) => c.status === "ACTIVE").length;
  const total = nonPending.length;

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteCollector.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch { /* silent */ }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-4 w-4" />
            Collectors
            <span className="ml-2 text-sm font-normal text-zinc-500">
              {online}/{total} online
            </span>
            <Badge variant="default" className="ml-auto">{total}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
          ) : nonPending.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-zinc-500">
              <Cpu className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No collectors registered</p>
              <p className="mt-1 text-xs text-zinc-600">
                Collectors register automatically on first connection.
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">Status</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Hostname</TableHead>
                  <TableHead>IP Address</TableHead>
                  <TableHead>Group</TableHead>
                  <TableHead>Labels</TableHead>
                  <TableHead>Last Seen</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {nonPending.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <StatusDot status={c.status} />
                    </TableCell>
                    <TableCell className="font-medium text-zinc-100">{c.name}</TableCell>
                    <TableCell className="font-mono text-xs text-zinc-400">
                      {c.hostname ?? "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-400">
                      {c.ip_addresses && c.ip_addresses.length > 0
                        ? c.ip_addresses.join(", ")
                        : <span className="italic text-zinc-600">—</span>}
                    </TableCell>
                    <TableCell>
                      {c.group_name ? (
                        <Badge variant="info" className="text-xs">{c.group_name}</Badge>
                      ) : (
                        <span className="text-zinc-600 text-xs italic">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(c.labels ?? {}).map(([k, v]) => (
                          <Badge key={k} variant="default" className="text-xs">
                            {k}: {v}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm">
                      {timeAgo(c.last_seen_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setEditTarget(c)}
                          className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                          title="Edit"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setDeleteTarget(c)}
                          className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Edit Collector Dialog */}
      <Dialog
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        title="Edit Collector"
      >
        {editTarget && (
          <EditCollectorDialog
            collector={editTarget}
            groups={groups ?? []}
            onClose={() => setEditTarget(null)}
          />
        )}
      </Dialog>

      {/* Delete Collector Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Collector"
      >
        <p className="text-sm text-zinc-400">
          Delete collector{" "}
          <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?
          Its API key, app assignments, and historical check data will be removed.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteCollector.isPending}>
            {deleteCollector.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Registration Tokens Section ──────────────────────────────────────────────

import { KeyRound, Copy, Check } from "lucide-react";

function RegistrationTokensCard() {
  const tz = useTimezone();
  const { data: tokens, isLoading } = useRegistrationTokens();
  const createToken = useCreateRegistrationToken();
  const deleteToken = useDeleteRegistrationToken();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addOneTime, setAddOneTime] = useState(false);
  const [addClusterId, setAddClusterId] = useState("");
  const [addExpiry, setAddExpiry] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const [createdToken, setCreatedToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<RegistrationToken | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    try {
      const result = await createToken.mutateAsync({
        name: addName.trim(),
        one_time: addOneTime,
        cluster_id: addClusterId || undefined,
        expires_at: addExpiry || undefined,
      });
      setAddOpen(false);
      setCreatedToken(result.data?.short_code ?? result.data?.token ?? null);
      setAddName("");
      setAddOneTime(false);
      setAddClusterId("");
      setAddExpiry("");
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create token");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteToken.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch { /* silent */ }
  }

  function handleCopy() {
    if (createdToken) {
      navigator.clipboard.writeText(createdToken);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" />
            Registration Tokens
            <Badge variant="default" className="ml-auto">{tokens?.length ?? 0}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
          ) : !tokens || tokens.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-zinc-500">
              <KeyRound className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No registration tokens</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Code</TableHead>
                  <TableHead>One-time</TableHead>
                  <TableHead>Used</TableHead>
                  <TableHead>Expires</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-12"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tokens.map((t) => {
                  const isExpired = !!(t.expires_at && new Date(t.expires_at) < new Date());
                  return (
                  <TableRow key={t.id} className={isExpired ? "opacity-60" : ""}>
                    <TableCell className={`font-medium ${isExpired ? "text-zinc-500 line-through" : "text-zinc-100"}`}>{t.name}</TableCell>
                    <TableCell>
                      {t.short_code ? (
                        <code className={`rounded bg-zinc-800 px-1.5 py-0.5 text-sm font-mono font-bold tracking-wider ${isExpired ? "text-zinc-500 line-through" : "text-emerald-400"}`}>
                          {t.short_code}
                        </code>
                      ) : (
                        <span className="text-zinc-600 text-xs">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={t.one_time ? "info" : "default"}>
                        {t.one_time ? "yes" : "no"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {isExpired ? (
                        <Badge variant="destructive">expired</Badge>
                      ) : (
                        <Badge variant={t.used ? "destructive" : "success"}>
                          {t.used ? "used" : "available"}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className={`text-sm ${isExpired ? "text-red-400" : "text-zinc-500"}`}>
                      {t.expires_at ? formatDate(t.expires_at, tz) : "—"}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm">
                      {formatDate(t.created_at, tz)}
                    </TableCell>
                    <TableCell>
                      <button
                        onClick={() => setDeleteTarget(t)}
                        className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                        title="Revoke"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </TableCell>
                  </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}

          <div className="mt-4 flex justify-end border-t border-zinc-800 pt-4">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => { setAddName(""); setAddOneTime(false); setAddClusterId(""); setAddExpiry(""); setAddError(null); setAddOpen(true); }}
              className="gap-1.5"
            >
              <Plus className="h-4 w-4" />
              New Token
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Create Token Dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="New Registration Token">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="rt-name">Name</Label>
            <Input id="rt-name" placeholder="e.g. prod-eu-token" value={addName} onChange={(e) => setAddName(e.target.value)} autoFocus />
          </div>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={addOneTime}
                onChange={(e) => setAddOneTime(e.target.checked)}
                className="rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500"
              />
              <span className="text-sm text-zinc-300">One-time use</span>
            </label>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rt-expiry">
              Expiry <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input id="rt-expiry" type="datetime-local" value={addExpiry} onChange={(e) => setAddExpiry(e.target.value)} />
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createToken.isPending}>
              {createToken.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Token Created — show registration code */}
      <Dialog open={!!createdToken} onClose={() => { setCreatedToken(null); setCopied(false); }} title="Registration Code Created">
        <div className="space-y-4">
          <p className="text-sm text-zinc-400">
            Use this code in <span className="font-mono text-zinc-200">monctl-setup</span> on
            the collector to register it.
          </p>
          <div className="flex items-center justify-center gap-3 rounded-lg bg-zinc-800 px-4 py-5">
            <code className="text-3xl font-mono font-bold text-emerald-400 tracking-[0.3em]">{createdToken}</code>
            <button
              type="button"
              onClick={handleCopy}
              className="rounded p-1.5 text-zinc-400 hover:text-zinc-100 transition-colors cursor-pointer"
              title="Copy"
            >
              {copied ? <Check className="h-5 w-5 text-emerald-400" /> : <Copy className="h-5 w-5" />}
            </button>
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={() => { setCreatedToken(null); setCopied(false); }}>
            Done
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Delete Token Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Revoke Token">
        <p className="text-sm text-zinc-400">
          Revoke registration token{" "}
          <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?
          Collectors that already registered will not be affected.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteToken.isPending}>
            {deleteToken.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Revoke
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export function CollectorsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Collectors</h1>
        <p className="text-sm text-zinc-500">
          Manage collector groups, registered collectors, and registration tokens.
        </p>
      </div>
      <PendingCollectorsCard />
      <CollectorGroupsCard />
      <CollectorsCard />
      <RegistrationTokensCard />
    </div>
  );
}
