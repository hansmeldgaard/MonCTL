import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { formatTime } from "@/lib/utils.ts";
import {
  Building2,
  ChevronLeft,
  ChevronRight,
  FileText,
  FolderInput,
  Loader2,
  Monitor,
  Plus,
  Power,
  PowerOff,
  Tag,
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
import { Select } from "@/components/ui/select.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";
import type { Device } from "@/types/api.ts";
import {
  useDevices,
  useLatestResults,
  useBulkDeleteDevices,
  useBulkPatchDevices,
  useCollectorGroups,
  useTenants,
  useLabelKeys,
  useLabelValues,
  useDeviceCategories,
  useAutoApplyTemplates,
} from "@/api/hooks.ts";
import { ListChecks } from "lucide-react";
import type { DeviceBulkPatchRequest } from "@/types/api.ts";
import {
  useTablePreferences,
  PAGE_SIZE_OPTIONS,
} from "@/hooks/useTablePreferences.ts";
import { AddDeviceDialog } from "@/components/AddDeviceDialog.tsx";
import { BulkImportDevicesDialog } from "@/components/BulkImportDevicesDialog.tsx";
import { ApplyTemplateDialog } from "@/components/ApplyTemplateDialog.tsx";
import { DeviceIcon, categoryIconUrl } from "@/components/DeviceIcon.tsx";

export function DevicesBetaPage() {
  const { canCreate, canEdit, canDelete } = usePermissions();
  const tz = useTimezone();
  // ── URL query params (for deep linking from device types page) ──
  const [searchParams] = useSearchParams();

  // ── Table preferences ──────────────────────────────────
  const { pageSize, scrollMode, updatePreferences } = useTablePreferences();

  // ── Pagination ──────────────────────────────────────────
  const [page, setPage] = useState(0);

  // ── Sorting ─────────────────────────────────────────────
  const [sortBy, setSortBy] = useState("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  // ── Per-column filters (immediate) ──────────────────────
  const [filterName, setFilterName] = useState("");
  const [filterAddress, setFilterAddress] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterDeviceType, setFilterDeviceType] = useState(
    searchParams.get("device_type_name") ?? "",
  );
  const [filterTenant, setFilterTenant] = useState("");
  const [filterGroup, setFilterGroup] = useState("");
  const [filterLabelKey, setFilterLabelKey] = useState("");
  const [filterLabelValue, setFilterLabelValue] = useState("");
  const [labelFilterOpen, setLabelFilterOpen] = useState(false);
  const labelFilterRef = useRef<HTMLDivElement>(null);
  const [labelPopoverDeviceId, setLabelPopoverDeviceId] = useState<
    string | null
  >(null);
  const labelPopoverRef = useRef<HTMLDivElement>(null);

  // ── Debounced filter values ─────────────────────────────
  const [debouncedFilters, setDebouncedFilters] = useState({
    name: "",
    address: "",
    device_category: "",
    device_type_name: "",
    tenant_name: "",
    collector_group_name: "",
    label_key: "",
    label_value: "",
  });

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedFilters({
        name: filterName,
        address: filterAddress,
        device_category: filterType,
        device_type_name: filterDeviceType,
        tenant_name: filterTenant,
        collector_group_name: filterGroup,
        label_key: filterLabelKey,
        label_value: filterLabelValue,
      });
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [
    filterName,
    filterAddress,
    filterType,
    filterDeviceType,
    filterTenant,
    filterGroup,
    filterLabelKey,
    filterLabelValue,
  ]);

  // ── Compact mode (server-synced via ui_preferences.display) ───────
  const { compact } = useDisplayPreferences();

  // ── Selection ───────────────────────────────────────────
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // ── Bulk delete ─────────────────────────────────────────
  const bulkDelete = useBulkDeleteDevices();
  const bulkPatch = useBulkPatchDevices();
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [applyTemplateOpen, setApplyTemplateOpen] = useState(false);
  const [showMoveGroupDialog, setShowMoveGroupDialog] = useState(false);
  const [showMoveTenantDialog, setShowMoveTenantDialog] = useState(false);
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [selectedTenantId, setSelectedTenantId] = useState("");
  const autoApplyTemplates = useAutoApplyTemplates();

  // ── Add / Import dialogs ────────────────────────────────
  const [addOpen, setAddOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  // ── Infinite scroll state ───────────────────────────────
  const [infinitePages, setInfinitePages] = useState(1);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Reset infinite pages when filters/sort/scrollMode change
  useEffect(() => {
    setInfinitePages(1);
  }, [debouncedFilters, sortBy, sortDir, scrollMode]);

  // ── Fetch devices ───────────────────────────────────────
  const fetchLimit =
    scrollMode === "infinite" ? pageSize * infinitePages : pageSize;
  const fetchOffset = scrollMode === "infinite" ? 0 : page * pageSize;
  const {
    data: response,
    isLoading,
    isFetching,
  } = useDevices({
    limit: fetchLimit,
    offset: fetchOffset,
    sort_by: sortBy,
    sort_dir: sortDir,
    ...Object.fromEntries(
      Object.entries(debouncedFilters).filter(([, v]) => v !== ""),
    ),
  });

  const { data: deviceCategories } = useDeviceCategories();
  const categoryMap = new Map(
    (deviceCategories ?? []).map((dc) => [dc.name, dc]),
  );

  const devices = response?.data ?? [];
  const meta = (response as any)?.meta ?? {
    total: 0,
    count: 0,
    limit: pageSize,
    offset: 0,
  };
  const total: number = meta.total ?? devices.length;

  // ── Infinite scroll observer ───────────────────────────
  const hasMoreInfinite = scrollMode === "infinite" && devices.length < total;
  const loadMore = useCallback(() => {
    if (hasMoreInfinite && !isFetching) {
      setInfinitePages((p) => p + 1);
    }
  }, [hasMoreInfinite, isFetching]);

  useEffect(() => {
    if (scrollMode !== "infinite" || !sentinelRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMore();
      },
      { root: document.querySelector("main"), threshold: 0.1 },
    );
    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [scrollMode, loadMore]);

  // ── Latest results for status dots ──────────────────────
  const { data: latestResults } = useLatestResults();
  const { data: labelKeys } = useLabelKeys();
  const { data: collectorGroups } = useCollectorGroups();
  const { data: tenants } = useTenants();
  const labelColorMap = new Map(
    (labelKeys ?? []).map((lk) => [lk.key, lk.color]),
  );
  const { data: labelValues } = useLabelValues(filterLabelKey || null);

  // Close label filter popover on outside click
  useEffect(() => {
    if (!labelFilterOpen) return;
    function handleClick(e: MouseEvent) {
      if (
        labelFilterRef.current &&
        !labelFilterRef.current.contains(e.target as Node)
      ) {
        setLabelFilterOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [labelFilterOpen]);

  // Close label popover on outside click
  useEffect(() => {
    if (!labelPopoverDeviceId) return;
    function handleClick(e: MouseEvent) {
      if (
        labelPopoverRef.current &&
        !labelPopoverRef.current.contains(e.target as Node)
      ) {
        setLabelPopoverDeviceId(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [labelPopoverDeviceId]);

  // Build status maps
  const availReachability = new Map<string, boolean>();
  const anyReachability = new Map<string, boolean>();
  const deviceLatency = new Map<
    string,
    { appName: string; latencyMs: number | null; up: boolean }
  >();

  if (latestResults) {
    for (const r of latestResults) {
      // Any-result map (legacy fallback)
      const curAny = anyReachability.get(r.device_id);
      if (curAny === undefined) anyReachability.set(r.device_id, r.reachable);
      else if (!r.reachable) anyReachability.set(r.device_id, false);

      // Availability-role map
      if (r.role === "availability") {
        const curAvail = availReachability.get(r.device_id);
        if (curAvail === undefined)
          availReachability.set(r.device_id, r.reachable);
        else if (!r.reachable) availReachability.set(r.device_id, false);
      }

      // Latency: prefer availability-role; fall back to first result per device
      if (r.role === "availability" || !deviceLatency.has(r.device_id)) {
        const latency = r.rtt_ms ?? r.response_time_ms ?? null;
        deviceLatency.set(r.device_id, {
          appName: r.app_name ?? "check",
          latencyMs: latency && latency > 0 && r.reachable ? latency : null,
          up: r.reachable,
        });
      }
    }
  }

  // Final UP/DOWN: prefer availability-role; fall back to any-result
  const deviceReachability = new Map<string, boolean>();
  for (const [id] of anyReachability) {
    deviceReachability.set(
      id,
      availReachability.has(id)
        ? availReachability.get(id)!
        : anyReachability.get(id)!,
    );
  }

  // ── Sort handler ────────────────────────────────────────
  function handleSort(col: string) {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("asc");
    }
  }

  // ── Selection helpers ───────────────────────────────────
  function toggleSelectAll() {
    if (devices.length > 0 && devices.every((d) => selected.has(d.id))) {
      setSelected(new Set());
    } else {
      setSelected(new Set(devices.map((d) => d.id)));
    }
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // ── Bulk delete handler ─────────────────────────────────
  async function handleBulkDelete() {
    await bulkDelete.mutateAsync([...selected]);
    setSelected(new Set());
    setConfirmDeleteOpen(false);
  }

  // ── Bulk patch handler ──────────────────────────────────
  async function handleBulkPatch(patch: Partial<DeviceBulkPatchRequest>) {
    await bulkPatch.mutateAsync({
      device_ids: [...selected],
      ...patch,
    });
    setSelected(new Set());
  }

  // ── Pagination math ─────────────────────────────────────
  const startItem = total === 0 ? 0 : page * pageSize + 1;
  const endItem = Math.min(page * pageSize + devices.length, total);
  const hasNext = endItem < total;
  const hasPrev = page > 0;

  const hasActiveFilters =
    filterName !== "" ||
    filterAddress !== "" ||
    filterType !== "" ||
    filterTenant !== "" ||
    filterGroup !== "" ||
    filterLabelKey !== "";

  const allVisibleSelected =
    devices.length > 0 && devices.every((d) => selected.has(d.id));

  // ── Time display mode (absolute vs relative) ─────────────
  const { mode: timeMode } = useTimeDisplayMode();

  // ── FlexTable column definitions ─────────────────────────
  // Order here is the default order; user's stored ColumnConfig overrides
  // it in useColumnConfig.orderedVisibleColumns.
  const columns = useMemo<FlexColumnDef<Device>[]>(
    () => [
      {
        key: "__select",
        label: (
          <input
            type="checkbox"
            checked={allVisibleSelected}
            onChange={toggleSelectAll}
            className="h-4 w-4 rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500 cursor-pointer"
            aria-label="Select all"
          />
        ),
        pickerLabel: "Select",
        sortable: false,
        filterable: false,
        alwaysVisible: true,
        minWidth: 40,
        defaultWidth: 40,
        cell: (device) => (
          <input
            type="checkbox"
            checked={selected.has(device.id)}
            onChange={() => toggleSelect(device.id)}
            className="h-4 w-4 rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500 cursor-pointer"
            aria-label={`Select ${device.name}`}
          />
        ),
      },
      {
        key: "__status",
        label: "Status",
        pickerLabel: "Status",
        sortable: false,
        filterable: false,
        minWidth: 48,
        defaultWidth: 56,
        cell: (device) => {
          const isUp = deviceReachability.get(device.id);
          const latencyInfo = deviceLatency.get(device.id);
          return (
            <div className="relative group w-fit cursor-default">
              {!device.is_enabled ? (
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full bg-zinc-600"
                  title="Disabled"
                />
              ) : (
                <span
                  className={`inline-block h-2.5 w-2.5 rounded-full ${
                    isUp === true
                      ? "bg-emerald-500 animate-pulse-dot"
                      : isUp === false
                        ? "bg-red-500"
                        : "bg-zinc-600"
                  }`}
                />
              )}
              {latencyInfo && (
                <div className="absolute left-4 top-1/2 -translate-y-1/2 z-50 hidden group-hover:flex items-center gap-1.5 whitespace-nowrap rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-xs shadow-lg pointer-events-none">
                  <span className="text-zinc-500">{latencyInfo.appName}:</span>
                  {latencyInfo.latencyMs !== null ? (
                    <span className="font-mono text-zinc-200">
                      {Math.round(latencyInfo.latencyMs)}ms
                    </span>
                  ) : (
                    <span className="text-red-400">
                      {latencyInfo.up ? "N/A" : "unreachable"}
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        },
      },
      {
        key: "name",
        label: "Name",
        defaultWidth: 220,
        cell: (device) => (
          <Link
            to={`/devices/${device.id}`}
            className="font-medium text-zinc-100 hover:text-brand-400 transition-colors"
          >
            {device.name}
          </Link>
        ),
      },
      {
        key: "address",
        label: "Address",
        defaultWidth: 140,
        cellClassName: "font-mono text-xs text-zinc-400",
        cell: (device) => device.address,
      },
      {
        key: "device_category",
        label: "Category",
        defaultWidth: 160,
        cell: (device) => {
          const dc = categoryMap.get(device.device_category);
          return (
            <div className="flex items-center gap-1.5">
              <DeviceIcon
                icon={dc?.icon}
                customIconUrl={
                  dc?.has_custom_icon ? categoryIconUrl(dc.id) : null
                }
                className="h-4 w-4 text-zinc-400"
              />
              <span className="text-sm text-zinc-300">
                {device.device_category}
              </span>
            </div>
          );
        },
      },
      {
        key: "device_type_name",
        label: "Type",
        defaultWidth: 180,
        cellClassName: "text-zinc-400 text-sm",
        cell: (device) =>
          device.device_type_name || (
            <span className="text-zinc-600">&mdash;</span>
          ),
      },
      {
        key: "tenant_name",
        label: "Tenant",
        defaultWidth: 140,
        cellClassName: "text-zinc-400 text-sm",
        cell: (device) =>
          device.tenant_name ? (
            <Badge variant="default">{device.tenant_name}</Badge>
          ) : (
            <span className="text-zinc-600">&mdash;</span>
          ),
      },
      {
        key: "collector_group_name",
        label: "Collector Group",
        defaultWidth: 160,
        cell: (device) =>
          device.collector_group_name ? (
            <Badge variant="default">{device.collector_group_name}</Badge>
          ) : (
            <span className="text-zinc-600">&mdash;</span>
          ),
      },
      {
        key: "__labels",
        label: (
          <div className="relative" ref={labelFilterRef}>
            <button
              type="button"
              onClick={() => setLabelFilterOpen(!labelFilterOpen)}
              className={`inline-flex items-center gap-1 text-xs transition-colors cursor-pointer ${filterLabelKey ? "text-brand-400" : "text-zinc-400 hover:text-zinc-200"}`}
              title="Filter by label"
            >
              <Tag className="h-3 w-3" /> Labels
              {filterLabelKey && (
                <Badge variant="default" className="text-[9px] py-0 px-1">
                  {filterLabelKey}
                  {filterLabelValue ? `=${filterLabelValue}` : ""}
                </Badge>
              )}
            </button>
            {labelFilterOpen && (
              <div className="absolute right-0 top-6 z-20 w-52 rounded-md border border-zinc-700 bg-zinc-900 p-2.5 space-y-2 shadow-lg">
                <div>
                  <label className="text-[10px] text-zinc-500 block mb-0.5">
                    Label Key
                  </label>
                  <select
                    value={filterLabelKey}
                    onChange={(e) => {
                      setFilterLabelKey(e.target.value);
                      setFilterLabelValue("");
                    }}
                    className="w-full text-xs h-7 bg-zinc-800 border border-zinc-700 rounded px-2 text-zinc-300"
                  >
                    <option value="">All</option>
                    {(labelKeys ?? []).map((lk) => (
                      <option key={lk.key} value={lk.key}>
                        {lk.key}
                      </option>
                    ))}
                  </select>
                </div>
                {filterLabelKey && (
                  <div>
                    <label className="text-[10px] text-zinc-500 block mb-0.5">
                      Value
                    </label>
                    <select
                      value={filterLabelValue}
                      onChange={(e) => setFilterLabelValue(e.target.value)}
                      className="w-full text-xs h-7 bg-zinc-800 border border-zinc-700 rounded px-2 text-zinc-300"
                    >
                      <option value="">Any value</option>
                      {(labelValues ?? []).map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {filterLabelKey && (
                  <button
                    type="button"
                    onClick={() => {
                      setFilterLabelKey("");
                      setFilterLabelValue("");
                    }}
                    className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
                  >
                    Clear label filter
                  </button>
                )}
              </div>
            )}
          </div>
        ),
        pickerLabel: "Labels",
        sortable: false,
        filterable: false,
        defaultWidth: 100,
        cell: (device) => {
          const labelEntries = Object.entries(device.labels ?? {});
          if (labelEntries.length === 0) {
            return <span className="text-zinc-600">&mdash;</span>;
          }
          return (
            <div
              className="relative"
              ref={
                labelPopoverDeviceId === device.id ? labelPopoverRef : undefined
              }
            >
              <button
                type="button"
                className="flex items-center gap-1 cursor-pointer hover:opacity-80 transition-opacity"
                onClick={() =>
                  setLabelPopoverDeviceId(
                    labelPopoverDeviceId === device.id ? null : device.id,
                  )
                }
              >
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{
                    backgroundColor:
                      labelColorMap.get(labelEntries[0][0]) || "#71717a",
                  }}
                />
                {labelEntries.length > 1 && (
                  <span className="text-xs text-zinc-500">
                    +{labelEntries.length - 1}
                  </span>
                )}
              </button>
              {labelPopoverDeviceId === device.id && (
                <div className="absolute left-0 top-6 z-20 min-w-[180px] rounded-md border border-zinc-700 bg-zinc-900 p-2.5 shadow-lg space-y-1.5">
                  {labelEntries.map(([k, v]) => {
                    const lColor = labelColorMap.get(k) || "#71717a";
                    return (
                      <div
                        key={k}
                        className="flex items-center gap-2 text-xs whitespace-nowrap"
                      >
                        <span
                          className="inline-block h-2 w-2 rounded-full shrink-0"
                          style={{ backgroundColor: lColor }}
                        />
                        <span className="text-zinc-400">{k}:</span>
                        <span className="text-zinc-200">{v}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        },
      },
      {
        key: "created_at",
        label: "Created",
        filterable: false,
        defaultWidth: 120,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (device) => {
          if (!device.created_at) return "—";
          return (
            <span
              title={formatTime(
                device.created_at,
                timeMode === "relative" ? "absolute" : "relative",
                tz,
              )}
            >
              {formatTime(device.created_at, timeMode, tz)}
            </span>
          );
        },
      },
      {
        key: "updated_at",
        label: "Updated",
        filterable: false,
        defaultWidth: 120,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (device) => {
          if (!device.updated_at) return "—";
          return (
            <span
              title={formatTime(
                device.updated_at,
                timeMode === "relative" ? "absolute" : "relative",
                tz,
              )}
            >
              {formatTime(device.updated_at, timeMode, tz)}
            </span>
          );
        },
      },
    ],
    [
      allVisibleSelected,
      selected,
      deviceReachability,
      deviceLatency,
      categoryMap,
      labelFilterOpen,
      labelPopoverDeviceId,
      filterLabelKey,
      filterLabelValue,
      labelKeys,
      labelValues,
      labelColorMap,
      timeMode,
      tz,
    ],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset: resetColumns,
  } = useColumnConfig<Device>("devices", columns);

  // Synthesize the filters map + change handler expected by FlexTable.
  // Keeps the existing per-state setters so the debounce effect above
  // still fires correctly.
  const filtersMap: Record<string, string> = {
    name: filterName,
    address: filterAddress,
    device_category: filterType,
    device_type_name: filterDeviceType,
    tenant_name: filterTenant,
    collector_group_name: filterGroup,
  };

  const handleFilterChange = useCallback((col: string, value: string) => {
    switch (col) {
      case "name":
        setFilterName(value);
        break;
      case "address":
        setFilterAddress(value);
        break;
      case "device_category":
        setFilterType(value);
        break;
      case "device_type_name":
        setFilterDeviceType(value);
        break;
      case "tenant_name":
        setFilterTenant(value);
        break;
      case "collector_group_name":
        setFilterGroup(value);
        break;
    }
  }, []);

  // ── Loading state ───────────────────────────────────────
  // Early return AFTER all hooks so Rules of Hooks stays satisfied.
  if (isLoading && devices.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <span className="text-sm text-zinc-500 flex-1">
          {total} device{total !== 1 ? "s" : ""}
        </span>

        {/* Bulk actions */}
        {selected.size > 0 && (
          <div className="flex items-center gap-3 rounded-lg bg-zinc-800/50 border border-zinc-700 px-4 py-2">
            <span className="text-sm text-zinc-300">
              {selected.size} selected
            </span>
            {canEdit("device") && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleBulkPatch({ is_enabled: true })}
                  disabled={bulkPatch.isPending}
                  className="gap-1.5"
                >
                  <Power className="h-3.5 w-3.5" /> Enable
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleBulkPatch({ is_enabled: false })}
                  disabled={bulkPatch.isPending}
                  className="gap-1.5"
                >
                  <PowerOff className="h-3.5 w-3.5" /> Disable
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setSelectedGroupId("");
                    setShowMoveGroupDialog(true);
                  }}
                  disabled={bulkPatch.isPending}
                  className="gap-1.5"
                >
                  <FolderInput className="h-3.5 w-3.5" /> Move to Group
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setSelectedTenantId("");
                    setShowMoveTenantDialog(true);
                  }}
                  disabled={bulkPatch.isPending}
                  className="gap-1.5"
                >
                  <Building2 className="h-3.5 w-3.5" /> Move to Tenant
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    const ids = Array.from(selected);
                    await autoApplyTemplates.mutateAsync(ids);
                    setSelected(new Set());
                  }}
                  disabled={autoApplyTemplates.isPending}
                  className="gap-1.5"
                >
                  {autoApplyTemplates.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <ListChecks className="h-3.5 w-3.5" />
                  )}{" "}
                  Auto-Assign
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setApplyTemplateOpen(true)}
                  className="gap-1.5"
                >
                  <FileText className="h-3.5 w-3.5" /> Apply Template
                </Button>
              </>
            )}
            {canDelete("device") && (
              <Button
                size="sm"
                variant="destructive"
                onClick={() => setConfirmDeleteOpen(true)}
                className="gap-1.5"
              >
                <Trash2 className="h-3.5 w-3.5" /> Delete Selected
              </Button>
            )}
          </div>
        )}

        {/* View settings: compact density, time mode, column visibility */}
        <DisplayMenu
          columns={columns}
          configMap={configMap}
          onToggleHidden={setHidden}
          onReset={resetColumns}
        />

        {canCreate("device") && (
          <>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setImportOpen(true)}
              className="gap-1.5"
            >
              <FolderInput className="h-4 w-4" />
              Import
            </Button>
            <Button
              size="sm"
              onClick={() => setAddOpen(true)}
              className="gap-1.5"
            >
              <Plus className="h-4 w-4" />
              Add Device
            </Button>
          </>
        )}
      </div>

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Monitor className="h-4 w-4" />
            Devices
          </CardTitle>
        </CardHeader>
        <CardContent>
          {devices.length === 0 && !isLoading && !hasActiveFilters ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Monitor className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No devices found</p>
              {canCreate("device") && (
                <Button
                  size="sm"
                  variant="secondary"
                  className="mt-4"
                  onClick={() => setAddOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  Add your first device
                </Button>
              )}
            </div>
          ) : (
            <>
              <div
                className={
                  compact
                    ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
                    : ""
                }
              >
                <FlexTable<Device>
                  orderedVisibleColumns={orderedVisibleColumns}
                  configMap={configMap}
                  onOrderChange={setOrder}
                  onWidthChange={setWidth}
                  rows={devices}
                  rowKey={(d) => d.id}
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={handleSort}
                  filters={filtersMap}
                  onFilterChange={handleFilterChange}
                  rowClassName={(d) =>
                    !d.is_enabled ? "opacity-50" : undefined
                  }
                  emptyState={
                    hasActiveFilters
                      ? "No devices match your filters"
                      : "No devices"
                  }
                />
              </div>

              {/* Infinite scroll sentinel */}
              {scrollMode === "infinite" && (
                <div ref={sentinelRef} className="flex justify-center py-4">
                  {isFetching && (
                    <Loader2 className="h-5 w-5 animate-spin text-brand-500" />
                  )}
                  {!isFetching && hasMoreInfinite && (
                    <span className="text-xs text-zinc-600">
                      Scroll for more...
                    </span>
                  )}
                  {!hasMoreInfinite && devices.length > 0 && (
                    <span className="text-xs text-zinc-600">
                      Showing all {total} devices
                    </span>
                  )}
                </div>
              )}

              {/* Pagination */}
              <div className="flex items-center justify-between border-t border-zinc-800 pt-3 mt-3">
                <div className="flex items-center gap-2">
                  <Select
                    value={scrollMode}
                    onChange={(e) => {
                      updatePreferences({
                        table_scroll_mode: e.target.value as
                          | "paginated"
                          | "infinite",
                      });
                      setPage(0);
                    }}
                    className="w-36 text-xs h-7"
                  >
                    <option value="paginated">Paginated</option>
                    <option value="infinite">Infinite Scroll</option>
                  </Select>
                  <Select
                    value={String(pageSize)}
                    onChange={(e) => {
                      updatePreferences({
                        table_page_size: Number(e.target.value),
                      });
                      setPage(0);
                    }}
                    className="w-20 text-xs h-7"
                  >
                    {PAGE_SIZE_OPTIONS.map((s) => (
                      <option key={s} value={String(s)}>
                        {s}
                      </option>
                    ))}
                  </Select>
                  <span className="text-xs text-zinc-600">
                    {scrollMode === "infinite" ? "per batch" : "rows"}
                  </span>
                </div>
                <span className="text-sm text-zinc-500">
                  {scrollMode === "infinite" ? (
                    `Showing ${devices.length} of ${total}`
                  ) : (
                    <>
                      Showing {startItem}&ndash;{endItem} of {total}
                    </>
                  )}
                </span>
                {scrollMode === "paginated" ? (
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={!hasPrev}
                      onClick={() => setPage((p) => p - 1)}
                    >
                      <ChevronLeft className="h-4 w-4" /> Previous
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={!hasNext}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      Next <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                ) : (
                  <div />
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Add Device Dialog */}
      <AddDeviceDialog open={addOpen} onClose={() => setAddOpen(false)} />

      {/* Bulk Import Dialog */}
      <BulkImportDevicesDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
      />

      {/* Apply Template Dialog */}
      <ApplyTemplateDialog
        open={applyTemplateOpen}
        onClose={() => setApplyTemplateOpen(false)}
        deviceIds={[...selected]}
      />

      {/* Confirm Delete Dialog */}
      <Dialog
        open={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        title="Delete Devices"
      >
        <p className="text-sm text-zinc-400">
          Are you sure you want to delete{" "}
          <span className="font-semibold text-zinc-200">{selected.size}</span>{" "}
          device(s)? This action cannot be undone.
        </p>
        <DialogFooter>
          <Button
            variant="secondary"
            onClick={() => setConfirmDeleteOpen(false)}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleBulkDelete}
            disabled={bulkDelete.isPending}
            className="gap-1.5"
          >
            {bulkDelete.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Delete {selected.size} Devices
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Move to Collector Group Dialog */}
      <Dialog
        open={showMoveGroupDialog}
        onClose={() => setShowMoveGroupDialog(false)}
        title="Move to Collector Group"
      >
        <p className="text-sm text-zinc-400 mb-4">
          Select the target collector group for{" "}
          <span className="font-semibold text-zinc-200">{selected.size}</span>{" "}
          device(s). Existing assignments will be kept.
        </p>
        <Select
          value={selectedGroupId}
          onChange={(e) => setSelectedGroupId(e.target.value)}
        >
          <option value="">Select group...</option>
          {(collectorGroups ?? []).map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </Select>
        <DialogFooter>
          <Button
            variant="secondary"
            onClick={() => setShowMoveGroupDialog(false)}
          >
            Cancel
          </Button>
          <Button
            disabled={!selectedGroupId || bulkPatch.isPending}
            onClick={async () => {
              await handleBulkPatch({ collector_group_id: selectedGroupId });
              setShowMoveGroupDialog(false);
            }}
          >
            {bulkPatch.isPending ? "Moving..." : "Move"}
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Move to Tenant Dialog */}
      <Dialog
        open={showMoveTenantDialog}
        onClose={() => setShowMoveTenantDialog(false)}
        title="Move to Tenant"
      >
        <p className="text-sm text-zinc-400 mb-4">
          Select the target tenant for{" "}
          <span className="font-semibold text-zinc-200">{selected.size}</span>{" "}
          device(s). Existing assignments will be kept.
        </p>
        <Select
          value={selectedTenantId}
          onChange={(e) => setSelectedTenantId(e.target.value)}
        >
          <option value="">Select tenant...</option>
          {(tenants ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </Select>
        <DialogFooter>
          <Button
            variant="secondary"
            onClick={() => setShowMoveTenantDialog(false)}
          >
            Cancel
          </Button>
          <Button
            disabled={!selectedTenantId || bulkPatch.isPending}
            onClick={async () => {
              await handleBulkPatch({ tenant_id: selectedTenantId });
              setShowMoveTenantDialog(false);
            }}
          >
            {bulkPatch.isPending ? "Moving..." : "Move"}
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
