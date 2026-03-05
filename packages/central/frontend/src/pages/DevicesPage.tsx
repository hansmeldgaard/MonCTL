import { useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Monitor, Plus, Search } from "lucide-react";
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
import { useCollectors, useDevices, useLatestResults } from "@/api/hooks.ts";
import { AddDeviceDialog } from "@/components/AddDeviceDialog.tsx";

export function DevicesPage() {
  const { data: devices, isLoading } = useDevices();
  const { data: latestResults } = useLatestResults();
  const { data: collectors } = useCollectors();
  const [search, setSearch] = useState("");
  const [addOpen, setAddOpen] = useState(false);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  // collector_id -> collector name lookup
  const collectorNames = new Map<string, string>();
  for (const c of collectors ?? []) {
    collectorNames.set(c.id, c.name || c.hostname);
  }

  // Build maps of device_id -> reachability and device_id -> active collector_id
  // Separate availability-role results from all results (for legacy fallback).
  const availReachability = new Map<string, boolean>(); // role="availability" only
  const anyReachability   = new Map<string, boolean>(); // all results (legacy fallback)
  // device_id → { appName, latencyMs } for the availability check (or best available)
  const deviceLatency = new Map<string, { appName: string; latencyMs: number | null; up: boolean }>();
  const deviceActiveCollector = new Map<string, string>();

  if (latestResults) {
    for (const r of latestResults) {
      // Any-result map (legacy fallback)
      const curAny = anyReachability.get(r.device_id);
      if (curAny === undefined) anyReachability.set(r.device_id, r.reachable);
      else if (!r.reachable) anyReachability.set(r.device_id, false);

      // Availability-role map
      if (r.role === "availability") {
        const curAvail = availReachability.get(r.device_id);
        if (curAvail === undefined) availReachability.set(r.device_id, r.reachable);
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

      // Track the active collector (first result per device = most recent)
      if (r.collector_id && !deviceActiveCollector.has(r.device_id)) {
        deviceActiveCollector.set(r.device_id, r.collector_id);
      }
    }
  }

  // Final UP/DOWN: prefer availability-role; fall back to any-result for legacy devices
  const deviceReachability = new Map<string, boolean>();
  for (const [id] of anyReachability) {
    deviceReachability.set(
      id,
      availReachability.has(id) ? availReachability.get(id)! : anyReachability.get(id)!,
    );
  }

  const filtered = (devices ?? []).filter((d) => {
    const q = search.toLowerCase();
    return (
      d.name.toLowerCase().includes(q) ||
      d.address.toLowerCase().includes(q) ||
      d.device_type.toLowerCase().includes(q) ||
      (d.tenant_name ?? "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-4">
      {/* Search + Actions */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <Input
            placeholder="Search devices..."
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <span className="text-sm text-zinc-500 flex-1">
          {filtered.length} device{filtered.length !== 1 ? "s" : ""}
        </span>
        <Button
          size="sm"
          onClick={() => setAddOpen(true)}
          className="gap-1.5"
        >
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
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Monitor className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">
                {search ? "No devices match your search" : "No devices found"}
              </p>
              {!search && (
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
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">Status</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Address</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Tenant</TableHead>
                  <TableHead>Collector</TableHead>
                  <TableHead>Labels</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((device) => {
                  const isUp = deviceReachability.get(device.id);
                  const latencyInfo = deviceLatency.get(device.id);
                  const activeCollectorId = deviceActiveCollector.get(device.id);
                  const activeCollectorName = activeCollectorId
                    ? collectorNames.get(activeCollectorId)
                    : undefined;
                  return (
                    <TableRow key={device.id}>
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
                            <div className="absolute left-4 top-1/2 -translate-y-1/2 z-50 hidden
                                            group-hover:flex items-center gap-1.5
                                            whitespace-nowrap rounded-md border border-zinc-700
                                            bg-zinc-900 px-2 py-1.5 text-xs shadow-lg
                                            pointer-events-none">
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
                      </TableCell>
                      <TableCell>
                        <Link
                          to={`/devices/${device.id}`}
                          className="font-medium text-zinc-100 hover:text-brand-400 transition-colors"
                        >
                          {device.name}
                        </Link>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-zinc-400">
                        {device.address}
                      </TableCell>
                      <TableCell>
                        <Badge variant="info">{device.device_type}</Badge>
                      </TableCell>
                      <TableCell className="text-zinc-400 text-sm">
                        {device.tenant_name
                          ? <Badge variant="default">{device.tenant_name}</Badge>
                          : <span className="text-zinc-600">—</span>}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-0.5">
                          {device.collector_group_name
                            ? <Badge variant="default">{device.collector_group_name}</Badge>
                            : null}
                          {activeCollectorName && (
                            <span className="text-xs text-zinc-500">
                              via {activeCollectorName}
                            </span>
                          )}
                          {!device.collector_group_name && !activeCollectorName && (
                            <span className="text-zinc-600">—</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(device.labels ?? {}).map(
                            ([key, value]) => (
                              <Badge
                                key={key}
                                variant="default"
                                className="text-xs"
                              >
                                {key}: {value}
                              </Badge>
                            ),
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Add Device Dialog */}
      <AddDeviceDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}
