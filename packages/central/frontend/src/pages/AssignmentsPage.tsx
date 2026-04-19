import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Bug, ChevronDown, ListChecks, Loader2, Trash2 } from "lucide-react";
import { CredentialCell } from "@/components/CredentialCell.tsx";
import { DebugRunDialog } from "@/components/DebugRunDialog.tsx";
import { IntervalInput } from "@/components/IntervalInput";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Select } from "@/components/ui/select.tsx";
import {
  useAssignments,
  useAppDetail,
  useBulkUpdateAssignments,
  useBulkDeleteAssignments,
  useCredentials,
  useLatestMutations,
} from "@/api/hooks.ts";
import { formatTime } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { useListState } from "@/hooks/useListState.ts";
import { useTablePreferences } from "@/hooks/useTablePreferences.ts";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences.ts";
import { useTimeDisplayMode } from "@/hooks/useTimeDisplayMode.ts";
import { useColumnConfig } from "@/hooks/useColumnConfig.ts";
import { FlexTable } from "@/components/FlexTable/FlexTable.tsx";
import { DisplayMenu } from "@/components/FlexTable/DisplayMenu.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { FlexColumnDef } from "@/components/FlexTable/types.ts";
import type { BulkUpdateAssignmentsRequest } from "@/types/api.ts";

