import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateShortName } from "@/lib/validation.ts";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Cpu,
  Database,
  FileText,
  Globe,
  HardDrive,
  Loader2,
  Lock,
  Package,
  Pencil,
  Plus,
  Printer,
  Search,
  Server,
  Settings2,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { Upload } from "lucide-react";
import { DeviceIcon, categoryIconUrl } from "@/components/DeviceIcon.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import {
  useCreateDeviceCategory,
  useUpdateDeviceCategory,
  useDeleteDeviceCategory,
  useUploadDeviceCategoryIcon,
  useDeleteDeviceCategoryIcon,
  useDeviceCategoryList,
  useDeviceCategoryCounts,
  useCategoryTemplateBindings,
  useBindCategoryTemplate,
  useUnbindCategoryTemplate,
  useTemplates,
} from "@/api/hooks.ts";
import type { DeviceCategory, TemplateBinding } from "@/types/api.ts";
import { cn } from "@/lib/utils.ts";

// Built-in (seeded) categories that shouldn't be deleted
const BUILTIN_CATEGORIES = new Set([
  "host", "network", "api", "database", "service",
  "container", "virtual-machine", "storage", "printer", "iot",
]);

const CATEGORIES = [
  "network", "server", "storage", "printer", "iot", "service", "database", "other",
] as const;

const CATEGORY_META: Record<string, { icon: typeof Server; label: string; accent: string; accentBg: string }> = {
  network:  { icon: Globe,     label: "Network",  accent: "text-sky-400",    accentBg: "bg-sky-400/10" },
  server:   { icon: Server,    label: "Server",   accent: "text-zinc-300",   accentBg: "bg-zinc-300/10" },
  storage:  { icon: HardDrive, label: "Storage",  accent: "text-amber-400",  accentBg: "bg-amber-400/10" },
  printer:  { icon: Printer,   label: "Printer",  accent: "text-zinc-400",   accentBg: "bg-zinc-400/10" },
  iot:      { icon: Cpu,       label: "IoT",      accent: "text-teal-400",   accentBg: "bg-teal-400/10" },
  service:  { icon: Wrench,    label: "Service",  accent: "text-violet-400", accentBg: "bg-violet-400/10" },
  database: { icon: Database,  label: "Database",  accent: "text-blue-400",   accentBg: "bg-blue-400/10" },
  other:    { icon: Settings2, label: "Other",    accent: "text-zinc-500",   accentBg: "bg-zinc-500/10" },
};

const ICON_OPTIONS = [
  { value: "", label: "— Default —" },
  { value: "server", label: "Server" },
  { value: "router", label: "Router" },
  { value: "switch", label: "Switch" },
  { value: "firewall", label: "Firewall" },
  { value: "printer", label: "Printer" },
  { value: "cloud", label: "Cloud" },
  { value: "database", label: "Database" },
  { value: "container", label: "Container" },
  { value: "cpu", label: "CPU / IoT" },
  { value: "globe", label: "Globe / Service" },
  { value: "hard-drive", label: "Storage" },
  { value: "monitor", label: "Monitor" },
] as const;

const PAGE_SIZE = 60;

