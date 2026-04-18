import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Boxes,
  Download,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
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
  usePacks,
  useExportPack,
  useDeletePack,
  useReconcilePack,
  usePreviewImport,
  useImportPack,
} from "@/api/hooks.ts";
import type {
  Pack,
  PackImportPreviewEntity,
  PackReconcileDiff,
} from "@/types/api.ts";
import { CreatePackDialog } from "@/components/CreatePackDialog.tsx";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { formatTime } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";

const SECTION_LABELS: Record<string, string> = {
  apps: "Apps",
  app_versions: "App Versions",
  alert_definitions: "Alert Definitions",
  threshold_variables: "Threshold Variables",
  credential_templates: "Credential Templates",
  snmp_oids: "SNMP OIDs",
  device_templates: "Device Templates",
  device_categories: "Device Categories",
  label_keys: "Label Keys",
  connectors: "Connectors",
  connector_versions: "Connector Versions",
  device_types: "Device Types",
  event_policies: "Event Policies",
  template_bindings: "Template Bindings",
};

export function PacksPage() {
  const { canCreate, canDelete } = usePermissions();
  const tz = useTimezone();
  const { mode } = useTimeDisplayMode();
  const { compact } = useDisplayPreferences();
  const navigate = useNavigate();
  const { pageSize, scrollMode } = useTablePreferences();
  const listState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "pack_uid", label: "Pack UID" },
      { key: "description", label: "Description", sortable: false },
    ],
    defaultPageSize: pageSize,
    scrollMode,
  });
  const { data: response, isLoading, isFetching } = usePacks(listState.params);
  const packs = response?.data ?? [];
  const meta = (response as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };
  const exportPack = useExportPack();
  const deletePack = useDeletePack();
  const reconcilePack = useReconcilePack();
  const previewImport = usePreviewImport();
  const importPack = useImportPack();

  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Pack | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importData, setImportData] = useState<Record<string, unknown> | null>(
    null,
  );
  const [importPreview, setImportPreview] = useState<{
    entities: PackImportPreviewEntity[];
    pack_uid: string;
    name: string;
    version: string;
    is_upgrade: boolean;
    current_version?: string;
  } | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, string>>({});
  const [importResult, setImportResult] = useState<{
    created: number;
    updated: number;
    skipped: number;
  } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [reconcileTarget, setReconcileTarget] = useState<Pack | null>(null);
  const [reconcileResult, setReconcileResult] = useState<{
    pack: Pack;
    diff: PackReconcileDiff;
  } | null>(null);
  const [reconcileError, setReconcileError] = useState<string | null>(null);

  function totalEntities(p: Pack): number {
    return Object.values(p.entity_counts).reduce((a, b) => a + b, 0);
  }

  async function handleExport(p: Pack) {
    try {
      const res = await exportPack.mutateAsync(p.id);
      const blob = new Blob([JSON.stringify(res.data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${p.pack_uid}-v${p.current_version}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* silent */
    }
  }

  async function handleReconcile() {
    if (!reconcileTarget) return;
    setReconcileError(null);
    try {
      const res = await reconcilePack.mutateAsync(reconcileTarget.pack_uid);
      setReconcileResult({ pack: reconcileTarget, diff: res.data.diff });
      setReconcileTarget(null);
    } catch (err) {
      setReconcileError(
        err instanceof Error ? err.message : "Reconcile failed",
      );
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deletePack.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      /* silent */
    }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      setImportData(data);
      setImportError(null);
      setImportResult(null);
      const res = await previewImport.mutateAsync(data);
      setImportPreview(res.data);
      const defaultResolutions: Record<string, string> = {};
      for (const entity of res.data.entities) {
        if (entity.status === "conflict") {
          defaultResolutions[`${entity.section}:${entity.name}`] = "skip";
        } else if (entity.status === "upgrade") {
          defaultResolutions[`${entity.section}:${entity.name}`] = "overwrite";
        }
      }
      setResolutions(defaultResolutions);
      setImportOpen(true);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Invalid JSON file");
      setImportOpen(true);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleImport() {
    if (!importData) return;
    try {
      const res = await importPack.mutateAsync({
        pack_data: importData,
        resolutions,
      });
      setImportResult(res.data);
      setImportPreview(null);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Import failed");
    }
  }

  function closeImport() {
    setImportOpen(false);
    setImportData(null);
    setImportPreview(null);
    setImportResult(null);
    setImportError(null);
    setResolutions({});
  }

  const columns = useMemo<FlexColumnDef<Pack>[]>(
    () => [
      {
        key: "name",
        label: "Name",
        defaultWidth: 220,
        cellClassName: "font-medium text-zinc-100",
        cell: (p) => (
          <button
            type="button"
            onClick={() => navigate(`/packs/${p.id}`)}
            className="font-medium text-brand-400 hover:text-brand-300 transition-colors cursor-pointer"
          >
            {p.name}
          </button>
        ),
      },
      {
        key: "pack_uid",
        label: "UID",
        defaultWidth: 200,
        cell: (p) => <Badge variant="info">{p.pack_uid}</Badge>,
      },
      {
        key: "current_version",
        label: "Version",
        filterable: false,
        defaultWidth: 100,
        cell: (p) => <Badge variant="default">v{p.current_version}</Badge>,
      },
      {
        key: "description",
        label: "Description",
        sortable: false,
        defaultWidth: 300,
        cellClassName: "text-zinc-400 max-w-[300px] truncate",
        cell: (p) => p.description ?? "—",
      },
      {
        key: "__entities",
        label: "Entities",
        pickerLabel: "Entities",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cellClassName: "text-zinc-400",
        cell: (p) => totalEntities(p),
      },
      {
        key: "installed_at",
        label: "Installed",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (p) => formatTime(p.installed_at, mode, tz),
      },
      {
        key: "__actions",
        label: "",
        pickerLabel: "Actions",
        sortable: false,
        filterable: false,
        defaultWidth: 120,
        cell: (p) => (
          <div
            className="flex items-center gap-1"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => handleExport(p)}
              className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
              title="Export"
            >
              <Download className="h-4 w-4" />
            </button>
            {canCreate("app") && (
              <button
                onClick={() => {
                  setReconcileError(null);
                  setReconcileTarget(p);
                }}
                className="rounded p-1 text-zinc-600 hover:text-sky-400 hover:bg-sky-500/10 transition-colors cursor-pointer"
                title="Reconcile with on-disk pack content"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            )}
            {canDelete("app") && (
              <button
                onClick={() => setDeleteTarget(p)}
                className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        ),
      },
    ],
    [canCreate, canDelete, mode, tz, navigate],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset: resetColumns,
  } = useColumnConfig<Pack>("packs", columns);

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
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Packs</h1>
          <p className="text-sm text-zinc-500">
            Import, export, and manage monitoring configuration bundles.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleFileUpload}
          />
          {canCreate("app") && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setCreateOpen(true)}
              className="gap-1.5"
            >
              <Plus className="h-4 w-4" /> Create Pack
            </Button>
          )}
          {canCreate("app") && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => fileInputRef.current?.click()}
              className="gap-1.5"
            >
              <Upload className="h-4 w-4" /> Import
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Boxes className="h-4 w-4" />
            Packs
            <Badge variant="default" className="ml-2">
              {meta.total}
            </Badge>
            <div className="ml-auto">
              <DisplayMenu
                columns={columns}
                configMap={configMap}
                onToggleHidden={setHidden}
                onReset={resetColumns}
              />
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!packs || packs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Boxes className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No packs installed</p>
              <p className="mt-1 text-xs text-zinc-600">
                Import a pack JSON file to get started.
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
              <FlexTable<Pack>
                orderedVisibleColumns={orderedVisibleColumns}
                configMap={configMap}
                onOrderChange={setOrder}
                onWidthChange={setWidth}
                rows={packs}
                rowKey={(p) => p.id}
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filters={listState.filters}
                onFilterChange={(col, v) => listState.setFilter(col, v)}
                rowClassName={() => "cursor-pointer"}
                emptyState="No packs match your filters"
              />
            </div>
          )}
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

      {/* Delete Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Pack"
      >
        <p className="text-sm text-zinc-400">
          Delete pack{" "}
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.name}
          </span>
          ?
        </p>
        <p className="mt-1 text-xs text-zinc-500">
          Entities created by this pack will NOT be deleted.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deletePack.isPending}
          >
            {deletePack.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}{" "}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Reconcile Confirm Dialog */}
      <Dialog
        open={!!reconcileTarget}
        onClose={() => {
          setReconcileTarget(null);
          setReconcileError(null);
        }}
        title="Reconcile Pack"
      >
        <p className="text-sm text-zinc-400">
          Re-apply the on-disk canonical content of pack{" "}
          <span className="font-semibold text-zinc-200">
            {reconcileTarget?.name}
          </span>
          ?
        </p>
        <p className="mt-1 text-xs text-zinc-500">
          Only entities created by this pack are touched. Operator-authored
          alert definitions, renamed apps, and threshold overrides are
          preserved.
        </p>
        {reconcileError && (
          <p className="mt-2 rounded bg-red-500/10 p-2 text-xs text-red-400">
            {reconcileError}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="secondary"
            onClick={() => {
              setReconcileTarget(null);
              setReconcileError(null);
            }}
          >
            Cancel
          </Button>
          <Button onClick={handleReconcile} disabled={reconcilePack.isPending}>
            {reconcilePack.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}{" "}
            Reconcile
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Reconcile Result Dialog */}
      <Dialog
        open={!!reconcileResult}
        onClose={() => setReconcileResult(null)}
        title={
          reconcileResult
            ? `Reconcile: ${reconcileResult.pack.name}`
            : "Reconcile Complete"
        }
      >
        {reconcileResult && (
          <div className="space-y-3">
            <p className="text-sm text-zinc-400">
              Pack reconciled. Per-entity diff:
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Entity</TableHead>
                  <TableHead className="text-right">Created</TableHead>
                  <TableHead className="text-right">Updated</TableHead>
                  <TableHead
                    className="text-right"
                    title="Skipped because owned by the operator (not this pack)"
                  >
                    Skipped (user)
                  </TableHead>
                  <TableHead
                    className="text-right"
                    title="Already matched the pack — no change needed"
                  >
                    Unchanged
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(reconcileResult.diff)
                  .filter(
                    ([, bucket]) =>
                      bucket.created +
                        bucket.updated +
                        bucket.skipped_user_owned +
                        bucket.skipped_unchanged >
                      0,
                  )
                  .map(([section, bucket]) => (
                    <TableRow key={section}>
                      <TableCell className="font-medium text-zinc-200">
                        {SECTION_LABELS[section] ?? section}
                      </TableCell>
                      <TableCell className="text-right text-emerald-400">
                        {bucket.created || ""}
                      </TableCell>
                      <TableCell className="text-right text-sky-400">
                        {bucket.updated || ""}
                      </TableCell>
                      <TableCell className="text-right text-zinc-500">
                        {bucket.skipped_user_owned || ""}
                      </TableCell>
                      <TableCell className="text-right text-zinc-500">
                        {bucket.skipped_unchanged || ""}
                      </TableCell>
                    </TableRow>
                  ))}
                {Object.values(reconcileResult.diff).every(
                  (b) =>
                    b.created +
                      b.updated +
                      b.skipped_user_owned +
                      b.skipped_unchanged ===
                    0,
                ) && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="text-center text-zinc-500"
                    >
                      No entities touched — already in sync.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
        <DialogFooter>
          <Button onClick={() => setReconcileResult(null)}>Close</Button>
        </DialogFooter>
      </Dialog>

      {/* Import Dialog */}
      <Dialog
        open={importOpen}
        onClose={closeImport}
        size="full"
        title={
          importResult
            ? "Import Complete"
            : importPreview
              ? `Import: ${importPreview.name}`
              : "Import Pack"
        }
      >
        {importError && !importPreview && (
          <div>
            <p className="text-sm text-red-400">{importError}</p>
            <DialogFooter>
              <Button variant="secondary" onClick={closeImport}>
                Close
              </Button>
            </DialogFooter>
          </div>
        )}

        {importResult && (
          <div>
            <p className="text-sm text-zinc-300">
              Created{" "}
              <span className="font-semibold text-green-400">
                {importResult.created}
              </span>
              , updated{" "}
              <span className="font-semibold text-amber-400">
                {importResult.updated}
              </span>
              , skipped{" "}
              <span className="font-semibold text-zinc-400">
                {importResult.skipped}
              </span>
              .
            </p>
            <DialogFooter>
              <Button onClick={closeImport}>Done</Button>
            </DialogFooter>
          </div>
        )}

        {importPreview && !importResult && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-zinc-400">
              <Badge variant="info">{importPreview.pack_uid}</Badge>
              <Badge variant="default">v{importPreview.version}</Badge>
              {importPreview.is_upgrade && (
                <Badge variant="default" className="bg-amber-600">
                  Upgrade from v{importPreview.current_version}
                </Badge>
              )}
            </div>

            <div className="max-h-80 overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Entity</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {importPreview.entities.map((entity) => {
                    const key = `${entity.section}:${entity.name}`;
                    const versionLabel =
                      entity.current_version && entity.incoming_version
                        ? `v${entity.current_version} → v${entity.incoming_version}`
                        : null;
                    return (
                      <TableRow key={key}>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-zinc-100">
                              {entity.name}
                            </span>
                            {versionLabel && (
                              <span className="text-[10px] text-zinc-500 font-mono">
                                {versionLabel}
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-zinc-400">
                          {SECTION_LABELS[entity.section] ?? entity.section}
                        </TableCell>
                        <TableCell>
                          {entity.status === "new" && (
                            <Badge className="bg-green-600">New</Badge>
                          )}
                          {entity.status === "conflict" && (
                            <Badge className="bg-amber-600">Conflict</Badge>
                          )}
                          {entity.status === "upgrade" &&
                            entity.has_changes && (
                              <Badge className="bg-blue-600">Upgrade</Badge>
                            )}
                          {entity.status === "upgrade" &&
                            !entity.has_changes && (
                              <Badge variant="info">Unchanged</Badge>
                            )}
                          {entity.status === "unchanged" && (
                            <Badge variant="info">Unchanged</Badge>
                          )}
                          {entity.status === "info" && (
                            <Badge className="bg-blue-600">Included</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          {entity.status === "conflict" ||
                          entity.status === "upgrade" ? (
                            <select
                              className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-200"
                              value={
                                resolutions[key] ??
                                (entity.status === "upgrade"
                                  ? "overwrite"
                                  : "skip")
                              }
                              onChange={(e) =>
                                setResolutions((prev) => ({
                                  ...prev,
                                  [key]: e.target.value,
                                }))
                              }
                            >
                              <option value="skip">Skip</option>
                              <option value="overwrite">Overwrite</option>
                              <option value="rename">Rename</option>
                            </select>
                          ) : entity.status === "new" ? (
                            <span className="text-xs text-green-400">
                              Will create
                            </span>
                          ) : entity.status === "info" ? (
                            <span className="text-xs text-blue-400">
                              Included with app
                            </span>
                          ) : entity.status === "unchanged" ? (
                            <span className="text-xs text-zinc-500">
                              No changes
                            </span>
                          ) : (
                            <span className="text-xs text-zinc-500">
                              Will skip
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            {importError && (
              <p className="text-sm text-red-400">{importError}</p>
            )}

            <DialogFooter>
              <Button variant="secondary" onClick={closeImport}>
                Cancel
              </Button>
              <Button onClick={handleImport} disabled={importPack.isPending}>
                {importPack.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}{" "}
                Import
              </Button>
            </DialogFooter>
          </div>
        )}

        {previewImport.isPending && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            <span className="ml-2 text-sm text-zinc-400">
              Analyzing pack...
            </span>
          </div>
        )}
      </Dialog>

      {/* Create Pack Dialog */}
      <CreatePackDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
    </div>
  );
}
