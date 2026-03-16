import { useState } from "react";
import { Loader2, Plus, Pencil, Trash2, Tag, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import {
  useLabelKeys,
  useCreateLabelKey,
  useUpdateLabelKey,
  useDeleteLabelKey,
} from "@/api/hooks.ts";
import type { LabelKey } from "@/types/api.ts";

function TagInput({ values, onChange }: { values: string[]; onChange: (v: string[]) => void }) {
  const [input, setInput] = useState("");

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      const val = input.trim();
      if (val && !values.includes(val)) {
        onChange([...values, val]);
      }
      setInput("");
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {values.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 rounded-md bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300"
          >
            {v}
            <button
              type="button"
              onClick={() => onChange(values.filter((x) => x !== v))}
              className="text-zinc-500 hover:text-red-400 cursor-pointer"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      <Input
        placeholder="Type value and press Enter"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        className="text-xs"
      />
    </div>
  );
}

export function LabelKeysPage() {
  const { data: labelKeys, isLoading } = useLabelKeys();
  const createLabelKey = useCreateLabelKey();
  const updateLabelKey = useUpdateLabelKey();
  const deleteLabelKey = useDeleteLabelKey();

  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<LabelKey | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LabelKey | null>(null);

  // Create form
  const [newKey, setNewKey] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newColor, setNewColor] = useState("");
  const [newShowDesc, setNewShowDesc] = useState(false);
  const [newValues, setNewValues] = useState<string[]>([]);
  const [createError, setCreateError] = useState<string | null>(null);

  // Edit form
  const [editDesc, setEditDesc] = useState("");
  const [editColor, setEditColor] = useState("");
  const [editShowDesc, setEditShowDesc] = useState(false);
  const [editValues, setEditValues] = useState<string[]>([]);

  function openCreate() {
    setNewKey("");
    setNewDesc("");
    setNewColor("");
    setNewShowDesc(false);
    setNewValues([]);
    setCreateError(null);
    setCreateOpen(true);
  }

  function openEdit(lk: LabelKey) {
    setEditDesc(lk.description ?? "");
    setEditColor(lk.color ?? "");
    setEditShowDesc(lk.show_description);
    setEditValues(lk.predefined_values ?? []);
    setEditTarget(lk);
  }

  async function handleCreate() {
    setCreateError(null);
    try {
      await createLabelKey.mutateAsync({
        key: newKey.trim().toLowerCase(),
        description: newDesc.trim() || undefined,
        color: newColor.trim() || undefined,
        show_description: newShowDesc,
        predefined_values: newValues,
      });
      setCreateOpen(false);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create");
    }
  }

  async function handleUpdate() {
    if (!editTarget) return;
    await updateLabelKey.mutateAsync({
      id: editTarget.id,
      data: {
        description: editDesc.trim() || undefined,
        color: editColor.trim() || undefined,
        show_description: editShowDesc,
        predefined_values: editValues,
      },
    });
    setEditTarget(null);
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    await deleteLabelKey.mutateAsync(deleteTarget.id);
    setDeleteTarget(null);
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Tag className="h-4 w-4" />
            Label Keys
            <Button size="sm" className="ml-auto gap-1.5" onClick={openCreate}>
              <Plus className="h-3.5 w-3.5" />
              Add Label Key
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!labelKeys || labelKeys.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-zinc-500">
              <Tag className="mb-2 h-6 w-6 text-zinc-600" />
              <p className="text-sm">No label keys defined yet.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-left text-xs text-zinc-500">
                    <th className="pb-2 pr-4 font-medium">Key</th>
                    <th className="pb-2 pr-4 font-medium">Display Name</th>
                    <th className="pb-2 pr-4 font-medium">Predefined Values</th>
                    <th className="pb-2 pr-4 font-medium">Color</th>
                    <th className="pb-2 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/50">
                  {labelKeys.map((lk) => (
                    <tr key={lk.id} className="text-zinc-300">
                      <td className="py-2.5 pr-4 font-mono text-xs">{lk.key}</td>
                      <td className="py-2.5 pr-4 text-xs">
                        {lk.show_description && lk.description ? (
                          <span>{lk.description}</span>
                        ) : (
                          <span className="text-zinc-600">—</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-4">
                        <div className="flex flex-wrap gap-1">
                          {(lk.predefined_values ?? []).slice(0, 5).map((v) => (
                            <Badge key={v} variant="default" className="text-[10px]">{v}</Badge>
                          ))}
                          {(lk.predefined_values ?? []).length > 5 && (
                            <span className="text-[10px] text-zinc-500">
                              +{lk.predefined_values.length - 5}
                            </span>
                          )}
                          {(lk.predefined_values ?? []).length === 0 && (
                            <span className="text-zinc-600 text-xs">—</span>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 pr-4">
                        {lk.color ? (
                          <span className="inline-flex items-center gap-1.5 text-xs">
                            <span
                              className="h-3 w-3 rounded-full border border-zinc-700"
                              style={{ backgroundColor: lk.color }}
                            />
                            {lk.color}
                          </span>
                        ) : (
                          <span className="text-zinc-600 text-xs">—</span>
                        )}
                      </td>
                      <td className="py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => openEdit(lk)}>
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setDeleteTarget(lk)}>
                            <Trash2 className="h-3.5 w-3.5 text-red-400" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Dialog */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="Add Label Key">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Key</Label>
            <Input
              placeholder="e.g. site, env, role"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              className="font-mono text-xs"
              autoFocus
            />
            <p className="text-[10px] text-zinc-500">Lowercase, a-z, 0-9, hyphens, underscores.</p>
          </div>
          <div className="space-y-1.5">
            <Label>Description</Label>
            <Input
              placeholder="e.g. Lokation, Miljø"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              className="text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={newShowDesc}
                onChange={(e) => setNewShowDesc(e.target.checked)}
                disabled={!newDesc.trim()}
                className="rounded border-zinc-700"
              />
              <span className={!newDesc.trim() ? "text-zinc-600" : "text-zinc-300"}>
                Show description instead of key
              </span>
            </label>
            <p className="text-[10px] text-zinc-500 ml-6">
              {newDesc.trim()
                ? `When enabled, labels display "${newDesc.trim()}: xyz" instead of "${newKey.trim().toLowerCase() || "key"}: xyz"`
                : "Add a description first to enable this option"}
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Color</Label>
            <div className="flex items-center gap-2">
              <Input
                placeholder="#3B82F6"
                value={newColor}
                onChange={(e) => setNewColor(e.target.value)}
                className="text-xs flex-1"
              />
              {newColor && (
                <span
                  className="h-6 w-6 rounded-full border border-zinc-700"
                  style={{ backgroundColor: newColor }}
                />
              )}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Predefined Values</Label>
            <TagInput values={newValues} onChange={setNewValues} />
          </div>
          {createError && <p className="text-sm text-red-400">{createError}</p>}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={createLabelKey.isPending}>
              {createLabelKey.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </div>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title={`Edit "${editTarget?.key}"`}>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Key</Label>
            <Input value={editTarget?.key ?? ""} disabled className="font-mono text-xs bg-zinc-900" />
          </div>
          <div className="space-y-1.5">
            <Label>Description</Label>
            <Input
              value={editDesc}
              onChange={(e) => setEditDesc(e.target.value)}
              className="text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={editShowDesc}
                onChange={(e) => setEditShowDesc(e.target.checked)}
                disabled={!editDesc.trim()}
                className="rounded border-zinc-700"
              />
              <span className={!editDesc.trim() ? "text-zinc-600" : "text-zinc-300"}>
                Show description instead of key
              </span>
            </label>
            <p className="text-[10px] text-zinc-500 ml-6">
              {editDesc.trim()
                ? `When enabled, labels display "${editDesc.trim()}: xyz" instead of "${editTarget?.key ?? "key"}: xyz"`
                : "Add a description first to enable this option"}
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Color</Label>
            <div className="flex items-center gap-2">
              <Input
                placeholder="#3B82F6"
                value={editColor}
                onChange={(e) => setEditColor(e.target.value)}
                className="text-xs flex-1"
              />
              {editColor && (
                <span
                  className="h-6 w-6 rounded-full border border-zinc-700"
                  style={{ backgroundColor: editColor }}
                />
              )}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Predefined Values</Label>
            <TagInput values={editValues} onChange={setEditValues} />
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setEditTarget(null)}>Cancel</Button>
            <Button onClick={handleUpdate} disabled={updateLabelKey.isPending}>
              {updateLabelKey.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </div>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete Label Key">
        <p className="text-sm text-zinc-400">
          Are you sure you want to delete the label key <strong className="text-zinc-200">"{deleteTarget?.key}"</strong>?
          This will only remove it from the autocomplete suggestions. Existing labels on devices will not be affected.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteLabelKey.isPending}>
            {deleteLabelKey.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
