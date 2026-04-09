import { useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Trash2, LayoutDashboard, Loader2 } from "lucide-react";
import { usePermissions } from "@/hooks/usePermissions.ts";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import {
  useAnalyticsDashboards,
  useCreateAnalyticsDashboard,
  useDeleteAnalyticsDashboard,
} from "@/api/hooks.ts";

export function CustomDashboardsPage() {
  const { canCreate, canDelete } = usePermissions();
  const { data: dashboards, isLoading } = useAnalyticsDashboards();
  const createMut = useCreateAnalyticsDashboard();
  const deleteMut = useDeleteAnalyticsDashboard();

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [search, setSearch] = useState("");

  const filtered = (dashboards || []).filter(
    (d) =>
      d.name.toLowerCase().includes(search.toLowerCase()) ||
      d.description.toLowerCase().includes(search.toLowerCase()),
  );

  async function handleCreate() {
    if (!newName.trim()) return;
    await createMut.mutateAsync({
      name: newName.trim(),
      description: newDesc.trim(),
    });
    setNewName("");
    setNewDesc("");
    setShowCreate(false);
  }

  function handleDelete(id: string, name: string) {
    if (!confirm(`Delete dashboard "${name}"?`)) return;
    deleteMut.mutate(id);
  }

  function formatDate(iso: string | null) {
    if (!iso) return "\u2014";
    return new Date(iso).toLocaleString();
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-100">
          Custom Dashboards
        </h1>
        {canCreate("dashboard") && (
          <Button
            size="sm"
            onClick={() => setShowCreate(true)}
            className="gap-1.5"
          >
            <Plus className="h-3.5 w-3.5" />
            New Dashboard
          </Button>
        )}
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="flex items-end gap-2 p-3 rounded-md border border-zinc-800 bg-zinc-900/50">
          <div className="flex-1 space-y-1">
            <label className="text-xs text-zinc-500">Name</label>
            <Input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Dashboard name"
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            />
          </div>
          <div className="flex-1 space-y-1">
            <label className="text-xs text-zinc-500">Description</label>
            <Input
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="Optional description"
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            />
          </div>
          <Button
            size="sm"
            onClick={handleCreate}
            disabled={createMut.isPending || !newName.trim()}
          >
            {createMut.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              "Create"
            )}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setShowCreate(false)}
          >
            Cancel
          </Button>
        </div>
      )}

      {/* Search */}
      <Input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search dashboards..."
        className="max-w-xs"
      />

      {/* Table */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-zinc-500">
          <LayoutDashboard className="h-10 w-10 mb-3 text-zinc-700" />
          <p className="text-sm">
            {dashboards?.length === 0
              ? "No dashboards yet. Create one to get started."
              : "No dashboards match your search."}
          </p>
        </div>
      ) : (
        <div className="border border-zinc-800 rounded-md">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Owner</TableHead>
                <TableHead className="text-right">Widgets</TableHead>
                <TableHead>Updated</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>
                    <Link
                      to={`/analytics/dashboards/${d.id}`}
                      className="text-brand-400 hover:underline font-medium"
                    >
                      {d.name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-zinc-500 text-xs max-w-xs truncate">
                    {d.description || "\u2014"}
                  </TableCell>
                  <TableCell className="text-xs text-zinc-400">
                    {d.owner_name || "\u2014"}
                  </TableCell>
                  <TableCell className="text-right text-xs">
                    {d.widget_count}
                  </TableCell>
                  <TableCell className="text-xs text-zinc-500">
                    {formatDate(d.updated_at)}
                  </TableCell>
                  {canDelete("dashboard") && (
                    <TableCell>
                      <button
                        onClick={() => handleDelete(d.id, d.name)}
                        className="text-zinc-600 hover:text-red-400 transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
