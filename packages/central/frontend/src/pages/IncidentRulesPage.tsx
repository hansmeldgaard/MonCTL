import { useMemo, useState } from "react";
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
  DependencyPicker,
  validateDependsOn,
} from "@/components/DependencyPicker.tsx";
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
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";
import type {
  IncidentRule,
  IncidentRuleDependsOn,
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
  const { compact } = useDisplayPreferences();

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

  const columns = useMemo<FlexColumnDef<IncidentRule>[]>(() => {
    const cols: FlexColumnDef<IncidentRule>[] = [
      {
        key: "name",
        label: "Name",
        defaultWidth: 240,
        cellClassName: "font-medium text-zinc-100",
        cell: (r) => r.name,
      },
      {
        key: "definition_name",
        label: "Alert Definition",
        defaultWidth: 200,
        cellClassName: "text-zinc-400",
        cell: (r) => r.definition_name ?? r.definition_id,
      },
      {
        key: "mode",
        label: "Mode",
        filterable: false,
        defaultWidth: 120,
        cell: (r) => <Badge variant="default">{r.mode}</Badge>,
      },
      {
        key: "__threshold",
        label: "Threshold",
        pickerLabel: "Threshold",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-300",
        cell: (r) =>
          r.mode === "consecutive"
            ? `${r.fire_count_threshold} consecutive`
            : `${r.fire_count_threshold} of ${r.window_size}`,
      },
      {
        key: "severity",
        label: "Severity",
        defaultWidth: 120,
        cell: (r) => (
          <Badge variant={severityVariant(r.severity)}>{r.severity}</Badge>
        ),
      },
      {
        key: "__features",
        label: "Features",
        pickerLabel: "Features",
        sortable: false,
        filterable: false,
        defaultWidth: 200,
        cell: (r) => {
          const feats = featureBadges(r);
          if (feats.length === 0) {
            return <span className="text-xs text-zinc-600">—</span>;
          }
          return (
            <div className="flex flex-wrap gap-1">
              {feats.map((f) => (
                <Badge key={f} variant="info" className="text-[10px]">
                  <Layers className="h-2.5 w-2.5 mr-0.5" />
                  {f}
                </Badge>
              ))}
            </div>
          );
        },
      },
      {
        key: "source",
        label: "Source",
        defaultWidth: 100,
        cell: (r) => (
          <Badge
            variant={r.source === "mirror" ? "default" : "success"}
            className="text-[10px]"
          >
            {r.source}
          </Badge>
        ),
      },
      {
        key: "enabled",
        label: "Enabled",
        filterable: false,
        defaultWidth: 100,
        cell: (r) => (
          <Badge variant={r.enabled ? "success" : "default"}>
            {r.enabled ? "Enabled" : "Disabled"}
          </Badge>
        ),
      },
    ];
    if (canManage("event")) {
      cols.push({
        key: "__actions",
        label: "",
        pickerLabel: "Actions",
        sortable: false,
        filterable: false,
        defaultWidth: 70,
        cell: (r) => (
          <div className="flex items-center gap-1">
            <button
              className="rounded p-1 text-zinc-600 hover:text-brand-400 hover:bg-brand-500/10 transition-colors cursor-pointer"
              onClick={() => setEditTarget(r)}
              title={
                r.source === "mirror"
                  ? "Edit (phase-2 fields only on mirror rules)"
                  : "Edit"
              }
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            {r.source !== "mirror" && (
              <button
                className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                onClick={() => setDeleteTarget(r)}
                title="Delete"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ),
      });
    }
    return cols;
  }, [canManage]);

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset,
  } = useColumnConfig<IncidentRule>("incident-rules", columns);

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
            <div className="flex items-center gap-2">
              <DisplayMenu
                columns={columns}
                configMap={configMap}
                onToggleHidden={setHidden}
                onReset={reset}
              />
              {canManage("event") && (
                <Button size="sm" onClick={() => setShowCreate(true)}>
                  <Plus className="h-3.5 w-3.5" />
                  Create Rule
                </Button>
              )}
            </div>
          </div>
          <p className="text-xs text-zinc-500 mt-1">
            Incident rules drive the IncidentEngine. Configure a rule's severity
            ladder, scope filter, dependencies, and flap guard here; the engine
            applies them on the next 30s cycle.
          </p>
        </CardHeader>
        <CardContent>
          <div
            className={
              compact
                ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
                : ""
            }
          >
            <FlexTable<IncidentRule>
              orderedVisibleColumns={orderedVisibleColumns}
              configMap={configMap}
              onOrderChange={setOrder}
              onWidthChange={setWidth}
              rows={rules}
              rowKey={(r) => r.id}
              sortBy={listState.sortBy}
              sortDir={listState.sortDir}
              onSort={listState.handleSort}
              filters={listState.filters}
              onFilterChange={(col, v) => listState.setFilter(col, v)}
              emptyState={
                listState.hasActiveFilters
                  ? "No rules match your filters"
                  : "No incident rules configured — create a native rule or let mirror sync pick up from event policies"
              }
            />
          </div>
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

  const [activeTab, setActiveTab] = useState<
    "settings" | "ladder" | "scope" | "deps"
  >("settings");
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
  const [dependsOn, setDependsOn] = useState<IncidentRuleDependsOn | null>(
    rule?.depends_on ?? null,
  );
  const [companionIds, setCompanionIds] = useState<string[]>(
    rule?.clear_on_companion_ids ?? [],
  );
  const [companionMode, setCompanionMode] = useState<"any" | "all">(
    rule?.clear_companion_mode ?? "any",
  );
  const [error, setError] = useState<string | null>(null);

  // All rules are needed for the dependency picker's parent select —
  // reuse the same hook the list page does. Fetches at dialog-open time;
  // relying on React Query's shared cache with the outer list page means
  // this is effectively free.
  const { data: allRulesResp } = useIncidentRules({ limit: 500, offset: 0 });
  const allRules = allRulesResp?.data ?? [];

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
  const dependsOnValidation = validateDependsOn(dependsOn);

  const ladderChanged =
    JSON.stringify(ladder ?? null) !==
    JSON.stringify(rule?.severity_ladder ?? null);
  const scopeChanged =
    JSON.stringify(scopeFilter ?? null) !==
    JSON.stringify(rule?.scope_filter ?? null);
  const flapChanged =
    (flapGuardSeconds ?? null) !== (rule?.flap_guard_seconds ?? null);
  const depsChanged =
    JSON.stringify(dependsOn ?? null) !==
    JSON.stringify(rule?.depends_on ?? null);
  // Mirror rules can edit any of the phase-2 fields but no base fields.
  // Save is only shown when at least one phase-2 field has changed.
  const mirrorHasSavableChanges =
    isMirror && (ladderChanged || scopeChanged || flapChanged || depsChanged);

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
    if (!dependsOnValidation.ok) {
      setError(dependsOnValidation.error);
      return;
    }
    try {
      if (isEdit) {
        if (isMirror) {
          // Mirror rules: only phase-2 feature fields are allowed by the
          // API. Send a minimal PATCH body containing only what changed.
          if (!ladderChanged && !scopeChanged && !flapChanged && !depsChanged) {
            onClose();
            return;
          }
          const body: Record<string, unknown> = { id: rule!.id };
          if (ladderChanged) body.severity_ladder = ladder;
          if (scopeChanged) body.scope_filter = scopeFilter;
          if (flapChanged) body.flap_guard_seconds = flapGuardSeconds;
          if (depsChanged) body.depends_on = dependsOn;
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
            depends_on: dependsOn,
            clear_on_companion_ids: companionIds.length ? companionIds : null,
            clear_companion_mode: companionMode,
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
          depends_on: dependsOn,
          clear_on_companion_ids: companionIds.length ? companionIds : null,
          clear_companion_mode: companionMode,
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
    if (!dependsOnValidation.ok) return true;
    if (!baseFieldsDisabled && (!name || !definitionId)) return true;
    return false;
  })();

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      className="!max-w-3xl h-[720px]"
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
          <TabTrigger value="settings" className="min-w-[10rem]">
            <span className="inline-flex items-center justify-center gap-1.5 w-full">
              Settings
              <span className="inline-block w-4" />
            </span>
          </TabTrigger>
          <TabTrigger value="ladder" className="min-w-[11rem]">
            <span className="inline-flex items-center justify-center gap-1.5 w-full">
              Severity Ladder
              <span className="inline-flex w-4 justify-center">
                {ladder && ladder.length > 0 ? (
                  <span className="rounded-full bg-brand-500/20 px-1.5 py-0.5 text-[10px] text-brand-300">
                    {ladder.length}
                  </span>
                ) : null}
              </span>
            </span>
          </TabTrigger>
          <TabTrigger value="scope" className="min-w-[13rem]">
            <span className="inline-flex items-center justify-center gap-1.5 w-full">
              Scope &amp; Flap Guard
              <span className="inline-flex w-4 justify-center">
                {(() => {
                  const n =
                    (scopeFilter && Object.keys(scopeFilter).length > 0
                      ? 1
                      : 0) +
                    (flapGuardSeconds != null && flapGuardSeconds > 0 ? 1 : 0);
                  return n > 0 ? (
                    <span className="rounded-full bg-brand-500/20 px-1.5 py-0.5 text-[10px] text-brand-300">
                      {n}
                    </span>
                  ) : null;
                })()}
              </span>
            </span>
          </TabTrigger>
          <TabTrigger value="deps" className="min-w-[11rem]">
            <span className="inline-flex items-center justify-center gap-1.5 w-full">
              Dependencies
              <span className="inline-flex w-4 justify-center">
                {dependsOn && dependsOn.rule_ids.length > 0 ? (
                  <span className="rounded-full bg-brand-500/20 px-1.5 py-0.5 text-[10px] text-brand-300">
                    {dependsOn.rule_ids.length}
                  </span>
                ) : null}
              </span>
            </span>
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
                features onto this mirror, or the <strong>Dependencies</strong>{" "}
                tab to suppress this mirror under a parent rule's incidents.
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

            <div className="border-t border-zinc-800 pt-5">
              <Label>Clear on companion alert</Label>
              <p className="text-xs text-zinc-500 mt-1">
                Clear the incident when a <em>different</em> alert is healthy
                for the same entity — e.g. a recovery / pairing check. Select
                one or more companion alert definitions below. This runs in
                addition to{" "}
                <span className="font-mono">auto_clear_on_resolve</span>.
              </p>

              <div className="mt-3 flex items-center gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="companion-mode"
                    value="any"
                    checked={companionMode === "any"}
                    onChange={() => setCompanionMode("any")}
                    className="accent-brand-500"
                    disabled={baseFieldsDisabled}
                  />
                  <span className="text-sm text-zinc-300">
                    Any companion healthy
                  </span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="companion-mode"
                    value="all"
                    checked={companionMode === "all"}
                    onChange={() => setCompanionMode("all")}
                    className="accent-brand-500"
                    disabled={baseFieldsDisabled}
                  />
                  <span className="text-sm text-zinc-300">
                    All companions healthy
                  </span>
                </label>
              </div>

              <div className="mt-3 space-y-2">
                {companionIds.map((cid) => {
                  const defn = definitions.find((d) => d.id === cid);
                  return (
                    <div
                      key={cid}
                      className="flex items-center justify-between rounded border border-zinc-800 bg-zinc-900/40 px-3 py-2"
                    >
                      <span className="text-xs text-zinc-200 font-mono">
                        {defn?.name ?? cid}
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={baseFieldsDisabled}
                        onClick={() =>
                          setCompanionIds(companionIds.filter((x) => x !== cid))
                        }
                      >
                        Remove
                      </Button>
                    </div>
                  );
                })}
                <Select
                  value=""
                  onChange={(e) => {
                    const v = e.target.value;
                    if (!v) return;
                    if (!companionIds.includes(v)) {
                      setCompanionIds([...companionIds, v]);
                    }
                  }}
                  disabled={baseFieldsDisabled}
                >
                  <option value="">
                    {companionIds.length
                      ? "Add another companion alert…"
                      : "Select companion alert definition…"}
                  </option>
                  {definitions
                    .filter((d) => !companionIds.includes(d.id))
                    .map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                </Select>
              </div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="deps">
          <DependencyPicker
            value={dependsOn}
            onChange={setDependsOn}
            availableRules={allRules}
            currentRuleId={rule?.id}
          />
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
