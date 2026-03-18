import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  FileText,
  Loader2,
  Minus,
  Monitor,
  Plus,
  Trash2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Input } from "@/components/ui/input.tsx";
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
import { useDevices, useLatestResults, useBulkDeleteDevices, useLabelKeys } from "@/api/hooks.ts";
import { AddDeviceDialog } from "@/components/AddDeviceDialog.tsx";
import { ApplyTemplateDialog } from "@/components/ApplyTemplateDialog.tsx";

export function DevicesPage() {
  // ── Pagination ──────────────────────────────────────────
  const [page, setPage] = useState(0);
  const [pageSize] = useState(50);

  // ── Sorting ─────────────────────────────────────────────
  const [sortBy, setSortBy] = useState("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  // ── Per-column filters (immediate) ──────────────────────
  const [filterName, setFilterName] = useState("");
  const [filterAddress, setFilterAddress] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterTenant, setFilterTenant] = useState("");
  const [filterGroup, setFilterGroup] = useState("");

  // ── Debounced filter values ─────────────────────────────
  const [debouncedFilters, setDebouncedFilters] = useState({
    name: "",
    address: "",
    device_type: "",
    tenant_name: "",
    collector_group_name: "",
  });

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedFilters({
        name: filterName,
        address: filterAddress,
        device_type: filterType,
        tenant_name: filterTenant,
        collector_group_name: filterGroup,
      });
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [filterName, filterAddress, filterType, filterTenant, filterGroup]);

  // ── Compact mode ────────────────────────────────────────
  const [compact, setCompact] = useState(false);

  // ── Selection ───────────────────────────────────────────
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // ── Bulk delete ─────────────────────────────────────────
  const bulkDelete = useBulkDeleteDevices();
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [applyTemplateOpen, setApplyTemplateOpen] = useState(false);

  // ── Add dialog ──────────────────────────────────────────
  const [addOpen, setAddOpen] = useState(false);

  // ── Fetch devices ───────────────────────────────────────
  const { data: response, isLoading } = useDevices({
    limit: pageSize,
    offset: page * pageSize,
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

  // ── Latest results for status dots ──────────────────────
  const { data: latestResults } = useLatestResults();
  const { data: labelKeys } = useLabelKeys();
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
          {devices.length === 0 && !isLoading ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Monitor className="mb-2 h-8 w-8 text-zinc-600" />
              {hasActiveFilters ? (
                <>
                  <p className="text-sm">No devices match your filters</p>
                  <Button
                    size="sm"
                    variant="secondary"
                    className="mt-4"
                    onClick={() => {
                      setFilterName("");
                      setFilterAddress("");
                      setFilterType("");
                      setFilterTenant("");
                      setFilterGroup("");
                    }}
                  >
                    Clear Filters
                  </Button>
                </>
              ) : (
                <>
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
                </>
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
                        <Input
                          placeholder="Filter..."
                          value={filterName}
                          onChange={(e) => setFilterName(e.target.value)}
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
                        <Input
                          placeholder="Filter..."
                          value={filterAddress}
                          onChange={(e) => setFilterAddress(e.target.value)}
                          className="mt-1 h-6 text-xs"
                        />
                      </TableHead>

                      {/* Type */}
                      <TableHead>
                        <div
                          className="flex items-center gap-1 cursor-pointer select-none"
                          onClick={() => handleSort("device_type")}
                        >
                          Type <SortIcon col="device_type" />
                        </div>
                        <Input
                          placeholder="Filter..."
                          value={filterType}
                          onChange={(e) => setFilterType(e.target.value)}
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
                        <Input
                          placeholder="Filter..."
                          value={filterTenant}
                          onChange={(e) => setFilterTenant(e.target.value)}
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
                        <Input
                          placeholder="Filter..."
                          value={filterGroup}
                          onChange={(e) => setFilterGroup(e.target.value)}
                          className="mt-1 h-6 text-xs"
                        />
                      </TableHead>

                      {/* Labels */}
                      <TableHead>Labels</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {devices.map((device) => {
                      const isUp = deviceReachability.get(device.id);
                      const latencyInfo = deviceLatency.get(device.id);
                      const labelEntries = Object.entries(device.labels ?? {});
                      const shownLabels = labelEntries.slice(0, 2);
                      const extraLabelCount = labelEntries.length - 2;

                      return (
                        <TableRow key={device.id}>
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
                              <span
                                className={`inline-block h-2.5 w-2.5 rounded-full ${
                                  isUp === true
                                    ? "bg-emerald-500 animate-pulse-dot"
                                    : isUp === false
                                      ? "bg-red-500"
                                      : "bg-zinc-600"
                                }`}
                              />
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

                          {/* Type */}
                          <TableCell>
                            <Badge variant="info">{device.device_type}</Badge>
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

              {/* Pagination */}
              <div className="flex items-center justify-between border-t border-zinc-800 pt-3 mt-3">
                <span className="text-sm text-zinc-500">
                  Showing {startItem}&ndash;{endItem} of {total}
                </span>
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
    </div>
  );
}