export function AssignmentsPage() {
  const tz = useTimezone();
  const { canEdit, canDelete } = usePermissions();
  const { pageSize, scrollMode } = useTablePreferences();
  const { compact } = useDisplayPreferences();
  const { mode: timeMode } = useTimeDisplayMode();

  const listState = useListState({
    columns: [
      { key: "app_name", label: "App" },
      { key: "device_name", label: "Device" },
      { key: "device_category", label: "Category" },
      { key: "device_type_name", label: "Device Type" },
      { key: "device_address", label: "Device Address", sortable: false },
      { key: "collector_group_name", label: "Collector Group" },
      { key: "schedule_value", label: "Schedule" },
      { key: "credential_name", label: "Credential" },
      { key: "enabled", label: "Enabled" },
    ],
    defaultSortBy: "app_name",
    defaultPageSize: pageSize,
    scrollMode,
  });

  const {
    data: response,
    isLoading,
    isFetching,
  } = useAssignments(listState.params);
  const assignments = response?.data ?? [];

  const assignmentIds = useMemo(
    () => assignments.map((a: any) => a.id as string),
    [assignments],
  );
  const { data: auditByIdRaw } = useLatestMutations(
    "assignment",
    assignmentIds,
  );
  const auditById = auditByIdRaw ?? {};
  const meta = (response as any)?.meta ?? {
    limit: 50,
    offset: 0,
    count: 0,
    total: 0,
  };

  // Selection
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Debug Run dialog
  const [debugTarget, setDebugTarget] = useState<{
    deviceId: string;
    assignmentId: string;
    appName: string;
    deviceName: string;
  } | null>(null);

  // Bulk actions
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkScheduleType, setBulkScheduleType] = useState("");
  const [bulkScheduleValue, setBulkScheduleValue] = useState("");
  const [bulkCredentialId, setBulkCredentialId] = useState("");
  const [bulkEnabled, setBulkEnabled] = useState("");
  const [bulkVersionMode, setBulkVersionMode] = useState("");
  const bulkUpdate = useBulkUpdateAssignments();
  const bulkDelete = useBulkDeleteAssignments();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const { data: credentials } = useCredentials();
  const bulkRef = useRef<HTMLDivElement>(null);

  // Determine if all selected assignments belong to the same app
  const selectedApps = useMemo(() => {
    if (selected.size === 0)
      return {
        singleApp: false,
        appId: null as string | null,
        appName: null as string | null,
      };
    const selectedAssignments = (assignments ?? []).filter((a: any) =>
      selected.has(a.id),
    );
    const uniqueAppIds = new Set(selectedAssignments.map((a: any) => a.app.id));
    if (uniqueAppIds.size === 1) {
      const first = selectedAssignments[0];
      return {
        singleApp: true,
        appId: first.app.id as string,
        appName: first.app.name as string,
      };
    }
    return { singleApp: false, appId: null, appName: null };
  }, [selected, assignments]);

  // Fetch app versions when a single app is selected
  const { data: bulkAppDetail } = useAppDetail(
    selectedApps.singleApp ? selectedApps.appId! : undefined,
  );

  // Close bulk popover on outside click
  useEffect(() => {
    if (!bulkOpen) return;
    function handleClick(e: MouseEvent) {
      if (bulkRef.current && !bulkRef.current.contains(e.target as Node)) {
        setBulkOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [bulkOpen]);

  const allVisibleSelected =
    assignments.length > 0 && assignments.every((a) => selected.has(a.id));
  const someSelected = selected.size > 0;

  const toggleSelectAll = useCallback(() => {
    setConfirmDelete(false);
    setSelected((prev) => {
      if (assignments.length > 0 && assignments.every((a) => prev.has(a.id))) {
        return new Set();
      }
      return new Set(assignments.map((a) => a.id));
    });
  }, [assignments]);

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  async function handleBulkApply() {
    const payload: BulkUpdateAssignmentsRequest = {
      assignment_ids: [...selected],
    };
    if (bulkScheduleType && bulkScheduleValue) {
      payload.schedule_type = bulkScheduleType;
      payload.schedule_value = bulkScheduleValue;
    }
    if (bulkCredentialId !== "") {
      payload.credential_id =
        bulkCredentialId === "__clear__" ? "" : bulkCredentialId;
    }
    if (bulkEnabled !== "") {
      payload.enabled = bulkEnabled === "true";
    }
    if (bulkVersionMode === "latest") {
      payload.use_latest = true;
    } else if (bulkVersionMode !== "") {
      payload.app_version_id = bulkVersionMode;
    }
    try {
      setBulkError("");
      await bulkUpdate.mutateAsync(payload);
      setBulkOpen(false);
      setBulkScheduleType("");
      setBulkScheduleValue("");
      setBulkCredentialId("");
      setBulkEnabled("");
      setBulkVersionMode("");
      setSelected(new Set());
    } catch (e: any) {
      setBulkError(e?.message ?? "Bulk update failed");
    }
  }

  // Column definitions — order here is the default; user overrides live
  // in useColumnConfig.orderedVisibleColumns.
  const columns = useMemo<FlexColumnDef<any>[]>(
    () => [
      {
        key: "__select",
        label: (
          <input
            type="checkbox"
            checked={allVisibleSelected}
            ref={(el) => {
              if (el) el.indeterminate = someSelected && !allVisibleSelected;
            }}
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
        cell: (a: any) => (
          <input
            type="checkbox"
            checked={selected.has(a.id)}
            onChange={() => toggleSelect(a.id)}
            className="h-4 w-4 rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500 cursor-pointer"
            aria-label={`Select assignment ${a.id}`}
          />
        ),
      },
      {
        key: "app_name",
        label: "App",
        defaultWidth: 260,
        cell: (a: any) => (
          <div className="flex items-center gap-2">
            <Link
              to={`/apps/${a.app.id}`}
              className="font-medium text-zinc-100 hover:text-brand-400 transition-colors"
            >
              {a.app.name}
            </Link>
            <Badge variant="default" className="text-xs">
              v{a.app.version}
            </Badge>
            {a.use_latest && (
              <Badge
                variant="default"
                className="text-[10px] text-zinc-500 border-zinc-700"
              >
                latest
              </Badge>
            )}
            {!a.is_on_latest && a.latest_version && (
              <Badge
                variant="warning"
                className="text-[10px]"
                title={`Latest available: v${a.latest_version}`}
              >
                stale → v{a.latest_version}
              </Badge>
            )}
          </div>
        ),
      },
      {
        key: "device_name",
        label: "Device",
        defaultWidth: 200,
        cell: (a: any) =>
          a.device ? (
            <Link
              to={`/devices/${a.device.id}`}
              className="text-brand-400 hover:text-brand-300 transition-colors"
            >
              {a.device.name}
            </Link>
          ) : (
            <span className="italic text-zinc-500">inline</span>
          ),
      },
      {
        key: "device_category",
        label: "Category",
        defaultWidth: 140,
        cellClassName: "text-zinc-400 text-xs",
        cell: (a: any) => a.device?.device_category ?? "—",
      },
      {
        key: "device_type_name",
        label: "Device Type",
        sortable: false,
        defaultWidth: 160,
        cellClassName: "text-zinc-400 text-xs",
        cell: (a: any) =>
          a.device?.device_type_name ?? (
            <span className="text-zinc-600">&mdash;</span>
          ),
      },
      {
        key: "device_address",
        label: "Device Address",
        sortable: false,
        defaultWidth: 140,
        cellClassName: "font-mono text-xs text-zinc-400",
        cell: (a: any) =>
          a.device ? (
            a.device.address
          ) : (
            <span className="text-zinc-600 not-italic">
              {String(a.config?.host ?? "—")}
            </span>
          ),
      },
      {
        key: "collector_group_name",
        label: "Collector Group",
        defaultWidth: 160,
        cellClassName: "text-zinc-400 text-xs",
        cell: (a: any) =>
          a.device?.collector_group_name ?? (
            <span className="text-zinc-600">&mdash;</span>
          ),
      },
      {
        key: "schedule",
        label: "Schedule",
        defaultWidth: 140,
        cellClassName: "text-zinc-400",
        cell: (a: any) => a.schedule_human,
      },
      {
        key: "credential_name",
        label: "Credential",
        sortable: false,
        defaultWidth: 180,
        cellClassName: "text-zinc-400",
        cell: (a: any) => (
          <CredentialCell
            credentialName={a.credential_name}
            credentialOverrides={a.credential_overrides}
            deviceDefaultCredentialName={a.device_default_credential_name}
          />
        ),
      },
      {
        key: "enabled",
        label: "Enabled",
        defaultWidth: 100,
        cell: (a: any) => (
          <Badge variant={a.enabled ? "success" : "default"}>
            {a.enabled ? "Enabled" : "Disabled"}
          </Badge>
        ),
      },
      {
        key: "created_at",
        label: "Created",
        filterable: false,
        defaultWidth: 120,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (a: any) => {
          if (!a.created_at) return "—";
          return (
            <span
              title={formatTime(
                a.created_at,
                timeMode === "relative" ? "absolute" : "relative",
                tz,
              )}
            >
              {formatTime(a.created_at, timeMode, tz)}
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
        cell: (a: any) => {
          if (!a.updated_at) return "—";
          return (
            <span
              title={formatTime(
                a.updated_at,
                timeMode === "relative" ? "absolute" : "relative",
                tz,
              )}
            >
              {formatTime(a.updated_at, timeMode, tz)}
            </span>
          );
        },
      },
      {
        key: "last_changed_by",
        label: "Last changed by",
        sortable: false,
        filterable: false,
        defaultWidth: 140,
        cellClassName: "text-zinc-400 text-xs whitespace-nowrap",
        cell: (a: any) => {
          const m = auditById[a.id];
          if (!m) return "—";
          return (
            <span title={`${m.action} · ${m.user_id || m.username}`}>
              {m.username || m.user_id || "—"}
            </span>
          );
        },
      },
      {
        key: "last_changed_at",
        label: "Last changed",
        sortable: false,
        filterable: false,
        defaultWidth: 120,
        cellClassName: "text-zinc-500 text-xs whitespace-nowrap",
        cell: (a: any) => {
          const m = auditById[a.id];
          if (!m?.timestamp) return "—";
          return (
            <span
              title={formatTime(
                m.timestamp,
                timeMode === "relative" ? "absolute" : "relative",
                tz,
              )}
            >
              {formatTime(m.timestamp, timeMode, tz)}
            </span>
          );
        },
      },
      {
        key: "__actions",
        label: "",
        pickerLabel: "Actions",
        sortable: false,
        filterable: false,
        minWidth: 60,
        defaultWidth: 60,
        cell: (a: any) =>
          canEdit("device") ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0 text-brand-400 hover:text-brand-300"
              onClick={(e) => {
                e.stopPropagation();
                setDebugTarget({
                  deviceId: a.device.id,
                  assignmentId: a.id,
                  appName: a.app.name,
                  deviceName: a.device.name,
                });
              }}
              title="Debug Run — run this app once and see the full output"
            >
              <Bug className="h-3 w-3" />
            </Button>
          ) : null,
      },
    ],
    [
      allVisibleSelected,
      someSelected,
      selected,
      toggleSelect,
      toggleSelectAll,
      timeMode,
      tz,
      canEdit,
      auditById,
    ],
  );

  const {
    orderedVisibleColumns,
    configMap,
    setHidden,
    setWidth,
    setOrder,
    reset: resetColumns,
  } = useColumnConfig<any>("assignments", columns);

  // Map FlexTable's column-key-based filter contract to useListState's
  // backing keys (schedule column → schedule_value filter param).
  const filtersMap: Record<string, string> = {
    ...listState.filters,
    schedule: listState.filters.schedule_value ?? "",
  };
  const handleFilterChange = useCallback(
    (col: string, value: string) => {
      if (col === "schedule") listState.setFilter("schedule_value", value);
      else listState.setFilter(col, value);
    },
    [listState],
  );

  if (isLoading) {
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
          {meta.total} assignment{meta.total !== 1 ? "s" : ""}
        </span>

        {someSelected && (
          <>
            <span className="text-sm font-medium text-brand-400">
              {selected.size} selected
            </span>
            <div className="relative" ref={bulkRef}>
              <div className="flex gap-1.5">
                {canEdit("assignment") && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setBulkOpen(!bulkOpen)}
                    className="gap-1.5"
                  >
                    Bulk actions
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                )}
                {canDelete("assignment") &&
                  (!confirmDelete ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setConfirmDelete(true)}
                      className="gap-1.5 text-red-400 border-red-400/30 hover:bg-red-400/10"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={bulkDelete.isPending}
                      onClick={async () => {
                        try {
                          setBulkError("");
                          await bulkDelete.mutateAsync([...selected]);
                          setSelected(new Set());
                          setConfirmDelete(false);
                        } catch (e: any) {
                          setBulkError(e?.message ?? "Bulk delete failed");
                          setConfirmDelete(false);
                        }
                      }}
                      className="gap-1.5 text-red-400 border-red-500 hover:bg-red-500/20"
                    >
                      {bulkDelete.isPending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                      Confirm delete {selected.size}?
                    </Button>
                  ))}
              </div>

              {bulkOpen && (
                <div className="absolute top-9 right-0 z-20 w-96 rounded-md border border-zinc-700 bg-zinc-900 p-3 space-y-3 shadow-lg">
                  <div>
                    <label className="text-xs text-zinc-500 block mb-1">
                      Schedule
                    </label>
                    <Select
                      value={bulkScheduleType}
                      onChange={(e) => setBulkScheduleType(e.target.value)}
                      className="w-full text-xs h-7"
                    >
                      <option value="">— No change —</option>
                      <option value="interval">Interval</option>
                      <option value="cron">Cron</option>
                    </Select>
                    {bulkScheduleType === "interval" && (
                      <IntervalInput
                        value={bulkScheduleValue || "60"}
                        onChange={setBulkScheduleValue}
                        className="mt-1.5"
                      />
                    )}
                    {bulkScheduleType === "cron" && (
                      <Input
                        value={bulkScheduleValue}
                        onChange={(e) => setBulkScheduleValue(e.target.value)}
                        placeholder="*/5 * * * *"
                        className="mt-1.5 w-full text-xs h-7"
                      />
                    )}
                  </div>

                  <div>
                    <label className="text-xs text-zinc-500 block mb-1">
                      Credential
                    </label>
                    <Select
                      value={bulkCredentialId}
                      onChange={(e) => setBulkCredentialId(e.target.value)}
                      className="w-full text-xs h-7"
                    >
                      <option value="">— No change —</option>
                      <option value="__clear__">Clear credential</option>
                      {(credentials ?? []).map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </Select>
                  </div>

                  <div>
                    <label className="text-xs text-zinc-500 block mb-1">
                      Version
                    </label>
                    <select
                      value={bulkVersionMode}
                      onChange={(e) => setBulkVersionMode(e.target.value)}
                      className="w-full text-xs h-7 bg-zinc-800 border border-zinc-700 rounded px-2 text-zinc-300"
                    >
                      <option value="">— No change —</option>
                      <option value="latest">Latest</option>
                      {selectedApps.singleApp &&
                        bulkAppDetail?.versions?.map((v: any) => (
                          <option key={v.id} value={v.id}>
                            {v.version}
                            {v.is_latest ? " (latest)" : ""}
                          </option>
                        ))}
                    </select>
                    {!selectedApps.singleApp && selected.size > 0 && (
                      <p className="text-[10px] text-zinc-600 mt-1">
                        Multiple apps selected — only "Latest" available
                      </p>
                    )}
                  </div>

                  <div>
                    <label className="text-xs text-zinc-500 block mb-1">
                      Enabled
                    </label>
                    <Select
                      value={bulkEnabled}
                      onChange={(e) => setBulkEnabled(e.target.value)}
                      className="w-full text-xs h-7"
                    >
                      <option value="">— No change —</option>
                      <option value="true">Enable all</option>
                      <option value="false">Disable all</option>
                    </Select>
                  </div>

                  {canEdit("assignment") && (
                    <Button
                      size="sm"
                      className="w-full"
                      disabled={bulkUpdate.isPending}
                      onClick={handleBulkApply}
                    >
                      {bulkUpdate.isPending && (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      )}
                      Apply to {selected.size} assignment
                      {selected.size !== 1 ? "s" : ""}
                    </Button>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        <DisplayMenu
          columns={columns}
          configMap={configMap}
          onToggleHidden={setHidden}
          onReset={resetColumns}
        />
      </div>

      {bulkError && (
        <div className="flex items-center justify-between rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          <span>{bulkError}</span>
          <button
            onClick={() => setBulkError("")}
            className="ml-3 text-red-400 hover:text-red-300"
          >
            &times;
          </button>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 justify-between">
            <span className="flex items-center gap-2">
              <ListChecks className="h-4 w-4" />
              App Assignments
            </span>
            <label className="flex items-center gap-2 text-xs font-normal text-zinc-400">
              Version
              <select
                value={listState.filters.version_status ?? ""}
                onChange={(e) =>
                  listState.setFilter("version_status", e.target.value)
                }
                className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-brand-500"
              >
                <option value="">All</option>
                <option value="on_latest">On latest</option>
                <option value="stale">Stale (not on latest)</option>
                <option value="pinned">Pinned (use_latest=false)</option>
              </select>
            </label>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div
            className={
              compact
                ? "[&_td]:py-1 [&_td]:text-xs [&_th]:py-1 [&_th]:text-xs"
                : ""
            }
          >
            <FlexTable<any>
              orderedVisibleColumns={orderedVisibleColumns}
              configMap={configMap}
              onOrderChange={setOrder}
              onWidthChange={setWidth}
              rows={assignments}
              rowKey={(a) => a.id}
              sortBy={listState.sortBy}
              sortDir={listState.sortDir}
              onSort={listState.handleSort}
              filters={filtersMap}
              onFilterChange={handleFilterChange}
              rowClassName={(a) =>
                selected.has(a.id) ? "bg-brand-500/5" : undefined
              }
              emptyState={
                listState.hasActiveFilters
                  ? "No assignments match your filters"
                  : "No assignments configured"
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

      <DebugRunDialog
        open={!!debugTarget}
        onClose={() => setDebugTarget(null)}
        deviceId={debugTarget?.deviceId ?? ""}
        assignmentId={debugTarget?.assignmentId ?? ""}
        appName={debugTarget?.appName ?? ""}
        deviceName={debugTarget?.deviceName ?? ""}
      />
    </div>
  );
}
