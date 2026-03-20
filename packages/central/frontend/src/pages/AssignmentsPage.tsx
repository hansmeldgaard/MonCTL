import { useState, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ListChecks, Loader2, Search } from "lucide-react";
import { CredentialCell } from "@/components/CredentialCell.tsx";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Select } from "@/components/ui/select.tsx";
import { ClearableInput } from "@/components/ui/clearable-input.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { useAssignments, useBulkUpdateAssignments, useCredentials } from "@/api/hooks.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { useListState } from "@/hooks/useListState.ts";
import { SortableHead } from "@/components/SortableHead.tsx";
import { PaginationBar } from "@/components/PaginationBar.tsx";
import type { BulkUpdateAssignmentsRequest } from "@/types/api.ts";

export function AssignmentsPage() {
  const tz = useTimezone();
  const listState = useListState({ defaultSortBy: "app_name" });
  const { data: response, isLoading } = useAssignments(listState.params);
  const assignments = response?.data ?? [];
  const meta = (response as any)?.meta ?? { limit: 50, offset: 0, count: 0, total: 0 };

  // Selection
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Bulk actions
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkScheduleType, setBulkScheduleType] = useState("");
  const [bulkScheduleValue, setBulkScheduleValue] = useState("");
  const [bulkCredentialId, setBulkCredentialId] = useState("");
  const [bulkEnabled, setBulkEnabled] = useState("");
  const bulkUpdate = useBulkUpdateAssignments();
  const { data: credentials } = useCredentials();
  const bulkRef = useRef<HTMLDivElement>(null);

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

  function toggleSelectAll() {
    if (allVisibleSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(assignments.map((a) => a.id)));
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

  async function handleBulkApply() {
    const payload: BulkUpdateAssignmentsRequest = {
      assignment_ids: [...selected],
    };
    if (bulkScheduleType && bulkScheduleValue) {
      payload.schedule_type = bulkScheduleType;
      payload.schedule_value = bulkScheduleValue;
    }
    if (bulkCredentialId !== "") {
      payload.credential_id = bulkCredentialId === "__clear__" ? "" : bulkCredentialId;
    }
    if (bulkEnabled !== "") {
      payload.enabled = bulkEnabled === "true";
    }
    await bulkUpdate.mutateAsync(payload);
    setBulkOpen(false);
    setBulkScheduleType("");
    setBulkScheduleValue("");
    setBulkCredentialId("");
    setBulkEnabled("");
    setSelected(new Set());
  }

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
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <ClearableInput
            placeholder="Search apps, devices..."
            className="pl-9"
            value={listState.search}
            onChange={(e) => listState.setSearch(e.target.value)}
            onClear={() => listState.setSearch("")}
          />
        </div>

        {someSelected && (
          <>
            <span className="text-sm font-medium text-brand-400">
              {selected.size} selected
            </span>
            <div className="relative" ref={bulkRef}>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setBulkOpen(!bulkOpen)}
                className="gap-1.5"
              >
                Bulk actions
                <ChevronDown className="h-3 w-3" />
              </Button>

              {bulkOpen && (
                <div className="absolute top-9 right-0 z-20 w-64 rounded-md border border-zinc-700 bg-zinc-900 p-3 space-y-3 shadow-lg">
                  {/* Schedule */}
                  <div>
                    <label className="text-xs text-zinc-500 block mb-1">Schedule</label>
                    <div className="flex gap-1.5">
                      <Select
                        value={bulkScheduleType}
                        onChange={(e) => setBulkScheduleType(e.target.value)}
                        className="flex-1 text-xs h-7"
                      >
                        <option value="">— No change —</option>
                        <option value="interval">Interval</option>
                        <option value="cron">Cron</option>
                      </Select>
                      {bulkScheduleType && (
                        <Input
                          value={bulkScheduleValue}
                          onChange={(e) => setBulkScheduleValue(e.target.value)}
                          placeholder={bulkScheduleType === "interval" ? "60" : "*/5 * * * *"}
                          className="flex-1 text-xs h-7"
                        />
                      )}
                    </div>
                  </div>

                  {/* Credential */}
                  <div>
                    <label className="text-xs text-zinc-500 block mb-1">Credential</label>
                    <Select
                      value={bulkCredentialId}
                      onChange={(e) => setBulkCredentialId(e.target.value)}
                      className="w-full text-xs h-7"
                    >
                      <option value="">— No change —</option>
                      <option value="__clear__">Clear credential</option>
                      {(credentials ?? []).map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </Select>
                  </div>

                  {/* Enabled */}
                  <div>
                    <label className="text-xs text-zinc-500 block mb-1">Enabled</label>
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

                  <Button
                    size="sm"
                    className="w-full"
                    disabled={bulkUpdate.isPending}
                    onClick={handleBulkApply}
                  >
                    {bulkUpdate.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    Apply to {selected.size} assignment{selected.size !== 1 ? "s" : ""}
                  </Button>
                </div>
              )}
            </div>
          </>
        )}

        <span className="text-sm text-zinc-500 ml-auto">
          {meta.total} assignment{meta.total !== 1 ? "s" : ""}
        </span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="h-4 w-4" />
            App Assignments
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    ref={(el) => { if (el) el.indeterminate = someSelected && !allVisibleSelected; }}
                    onChange={toggleSelectAll}
                    className="accent-brand-500 cursor-pointer"
                  />
                </TableHead>
                <SortableHead col="app_name" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>
                  App
                </SortableHead>
                <SortableHead col="device_name" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>
                  Device
                </SortableHead>
                <TableHead>Device Address</TableHead>
                <SortableHead col="schedule" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>
                  Schedule
                </SortableHead>
                <TableHead>Credential(s)</TableHead>
                <SortableHead col="enabled" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>
                  Enabled
                </SortableHead>
                <SortableHead col="created_at" sortBy={listState.sortBy} sortDir={listState.sortDir} onSort={listState.handleSort}>
                  Created
                </SortableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {assignments.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-8 text-zinc-500 text-sm">
                    {listState.search ? "No assignments match your search" : "No assignments configured"}
                  </TableCell>
                </TableRow>
              ) : assignments.map((assignment) => (
                <TableRow
                  key={assignment.id}
                  className={selected.has(assignment.id) ? "bg-brand-500/5" : ""}
                >
                  <TableCell>
                    <input
                      type="checkbox"
                      checked={selected.has(assignment.id)}
                      onChange={() => toggleSelect(assignment.id)}
                      className="accent-brand-500 cursor-pointer"
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-zinc-100">
                        {assignment.app.name}
                      </span>
                      <Badge variant="default" className="text-xs">
                        v{assignment.app.version}
                      </Badge>
                    </div>
                  </TableCell>
                  <TableCell>
                    {assignment.device ? (
                      <Link
                        to={`/devices/${assignment.device.id}`}
                        className="text-brand-400 hover:text-brand-300 transition-colors"
                      >
                        {assignment.device.name}
                      </Link>
                    ) : (
                      <span className="italic text-zinc-500">inline</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-zinc-400">
                    {assignment.device
                      ? assignment.device.address
                      : <span className="text-zinc-600 not-italic">{String(assignment.config?.host ?? "—")}</span>}
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {assignment.schedule_human}
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    <CredentialCell
                      credentialName={assignment.credential_name}
                      credentialOverrides={assignment.credential_overrides}
                      deviceDefaultCredentialName={assignment.device_default_credential_name}
                    />
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={assignment.enabled ? "success" : "default"}
                    >
                      {assignment.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-zinc-500">
                    {formatDate(assignment.created_at, tz)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <PaginationBar
            page={listState.page}
            pageSize={listState.pageSize}
            total={meta.total}
            count={meta.count}
            onPageChange={listState.setPage}
          />
        </CardContent>
      </Card>
    </div>
  );
}
