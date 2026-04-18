import { useMemo, useState } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName } from "@/lib/validation.ts";
import { FileText, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  useTemplates,
  useCreateTemplate,
  useUpdateTemplate,
  useDeleteTemplate,
} from "@/api/hooks.ts";
import type { Template, TemplateConfig } from "@/types/api.ts";
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
import { TemplateConfigEditor } from "@/components/TemplateConfigEditor.tsx";
import { usePermissions } from "@/hooks/usePermissions.ts";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";

export function TemplatesPage() {
  const { canCreate, canEdit, canDelete } = usePermissions();
  const tz = useTimezone();
  const { mode } = useTimeDisplayMode();
  const { compact } = useDisplayPreferences();
  const { pageSize, scrollMode } = useTablePreferences();
  const listState = useListState({
    columns: [
      { key: "name", label: "Name" },
      { key: "description", label: "Description", sortable: false },
    ],
    defaultPageSize: pageSize,
    scrollMode,
  });
  const {
    data: response,
    isLoading,
    isFetching,
  } = useTemplates(listState.params);
  const templates = response?.data ?? [];
  const meta = (response as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };
  const createTemplate = useCreateTemplate();
  const updateTemplate = useUpdateTemplate();
  const deleteTemplate = useDeleteTemplate();

  const [addOpen, setAddOpen] = useState(false);
  const addNameField = useField("", validateName);
  const [addDesc, setAddDesc] = useState("");
  const [addConfigObj, setAddConfigObj] = useState<TemplateConfig>({});
  const [addError, setAddError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<Template | null>(null);
  const editNameField = useField("", validateName);
  const [editDesc, setEditDesc] = useState("");
  const [editConfigObj, setEditConfigObj] = useState<TemplateConfig>({});
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<Template | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!validateAll(addNameField)) return;
    try {
      await createTemplate.mutateAsync({
        name: addNameField.value.trim(),
        description: addDesc.trim() || undefined,
        config: addConfigObj as Record<string, unknown>,
      });
      addNameField.reset();
      setAddDesc("");
      setAddConfigObj({});
      setAddOpen(false);
    } catch (err) {
      setAddError(
        err instanceof Error ? err.message : "Failed to create template",
      );
    }
  }

  function openEdit(t: Template) {
    setEditTarget(t);
    editNameField.reset(t.name);
    setEditDesc(t.description ?? "");
    setEditConfigObj(t.config || {});
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    if (!validateAll(editNameField)) return;
    try {
      await updateTemplate.mutateAsync({
        id: editTarget.id,
        data: {
          name: editNameField.value.trim(),
          description: editDesc.trim(),
          config: editConfigObj as Record<string, unknown>,
        },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(
        err instanceof Error ? err.message : "Failed to update template",
      );
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteTemplate.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      /* silent */
    }
  }

  function countItems(config: TemplateConfig): number {
    let count = 0;
    if (config.monitoring) {
      if (config.monitoring.availability) count++;
      if (config.monitoring.latency) count++;
      if (config.monitoring.interface) count++;
    }
    count += config.apps?.length ?? 0;
    return count;
  }

  const columns = useMemo<FlexColumnDef<Template>[]>(() => {
    const cols: FlexColumnDef<Template>[] = [
      {
        key: "name",
        label: "Name",
        defaultWidth: 220,
        cellClassName: "font-medium text-zinc-100",
        cell: (t) => t.name,
      },
      {
        key: "description",
        label: "Description",
        sortable: false,
        defaultWidth: 320,
        cellClassName: "text-zinc-400 max-w-[300px] truncate",
        cell: (t) => t.description ?? "\u2014",
      },
      {
        key: "__items",
        label: "Items",
        pickerLabel: "Items",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cell: (t) => (
          <Badge variant="default">{countItems(t.config || {})} items</Badge>
        ),
      },
      {
        key: "created_at",
        label: "Created",
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (t) => formatTime(t.created_at, mode, tz),
      },
    ];
    if (canEdit("template") || canDelete("template")) {
      cols.push({
        key: "__actions",
        label: "",
        pickerLabel: "Actions",
        sortable: false,
        filterable: false,
        defaultWidth: 90,
        cell: (t) => (
          <div className="flex items-center gap-1">
            {canEdit("template") && (
              <button
                onClick={() => openEdit(t)}
                className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                title="Edit"
              >
                <Pencil className="h-4 w-4" />
              </button>
            )}
            {canDelete("template") && (
              <button
                onClick={() => setDeleteTarget(t)}
                className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        ),
      });
    }
    return cols;
  }, [canEdit, canDelete, mode, tz]);

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset: resetColumns,
  } = useColumnConfig<Template>("templates", columns);

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
          <h1 className="text-lg font-semibold text-zinc-100">Templates</h1>
          <p className="text-sm text-zinc-500">
            Reusable monitoring configurations for bulk device setup.
          </p>
        </div>
        {canCreate("template") && (
          <Button
            size="sm"
            onClick={() => {
              addNameField.reset();
              setAddDesc("");
              setAddConfigObj({});
              setAddError(null);
              setAddOpen(true);
            }}
            className="gap-1.5"
          >
            <Plus className="h-4 w-4" /> New Template
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Templates
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
          {templates.length === 0 && !listState.hasActiveFilters ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <FileText className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No templates defined</p>
            </div>
          ) : (
            <div
              className={
                compact
                  ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
                  : ""
              }
            >
              <FlexTable<Template>
                orderedVisibleColumns={orderedVisibleColumns}
                configMap={configMap}
                onOrderChange={setOrder}
                onWidthChange={setWidth}
                rows={templates}
                rowKey={(t) => t.id}
                sortBy={listState.sortBy}
                sortDir={listState.sortDir}
                onSort={listState.handleSort}
                filters={listState.filters}
                onFilterChange={(col, v) => listState.setFilter(col, v)}
                emptyState="No templates match your filters"
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

      {/* Add Dialog */}
      <Dialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="New Template"
        size="lg"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tpl-name">Name</Label>
            <Input
              id="tpl-name"
              placeholder="e.g. Standard Server"
              value={addNameField.value}
              onChange={addNameField.onChange}
              onBlur={addNameField.onBlur}
              autoFocus
            />
            {addNameField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {addNameField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-desc">
              Description{" "}
              <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="tpl-desc"
              value={addDesc}
              onChange={(e) => setAddDesc(e.target.value)}
            />
          </div>
          <TemplateConfigEditor
            value={addConfigObj}
            onChange={setAddConfigObj}
          />
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createTemplate.isPending}>
              {createTemplate.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}{" "}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        title={`Edit: ${editTarget?.name ?? ""}`}
        size="lg"
      >
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tpl-edit-name">Name</Label>
            <Input
              id="tpl-edit-name"
              value={editNameField.value}
              onChange={editNameField.onChange}
              onBlur={editNameField.onBlur}
              autoFocus
            />
            {editNameField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {editNameField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-edit-desc">Description</Label>
            <Input
              id="tpl-edit-desc"
              value={editDesc}
              onChange={(e) => setEditDesc(e.target.value)}
            />
          </div>
          <TemplateConfigEditor
            value={editConfigObj}
            onChange={setEditConfigObj}
          />
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setEditTarget(null)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={updateTemplate.isPending}>
              {updateTemplate.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}{" "}
              Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Template"
      >
        <p className="text-sm text-zinc-400">
          Delete template{" "}
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.name}
          </span>
          ?
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteTemplate.isPending}
          >
            {deleteTemplate.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}{" "}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
