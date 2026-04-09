import { useState } from "react";
import {
  Search,
  Loader2,
  Download,
  CheckCircle2,
  AlertTriangle,
  Package,
} from "lucide-react";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { useSearchPyPI, useImportFromPyPI } from "@/api/hooks.ts";
import type { WheelUploadResult, MissingDependency } from "@/types/api.ts";

interface PyPIImportDialogProps {
  open: boolean;
  onClose: () => void;
}

export function PyPIImportDialog({ open, onClose }: PyPIImportDialogProps) {
  const [query, setQuery] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const { data: searchResults, isLoading: searching } =
    useSearchPyPI(searchQuery);
  const importPyPI = useImportFromPyPI();

  const [importResult, setImportResult] = useState<WheelUploadResult | null>(
    null,
  );
  const [importError, setImportError] = useState<string | null>(null);

  function handleClose() {
    setQuery("");
    setSearchQuery("");
    setImportResult(null);
    setImportError(null);
    onClose();
  }

  function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (query.trim().length >= 2) {
      setSearchQuery(query.trim());
      setImportResult(null);
      setImportError(null);
    }
  }

  async function handleImport(packageName: string) {
    setImportError(null);
    setImportResult(null);
    try {
      const res = await importPyPI.mutateAsync({ package_name: packageName });
      setImportResult(res.data);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Import failed");
    }
  }

  const missingDeps: MissingDependency[] =
    importResult?.missing_dependencies ?? [];

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Import from PyPI"
      size="lg"
    >
      <div className="space-y-4">
        {!importResult ? (
          <>
            <form onSubmit={handleSearch} className="flex gap-2">
              <Input
                placeholder="Search PyPI packages..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
                className="flex-1"
              />
              <Button
                type="submit"
                disabled={query.trim().length < 2 || searching}
                className="gap-1.5"
              >
                {searching ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
                Search
              </Button>
            </form>

            {searchResults && searchResults.length > 0 ? (
              <div className="max-h-80 overflow-y-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Package</TableHead>
                      <TableHead>Summary</TableHead>
                      <TableHead>Version</TableHead>
                      <TableHead className="w-24"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {searchResults.map((r) => (
                      <TableRow key={r.name}>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm text-zinc-200">
                              {r.name}
                            </span>
                            {r.registered && (
                              <Badge variant="info" className="text-[10px]">
                                Registered
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-zinc-400 max-w-[250px] truncate">
                          {r.summary ?? (
                            <span className="text-zinc-600 italic">--</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <span className="font-mono text-xs text-zinc-300">
                            {r.latest_version}
                          </span>
                        </TableCell>
                        <TableCell>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => handleImport(r.name)}
                            disabled={importPyPI.isPending}
                            className="gap-1"
                          >
                            <Download className="h-3.5 w-3.5" />
                            Import
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : searchResults && searchResults.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
                <Package className="mb-2 h-6 w-6 text-zinc-600" />
                <p className="text-sm">No packages found for "{searchQuery}"</p>
              </div>
            ) : null}

            {importError && (
              <p className="text-sm text-red-400">{importError}</p>
            )}

            <DialogFooter>
              <Button variant="secondary" onClick={handleClose}>
                Cancel
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2 rounded-md bg-emerald-950/30 border border-emerald-800 px-3 py-3">
              <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0" />
              <div>
                <p className="text-sm font-medium text-emerald-400">
                  Successfully imported {importResult.module_name}{" "}
                  {importResult.version}
                </p>
                <p className="text-xs text-zinc-400 mt-0.5">
                  {importResult.wheel_filename}
                </p>
              </div>
            </div>

            {missingDeps.length > 0 && (
              <div className="rounded-md border border-amber-500/20 bg-amber-500/5 p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-400" />
                  <span className="text-sm font-medium text-amber-400">
                    Missing Dependencies
                  </span>
                </div>
                <div className="space-y-1">
                  {missingDeps.map((d) => (
                    <div
                      key={d.name}
                      className="flex items-center justify-between text-xs"
                    >
                      <span className="font-mono text-zinc-300">{d.name}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-zinc-500">{d.version_spec}</span>
                        {d.registered ? (
                          <Badge variant="info" className="text-[10px]">
                            Registered
                          </Badge>
                        ) : (
                          <Badge variant="warning" className="text-[10px]">
                            Not in registry
                          </Badge>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <DialogFooter>
              <Button
                variant="secondary"
                onClick={() => {
                  setImportResult(null);
                  setImportError(null);
                }}
              >
                Import Another
              </Button>
              <Button onClick={handleClose}>Done</Button>
            </DialogFooter>
          </>
        )}
      </div>
    </Dialog>
  );
}
