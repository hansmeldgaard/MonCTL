import { useState, useEffect, useRef, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Building2,
  ChevronLeft,
  ChevronRight,
  FileText,
  FolderInput,
  Loader2,
  Minus,
  Monitor,
  Plus,
  Power,
  PowerOff,
  Trash2,
} from "lucide-react";
import { X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
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
import { Select } from "@/components/ui/select.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { useDevices, useLatestResults, useBulkDeleteDevices, useBulkPatchDevices, useCollectorGroups, useTenants, useLabelKeys } from "@/api/hooks.ts";
import type { DeviceBulkPatchRequest } from "@/types/api.ts";
import { useTablePreferences, PAGE_SIZE_OPTIONS } from "@/hooks/useTablePreferences.ts";
import { AddDeviceDialog } from "@/components/AddDeviceDialog.tsx";
import { ApplyTemplateDialog } from "@/components/ApplyTemplateDialog.tsx";

export function DevicesPage() {
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
  const [filterDeviceType, setFilterDeviceType] = useState("");
  const [filterTenant, setFilterTenant] = useState("");
  const [filterGroup, setFilterGroup] = useState("");

  // ── Debounced filter values ─────────────────────────────
  const [debouncedFilters, setDebouncedFilters] = useState({
    name: "",
    address: "",
    device_category: "",
    device_type_name: "",
    tenant_name: "",
    collector_group_name: "",
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
      });
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [filterName, filterAddress, filterType, filterDeviceType, filterTenant, filterGroup]);

  // ── Compact mode ────────────────────────────────────────
  const [compact, setCompact] = useState(false);

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

  // ── Add dialog ──────────────────────────────────────────
  const [addOpen, setAddOpen] = useState(false);

  // ── Infinite scroll state ───────────────────────────────
  const [infinitePages, setInfinitePages] = useState(1);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Reset infinite pages when filters/sort/scrollMode change
  useEffect(() => {
    setInfinitePages(1);
  }, [debouncedFilters, sortBy, sortDir, scrollMode]);

  // ── Fetch devices ───────────────────────────────────────
  const fetchLimit = scrollMode === "infinite" ? pageSize * infinitePages : pageSize;
  const fetchOffset = scrollMode === "infinite" ? 0 : page * pageSize;
  const { data: response, isLoading, isFetching } = useDevices({
    limit: fetchLimit,
    offset: fetchOffset,
    sort_by: sortBy,
    sort_dir: sortDir,
    ...Object.fromEntries(
      Object.entries(debouncedFilters).filter(([, v]) => v !== ""),
    ),
  });

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
      (entries) => { if (entries[0].isIntersecting) loadMore(); },
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
  const labelColorMap = new Map((labelKeys ?? []).map((lk) => [lk.key, lk.color]));

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

  // ── Sort icon ───────────────────────────────────────────
  function SortIcon({ col }: { col: string }) {
    if (sortBy !== col)
      return <ArrowUpDown className="h-3 w-3 text-zinc-600" />;
    return sortDir === "asc" ? (
      <ArrowUp className="h-3 w-3 text-brand-400" />
    ) : (
      <ArrowDown className="h-3 w-3 text-brand-400" />
    );
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

  // ── Loading state ───────────────────────────────────────
  if (isLoading && devices.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  const hasActiveFilters =
    filterName !== "" ||
    filterAddress !== "" ||
    filterType !== "" ||
    filterTenant !== "" ||
    filterGroup !== "";

  const allVisibleSelected =
    devices.length > 0 && devices.every((d) => selected.has(d.id));

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
              onClick={() => { setSelectedGroupId(""); setShowMoveGroupDialog(true); }}
              disabled={bulkPatch.isPending}
              className="gap-1.5"
            >
              <FolderInput className="h-3.5 w-3.5" /> Move to Group
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => { setSelectedTenantId(""); setShowMoveTenantDialog(true); }}
              disabled={bulkPatch.isPending}
              className="gap-1.5"
            >
              <Building2 className="h-3.5 w-3.5" /> Move to Tenant
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setApplyTemplateOpen(true)}
              className="gap-1.5"
            >
              <FileText className="h-3.5 w-3.5" /> Apply Template
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={() => setConfirmDeleteOpen(true)}
              className="gap-1.5"
            >
              <Trash2 className="h-3.5 w-3.5" /> Delete Selected
            </Button>
          </div>
        )}

        {/* Compact toggle */}
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setCompact(!compact)}
          className="gap-1.5"
        >
          {compact ? (
            <Plus className="h-3.5 w-3.5" />
          ) : (
            <Minus className="h-3.5 w-3.5" />
          )}
          {compact ? "Normal" : "Compact"}
        </Button>

        <Button size="sm" onClick={() => setAddOpen(true)} className="gap-1.5">
          <Plus className="h-4 w-4" />
          Add Device
        </Button>
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
              <Button
                size="sm"
                variant="secondary"
                className="mt-4"
                onClick={() => setAddOpen(true)}
              >
                <Plus className="h-4 w-4" />
                Add your first device
              </Button>
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
                <Table>
                  <TableHeader>
                    <TableRow>
                      {/* Checkbox */}
                      <TableHead className="w-10">
                        <input
                          type="checkbox"
                          checked={allVisibleSelected}
                          onChange={toggleSelectAll}
                          className="h-4 w-4 rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500 cursor-pointer"
                        />
                      </TableHead>

                      {/* Status */}
                      <TableHead className="w-10">Status</TableHead>

                      {/* Name */}
                      <TableHead>
                        <div
                          className="flex items-center gap-1 cursor-pointer select-none"
                          onClick={() => handleSort("name")}
                        >
                          Name <SortIcon col="name" />
                        </div>
                        <ClearableInput
                          placeholder="Filter..."
                          value={filterName}
                          onChange={(e) => setFilterName(e.target.value)}
                          onClear={() => setFilterName("")}
                          className="mt-1 h-6 text-xs"
                        />
                      </TableHead>

                      {/* Address */}
                      <TableHead>
                        <div
                          className="flex items-center gap-1 cursor-pointer select-none"
                          onClick={() => handleSort("address")}
                        >
                          Address <SortIcon col="address" />
                        </div>
                        <ClearableInput
                          placeholder="Filter..."
                          value={filterAddress}
                          onChange={(e) => setFilterAddress(e.target.value)}
                          onClear={() => setFilterAddress("")}
                          className="mt-1 h-6 text-xs"
                        />
                      </TableHead>

                      {/* Category */}
                      <TableHead>
                        <div
                          className="flex items-center gap-1 cursor-pointer select-none"
                          onClick={() => handleSort("device_category")}
                        >
                          Category <SortIcon col="device_category" />
                        </div>
                        <ClearableInput
                          placeholder="Filter..."
                          value={filterType}
                          onChange={(e) => setFilterType(e.target.value)}
                          onClear={() => setFilterType("")}
                          className="mt-1 h-6 text-xs"
                        />
                      </TableHead>

                      {/* Device Type */}
                      <TableHead>
                        <div
                          className="flex items-center gap-1 cursor-pointer select-none"
                          onClick={() => handleSort("device_type_name")}
                        >
                          Type <SortIcon col="device_type_name" />
                        </div>
                        <ClearableInput
                          placeholder="Filter..."
                          value={filterDeviceType}
                          onChange={(e) => setFilterDeviceType(e.target.value)}
                          onClear={() => setFilterDeviceType("")}
                          className="mt-1 h-6 text-xs"
                        />
                      </TableHead>

                      {/* Tenant */}
                      <TableHead>
                        <div
                          className="flex items-center gap-1 cursor-pointer select-none"
                          onClick={() => handleSort("tenant_name")}
                        >
                          Tenant <SortIcon col="tenant_name" />
                        </div>
                        <ClearableInput
                          placeholder="Filter..."
                          value={filterTenant}
                          onChange={(e) => setFilterTenant(e.target.value)}
                          onClear={() => setFilterTenant("")}
                          className="mt-1 h-6 text-xs"
                        />
                      </TableHead>

                      {/* Collector Group */}
                      <TableHead>
                        <div
                          className="flex items-center gap-1 cursor-pointer select-none"
                          onClick={() => handleSort("collector_group_name")}
                        >
                          Collector Group{" "}
                          <SortIcon col="collector_group_name" />
                        </div>
                        <ClearableInput
                          placeholder="Filter..."
                          value={filterGroup}
                          onChange={(e) => setFilterGroup(e.target.value)}
                          onClear={() => setFilterGroup("")}
                          className="mt-1 h-6 text-xs"
                        />
                      </TableHead>

                      {/* Labels */}
                      <TableHead>
                        <div className="flex items-center justify-between">
                          Labels
                          <button
                            type="button"
                            onClick={() => {
                              setFilterName("");
                              setFilterAddress("");
                              setFilterType("");
                              setFilterTenant("");
                              setFilterGroup("");
                            }}
                            className={`inline-flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors ${hasActiveFilters ? "opacity-100" : "opacity-0 pointer-events-none"}`}
                          >
                            <X className="h-3 w-3" /> Clear All
                          </button>
                        </div>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {devices.length === 0 && hasActiveFilters ? (
                      <TableRow>
                        <TableCell colSpan={9} className="text-center py-8 text-zinc-500 text-sm">
                          No devices match your filters
                        </TableCell>
                      </TableRow>
                    ) : devices.map((device) => {
                      const isUp = deviceReachability.get(device.id);
                      const latencyInfo = deviceLatency.get(device.id);
                      const labelEntries = Object.entries(device.labels ?? {});
                      const shownLabels = labelEntries.slice(0, 2);
                      const extraLabelCount = labelEntries.length - 2;

                      return (
                        <TableRow key={device.id} className={!device.is_enabled ? "opacity-50" : undefined}>
                          {/* Checkbox */}
                          <TableCell>
                            <input
                              type="checkbox"
                              checked={selected.has(device.id)}
                              onChange={() => toggleSelect(device.id)}
                              className="h-4 w-4 rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500 cursor-pointer"
                            />
                          </TableCell>

                          {/* Status */}
                          <TableCell>
                            <div className="relative group w-fit cursor-default">
                              {!device.is_enabled ? (
                                <span className="inline-block h-2.5 w-2.5 rounded-full bg-zinc-600" title="Disabled" />
                              ) : (
                              <span
                                className={`inline-block h-2.5 w-2.5 rounded-full ${
                                  isUp === true
                                    ? "bg-emerald-500 animate-pulse-dot"
                                    : isUp === false
                                      ? "bg-red-500"
                                      : "bg-zinc-600"
                                }`}
                              />)}
                              {/* Latency tooltip */}
                              {latencyInfo && (
                                <div
                                  className="absolute left-4 top-1/2 -translate-y-1/2 z-50 hidden
                                              group-hover:flex items-center gap-1.5
                                              whitespace-nowrap rounded-md border border-zinc-700
                                              bg-zinc-900 px-2 py-1.5 text-xs shadow-lg
                                              pointer-events-none"
                                >
                                  <span className="text-zinc-500">
                                    {latencyInfo.appName}:
                                  </span>
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
                          </TableCell>

                          {/* Name */}
                          <TableCell>
                            <Link
                              to={`/devices/${device.id}`}
                              className="font-medium text-zinc-100 hover:text-brand-400 transition-colors"
                            >
                              {device.name}
                            </Link>
                          </TableCell>

                          {/* Address */}
                          <TableCell className="font-mono text-xs text-zinc-400">
                            {device.address}
                          </TableCell>

                          {/* Category */}
                          <TableCell>
                            <Badge variant="info">{device.device_category}</Badge>
                          </TableCell>

                          {/* Device Type */}
                          <TableCell className="text-zinc-400 text-sm">
                            {device.device_type_name || <span className="text-zinc-600">&mdash;</span>}
                          </TableCell>

                          {/* Tenant */}
                          <TableCell className="text-zinc-400 text-sm">
                            {device.tenant_name ? (
                              <Badge variant="default">
                                {device.tenant_name}
                              </Badge>
                            ) : (
                              <span className="text-zinc-600">&mdash;</span>
                            )}
                          </TableCell>

                          {/* Collector Group */}
                          <TableCell>
                            {device.collector_group_name ? (
                              <Badge variant="default">
                                {device.collector_group_name}
                              </Badge>
                            ) : (
                              <span className="text-zinc-600">&mdash;</span>
                            )}
                          </TableCell>

                          {/* Labels */}
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {shownLabels.map(([k, v]) => {
                                const lColor = labelColorMap.get(k);
                                return (
                                  <Badge
                                    key={k}
                                    variant="default"
                                    className="text-xs"
                                    style={lColor ? { backgroundColor: `${lColor}20`, color: lColor, borderColor: `${lColor}40` } : undefined}
                                  >
                                    {k}: {v}
                                  </Badge>
                                );
                              })}
                              {extraLabelCount > 0 && (
                                <Badge
                                  variant="default"
                                  className="text-xs cursor-default"
                                  title={labelEntries
                                    .map(([k, v]) => `${k}: ${v}`)
                                    .join(", ")}
                                >
                                  +{extraLabelCount} more
                                </Badge>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>

                </Table>
              </div>

              {/* Infinite scroll sentinel */}
              {scrollMode === "infinite" && (
                <div ref={sentinelRef} className="flex justify-center py-4">
                  {isFetching && <Loader2 className="h-5 w-5 animate-spin text-brand-500" />}
                  {!isFetching && hasMoreInfinite && (
                    <span className="text-xs text-zinc-600">Scroll for more...</span>
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
                    onChange={(e) => { updatePreferences({ table_scroll_mode: e.target.value as "paginated" | "infinite" }); setPage(0); }}
                    className="w-36 text-xs h-7"
                  >
                    <option value="paginated">Paginated</option>
                    <option value="infinite">Infinite Scroll</option>
                  </Select>
                  <Select
                    value={String(pageSize)}
                    onChange={(e) => { updatePreferences({ table_page_size: Number(e.target.value) }); setPage(0); }}
                    className="w-20 text-xs h-7"
                  >
                    {PAGE_SIZE_OPTIONS.map((s) => (
                      <option key={s} value={String(s)}>{s}</option>
                    ))}
                  </Select>
                  <span className="text-xs text-zinc-600">
                    {scrollMode === "infinite" ? "per batch" : "rows"}
                  </span>
                </div>
                <span className="text-sm text-zinc-500">
                  {scrollMode === "infinite"
                    ? `Showing ${devices.length} of ${total}`
                    : <>Showing {startItem}&ndash;{endItem} of {total}</>}
                </span>
                {scrollMode === "paginated" ? <div className="flex items-center gap-2">
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
                </div> : <div />}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Add Device Dialog */}
      <AddDeviceDialog open={addOpen} onClose={() => setAddOpen(false)} />

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
            <option key={g.id} value={g.id}>{g.name}</option>
          ))}
        </Select>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setShowMoveGroupDialog(false)}>
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
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </Select>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setShowMoveTenantDialog(false)}>
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
