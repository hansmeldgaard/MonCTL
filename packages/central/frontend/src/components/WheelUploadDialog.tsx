import { useState, useRef, useCallback } from "react";
import { Upload, X, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { useUploadWheelsBatch } from "@/api/hooks.ts";
import type { WheelUploadResult, MissingDependency } from "@/types/api.ts";

interface WheelUploadDialogProps {
  open: boolean;
  onClose: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function WheelUploadDialog({ open, onClose }: WheelUploadDialogProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [results, setResults] = useState<WheelUploadResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadBatch = useUploadWheelsBatch();

  function handleClose() {
    setFiles([]);
    setResults(null);
    setError(null);
    setDragOver(false);
    onClose();
  }

  function addFiles(newFiles: FileList | File[]) {
    const whlFiles = Array.from(newFiles).filter((f) =>
      f.name.endsWith(".whl"),
    );
    if (whlFiles.length === 0) return;
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => f.name));
      return [...prev, ...whlFiles.filter((f) => !existing.has(f.name))];
    });
  }

  function removeFile(name: string) {
    setFiles((prev) => prev.filter((f) => f.name !== name));
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files) addFiles(e.dataTransfer.files);
  }, []);

  async function handleUpload() {
    if (files.length === 0) return;
    setError(null);
    setResults(null);
    try {
      const res = await uploadBatch.mutateAsync(files);
      setResults(res.data);
      setFiles([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    }
  }

  const allMissing: MissingDependency[] = results
    ? results.flatMap((r) => r.missing_dependencies ?? [])
    : [];
  const uniqueMissing = allMissing.filter(
    (d, i, arr) => arr.findIndex((x) => x.name === d.name) === i,
  );

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Upload Wheel Files"
      size="lg"
    >
      <div className="space-y-4">
        {!results ? (
          <>
            {/* Drop zone */}
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 cursor-pointer transition-colors ${
                dragOver
                  ? "border-brand-500 bg-brand-500/5"
                  : "border-zinc-700 hover:border-zinc-500 bg-zinc-800/30"
              }`}
            >
              <Upload className="h-8 w-8 text-zinc-500 mb-2" />
              <p className="text-sm text-zinc-400">
                Drop <code className="text-zinc-300">.whl</code> files here or
                click to browse
              </p>
              <p className="text-xs text-zinc-600 mt-1">
                Multiple files supported
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".whl"
                multiple
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) addFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>

            {/* File list */}
            {files.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-zinc-400">
                  {files.length} file{files.length !== 1 ? "s" : ""} selected
                </p>
                <div className="max-h-48 overflow-y-auto space-y-1">
                  {files.map((f) => (
                    <div
                      key={f.name}
                      className="flex items-center justify-between rounded-md bg-zinc-800/50 px-3 py-2"
                    >
                      <span className="text-sm font-mono text-zinc-200 truncate mr-2">
                        {f.name}
                      </span>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-xs text-zinc-500">
                          {formatBytes(f.size)}
                        </span>
                        <button
                          onClick={() => removeFile(f.name)}
                          className="rounded p-0.5 text-zinc-600 hover:text-red-400 transition-colors cursor-pointer"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {error && <p className="text-sm text-red-400">{error}</p>}

            <DialogFooter>
              <Button variant="secondary" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                onClick={handleUpload}
                disabled={files.length === 0 || uploadBatch.isPending}
              >
                {uploadBatch.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                Upload {files.length > 0 ? `(${files.length})` : ""}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            {/* Results */}
            <div className="space-y-2">
              {results.map((r, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 rounded-md bg-zinc-800/50 px-3 py-2"
                >
                  <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <span className="text-sm font-medium text-zinc-200">
                      {r.module_name}
                    </span>
                    <span className="text-xs text-zinc-500 ml-2">
                      {r.version} -- {r.wheel_filename}
                    </span>
                  </div>
                  <span className="text-xs text-zinc-500 shrink-0">
                    {formatBytes(r.file_size)}
                  </span>
                </div>
              ))}
            </div>

            {/* Missing dependencies */}
            {uniqueMissing.length > 0 && (
              <div className="rounded-md border border-amber-500/20 bg-amber-500/5 p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-400" />
                  <span className="text-sm font-medium text-amber-400">
                    Missing Dependencies
                  </span>
                </div>
                <div className="space-y-1">
                  {uniqueMissing.map((d) => (
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
              <Button onClick={handleClose}>Done</Button>
            </DialogFooter>
          </>
        )}
      </div>
    </Dialog>
  );
}