export function DeviceCategoriesPage() {
  const createType = useCreateDeviceCategory();
  const updateType = useUpdateDeviceCategory();
  const deleteType = useDeleteDeviceCategory();
  const uploadIcon = useUploadDeviceCategoryIcon();
  const deleteIcon = useDeleteDeviceCategoryIcon();

  // Search + category filter
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);

  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Category counts (respects search filter)
  const { data: catData } = useDeviceCategoryCounts(debouncedSearch || undefined);

  // Paginated type list
  const listParams = useMemo(() => ({
    limit: PAGE_SIZE,
    offset: 0,
    sort_by: "name" as const,
    sort_dir: "asc" as const,
    ...(debouncedSearch ? { search: debouncedSearch } : {}),
    ...(activeCategory ? { category: activeCategory } : {}),
  }), [debouncedSearch, activeCategory]);

  const { data: listData, isLoading, isFetching } = useDeviceCategoryList(listParams);

  const meta = listData?.meta;
  const total = meta?.total ?? 0;

  // Infinite scroll: accumulate pages
  const [pages, setPages] = useState<DeviceCategory[][]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Reset accumulated pages when filters change
  useEffect(() => {
    setPages([]);
  }, [debouncedSearch, activeCategory]);

  // Store first page
  useEffect(() => {
    if (listData?.data && listData.meta.offset === 0) {
      setPages([listData.data]);
    }
  }, [listData]);

  const allTypes = useMemo(() => pages.flat(), [pages]);
  const displayHasMore = total > allTypes.length;

  const loadMore = useCallback(async () => {
    if (loadingMore || !displayHasMore) return;
    setLoadingMore(true);
    try {
      const nextOffset = allTypes.length;
      const qs = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(nextOffset),
        sort_by: "name",
        sort_dir: "asc",
      });
      if (debouncedSearch) qs.set("search", debouncedSearch);
      if (activeCategory) qs.set("category", activeCategory);

      const res = await fetch(`/v1/device-categories?${qs}`, { credentials: "include" });
      const json = await res.json();
      if (json.data) {
        setPages((prev) => [...prev, json.data]);
      }
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore, displayHasMore, allTypes.length, debouncedSearch, activeCategory]);

  // IntersectionObserver for infinite scroll
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMore(); },
      { rootMargin: "200px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  // CRUD dialogs state
  const [addOpen, setAddOpen] = useState(false);
  const nameField = useField("", validateShortName);
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("other");
  const [icon, setIcon] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<DeviceCategory | null>(null);
  const editNameField = useField("", validateShortName);
  const [editDescription, setEditDescription] = useState("");
  const [editCategory, setEditCategory] = useState("other");
  const [editIcon, setEditIcon] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  // Expanded row for template bindings
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!validateAll(nameField)) return;
    try {
      await createType.mutateAsync({
        name: nameField.value.trim().toLowerCase().replace(/\s+/g, "-"),
        description: description.trim() || undefined,
        category,
        icon: icon || undefined,
      });
      nameField.reset();
      setDescription("");
      setCategory("other");
      setIcon("");
      setAddOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create device type");
    }
  }

  function openEdit(dt: DeviceCategory) {
    setEditTarget(dt);
    editNameField.reset(dt.name);
    setEditDescription(dt.description ?? "");
    setEditCategory(dt.category || "other");
    setEditIcon(dt.icon ?? "");
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    const isBuiltin = BUILTIN_CATEGORIES.has(editTarget.name);
    try {
      await updateType.mutateAsync({
        id: editTarget.id,
        data: {
          ...(isBuiltin ? {} : { name: editNameField.value.trim().toLowerCase().replace(/\s+/g, "-") }),
          description: editDescription.trim() || undefined,
          category: editCategory,
          icon: editIcon || undefined,
        },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update device type");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteType.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      // Error handled silently — type may be in use
    }
  }

  if (isLoading && pages.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Search bar + add button */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <Input
            placeholder="Search categories..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 pr-7"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-zinc-500 hover:text-zinc-300 cursor-pointer"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
        <span className="text-xs text-zinc-500 tabular-nums whitespace-nowrap">
          {total} categor{total !== 1 ? "ies" : "y"}
        </span>
        {isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-600" />}
        <div className="ml-auto">
          <Button size="sm" onClick={() => setAddOpen(true)} className="gap-1.5">
            <Plus className="h-4 w-4" />
            Add Category
          </Button>
        </div>
      </div>

      {/* Category filter pills */}
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={() => setActiveCategory(null)}
          className={cn(
            "rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer",
            activeCategory === null
              ? "bg-brand-600/20 text-brand-400 ring-1 ring-brand-500/30"
              : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300",
          )}
        >
          All
          {catData && (
            <span className="ml-1 tabular-nums">{catData.total}</span>
          )}
        </button>
        {CATEGORIES.map((cat) => {
          const meta = CATEGORY_META[cat];
          const Icon = meta.icon;
          const count = catData?.categories[cat] ?? 0;
          if (!count && !activeCategory) return null;
          return (
            <button
              key={cat}
              type="button"
              onClick={() => setActiveCategory(activeCategory === cat ? null : cat)}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer",
                activeCategory === cat
                  ? "bg-brand-600/20 text-brand-400 ring-1 ring-brand-500/30"
                  : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300",
                count === 0 && "opacity-40",
              )}
            >
              <Icon className="h-3 w-3" />
              {meta.label}
              <span className="tabular-nums">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Categories list view */}
      {allTypes.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-zinc-800 py-16 text-zinc-500">
          <Server className="mb-2 h-8 w-8 text-zinc-600" />
          <p className="text-sm">
            {debouncedSearch || activeCategory
              ? "No categories match your filters"
              : "No device categories defined"}
          </p>
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Description</TableHead>
              <TableHead className="w-20"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {allTypes.map((dt) => {
              const isBuiltin = BUILTIN_CATEGORIES.has(dt.name);
              const isPackManaged = !!dt.pack_id;
              const catMeta = CATEGORY_META[dt.category] ?? CATEGORY_META.other;
              const CatIcon = catMeta.icon;
              const isExpanded = expandedRow === dt.id;

              return (
                <>
                  <TableRow
                    key={dt.id}
                    className="cursor-pointer hover:bg-zinc-800/50"
                    onClick={() => setExpandedRow(isExpanded ? null : dt.id)}
                  >
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <ChevronDown className={cn("h-3.5 w-3.5 text-zinc-600 transition-transform", !isExpanded && "-rotate-90")} />
                        <DeviceIcon
                          icon={dt.icon}
                          customIconUrl={dt.has_custom_icon ? categoryIconUrl(dt.id) : null}
                          className="h-4 w-4 text-zinc-400"
                        />
                        <span className="font-mono text-sm font-medium text-zinc-200">{dt.name}</span>
                        {isBuiltin && <Lock className="h-3 w-3 text-zinc-600" />}
                        {isPackManaged && <Package className="h-3 w-3 text-violet-500/70" />}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="flex items-center gap-1.5">
                        <CatIcon className={cn("h-3.5 w-3.5", catMeta.accent)} />
                        <span className="text-sm text-zinc-400">{catMeta.label}</span>
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-zinc-500 truncate max-w-xs">
                      {dt.description || "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => openEdit(dt)}
                          className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        {!isBuiltin && !isPackManaged && (
                          <button
                            onClick={() => setDeleteTarget({ id: dt.id, name: dt.name })}
                            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                  {isExpanded && (
                    <TableRow key={`${dt.id}-templates`}>
                      <TableCell colSpan={4} className="bg-zinc-900/50 px-6 py-3">
                        <CategoryTemplateBindingsPanel categoryId={dt.id} />
                      </TableCell>
                    </TableRow>
                  )}
                </>
              );
            })}
          </TableBody>
        </Table>
      )}

      {/* Infinite scroll sentinel */}
      {displayHasMore && (
        <div ref={sentinelRef} className="flex items-center justify-center py-4">
          {loadingMore && <Loader2 className="h-5 w-5 animate-spin text-zinc-600" />}
        </div>
      )}

      {/* Add Category Dialog */}
      <Dialog open={addOpen} onClose={() => { setAddOpen(false); setFormError(null); }} title="Add Device Category">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="dt-name">Name</Label>
            <Input
              id="dt-name"
              placeholder="e.g. firewall, load-balancer"
              value={nameField.value}
              onChange={nameField.onChange}
              onBlur={nameField.onBlur}
              autoFocus
            />
            {nameField.error && <p className="text-xs text-red-400 mt-0.5">{nameField.error}</p>}
            <p className="text-xs text-zinc-500">
              Lowercase, hyphens allowed. Will be auto-formatted.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-category">Category</Label>
            <Select id="dt-category" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-icon">Icon</Label>
            <Select id="dt-icon" value={icon} onChange={(e) => setIcon(e.target.value)}>
              {ICON_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-description">
              Description <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="dt-description"
              placeholder="Short description of this device category"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          {formError && <p className="text-sm text-red-400">{formError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => { setAddOpen(false); setFormError(null); }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createType.isPending}>
              {createType.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Add Category
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Category Dialog */}
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title="Edit Device Category">
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="dt-edit-name">Name</Label>
            <Input
              id="dt-edit-name"
              value={editNameField.value}
              onChange={editNameField.onChange}
              onBlur={editNameField.onBlur}
              disabled={editTarget ? BUILTIN_CATEGORIES.has(editTarget.name) : false}
              autoFocus
            />
            {editTarget && BUILTIN_CATEGORIES.has(editTarget.name) && (
              <p className="text-xs text-zinc-500">Built-in category names cannot be changed.</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-edit-category">Category</Label>
            <Select id="dt-edit-category" value={editCategory} onChange={(e) => setEditCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-edit-icon">Icon</Label>
            <Select id="dt-edit-icon" value={editIcon} onChange={(e) => setEditIcon(e.target.value)}>
              {ICON_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </Select>
          </div>
          {/* Custom icon upload */}
          <div className="space-y-1.5">
            <Label>Custom Icon <span className="font-normal text-zinc-500">(optional, overrides built-in)</span></Label>
            {editTarget?.has_custom_icon ? (
              <div className="flex items-center gap-3">
                <img
                  src={categoryIconUrl(editTarget.id)}
                  alt=""
                  className="h-8 w-8 rounded border border-zinc-700 bg-zinc-800 object-contain p-0.5"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-red-400 hover:text-red-300"
                  onClick={async () => {
                    if (editTarget) {
                      await deleteIcon.mutateAsync(editTarget.id);
                      editTarget.has_custom_icon = false;
                    }
                  }}
                  disabled={deleteIcon.isPending}
                >
                  <X className="h-3.5 w-3.5 mr-1" />
                  Remove
                </Button>
              </div>
            ) : (
              <label className="flex items-center gap-2 cursor-pointer rounded-md border border-dashed border-zinc-700 px-3 py-2 text-sm text-zinc-500 hover:border-zinc-600 hover:text-zinc-400 transition-colors">
                <Upload className="h-4 w-4" />
                Upload image (PNG, JPEG, SVG, WebP &mdash; max 256 KB)
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/svg+xml,image/webp"
                  className="hidden"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (file && editTarget) {
                      await uploadIcon.mutateAsync({ id: editTarget.id, file });
                      editTarget.has_custom_icon = true;
                    }
                    e.target.value = "";
                  }}
                />
              </label>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dt-edit-description">Description</Label>
            <Input
              id="dt-edit-description"
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              placeholder="Short description"
            />
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditTarget(null)}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateType.isPending}>
              {updateType.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Confirm Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Device Category"
      >
        <p className="text-sm text-zinc-400">
          Are you sure you want to delete the device category{" "}
          <span className="font-mono text-zinc-200">{deleteTarget?.name}</span>?
          Devices already using this category will retain the value, but it will
          no longer appear in the category selector.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteType.isPending}
          >
            {deleteType.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}


/* ── Category template bindings panel (shown in expanded row) ── */

function CategoryTemplateBindingsPanel({ categoryId }: { categoryId: string }) {
  const { data: bindingsData, refetch } = useCategoryTemplateBindings(categoryId);
  const bindTemplate = useBindCategoryTemplate();
  const unbindTemplate = useUnbindCategoryTemplate();
  const { data: templatesData } = useTemplates({ limit: 200 });

  const bindings: TemplateBinding[] = bindingsData?.data ?? [];
  const allTemplates = templatesData?.data ?? [];
  const boundIds = new Set(bindings.map((b) => b.template_id));

  const [addTemplateId, setAddTemplateId] = useState("");

  async function handleSwap(idx: number, dir: -1 | 1) {
    const target = idx + dir;
    if (target < 0 || target >= bindings.length) return;
    const a = bindings[idx];
    const b = bindings[target];
    // Swap steps by re-binding with swapped step values
    await Promise.all([
      bindTemplate.mutateAsync({ device_category_id: categoryId, template_id: a.template_id, step: b.step }),
      bindTemplate.mutateAsync({ device_category_id: categoryId, template_id: b.template_id, step: a.step }),
    ]);
    refetch();
  }

  async function handleAdd() {
    if (!addTemplateId) return;
    const nextStep = bindings.length > 0 ? Math.max(...bindings.map((b) => b.step)) + 1 : 1;
    await bindTemplate.mutateAsync({
      device_category_id: categoryId,
      template_id: addTemplateId,
      step: nextStep,
    });
    setAddTemplateId("");
    refetch();
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <FileText className="h-3.5 w-3.5 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-400">Linked Templates</span>
      </div>

      <p className="text-xs text-zinc-500">
        Templates are applied in step order (1 → 99). Device type templates (step 100 → 199) are applied after and override on app name overlap.
      </p>

      {bindings.length > 0 ? (
        <div className="space-y-1">
          {bindings.map((b, idx) => (
            <div key={b.id} className="flex items-center gap-2 rounded border border-zinc-800 bg-zinc-800/40 px-2.5 py-1.5 text-sm">
              <span className="w-8 text-center text-xs text-zinc-500 tabular-nums font-mono">{b.step}</span>
              <span className="flex-1 truncate text-zinc-200">{b.template_name}</span>
              <div className="flex items-center gap-0.5">
                <button
                  type="button"
                  disabled={idx === 0}
                  onClick={() => handleSwap(idx, -1)}
                  className="rounded p-1 text-zinc-600 hover:text-zinc-300 disabled:opacity-20 disabled:cursor-default cursor-pointer"
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  disabled={idx === bindings.length - 1}
                  onClick={() => handleSwap(idx, 1)}
                  className="rounded p-1 text-zinc-600 hover:text-zinc-300 disabled:opacity-20 disabled:cursor-default cursor-pointer"
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                </button>
              </div>
              <button
                type="button"
                onClick={async () => {
                  await unbindTemplate.mutateAsync(b.id);
                  refetch();
                }}
                className="rounded p-0.5 text-zinc-600 hover:text-red-400 cursor-pointer"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-zinc-500 italic">No templates linked.</p>
      )}

      {/* Add template */}
      <div className="flex items-end gap-2">
        <div className="flex-1 space-y-1">
          <Label className="text-xs text-zinc-500">Add template</Label>
          <Select value={addTemplateId} onChange={(e) => setAddTemplateId(e.target.value)}>
            <option value="">Select template…</option>
            {allTemplates
              .filter((t) => !boundIds.has(t.id))
              .map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
          </Select>
        </div>
        <Button
          type="button"
          size="sm"
          disabled={!addTemplateId || bindTemplate.isPending}
          onClick={handleAdd}
        >
          {bindTemplate.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
        </Button>
      </div>
    </div>
  );
}
