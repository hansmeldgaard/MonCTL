import React, { useState } from "react";
import { KeyRound, Loader2, Pencil, Plus, Settings2, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Label } from "@/components/ui/label.tsx";
import { Select } from "@/components/ui/select.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Tabs, TabsList, TabTrigger, TabsContent } from "@/components/ui/tabs.tsx";
import {
  useCredentials,
  useCredentialKeys,
  useCredentialDetail,
  useCreateCredential,
  useUpdateCredential,
  useDeleteCredential,
  useCreateCredentialKey,
  useUpdateCredentialKey,
  useDeleteCredentialKey,
} from "@/api/hooks.ts";
import type { Credential, CredentialKey } from "@/types/api.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";

// ── Credential Keys Section ──────────────────────────────

function CredentialKeysCard() {
  const { data: keys, isLoading } = useCredentialKeys();
  const createKey = useCreateCredentialKey();
  const updateKey = useUpdateCredentialKey();
  const deleteKey = useDeleteCredentialKey();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addSecret, setAddSecret] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<CredentialKey | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editSecret, setEditSecret] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<CredentialKey | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    try {
      await createKey.mutateAsync({ name: addName.trim(), description: addDesc.trim() || undefined, is_secret: addSecret });
      setAddName(""); setAddDesc(""); setAddSecret(false); setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create key");
    }
  }

  function openEdit(k: CredentialKey) {
    setEditTarget(k);
    setEditName(k.name);
    setEditDesc(k.description ?? "");
    setEditSecret(k.is_secret);
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    try {
      await updateKey.mutateAsync({
        id: editTarget.id,
        data: { name: editName.trim(), description: editDesc.trim() || undefined, is_secret: editSecret },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update key");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try { await deleteKey.mutateAsync(deleteTarget.id); setDeleteTarget(null); } catch { /* silent */ }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Credential Keys
            <Badge variant="default" className="ml-auto">{keys?.length ?? 0}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-zinc-500" /></div>
          ) : !keys || keys.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-zinc-500">
              <Settings2 className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No credential keys defined</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Secret</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {keys.map((k) => (
                  <TableRow key={k.id}>
                    <TableCell className="font-medium font-mono text-sm text-zinc-100">{k.name}</TableCell>
                    <TableCell className="text-zinc-400 text-sm">{k.description ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant={k.is_secret ? "destructive" : "default"}>
                        {k.is_secret ? "secret" : "plain"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <button onClick={() => openEdit(k)} className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer" title="Edit">
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button onClick={() => setDeleteTarget(k)} className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer" title="Delete">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <div className="mt-4 flex justify-end border-t border-zinc-800 pt-4">
            <Button size="sm" variant="secondary" onClick={() => { setAddName(""); setAddDesc(""); setAddSecret(false); setAddError(null); setAddOpen(true); }} className="gap-1.5">
              <Plus className="h-4 w-4" /> New Key
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Add Key Dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="New Credential Key">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ck-name">Name</Label>
            <Input id="ck-name" placeholder="e.g. api_key" value={addName} onChange={(e) => setAddName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ck-desc">Description <span className="font-normal text-zinc-500">(optional)</span></Label>
            <Input id="ck-desc" placeholder="What this key stores" value={addDesc} onChange={(e) => setAddDesc(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={addSecret} onChange={(e) => setAddSecret(e.target.checked)} className="rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500" />
            <span className="text-sm text-zinc-300">Secret value (encrypted at rest)</span>
          </label>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createKey.isPending}>{createKey.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Create</Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Key Dialog */}
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title="Edit Credential Key">
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ck-edit-name">Name</Label>
            <Input id="ck-edit-name" value={editName} onChange={(e) => setEditName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ck-edit-desc">Description</Label>
            <Input id="ck-edit-desc" value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={editSecret} onChange={(e) => setEditSecret(e.target.checked)} className="rounded border-zinc-600 bg-zinc-800 text-brand-500 focus:ring-brand-500" />
            <span className="text-sm text-zinc-300">Secret value</span>
          </label>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditTarget(null)}>Cancel</Button>
            <Button type="submit" disabled={updateKey.isPending}>{updateKey.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save</Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Key Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete Credential Key">
        <p className="text-sm text-zinc-400">Delete key <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?</p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteKey.isPending}>{deleteKey.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Delete</Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Credential Detail Row ─────────────────────────────────

function CredentialDetailRow({ credentialId }: { credentialId: string }) {
  const { data: detail, isLoading } = useCredentialDetail(credentialId);
  if (isLoading) return <div className="py-2"><Loader2 className="h-4 w-4 animate-spin text-zinc-500" /></div>;
  if (!detail?.values?.length) return <p className="text-xs text-zinc-500 py-2">No keys configured.</p>;
  return (
    <div className="py-2 space-y-1">
      <p className="text-xs font-medium text-zinc-400 mb-1">Credential Keys:</p>
      <div className="flex flex-wrap gap-1.5">
        {detail.values.map((v) => (
          <Badge key={v.key_name} variant={v.is_secret ? "destructive" : "default"} className="text-xs">
            {v.key_name}{v.is_secret ? " (secret)" : ""}
          </Badge>
        ))}
      </div>
    </div>
  );
}

// ── Credentials Section ──────────────────────────────────

function CredentialsCard() {
  const tz = useTimezone();
  const { data: credentials, isLoading } = useCredentials();
  const { data: credentialKeys } = useCredentialKeys();
  const createCredential = useCreateCredential();
  const updateCredential = useUpdateCredential();
  const deleteCredential = useDeleteCredential();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addType, setAddType] = useState("snmp_community");
  const [addValues, setAddValues] = useState<Record<string, string>>({});
  const [addError, setAddError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<Credential | null>(null);
  const [editDesc, setEditDesc] = useState("");
  const [editType, setEditType] = useState("");
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) { setAddError("Name is required."); return; }
    try {
      await createCredential.mutateAsync({
        name: addName.trim(),
        description: addDesc.trim() || undefined,
        credential_type: addType,
        secret: addValues,
      });
      setAddName(""); setAddDesc(""); setAddType("snmp_community"); setAddValues({}); setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create credential");
    }
  }

  function openEdit(c: Credential) {
    setEditTarget(c);
    setEditDesc(c.description || "");
    setEditType(c.credential_type);
    setEditValues({});
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    try {
      const data: { description?: string; credential_type?: string; secret?: Record<string, unknown> } = {
        description: editDesc.trim(),
        credential_type: editType,
      };
      if (Object.keys(editValues).length > 0) {
        data.secret = editValues;
      }
      await updateCredential.mutateAsync({ id: editTarget.id, data });
      setEditTarget(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update credential");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try { await deleteCredential.mutateAsync(deleteTarget.id); setDeleteTarget(null); } catch { /* silent */ }
  }

  function handleAddKeyValue(keyName: string) {
    setAddValues((prev) => ({ ...prev, [keyName]: "" }));
  }

  function handleRemoveAddValue(keyName: string) {
    setAddValues((prev) => {
      const next = { ...prev };
      delete next[keyName];
      return next;
    });
  }

  const availableKeys = (credentialKeys ?? []).filter((k) => !(k.name in addValues));
  const availableEditKeys = (credentialKeys ?? []).filter((k) => !(k.name in editValues));

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" />
            Credentials
            <Badge variant="default" className="ml-auto">{credentials?.length ?? 0}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-zinc-500" /></div>
          ) : !credentials || credentials.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-zinc-500">
              <KeyRound className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No credentials stored</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {credentials.map((cred) => (
                  <React.Fragment key={cred.id}>
                    <TableRow className="cursor-pointer" onClick={() => setExpandedId(expandedId === cred.id ? null : cred.id)}>
                      <TableCell className="font-medium text-zinc-100">{cred.name}</TableCell>
                      <TableCell className="max-w-[300px] truncate text-zinc-400">{cred.description || "—"}</TableCell>
                      <TableCell><Badge variant="info">{cred.credential_type}</Badge></TableCell>
                      <TableCell className="text-zinc-500">{formatDate(cred.created_at, tz)}</TableCell>
                      <TableCell className="text-zinc-500">{formatDate(cred.updated_at, tz)}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <button onClick={(e) => { e.stopPropagation(); openEdit(cred); }} className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer" title="Edit">
                            <Pencil className="h-4 w-4" />
                          </button>
                          <button onClick={(e) => { e.stopPropagation(); setDeleteTarget(cred); }} className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer" title="Delete">
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </TableCell>
                    </TableRow>
                    {expandedId === cred.id && (
                      <TableRow>
                        <TableCell colSpan={6}>
                          <CredentialDetailRow credentialId={cred.id} />
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                ))}
              </TableBody>
            </Table>
          )}
          <div className="mt-4 flex justify-end border-t border-zinc-800 pt-4">
            <Button size="sm" variant="secondary" onClick={() => { setAddName(""); setAddDesc(""); setAddType("snmp_community"); setAddValues({}); setAddError(null); setAddOpen(true); }} className="gap-1.5">
              <Plus className="h-4 w-4" /> New Credential
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Add Credential Dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="New Credential">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="cr-name">Name</Label>
              <Input id="cr-name" placeholder="e.g. snmp-prod" value={addName} onChange={(e) => setAddName(e.target.value)} autoFocus />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cr-type">Type</Label>
              <Input id="cr-type" placeholder="e.g. snmp_community" value={addType} onChange={(e) => setAddType(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cr-desc">Description <span className="font-normal text-zinc-500">(optional)</span></Label>
            <Input id="cr-desc" value={addDesc} onChange={(e) => setAddDesc(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Secret Values</Label>
            {Object.entries(addValues).map(([key, val]) => {
              const keyDef = (credentialKeys ?? []).find((k) => k.name === key);
              return (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-xs font-mono text-zinc-400 w-24 shrink-0">{key}</span>
                  <Input
                    type={keyDef?.is_secret ? "password" : "text"}
                    value={val}
                    onChange={(e) => setAddValues((prev) => ({ ...prev, [key]: e.target.value }))}
                    placeholder={keyDef?.is_secret ? "••••••" : "value"}
                    className="flex-1 text-xs"
                  />
                  <button type="button" onClick={() => handleRemoveAddValue(key)} className="rounded p-1 text-zinc-600 hover:text-red-400 cursor-pointer">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
            {availableKeys.length > 0 && (
              <Select onChange={(e) => { if (e.target.value) { handleAddKeyValue(e.target.value); e.target.value = ""; } }}>
                <option value="">+ Add field...</option>
                {availableKeys.map((k) => (
                  <option key={k.id} value={k.name}>{k.name}{k.is_secret ? " (secret)" : ""}</option>
                ))}
              </Select>
            )}
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createCredential.isPending}>{createCredential.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Create</Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Credential Dialog */}
      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title={`Edit: ${editTarget?.name ?? ""}`}>
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="cr-edit-desc">Description</Label>
            <Input id="cr-edit-desc" value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cr-edit-type">Type</Label>
            <Input id="cr-edit-type" value={editType} onChange={(e) => setEditType(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Update Secret Values <span className="font-normal text-zinc-500">(leave empty to keep existing)</span></Label>
            {Object.entries(editValues).map(([key, val]) => {
              const keyDef = (credentialKeys ?? []).find((k) => k.name === key);
              return (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-xs font-mono text-zinc-400 w-24 shrink-0">{key}</span>
                  <Input
                    type={keyDef?.is_secret ? "password" : "text"}
                    value={val}
                    onChange={(e) => setEditValues((prev) => ({ ...prev, [key]: e.target.value }))}
                    className="flex-1 text-xs"
                  />
                  <button type="button" onClick={() => { setEditValues((prev) => { const n = { ...prev }; delete n[key]; return n; }); }} className="rounded p-1 text-zinc-600 hover:text-red-400 cursor-pointer">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
            {availableEditKeys.length > 0 && (
              <Select onChange={(e) => { if (e.target.value) { setEditValues((prev) => ({ ...prev, [e.target.value]: "" })); e.target.value = ""; } }}>
                <option value="">+ Add field...</option>
                {availableEditKeys.map((k) => (
                  <option key={k.id} value={k.name}>{k.name}</option>
                ))}
              </Select>
            )}
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setEditTarget(null)}>Cancel</Button>
            <Button type="submit" disabled={updateCredential.isPending}>{updateCredential.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save</Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Credential Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete Credential">
        <p className="text-sm text-zinc-400">
          Delete credential <span className="font-semibold text-zinc-200">{deleteTarget?.name}</span>?
          App assignments referencing this credential will stop working.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteCredential.isPending}>
            {deleteCredential.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Main Page ────────────────────────────────────────────

export function CredentialsPage() {
  const [tab, setTab] = useState("credentials");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Credentials</h1>
        <p className="text-sm text-zinc-500">
          Manage credential keys and encrypted credentials.
        </p>
      </div>
      <Tabs value={tab} onChange={setTab}>
        <TabsList>
          <TabTrigger value="credentials">Credentials</TabTrigger>
          <TabTrigger value="credential-keys">Credential Keys</TabTrigger>
        </TabsList>
        <TabsContent value="credentials">
          <CredentialsCard />
        </TabsContent>
        <TabsContent value="credential-keys">
          <CredentialKeysCard />
        </TabsContent>
      </Tabs>
    </div>
  );
}
