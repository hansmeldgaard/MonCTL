import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronDown, ChevronRight, Download, Loader2, Trash2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { usePackDetail, useExportPack, useDeletePack } from "@/api/hooks.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

const SECTION_LABELS: Record<string, string> = {
  apps: "Apps",
  alert_definitions: "Alert Definitions",
  credential_templates: "Credential Templates",
  snmp_oids: "SNMP OIDs",
  device_templates: "Device Templates",
  device_categories: "Device Categories",
  label_keys: "Label Keys",
  connectors: "Connectors",
  device_types: "Device Types",
  grafana_dashboards: "Grafana Dashboards",
};

const SECTIONS = ["apps", "alert_definitions", "credential_templates", "snmp_oids", "device_templates", "device_categories", "label_keys", "connectors", "device_types", "grafana_dashboards"];

export function PackDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const tz = useTimezone();
  const { data: pack, isLoading } = usePackDetail(id);
  const exportPack = useExportPack();
  const deletePack = useDeletePack();

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["apps", "connectors"]));
  const [tab, setTab] = useState<"contents" | "versions">("contents");

  function toggleSection(section: string) {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(section) ? next.delete(section) : next.add(section);
      return next;
    });
  }

  async function handleExport() {
    if (!pack) return;
    try {
      const res = await exportPack.mutateAsync(pack.id);
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${pack.pack_uid}-v${pack.current_version}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* silent */ }
  }

  async function handleDelete() {
    if (!pack) return;
    try {
      await deletePack.mutateAsync(pack.id);
      navigate("/packs");
    } catch { /* silent */ }
  }

  if (isLoading || !pack) {
    return <div className="flex h-64 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>;
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-zinc-100">{pack.name}</h1>
            <Badge variant="info">{pack.pack_uid}</Badge>
            <Badge variant="default">v{pack.current_version}</Badge>
          </div>
          {pack.description && <p className="mt-1 text-sm text-zinc-400">{pack.description}</p>}
          {pack.author && <p className="mt-0.5 text-xs text-zinc-500">by {pack.author}</p>}
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={handleExport} className="gap-1.5">
            <Download className="h-4 w-4" /> Export
          </Button>
          <Button size="sm" variant="destructive" onClick={() => setDeleteOpen(true)} className="gap-1.5">
            <Trash2 className="h-4 w-4" /> Delete
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-zinc-800">
        <button
          onClick={() => setTab("contents")}
          className={`px-3 py-2 text-sm font-medium transition-colors cursor-pointer ${tab === "contents" ? "text-brand-400 border-b-2 border-brand-400" : "text-zinc-500 hover:text-zinc-300"}`}
        >
          Contents
        </button>
        <button
          onClick={() => setTab("versions")}
          className={`px-3 py-2 text-sm font-medium transition-colors cursor-pointer ${tab === "versions" ? "text-brand-400 border-b-2 border-brand-400" : "text-zinc-500 hover:text-zinc-300"}`}
        >
          Version History
        </button>
      </div>

      {/* Contents tab */}
      {tab === "contents" && (
        <Card>
          <CardContent className="pt-6 space-y-1">
            {SECTIONS.map(section => {
              const count = pack.entity_counts[section] ?? 0;
              const isOpen = expanded.has(section);
              const manifest = pack.versions?.[0]?.manifest?.[section] ?? [];

              return (
                <div key={section}>
                  <button
                    onClick={() => toggleSection(section)}
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800 transition-colors cursor-pointer"
                  >
                    {isOpen ? <ChevronDown className="h-4 w-4 text-zinc-500" /> : <ChevronRight className="h-4 w-4 text-zinc-500" />}
                    <span className="font-medium">{SECTION_LABELS[section]}</span>
                    <Badge variant="info" className="ml-auto">{count}</Badge>
                  </button>
                  {isOpen && count > 0 && (
                    <div className="ml-8 mb-2">
                      {manifest.map((name: string) => (
                        <div key={name} className="py-0.5 text-sm text-zinc-400">{name}</div>
                      ))}
                      {manifest.length === 0 && <div className="py-0.5 text-xs text-zinc-600">{count} entities (no manifest details)</div>}
                    </div>
                  )}
                  {isOpen && count === 0 && (
                    <div className="ml-8 mb-2 py-0.5 text-xs text-zinc-600">None</div>
                  )}
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* Versions tab */}
      {tab === "versions" && (
        <Card>
          <CardContent className="pt-6">
            {!pack.versions || pack.versions.length === 0 ? (
              <p className="text-sm text-zinc-500">No version history.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Version</TableHead>
                    <TableHead>Changelog</TableHead>
                    <TableHead>Imported</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pack.versions.map(v => (
                    <TableRow key={v.id}>
                      <TableCell><Badge variant="default">v{v.version}</Badge></TableCell>
                      <TableCell className="text-zinc-400 max-w-[400px] truncate">{v.changelog ?? "—"}</TableCell>
                      <TableCell className="text-zinc-500">{formatDate(v.imported_at, tz)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Delete Dialog */}
      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)} title="Delete Pack">
        <p className="text-sm text-zinc-400">
          Delete pack <span className="font-semibold text-zinc-200">{pack.name}</span>?
        </p>
        <p className="mt-1 text-xs text-zinc-500">Entities created by this pack will NOT be deleted.</p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteOpen(false)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deletePack.isPending}>
            {deletePack.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
