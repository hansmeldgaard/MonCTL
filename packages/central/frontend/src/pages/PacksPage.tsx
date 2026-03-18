import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Boxes, Download, Loader2, Trash2, Upload } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  usePacks,
  useExportPack,
  useDeletePack,
  usePreviewImport,
  useImportPack,
} from "@/api/hooks.ts";
import type { Pack, PackImportPreviewEntity } from "@/types/api.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

const SECTION_LABELS: Record<string, string> = {
  apps: "Apps",
  alert_rules: "Alert Rules",
  credential_templates: "Credential Templates",
  snmp_oids: "SNMP OIDs",
  device_templates: "Device Templates",
  device_types: "Device Types",
  label_keys: "Label Keys",
  connectors: "Connectors",
};

export function PacksPage() {
  const tz = useTimezone();
  const navigate = useNavigate();
  const { data: packs, isLoading } = usePacks();
  const exportPack = useExportPack();
  const deletePack = useDeletePack();
  const previewImport = usePreviewImport();
  const importPack = useImportPack();

  const [deleteTarget, setDeleteTarget] = useState<Pack | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importData, setImportData] = useState<Record<string, unknown> | null>(null);
  const [importPreview, setImportPreview] = useState<{
    entities: PackImportPreviewEntity[];
    pack_uid: string;
    name: string;
    version: string;
    is_upgrade: boolean;
    current_version?: string;
  } | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, string>>({});
  const [importResult, setImportResult] = useState<{ created: number; updated: number; skipped: number } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function totalEntities(p: Pack): number {
    return Object.values(p.entity_counts).reduce((a, b) => a + b, 0);
  }

  async function handleExport(p: Pack) {
    try {
      const res = await exportPack.mutateAsync(p.id);
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${p.pack_uid}-v${p.current_version}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* silent */ }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try { await deletePack.mutateAsync(deleteTarget.id); setDeleteTarget(null); } catch { /* silent */ }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      setImportData(data);
      setImportError(null);
      setImportResult(null);
      const res = await previewImport.mutateAsync(data);
      setImportPreview(res.data);
      const defaultResolutions: Record<string, string> = {};
      for (const entity of res.data.entities) {
        if (entity.status === "conflict") {
          defaultResolutions[`${entity.section}:${entity.name}`] = "skip";
        }
      }
      setResolutions(defaultResolutions);
      setImportOpen(true);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Invalid JSON file");
      setImportOpen(true);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleImport() {
    if (!importData) return;
    try {
      const res = await importPack.mutateAsync({
        pack_data: importData,
        resolutions,
      });
      setImportResult(res.data);
      setImportPreview(null);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Import failed");
    }
  }

  function closeImport() {
    setImportOpen(false);
    setImportData(null);
    setImportPreview(null);
    setImportResult(null);
    setImportError(null);
    setResolutions({});
  }

  if (isLoading) {
    return <div className="flex h-64 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Packs</h1>
          <p className="text-sm text-zinc-500">Import, export, and manage monitoring configuration bundles.</p>
        </div>
        <div className="flex gap-2">
          <input ref={fileInputRef} type="file" accept=".json" className="hidden" onChange={handleFileUpload} />
          <Button size="sm" variant="secondary" onClick={() => fileInputRef.current?.click()} className="gap-1.5">
            <Upload className="h-4 w-4" /> Import
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          {!packs || packs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-zinc-500">
              <Boxes className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No packs installed</p>
              <p className="mt-1 text-xs text-zinc-600">Import a pack JSON file to get started.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>UID</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Author</TableHead>
                  <TableHead>Entities</TableHead>
                  <TableHead>Installed</TableHead>
                  <TableHead className="w-24"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {packs.map((p) => (
                  <TableRow key={p.id} className="cursor-pointer" onClick={() => navigate(`/packs/${p.id}`)}>
                    <TableCell className="font-medium text-zinc-100">{p.name}</TableCell>
                    <TableCell><Badge variant="info">{p.pack_uid}</Badge></TableCell>
                    <TableCell><Badge variant="default">v{p.current_version}</Badge></TableCell>
                    <TableCell className="text-zinc-400">{p.author ?? "—"}</TableCell>
                    <TableCell className="text-zinc-400">{totalEntities(p)}</TableCell>
                    <TableCell className="text-zinc-500">{formatDate(p.installed_at, tz)}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                        <button onClick={() => handleExport(p)} className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer" title="Export">
                          <Download className="h-4 w-4" />
                        </button>
                        <button onClick={() => setDeleteTarget(p)} className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer" title="Delete">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Delete Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete Pack">
        <p className="text-sm text-zinc-400">
          Delete pack <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?
        </p>
        <p className="mt-1 text-xs text-zinc-500">Entities created by this pack will NOT be deleted.</p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deletePack.isPending}>
            {deletePack.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Delete
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Import Dialog */}
      <Dialog open={importOpen} onClose={closeImport} title={importResult ? "Import Complete" : importPreview ? `Import: ${importPreview.name}` : "Import Pack"}>
        {importError && !importPreview && (
          <div>
            <p className="text-sm text-red-400">{importError}</p>
            <DialogFooter>
              <Button variant="secondary" onClick={closeImport}>Close</Button>
            </DialogFooter>
          </div>
        )}

        {importResult && (
          <div>
            <p className="text-sm text-zinc-300">
              Created <span className="font-semibold text-green-400">{importResult.created}</span>,
              updated <span className="font-semibold text-amber-400">{importResult.updated}</span>,
              skipped <span className="font-semibold text-zinc-400">{importResult.skipped}</span>.
            </p>
            <DialogFooter>
              <Button onClick={closeImport}>Done</Button>
            </DialogFooter>
          </div>
        )}

        {importPreview && !importResult && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-zinc-400">
              <Badge variant="info">{importPreview.pack_uid}</Badge>
              <Badge variant="default">v{importPreview.version}</Badge>
              {importPreview.is_upgrade && <Badge variant="default" className="bg-amber-600">Upgrade from v{importPreview.current_version}</Badge>}
            </div>

            <div className="max-h-80 overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Entity</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {importPreview.entities.map((entity) => {
                    const key = `${entity.section}:${entity.name}`;
                    return (
                      <TableRow key={key}>
                        <TableCell className="font-medium text-zinc-100">{entity.name}</TableCell>
                        <TableCell className="text-zinc-400">{SECTION_LABELS[entity.section] ?? entity.section}</TableCell>
                        <TableCell>
                          {entity.status === "new" && <Badge className="bg-green-600">New</Badge>}
                          {entity.status === "conflict" && <Badge className="bg-amber-600">Conflict</Badge>}
                          {entity.status === "unchanged" && <Badge variant="info">Unchanged</Badge>}
                        </TableCell>
                        <TableCell>
                          {entity.status === "conflict" ? (
                            <select
                              className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-200"
                              value={resolutions[key] ?? "skip"}
                              onChange={(e) => setResolutions(prev => ({ ...prev, [key]: e.target.value }))}
                            >
                              <option value="skip">Skip</option>
                              <option value="overwrite">Overwrite</option>
                              <option value="rename">Rename</option>
                            </select>
                          ) : entity.status === "new" ? (
                            <span className="text-xs text-green-400">Will create</span>
                          ) : (
                            <span className="text-xs text-zinc-500">Will skip</span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            {importError && <p className="text-sm text-red-400">{importError}</p>}

            <DialogFooter>
              <Button variant="secondary" onClick={closeImport}>Cancel</Button>
              <Button onClick={handleImport} disabled={importPack.isPending}>
                {importPack.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Import
              </Button>
            </DialogFooter>
          </div>
        )}

        {previewImport.isPending && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            <span className="ml-2 text-sm text-zinc-400">Analyzing pack...</span>
          </div>
        )}
      </Dialog>
    </div>
  );
}
