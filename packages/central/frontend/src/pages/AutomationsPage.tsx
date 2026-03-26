import { useState, useEffect } from "react";
import { useLocation } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  Clock,
  Code2,
  Loader2,
  Play,
  Plus,
  Settings2,
  Trash2,
  Pencil,
  Zap,
  History,
  ArrowUp,
  ArrowDown,
  CheckCircle2,
  XCircle,
  Timer,
  SkipForward,
  Server,
  Monitor,
} from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Card, CardContent } from "@/components/ui/card.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
import {
  useActions,
  useCreateAction,
  useUpdateAction,
  useDeleteAction,
  useAutomations,
  useCreateAutomation,
  useUpdateAutomation,
  useDeleteAutomation,
  useTriggerAutomation,
  useAutomationRuns,
  useAutomationRun,
  useDevices,
  useCredentialTypes,
  useEventPolicies,
  useLabelKeys,
  useLabelValues,
} from "@/api/hooks.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import type {
  Action,
  Automation,
  AutomationRunStepResult,
} from "@/types/api.ts";

type Tab = "automations" | "actions" | "runs";

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

function formatCooldown(seconds: number): string {
  if (seconds === 0) return "None";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

function timeAgo(isoString: string): string {
  if (!isoString) return "-";
  const diff = Date.now() - new Date(isoString).getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

const statusBadge = (status: string) => {
  switch (status) {
    case "success":
      return <Badge variant="success">success</Badge>;
    case "failed":
      return <Badge variant="destructive">failed</Badge>;
    case "timeout":
      return <Badge variant="warning">timeout</Badge>;
    case "running":
      return <Badge variant="info">running</Badge>;
    case "skipped":
      return <Badge variant="default">skipped</Badge>;
    default:
      return <Badge variant="default">{status}</Badge>;
  }
};

// ── Actions Tab ─────────────────────────────────────────────────────────────

function ActionsTab() {
  const { pageSize } = useTablePreferences();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [editAction, setEditAction] = useState<Action | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Action | null>(null);

  const { data, isLoading } = useActions({ search: search || undefined, page, page_size: pageSize });
  const actions = data?.data ?? [];
  const total = data?.total ?? 0;

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center justify-between mb-3">
        <ClearableInput
          placeholder="Search actions..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          onClear={() => { setSearch(""); setPage(1); }}
          className="w-64 h-8 text-sm"
        />
        <Button size="sm" onClick={() => setCreateOpen(true)} className="gap-1.5">
          <Plus className="h-3.5 w-3.5" /> New Action
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="w-24">Target</TableHead>
                <TableHead className="w-32">Credential</TableHead>
                <TableHead className="w-24">Timeout</TableHead>
                <TableHead className="w-20">Enabled</TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {actions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-zinc-500 py-8">
                    {search ? "No actions match your search" : "No actions created yet"}
                  </TableCell>
                </TableRow>
              ) : (
                actions.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <button
                        onClick={() => setEditAction(a)}
                        className="text-brand-400 hover:underline text-left cursor-pointer"
                      >
                        {a.name}
                      </button>
                      {a.description && (
                        <p className="text-xs text-zinc-500 mt-0.5 truncate max-w-xs">{a.description}</p>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={a.target === "collector" ? "success" : "info"}>
                        {a.target === "collector" ? (
                          <><Monitor className="h-3 w-3 mr-1" />collector</>
                        ) : (
                          <><Server className="h-3 w-3 mr-1" />central</>
                        )}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {a.credential_type || <span className="text-zinc-600">-</span>}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">{a.timeout_seconds}s</TableCell>
                    <TableCell>
                      <span className={`inline-block h-2 w-2 rounded-full ${a.enabled ? "bg-emerald-500" : "bg-zinc-600"}`} />
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" onClick={() => setEditAction(a)} title="Edit">
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(a)} title="Delete">
                          <Trash2 className="h-3.5 w-3.5 text-red-400" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {total > pageSize && (
        <PaginationBar page={page} pageSize={pageSize} total={total} count={actions.length} onPageChange={setPage} />
      )}

      {/* Create/Edit Dialog */}
      {(createOpen || editAction) && (
        <ActionFormDialog
          action={editAction}
          onClose={() => { setCreateOpen(false); setEditAction(null); }}
        />
      )}

      {/* Delete Confirmation */}
      {deleteTarget && (
        <DeleteActionDialog action={deleteTarget} onClose={() => setDeleteTarget(null)} />
      )}
    </>
  );
}

function ActionFormDialog({ action, onClose }: { action: Action | null; onClose: () => void }) {
  const isEdit = !!action;
  const [name, setName] = useState(action?.name ?? "");
  const [description, setDescription] = useState(action?.description ?? "");
  const [target, setTarget] = useState(action?.target ?? "collector");
  const [sourceCode, setSourceCode] = useState(action?.source_code ?? "");
  const [credentialType, setCredentialType] = useState(action?.credential_type ?? "");
  const [timeout, setTimeout] = useState(String(action?.timeout_seconds ?? 60));
  const [enabled, setEnabled] = useState(action?.enabled ?? true);
  const [error, setError] = useState<string | null>(null);

  const createMut = useCreateAction();
  const updateMut = useUpdateAction();
  const { data: credentialTypes = [] } = useCredentialTypes();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) { setError("Name is required."); return; }

    const payload = {
      name: name.trim(),
      description: description.trim() || null,
      target,
      source_code: sourceCode,
      credential_type: credentialType || null,
      timeout_seconds: parseInt(timeout) || 60,
      enabled,
    };

    try {
      if (isEdit) {
        await updateMut.mutateAsync({ id: action!.id, ...payload });
      } else {
        await createMut.mutateAsync(payload as Parameters<typeof createMut.mutateAsync>[0]);
      }
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save action");
    }
  }

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <Dialog open onClose={onClose} title={isEdit ? "Edit Action" : "New Action"} size="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="action-name">Name</Label>
            <Input id="action-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Restart Service" autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="action-target">Target</Label>
            <Select id="action-target" value={target} onChange={(e) => setTarget(e.target.value as "collector" | "central")}>
              <option value="collector">Collector</option>
              <option value="central">Central</option>
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="action-desc">Description</Label>
          <Input id="action-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional description..." />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="action-cred">Credential Type</Label>
            <Select id="action-cred" value={credentialType} onChange={(e) => setCredentialType(e.target.value)}>
              <option value="">None</option>
              {Array.isArray(credentialTypes) && credentialTypes.map((ct: { id?: string; name: string }) => (
                <option key={ct.name} value={ct.name}>{ct.name}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="action-timeout">Timeout (seconds)</Label>
            <Input id="action-timeout" type="number" min={5} max={300} value={timeout} onChange={(e) => setTimeout(e.target.value)} />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="action-code">Source Code</Label>
          <div className="rounded-md border border-zinc-700 bg-zinc-950 text-xs text-zinc-500 px-3 py-2 mb-1 font-mono leading-relaxed">
            # context.device_id, context.device_name, context.device_ip<br />
            # context.credential — decrypted credential dict<br />
            # context.shared_data — data from previous steps<br />
            # context.set_output(key, value) — store data for next steps
          </div>
          <textarea
            id="action-code"
            className="w-full h-56 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm font-mono text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-brand-500 resize-y"
            value={sourceCode}
            onChange={(e) => setSourceCode(e.target.value)}
            placeholder="# Write your Python script here..."
            spellCheck={false}
          />
        </div>

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="action-enabled"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="rounded border-zinc-600"
          />
          <Label htmlFor="action-enabled">Enabled</Label>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={isPending}>
            {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {isEdit ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}

function DeleteActionDialog({ action, onClose }: { action: Action; onClose: () => void }) {
  const deleteMut = useDeleteAction();
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    setError(null);
    try {
      await deleteMut.mutateAsync(action.id);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    }
  }

  return (
    <Dialog open onClose={onClose} title="Delete Action">
      <p className="text-sm text-zinc-300">
        Delete <strong>{action.name}</strong>? This cannot be undone.
      </p>
      <p className="text-xs text-zinc-500 mt-1">
        Actions referenced by automations cannot be deleted.
      </p>
      {error && <p className="text-sm text-red-400 mt-2">{error}</p>}
      <DialogFooter>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="destructive" onClick={handleDelete} disabled={deleteMut.isPending}>
          {deleteMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Delete
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

// ── Automations Tab ─────────────────────────────────────────────────────────

function AutomationsTab({ prefill, onPrefillConsumed }: { prefill?: AutomationPrefill | null; onPrefillConsumed?: () => void }) {
  const { pageSize } = useTablePreferences();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [createPrefill, setCreatePrefill] = useState<AutomationPrefill | null>(null);
  const [editTarget, setEditTarget] = useState<Automation | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Automation | null>(null);
  const [triggerTarget, setTriggerTarget] = useState<Automation | null>(null);

  // Auto-open create dialog when prefill arrives from Events page
  useEffect(() => {
    if (prefill) {
      setCreatePrefill(prefill);
      setCreateOpen(true);
      onPrefillConsumed?.();
    }
  }, [prefill, onPrefillConsumed]);

  const { data, isLoading } = useAutomations({ search: search || undefined, page, page_size: pageSize });
  const automations = data?.data ?? [];
  const total = data?.total ?? 0;

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center justify-between mb-3">
        <ClearableInput
          placeholder="Search automations..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          onClear={() => { setSearch(""); setPage(1); }}
          className="w-64 h-8 text-sm"
        />
        <Button size="sm" onClick={() => setCreateOpen(true)} className="gap-1.5">
          <Plus className="h-3.5 w-3.5" /> New Automation
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="w-24">Trigger</TableHead>
                <TableHead className="w-48">Config</TableHead>
                <TableHead className="w-32">Steps</TableHead>
                <TableHead className="w-24">Cooldown</TableHead>
                <TableHead className="w-20">Enabled</TableHead>
                <TableHead className="w-28"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {automations.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-zinc-500 py-8">
                    {search ? "No automations match your search" : "No automations created yet"}
                  </TableCell>
                </TableRow>
              ) : (
                automations.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <button
                        onClick={() => setEditTarget(a)}
                        className="text-brand-400 hover:underline text-left cursor-pointer"
                      >
                        {a.name}
                      </button>
                      {a.description && (
                        <p className="text-xs text-zinc-500 mt-0.5 truncate max-w-xs">{a.description}</p>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={a.trigger_type === "event" ? "info" : "warning"}>
                        {a.trigger_type === "event" ? (
                          <><Zap className="h-3 w-3 mr-1" />event</>
                        ) : (
                          <><Clock className="h-3 w-3 mr-1" />cron</>
                        )}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-zinc-400 font-mono">
                      {a.trigger_type === "event"
                        ? a.event_severity_filter || "any severity"
                        : a.cron_expression || "-"}
                    </TableCell>
                    <TableCell>
                      <span className="text-zinc-300 text-sm">{a.steps.length} step{a.steps.length !== 1 ? "s" : ""}</span>
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {formatCooldown(a.cooldown_seconds)}
                    </TableCell>
                    <TableCell>
                      <span className={`inline-block h-2 w-2 rounded-full ${a.enabled ? "bg-emerald-500" : "bg-zinc-600"}`} />
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        {a.trigger_type === "cron" && (
                          <Button variant="ghost" size="icon" onClick={() => setTriggerTarget(a)} title="Manual trigger">
                            <Play className="h-3.5 w-3.5 text-emerald-400" />
                          </Button>
                        )}
                        <Button variant="ghost" size="icon" onClick={() => setEditTarget(a)} title="Edit">
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(a)} title="Delete">
                          <Trash2 className="h-3.5 w-3.5 text-red-400" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {total > pageSize && (
        <PaginationBar page={page} pageSize={pageSize} total={total} count={automations.length} onPageChange={setPage} />
      )}

      {(createOpen || editTarget) && (
        <AutomationFormDialog
          automation={editTarget}
          prefill={createOpen ? createPrefill : null}
          onClose={() => { setCreateOpen(false); setEditTarget(null); setCreatePrefill(null); }}
        />
      )}

      {deleteTarget && (
        <DeleteAutomationDialog automation={deleteTarget} onClose={() => setDeleteTarget(null)} />
      )}

      {triggerTarget && (
        <ManualTriggerDialog automation={triggerTarget} onClose={() => setTriggerTarget(null)} />
      )}
    </>
  );
}

function AutomationFormDialog({ automation, prefill, onClose }: { automation: Automation | null; prefill?: AutomationPrefill | null; onClose: () => void }) {
  const isEdit = !!automation;
  const initDeviceIds = automation?.device_ids ?? prefill?.device_ids ?? [];
  const [name, setName] = useState(automation?.name ?? "");
  const [description, setDescription] = useState(automation?.description ?? "");
  const [triggerType, setTriggerType] = useState((automation?.trigger_type ?? prefill?.trigger_type ?? "event") as "event" | "cron");
  const [severityFilter, setSeverityFilter] = useState(automation?.event_severity_filter ?? prefill?.event_severity_filter ?? "");
  const [selectedPolicyIds, setSelectedPolicyIds] = useState<string[]>(automation?.event_policy_ids ?? []);
  const [cronExpr, setCronExpr] = useState(automation?.cron_expression ?? "");
  const [cooldown, setCooldown] = useState(String(automation?.cooldown_seconds ?? 300));
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<string[]>(initDeviceIds);
  const [deviceScope, setDeviceScope] = useState<"all" | "devices" | "labels">(
    initDeviceIds.length ? "devices" : automation?.device_label_filter ? "labels" : "all"
  );
  const [labelKey, setLabelKey] = useState(Object.keys(automation?.device_label_filter ?? {})[0] ?? "");
  const [labelValue, setLabelValue] = useState(Object.values(automation?.device_label_filter ?? {})[0] ?? "");
  const [deviceSearch, setDeviceSearch] = useState("");
  const [policySearch, setPolicySearch] = useState("");
  const [labelSearch, setLabelSearch] = useState("");
  const [enabled, setEnabled] = useState(automation?.enabled ?? true);
  const [steps, setSteps] = useState<Array<{ action_id: string; step_order: number; credential_type_override: string; timeout_override: string }>>(
    automation?.steps?.map((s) => ({
      action_id: s.action_id,
      step_order: s.step_order,
      credential_type_override: s.credential_type_override ?? "",
      timeout_override: s.timeout_override ? String(s.timeout_override) : "",
    })) ?? []
  );
  const [error, setError] = useState<string | null>(null);

  const createMut = useCreateAutomation();
  const updateMut = useUpdateAutomation();
  const { data: actionsData } = useActions({ page_size: 100 });
  const availableActions = actionsData?.data ?? [];
  const { data: devicesResp } = useDevices({ limit: 500 });
  const allDevices = devicesResp?.data ?? [];
  const { data: policiesResp } = useEventPolicies({ limit: 200 });
  const allPolicies = policiesResp?.data ?? [];
  const { data: labelKeys = [] } = useLabelKeys();
  const { data: labelValues = [] } = useLabelValues(labelKey || null);

  function addStep() {
    setSteps((prev) => [...prev, { action_id: "", step_order: prev.length + 1, credential_type_override: "", timeout_override: "" }]);
  }

  function removeStep(idx: number) {
    setSteps((prev) => prev.filter((_, i) => i !== idx).map((s, i) => ({ ...s, step_order: i + 1 })));
  }

  function moveStep(idx: number, dir: -1 | 1) {
    setSteps((prev) => {
      const arr = [...prev];
      const newIdx = idx + dir;
      if (newIdx < 0 || newIdx >= arr.length) return prev;
      [arr[idx], arr[newIdx]] = [arr[newIdx], arr[idx]];
      return arr.map((s, i) => ({ ...s, step_order: i + 1 }));
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) { setError("Name is required."); return; }
    if (triggerType === "cron" && !cronExpr.trim()) { setError("Cron expression is required."); return; }

    const stepsPayload = steps
      .filter((s) => s.action_id)
      .map((s) => ({
        action_id: s.action_id,
        step_order: s.step_order,
        credential_type_override: s.credential_type_override || null,
        timeout_override: s.timeout_override ? parseInt(s.timeout_override) : null,
      }));

    const payload = {
      name: name.trim(),
      description: description.trim() || null,
      trigger_type: triggerType,
      event_severity_filter: triggerType === "event" ? (severityFilter || null) : null,
      event_policy_ids: triggerType === "event" && selectedPolicyIds.length > 0 ? selectedPolicyIds : null,
      event_label_filter: null,
      cron_expression: triggerType === "cron" ? cronExpr.trim() : null,
      cron_device_label_filter: null,
      cron_device_ids: null,
      device_ids: deviceScope === "devices" && selectedDeviceIds.length > 0 ? selectedDeviceIds : null,
      device_label_filter: deviceScope === "labels" && labelKey ? { [labelKey]: labelValue } : null,
      cooldown_seconds: parseInt(cooldown) || 0,
      enabled,
      steps: stepsPayload,
    };

    try {
      if (isEdit) {
        await updateMut.mutateAsync({ id: automation!.id, ...payload });
      } else {
        await createMut.mutateAsync(payload);
      }
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save");
    }
  }

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <Dialog open onClose={onClose} title={isEdit ? "Edit Automation" : "New Automation"} size="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="auto-name">Name</Label>
            <Input id="auto-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Auto-remediate link down" autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="auto-trigger">Trigger Type</Label>
            <Select id="auto-trigger" value={triggerType} onChange={(e) => setTriggerType(e.target.value as "event" | "cron")} disabled={isEdit}>
              <option value="event">Event</option>
              <option value="cron">Cron Schedule</option>
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="auto-desc">Description</Label>
          <Input id="auto-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional..." />
        </div>

        {triggerType === "event" && (
          <div className="space-y-3">
            {/* Event Policies */}
            <div className="space-y-1.5">
              <Label>Event Policies {selectedPolicyIds.length > 0 && <span className="text-zinc-500">({selectedPolicyIds.length} selected)</span>}</Label>
              <ClearableInput
                placeholder="Search policies..."
                value={policySearch}
                onChange={(e) => setPolicySearch(e.target.value)}
                onClear={() => setPolicySearch("")}
                className="h-7 text-xs"
              />
              <div className="max-h-32 overflow-y-auto rounded-md border border-zinc-700 bg-zinc-900">
                {allPolicies.length === 0 ? (
                  <p className="text-xs text-zinc-500 px-3 py-2">No event policies configured</p>
                ) : (
                  allPolicies
                    .filter((p) => !policySearch || p.name.toLowerCase().includes(policySearch.toLowerCase()) || (p.definition_name || "").toLowerCase().includes(policySearch.toLowerCase()))
                    .map((p) => (
                      <label key={p.id} className="flex items-center gap-2 px-3 py-1 hover:bg-zinc-800 cursor-pointer text-sm text-zinc-300">
                        <input
                          type="checkbox"
                          checked={selectedPolicyIds.includes(p.id)}
                          onChange={(e) => {
                            if (e.target.checked) setSelectedPolicyIds((prev) => [...prev, p.id]);
                            else setSelectedPolicyIds((prev) => prev.filter((id) => id !== p.id));
                          }}
                          className="rounded border-zinc-600"
                        />
                        <span className="flex-1 truncate">{p.name}</span>
                        <span className="text-zinc-500 text-xs">{p.event_severity}</span>
                      </label>
                    ))
                )}
              </div>
              <p className="text-xs text-zinc-500">Leave empty to match all events. Select specific policies to narrow the trigger.</p>
            </div>

            {/* Severity Filter */}
            <div className="space-y-1.5">
              <Label htmlFor="auto-severity">Severity Filter</Label>
              <Select id="auto-severity" value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
                <option value="">Any severity</option>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
                <option value="emergency">Emergency</option>
              </Select>
            </div>
          </div>
        )}

        {triggerType === "cron" && (
          <div className="space-y-1.5">
            <Label htmlFor="auto-cron">Cron Expression</Label>
            <Input id="auto-cron" value={cronExpr} onChange={(e) => setCronExpr(e.target.value)} placeholder="*/5 * * * *" className="font-mono" />
            <p className="text-xs text-zinc-500">Standard cron format: minute hour day month weekday</p>
          </div>
        )}

        {/* Device Scope */}
        <div className="space-y-2">
          <Label>Device Scope</Label>
          <div className="flex gap-3">
            {(["all", "devices", "labels"] as const).map((opt) => (
              <label key={opt} className="flex items-center gap-1.5 text-sm text-zinc-300 cursor-pointer">
                <input type="radio" name="device-scope" checked={deviceScope === opt} onChange={() => setDeviceScope(opt)} className="border-zinc-600" />
                {opt === "all" ? "All devices" : opt === "devices" ? "Specific devices" : "By label"}
              </label>
            ))}
          </div>
          {deviceScope === "devices" && (
            <div className="space-y-1.5">
              <ClearableInput
                placeholder="Search by name or IP..."
                value={deviceSearch}
                onChange={(e) => setDeviceSearch(e.target.value)}
                onClear={() => setDeviceSearch("")}
                className="h-7 text-xs"
              />
              {selectedDeviceIds.length > 0 && (
                <p className="text-xs text-zinc-500">{selectedDeviceIds.length} device(s) selected</p>
              )}
              <div className="max-h-36 overflow-y-auto rounded-md border border-zinc-700 bg-zinc-900">
                {allDevices
                  .filter((d) => {
                    if (!deviceSearch) return true;
                    const q = deviceSearch.toLowerCase();
                    return d.name.toLowerCase().includes(q) || d.address.toLowerCase().includes(q);
                  })
                  .map((d) => (
                    <label key={d.id} className="flex items-center gap-2 px-3 py-1 hover:bg-zinc-800 cursor-pointer text-sm text-zinc-300">
                      <input
                        type="checkbox"
                        checked={selectedDeviceIds.includes(d.id)}
                        onChange={(e) => {
                          if (e.target.checked) setSelectedDeviceIds((p) => [...p, d.id]);
                          else setSelectedDeviceIds((p) => p.filter((id) => id !== d.id));
                        }}
                        className="rounded border-zinc-600"
                      />
                      <span className="truncate">{d.name}</span>
                      <span className="text-zinc-500 text-xs ml-auto shrink-0">{d.address}</span>
                    </label>
                  ))}
              </div>
            </div>
          )}
          {deviceScope === "labels" && (
            <div className="space-y-1.5">
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <ClearableInput
                    placeholder="Search labels..."
                    value={labelSearch}
                    onChange={(e) => setLabelSearch(e.target.value)}
                    onClear={() => setLabelSearch("")}
                    className="h-7 text-xs"
                  />
                  <Select value={labelKey} onChange={(e) => { setLabelKey(e.target.value); setLabelValue(""); }}>
                    <option value="">Select label key...</option>
                    {labelKeys
                      .filter((lk) => !labelSearch || lk.key.toLowerCase().includes(labelSearch.toLowerCase()))
                      .map((lk) => (
                        <option key={lk.id} value={lk.key}>{lk.key}{lk.description ? ` — ${lk.description}` : ""}</option>
                      ))}
                  </Select>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-zinc-500 h-7 flex items-center">Value</p>
                  <Select value={labelValue} onChange={(e) => setLabelValue(e.target.value)} disabled={!labelKey}>
                    <option value="">Any value</option>
                    {labelValues.map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </Select>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="auto-cooldown">Cooldown (seconds)</Label>
          <Input id="auto-cooldown" type="number" min={0} value={cooldown} onChange={(e) => setCooldown(e.target.value)} />
          <p className="text-xs text-zinc-500">Minimum seconds between runs per device. 0 = no cooldown.</p>
        </div>

        {/* Steps */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Steps</Label>
            <Button type="button" variant="ghost" size="sm" onClick={addStep} className="gap-1">
              <Plus className="h-3 w-3" /> Add Step
            </Button>
          </div>
          {steps.length === 0 && (
            <p className="text-xs text-zinc-500 py-2">No steps added. Add at least one action step.</p>
          )}
          {steps.map((step, idx) => (
            <div key={idx} className="flex items-center gap-2 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2">
              <span className="text-xs text-zinc-500 font-mono w-5">{step.step_order}.</span>
              <Select
                value={step.action_id}
                onChange={(e) => {
                  const newSteps = [...steps];
                  newSteps[idx] = { ...newSteps[idx], action_id: e.target.value };
                  setSteps(newSteps);
                }}
                className="flex-1"
              >
                <option value="">Select action...</option>
                {availableActions.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.target})
                  </option>
                ))}
              </Select>
              <Button type="button" variant="ghost" size="icon" onClick={() => moveStep(idx, -1)} disabled={idx === 0} title="Move up">
                <ArrowUp className="h-3 w-3" />
              </Button>
              <Button type="button" variant="ghost" size="icon" onClick={() => moveStep(idx, 1)} disabled={idx === steps.length - 1} title="Move down">
                <ArrowDown className="h-3 w-3" />
              </Button>
              <Button type="button" variant="ghost" size="icon" onClick={() => removeStep(idx)} title="Remove">
                <Trash2 className="h-3 w-3 text-red-400" />
              </Button>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <input type="checkbox" id="auto-enabled" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="rounded border-zinc-600" />
          <Label htmlFor="auto-enabled">Enabled</Label>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={isPending}>
            {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {isEdit ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}

function DeleteAutomationDialog({ automation, onClose }: { automation: Automation; onClose: () => void }) {
  const deleteMut = useDeleteAutomation();

  async function handleDelete() {
    await deleteMut.mutateAsync(automation.id);
    onClose();
  }

  return (
    <Dialog open onClose={onClose} title="Delete Automation">
      <p className="text-sm text-zinc-300">
        Delete <strong>{automation.name}</strong>? All steps will be removed. This cannot be undone.
      </p>
      <DialogFooter>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="destructive" onClick={handleDelete} disabled={deleteMut.isPending}>
          {deleteMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Delete
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

function ManualTriggerDialog({ automation, onClose }: { automation: Automation; onClose: () => void }) {
  const [selectedDevices, setSelectedDevices] = useState<string[]>([]);
  const [result, setResult] = useState<{ run_ids: string[]; count: number } | null>(null);
  const { data: devicesData } = useDevices({ limit: 200 });
  const devices = devicesData?.data ?? [];
  const triggerMut = useTriggerAutomation();

  async function handleTrigger() {
    if (selectedDevices.length === 0) return;
    try {
      const res = await triggerMut.mutateAsync({ id: automation.id, device_ids: selectedDevices });
      setResult((res as { data: { run_ids: string[]; count: number } }).data);
    } catch {
      // error handled by mutation
    }
  }

  return (
    <Dialog open onClose={onClose} title={`Trigger: ${automation.name}`}>
      {result ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-emerald-400">
            <CheckCircle2 className="h-5 w-5" />
            <span className="text-sm">Triggered {result.count} run(s)</span>
          </div>
          <p className="text-xs text-zinc-500">Run IDs: {result.run_ids.join(", ").substring(0, 100)}...</p>
          <DialogFooter>
            <Button variant="secondary" onClick={onClose}>Close</Button>
          </DialogFooter>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-zinc-400">Select devices to run this automation on:</p>
          <div className="max-h-48 overflow-y-auto rounded-md border border-zinc-700 bg-zinc-900">
            {devices.map((d) => (
              <label key={d.id} className="flex items-center gap-2 px-3 py-1.5 hover:bg-zinc-800 cursor-pointer text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={selectedDevices.includes(d.id)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedDevices((prev) => [...prev, d.id]);
                    } else {
                      setSelectedDevices((prev) => prev.filter((id) => id !== d.id));
                    }
                  }}
                  className="rounded border-zinc-600"
                />
                {d.name}
                <span className="text-zinc-500 text-xs ml-auto">{d.address}</span>
              </label>
            ))}
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={onClose}>Cancel</Button>
            <Button onClick={handleTrigger} disabled={selectedDevices.length === 0 || triggerMut.isPending} className="gap-1.5">
              {triggerMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Run Now ({selectedDevices.length})
            </Button>
          </DialogFooter>
        </div>
      )}
    </Dialog>
  );
}

// ── Run History Tab ─────────────────────────────────────────────────────────

function RunHistoryTab() {
  const { pageSize } = useTablePreferences();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);

  const { data, isLoading } = useAutomationRuns({
    status: statusFilter || undefined,
    page,
    page_size: pageSize,
  });
  const runs = data?.data ?? [];
  const total = data?.total ?? 0;

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center gap-3 mb-3">
        <Select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }} className="w-40 h-8 text-sm">
          <option value="">All statuses</option>
          <option value="success">Success</option>
          <option value="failed">Failed</option>
          <option value="timeout">Timeout</option>
          <option value="running">Running</option>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Automation</TableHead>
                <TableHead className="w-24">Trigger</TableHead>
                <TableHead>Device</TableHead>
                <TableHead className="w-24">Status</TableHead>
                <TableHead className="w-24">Steps</TableHead>
                <TableHead className="w-24">Duration</TableHead>
                <TableHead className="w-28">Triggered By</TableHead>
                <TableHead className="w-28">Started</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-zinc-500 py-8">
                    No automation runs yet
                  </TableCell>
                </TableRow>
              ) : (
                runs.map((r) => (
                  <TableRow key={r.run_id} className="cursor-pointer hover:bg-zinc-800/50" onClick={() => setSelectedRun(r.run_id)}>
                    <TableCell className="text-zinc-200">{r.automation_name}</TableCell>
                    <TableCell>
                      <Badge variant={r.trigger_type === "event" ? "info" : r.trigger_type === "cron" ? "warning" : "default"}>
                        {r.trigger_type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-zinc-300 text-sm">{r.device_name || "-"}</TableCell>
                    <TableCell>{statusBadge(r.status)}</TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {r.completed_steps}/{r.total_steps}
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">{formatDuration(r.duration_ms)}</TableCell>
                    <TableCell className="text-zinc-500 text-xs">{r.triggered_by}</TableCell>
                    <TableCell className="text-zinc-500 text-xs">{timeAgo(r.started_at)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {total > pageSize && (
        <PaginationBar page={page} pageSize={pageSize} total={total} count={runs.length} onPageChange={setPage} />
      )}

      {selectedRun && (
        <RunDetailDialog runId={selectedRun} onClose={() => setSelectedRun(null)} />
      )}
    </>
  );
}

function RunDetailDialog({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { data: run, isLoading } = useAutomationRun(runId);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);

  return (
    <Dialog open onClose={onClose} title="Run Details" size="lg">
      {isLoading || !run ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
        </div>
      ) : (
        <div className="space-y-4">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium text-zinc-200">{run.automation_name}</h3>
              <p className="text-xs text-zinc-500 mt-0.5">
                {run.device_name} ({run.device_ip}) &middot; {run.trigger_type} &middot; {run.triggered_by}
              </p>
            </div>
            {statusBadge(run.status)}
          </div>

          <div className="flex gap-4 text-xs text-zinc-500">
            <span>Duration: {formatDuration(run.duration_ms)}</span>
            <span>Steps: {run.completed_steps}/{run.total_steps}</span>
            <span>Started: {run.started_at ? new Date(run.started_at).toLocaleString() : "-"}</span>
          </div>

          {run.event_id && (
            <p className="text-xs text-zinc-500">
              Event: {run.event_severity} &mdash; {run.event_message.substring(0, 100)}
            </p>
          )}

          {/* Step Results */}
          <div className="space-y-1">
            <Label>Steps</Label>
            {(run.step_results ?? []).map((step: AutomationRunStepResult) => (
              <div key={step.step} className="rounded-md border border-zinc-700 bg-zinc-900">
                <button
                  onClick={() => setExpandedStep(expandedStep === step.step ? null : step.step)}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm cursor-pointer"
                >
                  {expandedStep === step.step ? <ChevronDown className="h-3.5 w-3.5 text-zinc-500" /> : <ChevronRight className="h-3.5 w-3.5 text-zinc-500" />}
                  <span className="font-mono text-xs text-zinc-500 w-5">{step.step}.</span>
                  <span className="text-zinc-200 flex-1">{step.action_name}</span>
                  <Badge variant={step.target === "collector" ? "success" : "info"} className="text-[10px]">{step.target}</Badge>
                  {step.status === "success" && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
                  {step.status === "failed" && <XCircle className="h-3.5 w-3.5 text-red-500" />}
                  {step.status === "timeout" && <Timer className="h-3.5 w-3.5 text-amber-500" />}
                  {step.status === "skipped" && <SkipForward className="h-3.5 w-3.5 text-zinc-500" />}
                  <span className="text-xs text-zinc-500">{formatDuration(step.duration_ms)}</span>
                </button>
                {expandedStep === step.step && (
                  <div className="border-t border-zinc-700 px-3 py-2 space-y-2">
                    {step.stdout && (
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase mb-0.5">stdout</p>
                        <pre className="text-xs text-zinc-300 bg-zinc-950 rounded px-2 py-1 overflow-x-auto max-h-32 whitespace-pre-wrap">{step.stdout}</pre>
                      </div>
                    )}
                    {step.stderr && (
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase mb-0.5">stderr</p>
                        <pre className="text-xs text-red-300 bg-zinc-950 rounded px-2 py-1 overflow-x-auto max-h-32 whitespace-pre-wrap">{step.stderr}</pre>
                      </div>
                    )}
                    {step.output_data && Object.keys(step.output_data).length > 0 && (
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase mb-0.5">output data</p>
                        <pre className="text-xs text-zinc-300 bg-zinc-950 rounded px-2 py-1 overflow-x-auto max-h-32">{JSON.stringify(step.output_data, null, 2)}</pre>
                      </div>
                    )}
                    {!step.stdout && !step.stderr && Object.keys(step.output_data ?? {}).length === 0 && (
                      <p className="text-xs text-zinc-600">No output</p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          <DialogFooter>
            <Button variant="secondary" onClick={onClose}>Close</Button>
          </DialogFooter>
        </div>
      )}
    </Dialog>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

interface AutomationPrefill {
  trigger_type?: string;
  event_severity_filter?: string;
  device_ids?: string[];
}

export function AutomationsPage() {
  const [tab, setTab] = useState<Tab>("automations");
  const location = useLocation();
  const [prefill, setPrefill] = useState<AutomationPrefill | null>(null);

  // Handle prefill from Events page navigation
  useEffect(() => {
    const state = location.state as { prefill?: AutomationPrefill } | null;
    if (state?.prefill) {
      setPrefill(state.prefill);
      setTab("automations");
      // Clear the state so it doesn't re-trigger on re-render
      window.history.replaceState({}, "");
    }
  }, [location.state]);

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <div className="flex items-center gap-1 rounded-lg bg-zinc-900 p-1 w-fit border border-zinc-800">
        <Button variant={tab === "automations" ? "secondary" : "ghost"} size="sm" onClick={() => setTab("automations")}>
          <Settings2 className="h-3.5 w-3.5" />
          Automations
        </Button>
        <Button variant={tab === "actions" ? "secondary" : "ghost"} size="sm" onClick={() => setTab("actions")}>
          <Code2 className="h-3.5 w-3.5" />
          Actions
        </Button>
        <Button variant={tab === "runs" ? "secondary" : "ghost"} size="sm" onClick={() => setTab("runs")}>
          <History className="h-3.5 w-3.5" />
          Run History
        </Button>
      </div>

      {tab === "automations" && <AutomationsTab prefill={prefill} onPrefillConsumed={() => setPrefill(null)} />}
      {tab === "actions" && <ActionsTab />}
      {tab === "runs" && <RunHistoryTab />}
    </div>
  );
}
