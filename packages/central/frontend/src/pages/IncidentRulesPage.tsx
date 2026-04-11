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
  Tabs,
  TabsList,
  TabTrigger,
  TabsContent,
} from "@/components/ui/tabs.tsx";
import { LadderEditor, validateLadder } from "@/components/LadderEditor.tsx";
import { ScopeFilterEditor } from "@/components/ScopeFilterEditor.tsx";
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
import type {
  IncidentRule,
  IncidentRuleScopeFilter,
  IncidentRuleSeverityLadderStep,
} from "@/types/api.ts";

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

  const [activeTab, setActiveTab] = useState<"settings" | "ladder" | "scope">(
    "settings",
  );
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
  const [ladder, setLadder] = useState<IncidentRuleSeverityLadderStep[] | null>(
    rule?.severity_ladder ?? null,
  );
  const [scopeFilter, setScopeFilter] =
    useState<IncidentRuleScopeFilter | null>(rule?.scope_filter ?? null);
  const [flapGuardSeconds, setFlapGuardSeconds] = useState<number | null>(
    rule?.flap_guard_seconds ?? null,
  );
  const [error, setError] = useState<string | null>(null);

  const isPending = createMut.isPending || updateMut.isPending;
  const baseFieldsDisabled = isEdit && isMirror;

  const ladderValidation = validateLadder(ladder);
  // Scope filter validation: keys must be non-empty, no duplicates. The
  // ScopeFilterEditor collapses duplicates on save but the error surfaces
  // in the editor itself; save gate uses the normalized dict here.
  const scopeFilterInvalid = (() => {
    if (!scopeFilter) return false;
    // If the dict has any empty key it's invalid — but rowsToDict already
    // strips empty keys, so this is really a check for "nothing remains"
    // vs "something remains that shouldn't have been allowed".
    for (const key of Object.keys(scopeFilter)) {
      if (!key.trim()) return true;
    }
    return false;
  })();
  const flapGuardInvalid =
    flapGuardSeconds !== null &&
    (!Number.isInteger(flapGuardSeconds) || flapGuardSeconds < 0);

  const ladderChanged =
    JSON.stringify(ladder ?? null) !==
    JSON.stringify(rule?.severity_ladder ?? null);
  const scopeChanged =
    JSON.stringify(scopeFilter ?? null) !==
    JSON.stringify(rule?.scope_filter ?? null);
  const flapChanged =
    (flapGuardSeconds ?? null) !== (rule?.flap_guard_seconds ?? null);
  // Mirror rules can edit any of the phase-2 fields but no base fields.
  // Save is only shown when at least one phase-2 field has changed.
  const mirrorHasSavableChanges =
    isMirror && (ladderChanged || scopeChanged || flapChanged);

  const handleSubmit = async () => {
    setError(null);
    if (!ladderValidation.ok) {
      setError(ladderValidation.error);
      return;
    }
    if (scopeFilterInvalid) {
      setError("Scope filter has an invalid key");
      return;
    }
    if (flapGuardInvalid) {
      setError("Flap guard must be a non-negative integer number of seconds");
      return;
    }
    try {
      if (isEdit) {
        if (isMirror) {
          // Mirror rules: only phase-2 feature fields are allowed by the
          // API. Send a minimal PATCH body containing only what changed.
          if (!ladderChanged && !scopeChanged && !flapChanged) {
            onClose();
            return;
          }
          const body: Record<string, unknown> = { id: rule!.id };
          if (ladderChanged) body.severity_ladder = ladder;
          if (scopeChanged) body.scope_filter = scopeFilter;
          if (flapChanged) body.flap_guard_seconds = flapGuardSeconds;
          await updateMut.mutateAsync(
            body as { id: string } & Record<string, unknown>,
          );
        } else {
          if (!name || !definitionId) return;
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
            severity_ladder: ladder,
            scope_filter: scopeFilter,
            flap_guard_seconds: flapGuardSeconds,
          });
        }
      } else {
        if (!name || !definitionId) return;
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
          severity_ladder: ladder,
          scope_filter: scopeFilter,
          flap_guard_seconds: flapGuardSeconds,
        });
      }
      onClose();
    } catch (e: unknown) {
      const msg =
        e instanceof Error ? e.message : "Failed to save incident rule";
      setError(msg);
    }
  };

  const showSaveButton = baseFieldsDisabled ? mirrorHasSavableChanges : true;
  const saveDisabled = (() => {
    if (isPending) return true;
    if (!ladderValidation.ok) return true;
    if (scopeFilterInvalid) return true;
    if (flapGuardInvalid) return true;
    if (!baseFieldsDisabled && (!name || !definitionId)) return true;
    return false;
  })();

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={
        isEdit
          ? `${isMirror ? "View" : "Edit"} Incident Rule — ${rule!.name}`
          : "Create Incident Rule"
      }
    >
      <Tabs
        value={activeTab}
        onChange={(v) => setActiveTab(v as "settings" | "ladder" | "scope")}
      >
        <TabsList>
          <TabTrigger value="settings">Settings</TabTrigger>
          <TabTrigger value="ladder">
            Severity Ladder
            {ladder && ladder.length > 0 && (
              <span className="ml-1.5 rounded-full bg-brand-500/20 px-1.5 py-0.5 text-[10px] text-brand-300">
                {ladder.length}
              </span>
            )}
          </TabTrigger>
          <TabTrigger value="scope">
            Scope &amp; Flap Guard
            {(() => {
              const n =
                (scopeFilter && Object.keys(scopeFilter).length > 0 ? 1 : 0) +
                (flapGuardSeconds != null && flapGuardSeconds > 0 ? 1 : 0);
              return n > 0 ? (
                <span className="ml-1.5 rounded-full bg-brand-500/20 px-1.5 py-0.5 text-[10px] text-brand-300">
                  {n}
                </span>
              ) : null;
            })()}
          </TabTrigger>
        </TabsList>

        <TabsContent value="settings">
          <div className="space-y-4">
            {baseFieldsDisabled && (
              <div className="rounded border border-zinc-800 bg-zinc-900/60 p-3 text-xs text-zinc-400">
                This is a <strong>mirror rule</strong> auto-synced from the
                Event Policy <em>{rule!.name}</em>. Base fields are read-only
                here — edit the Event Policy instead. Use the{" "}
                <strong>Severity Ladder</strong> or{" "}
                <strong>Scope &amp; Flap Guard</strong> tabs to layer phase-2
                features onto this mirror. Dependency picker lands in phase 3d.
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
                <span className="text-sm text-zinc-300">
                  Auto-clear on resolve
                </span>
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
          </div>
        </TabsContent>

        <TabsContent value="ladder">
          <LadderEditor
            value={ladder}
            onChange={setLadder}
            baseSeverity={severity}
          />
        </TabsContent>

        <TabsContent value="scope">
          <div className="space-y-6">
            <div>
              <Label>Scope filter</Label>
              <div className="mt-2">
                <ScopeFilterEditor
                  value={scopeFilter}
                  onChange={setScopeFilter}
                />
              </div>
            </div>

            <div className="border-t border-zinc-800 pt-5">
              <Label>Flap guard (seconds)</Label>
              <p className="text-xs text-zinc-500 mt-1">
                Hold auto-clear for this many seconds after the underlying alert
                resolves. A re-fire inside the window re-attaches to the same
                incident — no churn in the incidents table. Leave blank to clear
                immediately (legacy behavior). Suggested default:{" "}
                <span className="font-mono">90</span> seconds (3× the 30s
                evaluation interval, per the phase 2e design).
              </p>
              <div className="mt-2 flex items-center gap-3">
                <Input
                  type="number"
                  min={0}
                  value={flapGuardSeconds ?? ""}
                  onChange={(e) => {
                    const raw = e.target.value;
                    if (raw === "") {
                      setFlapGuardSeconds(null);
                      return;
                    }
                    const n = Number(raw);
                    setFlapGuardSeconds(Number.isFinite(n) ? n : null);
                  }}
                  placeholder="blank = no guard"
                  className="w-40 font-mono text-xs"
                />
                {flapGuardSeconds != null && flapGuardSeconds > 0 && (
                  <span className="text-xs text-zinc-500">
                    ≈{" "}
                    {flapGuardSeconds < 60
                      ? `${flapGuardSeconds}s`
                      : flapGuardSeconds < 3600
                        ? `${Math.floor(flapGuardSeconds / 60)}m ${
                            flapGuardSeconds % 60
                          }s`
                        : `${Math.floor(flapGuardSeconds / 3600)}h ${Math.floor(
                            (flapGuardSeconds % 3600) / 60,
                          )}m`}
                  </span>
                )}
                {flapGuardSeconds != null && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setFlapGuardSeconds(null)}
                  >
                    Clear
                  </Button>
                )}
              </div>
              {flapGuardInvalid && (
                <div className="mt-2 rounded border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
                  Flap guard must be a non-negative whole number of seconds.
                </div>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>

      {error && (
        <div className="mt-4 rounded border border-red-900 bg-red-950/40 p-2 text-xs text-red-300">
          {error}
        </div>
      )}

      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          {baseFieldsDisabled && !mirrorHasSavableChanges ? "Close" : "Cancel"}
        </Button>
        {showSaveButton && (
          <Button onClick={() => void handleSubmit()} disabled={saveDisabled}>
            {isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {isEdit ? "Save" : "Create"}
          </Button>
        )}
      </DialogFooter>
    </Dialog>
  );
}
