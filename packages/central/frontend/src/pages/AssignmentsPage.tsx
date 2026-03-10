import { useState } from "react";
import { ListChecks, Loader2, Search } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Input } from "@/components/ui/input.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { useAssignments } from "@/api/hooks.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

export function AssignmentsPage() {
  const tz = useTimezone();
  const { data: assignments, isLoading } = useAssignments();
  const [search, setSearch] = useState("");

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    );
  }

  const filtered = (assignments ?? []).filter((a) => {
    const q = search.toLowerCase();
    return (
      a.app.name.toLowerCase().includes(q) ||
      (a.device?.name ?? "").toLowerCase().includes(q) ||
      (a.device?.address ?? "").toLowerCase().includes(q) ||
      // Also search inline config host
      JSON.stringify(a.config ?? {}).toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <Input
            placeholder="Search by app or device..."
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <span className="text-sm text-zinc-500">
          {filtered.length} assignment{filtered.length !== 1 ? "s" : ""}
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
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <ListChecks className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">
                {search
                  ? "No assignments match your search"
                  : "No assignments configured"}
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>App</TableHead>
                  <TableHead>Device</TableHead>
                  <TableHead>Device Address</TableHead>
                  <TableHead>Schedule</TableHead>
                  <TableHead>Enabled</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((assignment) => (
                  <TableRow key={assignment.id}>
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
                    <TableCell className="text-zinc-300">
                      {assignment.device
                        ? assignment.device.name
                        : <span className="italic text-zinc-500">inline</span>}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-zinc-400">
                      {assignment.device
                        ? assignment.device.address
                        : <span className="text-zinc-600 not-italic">{String(assignment.config?.host ?? "—")}</span>}
                    </TableCell>
                    <TableCell className="text-zinc-400">
                      {assignment.schedule_human}
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}
