import { useState } from "react";
import {
  Layers,
  Loader2,
  Pencil,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  useAlertRules,
  useCreateIncidentRule,
  useDeleteIncidentRule,
  useIncidentRules,
  useUpdateIncidentRule,
} from "@/api/hooks.ts";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { FilterableSortHead } from "@/components/FilterableSortHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { IncidentRule } from "@/types/api.ts";

const severityVariant = (severity: string) => {
  switch (severity?.toLowerCase()) {
    case "critical":
    case "emergency":
      return "destructive" as const;
    case "warning":
      return "warning" as const;
    case "info":
      return "info" as const;
    default:
      return "default" as const;
  }
};

export function IncidentRulesPage() {
  const { canManage } = usePermissions();
  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<IncidentRule | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<IncidentRule | null>(null);
  const deleteMut = useDeleteIncidentRule();
  const { pageSize, scrollMode } = useTablePreferences();

  const listState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "definition_name", label: "Alert Definition" },
      { key: "severity", label: "Severity" },
      { key: "source", label: "Source" },
    ],
    defaultSortBy: "name",
    defaultSortDir: "asc",
    defaultPageSize: pageSize,
    scrollMode,
  });

  const {
    data: response,
    isLoading,
    isFetching,
  } = useIncidentRules(listState.params);
  const rules = response?.data ?? [];
  const meta = response?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    await deleteMut.mutateAsync(deleteTarget.id);
    setDeleteTarget(null);
  };

  const featureBadges = (r: IncidentRule) => {
    const badges: string[] = [];
    if (r.severity_ladder && r.severity_ladder.length > 0)
      badges.push(`ladder:${r.severity_ladder.length}`);
    if (r.scope_filter && Object.keys(r.scope_filter).length > 0)
      badges.push("scope");
    if (r.depends_on && r.depends_on.rule_ids?.length > 0) badges.push("deps");
    if (r.flap_guard_seconds != null && r.flap_guard_seconds > 0)
      badges.push(`flap:${r.flap_guard_seconds}s`);
    return badges;
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" />
              Incident Rules ({meta.total})
            </CardTitle>
            {canManage("event") && (
              <Button size="sm" onClick={() => setShowCreate(true)}>
                <Plus className="h-3.5 w-3.5" />
                Create Rule
              </Button>
            )}
          </div>
          <p className="text-xs text-zinc-500 mt-1">
            Native rules configured here plus mirror rules auto-synced from
            Event Policies. Mirror rules only expose phase-2 feature fields
            (ladder, scope, deps, flap guard) — edit the source EventPolicy for
            base fields.
          </p>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <FilterableSortHead
                  col="name"
                  label="Name"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterValue={listState.filters.name}
                  onFilterChange={(v) => listState.setFilter("name", v)}
                />
                <FilterableSortHead
                  col="definition_name"
                  label="Alert Definition"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterValue={listState.filters.definition_name}
                  onFilterChange={(v) =>
                    listState.setFilter("definition_name", v)
                  }
                />
                <FilterableSortHead
                  col="mode"
                  label="Mode"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterable={false}
                />
                <TableHead>Threshold</TableHead>
                <FilterableSortHead
                  col="severity"
                  label="Severity"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterValue={listState.filters.severity}
                  onFilterChange={(v) => listState.setFilter("severity", v)}
                />
                <TableHead>Features</TableHead>
                <FilterableSortHead
                  col="source"
                  label="Source"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterValue={listState.filters.source}
                  onFilterChange={(v) => listState.setFilter("source", v)}
                />
                <FilterableSortHead
                  col="enabled"
                  label="Enabled"
                  sortBy={listState.sortBy}
                  sortDir={listState.sortDir}
                  onSort={listState.handleSort}
                  filterable={false}
                />
                <TableHead className="w-12"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={9}
                    className="text-center text-zinc-500 py-8"
                  >
                    {listState.hasActiveFilters
                      ? "No rules match your filters"
                      : "No incident rules configured — create a native rule or let mirror sync pick up from event policies"}
                  </TableCell>
                </TableRow>
              ) : (
                rules.map((r) => {
                  const feats = featureBadges(r);
                  const isMirror = r.source === "mirror";
                  return (
                    <TableRow key={r.id}>
                      <TableCell className="font-medium text-zinc-100">
                        {r.name}
                      </TableCell>
                      <TableCell className="text-zinc-400">
                        {r.definition_name ?? r.definition_id}
                      </TableCell>
                      <TableCell>
                        <Badge variant="default">{r.mode}</Badge>
                      </TableCell>
                      <TableCell className="text-zinc-300">
                        {r.mode === "consecutive"
                          ? `${r.fire_count_threshold} consecutive`
                          : `${r.fire_count_threshold} of ${r.window_size}`}
                      </TableCell>
                      <TableCell>
                        <Badge variant={severityVariant(r.severity)}>
                          {r.severity}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {feats.length === 0 ? (
                          <span className="text-xs text-zinc-600">—</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {feats.map((f) => (
                              <Badge
                                key={f}
                                variant="info"
                                className="text-[10px]"
                              >
                                <Layers className="h-2.5 w-2.5 mr-0.5" />
                                {f}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={isMirror ? "default" : "success"}
                          className="text-[10px]"
                        >
                          {r.source}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={r.enabled ? "success" : "default"}>
                          {r.enabled ? "Enabled" : "Disabled"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {canManage("event") && (
                          <div className="flex items-center gap-1">
                            <button
                              className="rounded p-1 text-zinc-600 hover:text-brand-400 hover:bg-brand-500/10 transition-colors cursor-pointer"
                              onClick={() => setEditTarget(r)}
                              title={
                                isMirror
                                  ? "Edit (phase-2 fields only on mirror rules)"
                                  : "Edit"
                              }
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            {!isMirror && (
                              <button
                                className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                                onClick={() => setDeleteTarget(r)}
                                title="Delete"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            )}
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
          <PaginationBar
            page={listState.page}
            pageSize={listState.pageSize}
            total={meta.total}
            count={meta.count}
            onPageChange={listState.setPage}
            scrollMode={listState.scrollMode}
            sentinelRef={listState.sentinelRef}
            isFetching={isFetching}
            onLoadMore={listState.loadMore}
          />
        </CardContent>
      </Card>

      {showCreate && (
        <IncidentRuleDialog onClose={() => setShowCreate(false)} />
      )}

      {editTarget && (
        <IncidentRuleDialog
          rule={editTarget}
          onClose={() => setEditTarget(null)}
        />
      )}

      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Incident Rule"
      >
        <p className="text-sm text-zinc-400">
          Are you sure you want to delete the rule{" "}
          <span className="font-medium text-zinc-200">
            {deleteTarget?.name}
          </span>
          ? Open incidents created by this rule will remain in the incidents
          table but no new incidents will open.
        </p>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => void handleDelete()}
            disabled={deleteMut.isPending}
          >
            {deleteMut.isPending && (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

function IncidentRuleDialog({
  onClose,
  rule,
}: {
  onClose: () => void;
  rule?: IncidentRule;
}) {
  const isEdit = !!rule;
  const isMirror = rule?.source === "mirror";
  const { data: definitionsResp } = useAlertRules();
  const definitions = definitionsResp?.data ?? [];
  const createMut = useCreateIncidentRule();
  const updateMut = useUpdateIncidentRule();

  const [name, setName] = useState(rule?.name ?? "");
  const [description, setDescription] = useState(rule?.description ?? "");
  const [definitionId, setDefinitionId] = useState(rule?.definition_id ?? "");
  const [mode, setMode] = useState<"consecutive" | "cumulative">(
    rule?.mode ?? "consecutive",
  );
  const [threshold, setThreshold] = useState(rule?.fire_count_threshold ?? 3);
  const [windowSize, setWindowSize] = useState(rule?.window_size ?? 5);
  const [severity, setSeverity] = useState(rule?.severity ?? "warning");
  const [messageTemplate, setMessageTemplate] = useState(
    rule?.message_template ?? "",
  );
  const [autoClear, setAutoClear] = useState(
    rule?.auto_clear_on_resolve ?? true,
  );
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [error, setError] = useState<string | null>(null);

  const isPending = createMut.isPending || updateMut.isPending;

  const handleSubmit = async () => {
    setError(null);
    if (!name || !definitionId) return;
    try {
      if (isEdit) {
        // On mirror rules only the phase-2 feature fields are editable —
        // this dialog's base-fields form is disabled in that case, so we
        // don't send base fields. Phase 3b/3c/3d will add the feature
        // field editors on top of this dialog.
        if (isMirror) {
          // Nothing base-level to update from this 3a dialog on a mirror
          // rule. Fall through gracefully — phase-2 editors come later.
          onClose();
          return;
        }
        await updateMut.mutateAsync({
          id: rule!.id,
          name,
          description: description || null,
          mode,
          fire_count_threshold: threshold,
          window_size: windowSize,
          severity,
          message_template: messageTemplate || null,
          auto_clear_on_resolve: autoClear,
          enabled,
        });
      } else {
        await createMut.mutateAsync({
          name,
          description: description || null,
          definition_id: definitionId,
          mode,
          fire_count_threshold: threshold,
          window_size: windowSize,
          severity,
          message_template: messageTemplate || null,
          auto_clear_on_resolve: autoClear,
          enabled,
        });
      }
      onClose();
    } catch (e: unknown) {
      const msg =
        e instanceof Error ? e.message : "Failed to save incident rule";
      setError(msg);
    }
  };

  const baseFieldsDisabled = isEdit && isMirror;

  return (
    <Dialog
      open
      onClose={onClose}
      title={
        isEdit
          ? `${isMirror ? "View" : "Edit"} Incident Rule — ${rule!.name}`
          : "Create Incident Rule"
      }
    >
      <div className="space-y-4">
        {baseFieldsDisabled && (
          <div className="rounded border border-zinc-800 bg-zinc-900/60 p-3 text-xs text-zinc-400">
            This is a <strong>mirror rule</strong> auto-synced from the Event
            Policy <em>{rule!.name}</em>. Base fields are read-only here — edit
            the Event Policy instead. Phase-2 feature fields (severity ladder,
            scope filter, dependencies, flap guard) will be editable on this
            dialog in phase 3b/3c/3d.
          </div>
        )}

        <div className="space-y-1.5">
          <Label>Name</Label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Core Router Packet Loss"
            disabled={baseFieldsDisabled}
          />
        </div>

        <div className="space-y-1.5">
          <Label>Description (optional)</Label>
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What this rule is for"
            disabled={baseFieldsDisabled}
          />
        </div>

        <div className="space-y-1.5">
          <Label>Alert Definition</Label>
          <Select
            value={definitionId}
            onChange={(e) => setDefinitionId(e.target.value)}
            disabled={isEdit}
          >
            <option value="">Select alert definition</option>
            {definitions.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
          {isEdit && (
            <p className="text-xs text-zinc-500">
              Alert definition cannot be changed after creation.
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Mode</Label>
            <Select
              value={mode}
              onChange={(e) =>
                setMode(e.target.value as "consecutive" | "cumulative")
              }
              disabled={baseFieldsDisabled}
            >
              <option value="consecutive">Consecutive</option>
              <option value="cumulative">Cumulative</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Severity</Label>
            <Select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              disabled={baseFieldsDisabled}
            >
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
              <option value="emergency">Emergency</option>
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Fire Count Threshold</Label>
            <Input
              type="number"
              min={1}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              disabled={baseFieldsDisabled}
            />
          </div>
          {mode === "cumulative" && (
            <div className="space-y-1.5">
              <Label>Window Size</Label>
              <Input
                type="number"
                min={1}
                value={windowSize}
                onChange={(e) => setWindowSize(Number(e.target.value))}
                disabled={baseFieldsDisabled}
              />
            </div>
          )}
        </div>

        <div className="space-y-1.5">
          <Label>Message Template (optional)</Label>
          <Input
            value={messageTemplate}
            onChange={(e) => setMessageTemplate(e.target.value)}
            placeholder="{rule_name}: {value} on {device_name} [{fire_count}x]"
            disabled={baseFieldsDisabled}
          />
        </div>

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={autoClear}
              onChange={(e) => setAutoClear(e.target.checked)}
              className="rounded border-zinc-700"
              disabled={baseFieldsDisabled}
            />
            <span className="text-sm text-zinc-300">Auto-clear on resolve</span>
          </label>
          {isEdit && !isMirror && (
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="rounded border-zinc-700"
              />
              <span className="text-sm text-zinc-300">Enabled</span>
            </label>
          )}
        </div>

        {error && (
          <div className="rounded border border-red-900 bg-red-950/40 p-2 text-xs text-red-300">
            {error}
          </div>
        )}
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          {baseFieldsDisabled ? "Close" : "Cancel"}
        </Button>
        {!baseFieldsDisabled && (
          <Button
            onClick={() => void handleSubmit()}
            disabled={!name || !definitionId || isPending}
          >
            {isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {isEdit ? "Save" : "Create"}
          </Button>
        )}
      </DialogFooter>
    </Dialog>
  );
}
