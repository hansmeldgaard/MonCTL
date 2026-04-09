import React, { useEffect, useState } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateName, validateShortName } from "@/lib/validation.ts";
import {
  ArrowDown,
  ArrowUp,
  FileText,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  Settings2,
  Trash2,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx";
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
import {
  Tabs,
  TabsList,
  TabTrigger,
  TabsContent,
} from "@/components/ui/tabs.tsx";
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
  useCredentialTemplates,
  useCreateCredentialTemplate,
  useUpdateCredentialTemplate,
  useDeleteCredentialTemplate,
  useCredentialTypes,
  useCreateCredentialType,
  useUpdateCredentialType,
  useDeleteCredentialType,
} from "@/api/hooks.ts";
import type {
  Credential,
  CredentialKey,
  CredentialTemplate,
  CredentialType,
} from "@/types/api.ts";
import { formatDate } from "@/lib/utils.ts";
import { useTimezone } from "@/hooks/useTimezone.ts";
import { usePermissions } from "@/hooks/usePermissions.ts";

// ── Credential Keys Section ──────────────────────────────

const KEY_TYPE_BADGE: Record<
  string,
  { variant: "default" | "destructive" | "info"; label: string }
> = {
  plain: { variant: "default", label: "Plain" },
  secret: { variant: "destructive", label: "Secret" },
  enum: { variant: "info", label: "Enum" },
};

function CredentialKeysCard() {
  const { canEdit, canDelete } = usePermissions();
  const { data: keys, isLoading } = useCredentialKeys();
  const createKey = useCreateCredentialKey();
  const updateKey = useUpdateCredentialKey();
  const deleteKey = useDeleteCredentialKey();

  const [addOpen, setAddOpen] = useState(false);
  const addKeyNameField = useField("", validateShortName);
  const [addDesc, setAddDesc] = useState("");
  const [addKeyType, setAddKeyType] = useState<"plain" | "secret" | "enum">(
    "plain",
  );
  const [addEnumValues, setAddEnumValues] = useState<string[]>([]);
  const [addEnumInput, setAddEnumInput] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<CredentialKey | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editKeyType, setEditKeyType] = useState<"plain" | "secret" | "enum">(
    "plain",
  );
  const [editEnumValues, setEditEnumValues] = useState<string[]>([]);
  const [editEnumInput, setEditEnumInput] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<CredentialKey | null>(null);

  function resetAdd() {
    addKeyNameField.reset();
    setAddDesc("");
    setAddKeyType("plain");
    setAddEnumValues([]);
    setAddEnumInput("");
    setAddError(null);
    setAddOpen(true);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!validateAll(addKeyNameField)) return;
    if (addKeyType === "enum" && addEnumValues.length < 2) {
      setAddError("Enum requires at least 2 values.");
      return;
    }
    try {
      await createKey.mutateAsync({
        name: addKeyNameField.value.trim(),
        description: addDesc.trim() || undefined,
        key_type: addKeyType,
        enum_values: addKeyType === "enum" ? addEnumValues : undefined,
      });
      setAddOpen(false);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to create key");
    }
  }

  function openEdit(k: CredentialKey) {
    setEditTarget(k);
    setEditName(k.name);
    setEditDesc(k.description ?? "");
    setEditKeyType(k.key_type);
    setEditEnumValues(k.enum_values ?? []);
    setEditEnumInput("");
    setEditError(null);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    if (editKeyType === "enum" && editEnumValues.length < 2) {
      setEditError("Enum requires at least 2 values.");
      return;
    }
    try {
      await updateKey.mutateAsync({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          description: editDesc.trim() || undefined,
          key_type: editKeyType,
          enum_values: editKeyType === "enum" ? editEnumValues : undefined,
        },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update key");
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteKey.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      /* silent */
    }
  }

  function addEnumValue(
    values: string[],
    setValues: (v: string[]) => void,
    input: string,
    setInput: (v: string) => void,
  ) {
    const val = input.trim();
    if (!val) return;
    if (values.includes(val)) return;
    setValues([...values, val]);
    setInput("");
  }

  function renderEnumEditor(
    values: string[],
    setValues: (v: string[]) => void,
    input: string,
    setInput: (v: string) => void,
  ) {
    return (
      <div className="space-y-2 rounded border border-zinc-800 p-3">
        <Label className="text-xs text-zinc-400">Enum Values</Label>
        {values.map((v, i) => (
          <div key={i} className="flex items-center gap-2">
            <Input
              value={v}
              onChange={(e) => {
                const next = [...values];
                next[i] = e.target.value;
                setValues(next);
              }}
              className="flex-1 text-xs"
            />
            <button
              type="button"
              onClick={() => setValues(values.filter((_, j) => j !== i))}
              className="rounded p-1 text-zinc-600 hover:text-red-400 cursor-pointer"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addEnumValue(values, setValues, input, setInput);
              }
            }}
            placeholder="Add value..."
            className="flex-1 text-xs"
          />
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => addEnumValue(values, setValues, input, setInput)}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
        {values.length < 2 && (
          <p className="text-xs text-amber-400">Minimum 2 values required</p>
        )}
      </div>
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Credential Keys
            <Badge variant="default" className="ml-auto">
              {keys?.length ?? 0}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
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
                  <TableHead>Type</TableHead>
                  <TableHead>Values</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {keys.map((k) => {
                  const badge =
                    KEY_TYPE_BADGE[k.key_type] ?? KEY_TYPE_BADGE.plain;
                  return (
                    <TableRow key={k.id}>
                      <TableCell className="font-medium font-mono text-sm text-zinc-100">
                        {k.name}
                      </TableCell>
                      <TableCell>
                        <Badge variant={badge.variant}>{badge.label}</Badge>
                      </TableCell>
                      <TableCell className="text-zinc-400 text-sm max-w-[200px] truncate">
                        {k.key_type === "enum" && k.enum_values
                          ? k.enum_values.join(", ")
                          : "—"}
                      </TableCell>
                      <TableCell className="text-zinc-400 text-sm">
                        {k.description ?? "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          {canEdit("credential") && (
                            <button
                              onClick={() => openEdit(k)}
                              className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                              title="Edit"
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                          )}
                          {canDelete("credential") && (
                            <button
                              onClick={() => setDeleteTarget(k)}
                              className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                              title="Delete"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          <div className="mt-4 flex justify-end border-t border-zinc-800 pt-4">
            <Button
              size="sm"
              variant="secondary"
              onClick={resetAdd}
              className="gap-1.5"
            >
              <Plus className="h-4 w-4" /> New Key
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Add Key Dialog */}
      <Dialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="New Credential Key"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ck-name">Name</Label>
            <Input
              id="ck-name"
              placeholder="e.g. api_key"
              value={addKeyNameField.value}
              onChange={addKeyNameField.onChange}
              onBlur={addKeyNameField.onBlur}
              autoFocus
            />
            {addKeyNameField.error && (
              <p className="text-xs text-red-400 mt-0.5">
                {addKeyNameField.error}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ck-desc">
              Description{" "}
              <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="ck-desc"
              placeholder="What this key stores"
              value={addDesc}
              onChange={(e) => setAddDesc(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ck-type">Type</Label>
            <Select
              id="ck-type"
              value={addKeyType}
              onChange={(e) => {
                setAddKeyType(e.target.value as "plain" | "secret" | "enum");
                if (e.target.value !== "enum") setAddEnumValues([]);
              }}
            >
              <option value="plain">Plain — visible text value</option>
              <option value="secret">Secret — masked, encrypted at rest</option>
              <option value="enum">Enum — fixed list of allowed values</option>
            </Select>
          </div>
          {addKeyType === "enum" &&
            renderEnumEditor(
              addEnumValues,
              setAddEnumValues,
              addEnumInput,
              setAddEnumInput,
            )}
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createKey.isPending}>
              {createKey.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}{" "}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Key Dialog */}
      <Dialog
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        title="Edit Credential Key"
      >
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ck-edit-name">Name</Label>
            <Input
              id="ck-edit-name"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ck-edit-desc">Description</Label>
            <Input
              id="ck-edit-desc"
              value={editDesc}
              onChange={(e) => setEditDesc(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ck-edit-type">Type</Label>
            <Select
              id="ck-edit-type"
              value={editKeyType}
              onChange={(e) => {
                setEditKeyType(e.target.value as "plain" | "secret" | "enum");
                if (e.target.value !== "enum") setEditEnumValues([]);
              }}
            >
              <option value="plain">Plain</option>
              <option value="secret">Secret</option>
              <option value="enum">Enum</option>
            </Select>
          </div>
          {editKeyType === "enum" &&
            renderEnumEditor(
              editEnumValues,
              setEditEnumValues,
              editEnumInput,
              setEditEnumInput,
            )}
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setEditTarget(null)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={updateKey.isPending}>
              {updateKey.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}{" "}
              Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Key Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Credential Key"
      >
        <p className="text-sm text-zinc-400">
          Delete key{" "}
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.name}
          </span>
          ?
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteKey.isPending}
          >
            {deleteKey.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}{" "}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Credential Detail Row ─────────────────────────────────

function CredentialDetailRow({ credentialId }: { credentialId: string }) {
  const { data: detail, isLoading } = useCredentialDetail(credentialId);
  if (isLoading)
    return (
      <div className="py-2">
        <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />
      </div>
    );
  if (!detail?.values?.length)
    return <p className="text-xs text-zinc-500 py-2">No keys configured.</p>;
  return (
    <div className="py-2 space-y-1">
      <p className="text-xs font-medium text-zinc-400 mb-1">Credential Keys:</p>
      <div className="space-y-1">
        {detail.values.map((v) => (
          <div key={v.key_name} className="flex items-center gap-2">
            <Badge
              variant={v.is_secret ? "destructive" : "default"}
              className="text-xs"
            >
              {v.key_name}
            </Badge>
            {v.is_secret ? (
              <span className="text-xs text-zinc-600 italic">********</span>
            ) : v.value ? (
              <span className="text-xs font-mono text-zinc-300">{v.value}</span>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Credentials Section ──────────────────────────────────

function CredentialsCard() {
  const tz = useTimezone();
  const { canCreate, canEdit, canDelete } = usePermissions();
  const { data: credentials, isLoading } = useCredentials();
  const { data: credentialKeys } = useCredentialKeys();
  const { data: templates } = useCredentialTemplates();
  const { data: credentialTypes } = useCredentialTypes();
  const createCredential = useCreateCredential();
  const updateCredential = useUpdateCredential();
  const deleteCredential = useDeleteCredential();

  const [addOpen, setAddOpen] = useState(false);
  const credNameField = useField("", validateName);
  const [addDesc, setAddDesc] = useState("");
  const [addType, setAddType] = useState("");
  const [addTemplateId, setAddTemplateId] = useState("");
  const [addValues, setAddValues] = useState<Record<string, string>>({});
  const [addError, setAddError] = useState<string | null>(null);

  // Set default type from credential types
  useEffect(() => {
    if (!addType && credentialTypes && credentialTypes.length > 0) {
      setAddType(credentialTypes[0].name);
    }
  }, [credentialTypes, addType]);

  // When template changes, populate fields from template
  useEffect(() => {
    if (!addTemplateId) return;
    const tmpl = (templates ?? []).find((t) => t.id === addTemplateId);
    if (!tmpl) return;
    setAddType(tmpl.credential_type || tmpl.name);
    const vals: Record<string, string> = {};
    for (const f of tmpl.fields) {
      vals[f.key_name] = f.default_value ?? "";
    }
    setAddValues(vals);
  }, [addTemplateId, templates]);

  const [editTarget, setEditTarget] = useState<Credential | null>(null);
  const [editDesc, setEditDesc] = useState("");
  const [editType, setEditType] = useState("");
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [editError, setEditError] = useState<string | null>(null);
  const [editReady, setEditReady] = useState(false);

  // Fetch credential detail when editing, to get existing key names
  const { data: editDetail } = useCredentialDetail(editTarget?.id);

  // Pre-populate edit fields when detail loads
  useEffect(() => {
    if (!editTarget || !editDetail || editReady) return;
    const vals: Record<string, string> = {};
    // Build a lookup of existing values from the detail response
    const existingValues: Record<string, string | null> = {};
    for (const v of editDetail.values ?? []) {
      existingValues[v.key_name] = v.value; // null for secrets, actual value for plain/enum
    }
    // If template-based, populate from template fields
    if (editTarget.template_id) {
      const tmpl = (templates ?? []).find(
        (t) => t.id === editTarget.template_id,
      );
      if (tmpl) {
        for (const f of tmpl.fields) {
          vals[f.key_name] = existingValues[f.key_name] ?? "";
        }
      }
    }
    // Also add any keys from credential detail (covers non-template + extra keys)
    for (const v of editDetail.values ?? []) {
      if (!(v.key_name in vals)) {
        vals[v.key_name] = v.value ?? "";
      }
    }
    setEditValues(vals);
    setEditReady(true);
  }, [editTarget, editDetail, editReady, templates]);

  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!validateAll(credNameField)) return;
    try {
      await createCredential.mutateAsync({
        name: credNameField.value.trim(),
        description: addDesc.trim() || undefined,
        template_id: addTemplateId || undefined,
        credential_type: addTemplateId ? undefined : addType,
        secret: addValues,
      });
      credNameField.reset();
      setAddDesc("");
      setAddType(credentialTypes?.[0]?.name ?? "");
      setAddTemplateId("");
      setAddValues({});
      setAddOpen(false);
    } catch (err) {
      setAddError(
        err instanceof Error ? err.message : "Failed to create credential",
      );
    }
  }

  function openEdit(c: Credential) {
    setEditDesc(c.description || "");
    setEditType(c.credential_type);
    setEditError(null);
    setEditValues({});
    setEditReady(false);
    setEditTarget(c);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    try {
      const data: {
        description?: string;
        credential_type?: string;
        secret?: Record<string, unknown>;
      } = {
        description: editDesc.trim(),
        credential_type: editType,
      };
      // Only include values that were actually changed (non-empty)
      const changedValues: Record<string, string> = {};
      for (const [k, v] of Object.entries(editValues)) {
        if (v !== "") changedValues[k] = v;
      }
      if (Object.keys(changedValues).length > 0) {
        data.secret = changedValues;
      }
      await updateCredential.mutateAsync({ id: editTarget.id, data });
      setEditTarget(null);
      setEditReady(false);
    } catch (err) {
      setEditError(
        err instanceof Error ? err.message : "Failed to update credential",
      );
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteCredential.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      /* silent */
    }
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

  const availableKeys = (credentialKeys ?? []).filter(
    (k) => !(k.name in addValues),
  );
  const availableEditKeys = (credentialKeys ?? []).filter(
    (k) => !(k.name in editValues),
  );

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" />
            Credentials
            <Badge variant="default" className="ml-auto">
              {credentials?.length ?? 0}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
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
                    <TableRow
                      className="cursor-pointer"
                      onClick={() =>
                        setExpandedId(expandedId === cred.id ? null : cred.id)
                      }
                    >
                      <TableCell className="font-medium text-zinc-100">
                        {cred.name}
                      </TableCell>
                      <TableCell className="max-w-[300px] truncate text-zinc-400">
                        {cred.description || "—"}
                      </TableCell>
                      <TableCell>
                        <Badge variant="info">{cred.credential_type}</Badge>
                      </TableCell>
                      <TableCell className="text-zinc-500">
                        {formatDate(cred.created_at, tz)}
                      </TableCell>
                      <TableCell className="text-zinc-500">
                        {formatDate(cred.updated_at, tz)}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          {canEdit("credential") && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                openEdit(cred);
                              }}
                              className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                              title="Edit"
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                          )}
                          {canDelete("credential") && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setDeleteTarget(cred);
                              }}
                              className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                              title="Delete"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          )}
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
          {canCreate("credential") && (
            <div className="mt-4 flex justify-end border-t border-zinc-800 pt-4">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  credNameField.reset();
                  setAddDesc("");
                  setAddType(credentialTypes?.[0]?.name ?? "");
                  setAddTemplateId("");
                  setAddValues({});
                  setAddError(null);
                  setAddOpen(true);
                }}
                className="gap-1.5"
              >
                <Plus className="h-4 w-4" /> New Credential
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add Credential Dialog */}
      <Dialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="New Credential"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="cr-template">Template</Label>
            <Select
              id="cr-template"
              value={addTemplateId}
              onChange={(e) => {
                setAddTemplateId(e.target.value);
                if (!e.target.value) {
                  setAddValues({});
                  setAddType(credentialTypes?.[0]?.name ?? "");
                }
              }}
            >
              <option value="">Custom (no template)</option>
              {(templates ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {t.description ? ` — ${t.description}` : ""}
                </option>
              ))}
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="cr-name">Name</Label>
              <Input
                id="cr-name"
                placeholder="e.g. snmp-prod"
                value={credNameField.value}
                onChange={credNameField.onChange}
                onBlur={credNameField.onBlur}
                autoFocus
              />
              {credNameField.error && (
                <p className="text-xs text-red-400 mt-0.5">
                  {credNameField.error}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cr-type">Type</Label>
              <Select
                id="cr-type"
                value={addType}
                onChange={(e) => setAddType(e.target.value)}
                disabled={!!addTemplateId}
              >
                {(credentialTypes ?? []).map((ct) => (
                  <option key={ct.id} value={ct.name}>
                    {ct.name}
                    {ct.description ? ` — ${ct.description}` : ""}
                  </option>
                ))}
                {(!credentialTypes || credentialTypes.length === 0) && (
                  <option value={addType}>{addType}</option>
                )}
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cr-desc">
              Description{" "}
              <span className="font-normal text-zinc-500">(optional)</span>
            </Label>
            <Input
              id="cr-desc"
              value={addDesc}
              onChange={(e) => setAddDesc(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>Secret Values</Label>
            {addTemplateId ? (
              /* Template mode: show template fields in order */
              (() => {
                const tmpl = (templates ?? []).find(
                  (t) => t.id === addTemplateId,
                );
                if (!tmpl) return null;
                const sortedFields = [...tmpl.fields].sort(
                  (a, b) => a.display_order - b.display_order,
                );
                const secLevel = (
                  addValues.security_level ?? "authPriv"
                ).toLowerCase();
                const showAuth = secLevel !== "noauthnopriv";
                const showPriv = secLevel === "authpriv";
                return sortedFields.map((f) => {
                  // Hide auth/priv fields based on security_level
                  if (
                    !showAuth &&
                    ["auth_protocol", "auth_password", "auth_key"].includes(
                      f.key_name,
                    )
                  )
                    return null;
                  if (
                    !showPriv &&
                    ["priv_protocol", "priv_password", "priv_key"].includes(
                      f.key_name,
                    )
                  )
                    return null;
                  const keyDef = (credentialKeys ?? []).find(
                    (k) => k.name === f.key_name,
                  );
                  // Render enum keys as select dropdown
                  if (keyDef?.key_type === "enum" && keyDef.enum_values) {
                    return (
                      <div key={f.key_name} className="flex items-center gap-2">
                        <span className="text-xs font-mono text-zinc-400 w-28 shrink-0">
                          {f.key_name}
                          {f.required ? " *" : ""}
                        </span>
                        <Select
                          value={addValues[f.key_name] ?? f.default_value ?? ""}
                          onChange={(e) =>
                            setAddValues((prev) => ({
                              ...prev,
                              [f.key_name]: e.target.value,
                            }))
                          }
                          className="flex-1 text-xs"
                        >
                          {keyDef.enum_values.map((v) => (
                            <option key={v} value={v}>
                              {v}
                            </option>
                          ))}
                        </Select>
                      </div>
                    );
                  }
                  return (
                    <div key={f.key_name} className="flex items-center gap-2">
                      <span className="text-xs font-mono text-zinc-400 w-28 shrink-0">
                        {f.key_name}
                        {f.required ? " *" : ""}
                      </span>
                      <Input
                        type={
                          keyDef?.key_type === "secret" ? "password" : "text"
                        }
                        value={addValues[f.key_name] ?? f.default_value ?? ""}
                        onChange={(e) =>
                          setAddValues((prev) => ({
                            ...prev,
                            [f.key_name]: e.target.value,
                          }))
                        }
                        placeholder={
                          keyDef?.key_type === "secret"
                            ? "••••••"
                            : (f.default_value ?? "value")
                        }
                        className="flex-1 text-xs"
                      />
                    </div>
                  );
                });
              })()
            ) : (
              /* Custom mode: free key picker */
              <>
                {Object.entries(addValues).map(([key, val]) => {
                  const keyDef = (credentialKeys ?? []).find(
                    (k) => k.name === key,
                  );
                  if (keyDef?.key_type === "enum" && keyDef.enum_values) {
                    return (
                      <div key={key} className="flex items-center gap-2">
                        <span className="text-xs font-mono text-zinc-400 w-24 shrink-0">
                          {key}
                        </span>
                        <Select
                          value={val}
                          onChange={(e) =>
                            setAddValues((prev) => ({
                              ...prev,
                              [key]: e.target.value,
                            }))
                          }
                          className="flex-1 text-xs"
                        >
                          <option value="">Select...</option>
                          {keyDef.enum_values.map((v) => (
                            <option key={v} value={v}>
                              {v}
                            </option>
                          ))}
                        </Select>
                        <button
                          type="button"
                          onClick={() => handleRemoveAddValue(key)}
                          className="rounded p-1 text-zinc-600 hover:text-red-400 cursor-pointer"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    );
                  }
                  return (
                    <div key={key} className="flex items-center gap-2">
                      <span className="text-xs font-mono text-zinc-400 w-24 shrink-0">
                        {key}
                      </span>
                      <Input
                        type={
                          keyDef?.key_type === "secret" ? "password" : "text"
                        }
                        value={val}
                        onChange={(e) =>
                          setAddValues((prev) => ({
                            ...prev,
                            [key]: e.target.value,
                          }))
                        }
                        placeholder={
                          keyDef?.key_type === "secret" ? "••••••" : "value"
                        }
                        className="flex-1 text-xs"
                      />
                      <button
                        type="button"
                        onClick={() => handleRemoveAddValue(key)}
                        className="rounded p-1 text-zinc-600 hover:text-red-400 cursor-pointer"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  );
                })}
                {availableKeys.length > 0 && (
                  <Select
                    onChange={(e) => {
                      if (e.target.value) {
                        handleAddKeyValue(e.target.value);
                        e.target.value = "";
                      }
                    }}
                  >
                    <option value="">+ Add field...</option>
                    {availableKeys.map((k) => (
                      <option key={k.id} value={k.name}>
                        {k.name} ({k.key_type})
                      </option>
                    ))}
                  </Select>
                )}
              </>
            )}
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createCredential.isPending}>
              {createCredential.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}{" "}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Credential Dialog */}
      <Dialog
        open={!!editTarget}
        onClose={() => {
          setEditTarget(null);
          setEditReady(false);
        }}
        title={`Edit: ${editTarget?.name ?? ""}`}
      >
        {!editReady ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
          </div>
        ) : (
          <form onSubmit={handleEdit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="cr-edit-desc">Description</Label>
              <Input
                id="cr-edit-desc"
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cr-edit-type">Type</Label>
              <Input
                id="cr-edit-type"
                value={editType}
                onChange={(e) => setEditType(e.target.value)}
                disabled={!!editTarget?.template_id}
              />
            </div>
            <div className="space-y-2">
              <Label>
                Secret Values{" "}
                <span className="font-normal text-zinc-500">
                  (empty fields keep existing value)
                </span>
              </Label>
              {editTarget?.template_id ? (
                /* Template mode: show template fields in order */
                (() => {
                  const tmpl = (templates ?? []).find(
                    (t) => t.id === editTarget.template_id,
                  );
                  if (!tmpl) return null;
                  const sortedFields = [...tmpl.fields].sort(
                    (a, b) => a.display_order - b.display_order,
                  );
                  const secLevel =
                    (editValues.security_level ?? "").toLowerCase() ||
                    "authpriv";
                  const showAuth = secLevel !== "noauthnopriv";
                  const showPriv = secLevel === "authpriv";
                  return sortedFields.map((f) => {
                    if (
                      !showAuth &&
                      ["auth_protocol", "auth_password", "auth_key"].includes(
                        f.key_name,
                      )
                    )
                      return null;
                    if (
                      !showPriv &&
                      ["priv_protocol", "priv_password", "priv_key"].includes(
                        f.key_name,
                      )
                    )
                      return null;
                    const keyDef = (credentialKeys ?? []).find(
                      (k) => k.name === f.key_name,
                    );
                    if (keyDef?.key_type === "enum" && keyDef.enum_values) {
                      return (
                        <div
                          key={f.key_name}
                          className="flex items-center gap-2"
                        >
                          <span className="text-xs font-mono text-zinc-400 w-28 shrink-0">
                            {f.key_name}
                            {f.required ? " *" : ""}
                          </span>
                          <Select
                            value={editValues[f.key_name] ?? ""}
                            onChange={(e) =>
                              setEditValues((prev) => ({
                                ...prev,
                                [f.key_name]: e.target.value,
                              }))
                            }
                            className="flex-1 text-xs"
                          >
                            <option value="">Keep existing</option>
                            {keyDef.enum_values.map((v) => (
                              <option key={v} value={v}>
                                {v}
                              </option>
                            ))}
                          </Select>
                        </div>
                      );
                    }
                    return (
                      <div key={f.key_name} className="flex items-center gap-2">
                        <span className="text-xs font-mono text-zinc-400 w-28 shrink-0">
                          {f.key_name}
                          {f.required ? " *" : ""}
                        </span>
                        <Input
                          type={
                            keyDef?.key_type === "secret" ? "password" : "text"
                          }
                          value={editValues[f.key_name] ?? ""}
                          onChange={(e) =>
                            setEditValues((prev) => ({
                              ...prev,
                              [f.key_name]: e.target.value,
                            }))
                          }
                          placeholder={
                            keyDef?.key_type === "secret"
                              ? "Keep existing"
                              : "Keep existing"
                          }
                          className="flex-1 text-xs"
                        />
                      </div>
                    );
                  });
                })()
              ) : (
                /* Custom mode: free key picker */
                <>
                  {Object.entries(editValues).map(([key, val]) => {
                    const keyDef = (credentialKeys ?? []).find(
                      (k) => k.name === key,
                    );
                    if (keyDef?.key_type === "enum" && keyDef.enum_values) {
                      return (
                        <div key={key} className="flex items-center gap-2">
                          <span className="text-xs font-mono text-zinc-400 w-24 shrink-0">
                            {key}
                          </span>
                          <Select
                            value={val}
                            onChange={(e) =>
                              setEditValues((prev) => ({
                                ...prev,
                                [key]: e.target.value,
                              }))
                            }
                            className="flex-1 text-xs"
                          >
                            <option value="">Keep existing</option>
                            {keyDef.enum_values.map((v) => (
                              <option key={v} value={v}>
                                {v}
                              </option>
                            ))}
                          </Select>
                          <button
                            type="button"
                            onClick={() => {
                              setEditValues((prev) => {
                                const n = { ...prev };
                                delete n[key];
                                return n;
                              });
                            }}
                            className="rounded p-1 text-zinc-600 hover:text-red-400 cursor-pointer"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      );
                    }
                    return (
                      <div key={key} className="flex items-center gap-2">
                        <span className="text-xs font-mono text-zinc-400 w-24 shrink-0">
                          {key}
                        </span>
                        <Input
                          type={
                            keyDef?.key_type === "secret" ? "password" : "text"
                          }
                          value={val}
                          onChange={(e) =>
                            setEditValues((prev) => ({
                              ...prev,
                              [key]: e.target.value,
                            }))
                          }
                          placeholder="Keep existing"
                          className="flex-1 text-xs"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            setEditValues((prev) => {
                              const n = { ...prev };
                              delete n[key];
                              return n;
                            });
                          }}
                          className="rounded p-1 text-zinc-600 hover:text-red-400 cursor-pointer"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    );
                  })}
                  {availableEditKeys.length > 0 && (
                    <Select
                      onChange={(e) => {
                        if (e.target.value) {
                          setEditValues((prev) => ({
                            ...prev,
                            [e.target.value]: "",
                          }));
                          e.target.value = "";
                        }
                      }}
                    >
                      <option value="">+ Add field...</option>
                      {availableEditKeys.map((k) => (
                        <option key={k.id} value={k.name}>
                          {k.name} ({k.key_type})
                        </option>
                      ))}
                    </Select>
                  )}
                </>
              )}
            </div>
            {editError && <p className="text-sm text-red-400">{editError}</p>}
            <DialogFooter>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setEditTarget(null);
                  setEditReady(false);
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={updateCredential.isPending}>
                {updateCredential.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}{" "}
                Save
              </Button>
            </DialogFooter>
          </form>
        )}
      </Dialog>

      {/* Delete Credential Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Credential"
      >
        <p className="text-sm text-zinc-400">
          Delete credential{" "}
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.name}
          </span>
          ? App assignments referencing this credential will stop working.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteCredential.isPending}
          >
            {deleteCredential.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}{" "}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Credential Templates Section ─────────────────────────

function CredentialTemplatesCard() {
  const tz = useTimezone();
  const { canEdit, canDelete } = usePermissions();
  const { data: templates, isLoading } = useCredentialTemplates();
  const { data: credentialKeys } = useCredentialKeys();
  const { data: credentialTypes } = useCredentialTypes();
  const createTemplate = useCreateCredentialTemplate();
  const updateTemplate = useUpdateCredentialTemplate();
  const deleteTemplate = useDeleteCredentialTemplate();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addCredType, setAddCredType] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [addFields, setAddFields] = useState<
    { key_name: string; required: boolean; default_value: string }[]
  >([]);
  const [addError, setAddError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<CredentialTemplate | null>(
    null,
  );

  const [editTarget, setEditTarget] = useState<CredentialTemplate | null>(null);
  const [editName, setEditName] = useState("");
  const [editCredType, setEditCredType] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editFields, setEditFields] = useState<
    { key_name: string; required: boolean; default_value: string }[]
  >([]);
  const [editError, setEditError] = useState<string | null>(null);

  const addUsedKeyNames = new Set(addFields.map((f) => f.key_name));
  const editUsedKeyNames = new Set(editFields.map((f) => f.key_name));
  const availableAddKeys = (credentialKeys ?? []).filter(
    (k) => !addUsedKeyNames.has(k.name),
  );
  const availableEditKeys = (credentialKeys ?? []).filter(
    (k) => !editUsedKeyNames.has(k.name),
  );

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setAddError(null);
    if (!addName.trim()) {
      setAddError("Name is required.");
      return;
    }
    if (!addCredType) {
      setAddError("Credential type is required.");
      return;
    }
    if (addFields.length === 0) {
      setAddError("At least one field is required.");
      return;
    }
    try {
      await createTemplate.mutateAsync({
        name: addName.trim(),
        credential_type: addCredType,
        description: addDesc.trim() || undefined,
        fields: addFields.map((f, i) => ({
          key_name: f.key_name,
          required: f.required,
          default_value: f.default_value || null,
          display_order: i + 1,
        })),
      });
      setAddName("");
      setAddCredType("");
      setAddDesc("");
      setAddFields([]);
      setAddOpen(false);
    } catch (err) {
      setAddError(
        err instanceof Error ? err.message : "Failed to create template",
      );
    }
  }

  function openEdit(t: CredentialTemplate) {
    setEditName(t.name);
    setEditCredType(t.credential_type ?? "");
    setEditDesc(t.description ?? "");
    setEditFields(
      [...t.fields]
        .sort((a, b) => a.display_order - b.display_order)
        .map((f) => ({
          key_name: f.key_name,
          required: f.required,
          default_value: f.default_value ?? "",
        })),
    );
    setEditError(null);
    setEditTarget(t);
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget) return;
    setEditError(null);
    if (!editName.trim()) {
      setEditError("Name is required.");
      return;
    }
    if (!editCredType) {
      setEditError("Credential type is required.");
      return;
    }
    if (editFields.length === 0) {
      setEditError("At least one field is required.");
      return;
    }
    try {
      await updateTemplate.mutateAsync({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          credential_type: editCredType,
          description: editDesc.trim() || undefined,
          fields: editFields.map((f, i) => ({
            key_name: f.key_name,
            required: f.required,
            default_value: f.default_value || null,
            display_order: i + 1,
          })),
        },
      });
      setEditTarget(null);
    } catch (err) {
      setEditError(
        err instanceof Error ? err.message : "Failed to update template",
      );
    }
  }

  function swapFields(
    fields: typeof addFields,
    setFields: typeof setAddFields,
    idx: number,
    dir: -1 | 1,
  ) {
    const next = [...fields];
    const target = idx + dir;
    if (target < 0 || target >= next.length) return;
    [next[idx], next[target]] = [next[target], next[idx]];
    setFields(next);
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteTemplate.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      /* silent */
    }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Credential Templates
            <Badge variant="default" className="ml-auto">
              {templates?.length ?? 0}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-zinc-500" />
            </div>
          ) : !templates || templates.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-zinc-500">
              <FileText className="mb-2 h-8 w-8 text-zinc-600" />
              <p className="text-sm">No credential templates defined</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Fields</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-16"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {templates.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium font-mono text-sm text-zinc-100">
                      {t.name}
                    </TableCell>
                    <TableCell>
                      <Badge variant="info">{t.credential_type}</Badge>
                    </TableCell>
                    <TableCell className="text-zinc-400 text-sm">
                      {t.description ?? "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {[...t.fields]
                          .sort((a, b) => a.display_order - b.display_order)
                          .map((f) => (
                            <Badge
                              key={f.key_name}
                              variant={f.required ? "default" : "info"}
                              className="text-xs"
                            >
                              {f.key_name}
                              {f.required ? " *" : ""}
                            </Badge>
                          ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm">
                      {formatDate(t.created_at, tz)}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        {canEdit("credential") && (
                          <button
                            onClick={() => openEdit(t)}
                            className="rounded p-1 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700/50 transition-colors cursor-pointer"
                            title="Edit"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                        )}
                        {canDelete("credential") && (
                          <button
                            onClick={() => setDeleteTarget(t)}
                            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <div className="mt-4 flex justify-end border-t border-zinc-800 pt-4">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setAddName("");
                setAddCredType("");
                setAddDesc("");
                setAddFields([]);
                setAddError(null);
                setAddOpen(true);
              }}
              className="gap-1.5"
            >
              <Plus className="h-4 w-4" /> New Template
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Add Template Dialog */}
      <Dialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="New Credential Template"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="ct-name">Name</Label>
              <Input
                id="ct-name"
                placeholder="e.g. snmpv2c"
                value={addName}
                onChange={(e) => setAddName(e.target.value)}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ct-cred-type">Credential Type</Label>
              <Select
                id="ct-cred-type"
                value={addCredType}
                onChange={(e) => setAddCredType(e.target.value)}
              >
                <option value="">Select type...</option>
                {(credentialTypes ?? []).map((ct) => (
                  <option key={ct.id} value={ct.name}>
                    {ct.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ct-desc">Description</Label>
              <Input
                id="ct-desc"
                placeholder="e.g. SNMP v2c community-based"
                value={addDesc}
                onChange={(e) => setAddDesc(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Fields</Label>
            {addFields.map((f, idx) => {
              const keyDef = (credentialKeys ?? []).find(
                (k) => k.name === f.key_name,
              );
              const badge = keyDef
                ? (KEY_TYPE_BADGE[keyDef.key_type] ?? KEY_TYPE_BADGE.plain)
                : KEY_TYPE_BADGE.plain;
              return (
                <div
                  key={f.key_name}
                  className="flex items-center gap-2 rounded border border-zinc-800 px-2 py-1.5"
                >
                  <span className="text-xs font-mono text-zinc-300 w-28 shrink-0">
                    {f.key_name}
                  </span>
                  <Badge variant={badge.variant} className="text-[10px]">
                    {badge.label}
                  </Badge>
                  <label className="flex items-center gap-1 text-xs text-zinc-400 ml-auto">
                    <input
                      type="checkbox"
                      checked={f.required}
                      onChange={(e) => {
                        const next = [...addFields];
                        next[idx] = { ...f, required: e.target.checked };
                        setAddFields(next);
                      }}
                      className="accent-brand-500"
                    />
                    Required
                  </label>
                  {keyDef?.key_type === "enum" && keyDef.enum_values ? (
                    <Select
                      value={f.default_value || ""}
                      onChange={(e) => {
                        const next = [...addFields];
                        next[idx] = {
                          ...f,
                          default_value: e.target.value || "",
                        };
                        setAddFields(next);
                      }}
                      className="w-28 text-xs"
                    >
                      <option value="">No default</option>
                      {keyDef.enum_values.map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Input
                      type={keyDef?.key_type === "secret" ? "password" : "text"}
                      value={f.default_value}
                      onChange={(e) => {
                        const next = [...addFields];
                        next[idx] = { ...f, default_value: e.target.value };
                        setAddFields(next);
                      }}
                      placeholder={
                        keyDef?.key_type === "secret" ? "no default" : "default"
                      }
                      className="w-28 text-xs"
                    />
                  )}
                  <div className="flex gap-0.5">
                    <button
                      type="button"
                      disabled={idx === 0}
                      onClick={() =>
                        swapFields(addFields, setAddFields, idx, -1)
                      }
                      className="rounded p-1 text-zinc-600 hover:text-zinc-300 disabled:opacity-20 disabled:cursor-default cursor-pointer"
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      disabled={idx === addFields.length - 1}
                      onClick={() =>
                        swapFields(addFields, setAddFields, idx, 1)
                      }
                      className="rounded p-1 text-zinc-600 hover:text-zinc-300 disabled:opacity-20 disabled:cursor-default cursor-pointer"
                    >
                      <ArrowDown className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      setAddFields(addFields.filter((_, i) => i !== idx))
                    }
                    className="rounded p-1 text-zinc-600 hover:text-red-400 cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
            {availableAddKeys.length > 0 && (
              <Select
                onChange={(e) => {
                  if (e.target.value) {
                    setAddFields([
                      ...addFields,
                      {
                        key_name: e.target.value,
                        required: true,
                        default_value: "",
                      },
                    ]);
                    e.target.value = "";
                  }
                }}
              >
                <option value="">+ Add field...</option>
                {availableAddKeys.map((k) => (
                  <option key={k.id} value={k.name}>
                    {k.name} ({k.key_type})
                  </option>
                ))}
              </Select>
            )}
          </div>
          {addError && <p className="text-sm text-red-400">{addError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createTemplate.isPending}>
              {createTemplate.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}{" "}
              Create
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Edit Template Dialog */}
      <Dialog
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        title="Edit Credential Template"
      >
        <form onSubmit={handleEdit} className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="ct-edit-name">Name</Label>
              <Input
                id="ct-edit-name"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ct-edit-cred-type">Credential Type</Label>
              <Select
                id="ct-edit-cred-type"
                value={editCredType}
                onChange={(e) => setEditCredType(e.target.value)}
              >
                <option value="">Select type...</option>
                {(credentialTypes ?? []).map((ct) => (
                  <option key={ct.id} value={ct.name}>
                    {ct.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ct-edit-desc">Description</Label>
              <Input
                id="ct-edit-desc"
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Fields</Label>
            {editFields.map((f, idx) => {
              const keyDef = (credentialKeys ?? []).find(
                (k) => k.name === f.key_name,
              );
              const badge = keyDef
                ? (KEY_TYPE_BADGE[keyDef.key_type] ?? KEY_TYPE_BADGE.plain)
                : KEY_TYPE_BADGE.plain;
              return (
                <div
                  key={f.key_name}
                  className="flex items-center gap-2 rounded border border-zinc-800 px-2 py-1.5"
                >
                  <span className="text-xs font-mono text-zinc-300 w-28 shrink-0">
                    {f.key_name}
                  </span>
                  <Badge variant={badge.variant} className="text-[10px]">
                    {badge.label}
                  </Badge>
                  <label className="flex items-center gap-1 text-xs text-zinc-400 ml-auto">
                    <input
                      type="checkbox"
                      checked={f.required}
                      onChange={(e) => {
                        const next = [...editFields];
                        next[idx] = { ...f, required: e.target.checked };
                        setEditFields(next);
                      }}
                      className="accent-brand-500"
                    />
                    Required
                  </label>
                  {keyDef?.key_type === "enum" && keyDef.enum_values ? (
                    <Select
                      value={f.default_value || ""}
                      onChange={(e) => {
                        const next = [...editFields];
                        next[idx] = {
                          ...f,
                          default_value: e.target.value || "",
                        };
                        setEditFields(next);
                      }}
                      className="w-28 text-xs"
                    >
                      <option value="">No default</option>
                      {keyDef.enum_values.map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Input
                      type={keyDef?.key_type === "secret" ? "password" : "text"}
                      value={f.default_value}
                      onChange={(e) => {
                        const next = [...editFields];
                        next[idx] = { ...f, default_value: e.target.value };
                        setEditFields(next);
                      }}
                      placeholder={
                        keyDef?.key_type === "secret" ? "no default" : "default"
                      }
                      className="w-28 text-xs"
                    />
                  )}
                  <div className="flex gap-0.5">
                    <button
                      type="button"
                      disabled={idx === 0}
                      onClick={() =>
                        swapFields(editFields, setEditFields, idx, -1)
                      }
                      className="rounded p-1 text-zinc-600 hover:text-zinc-300 disabled:opacity-20 disabled:cursor-default cursor-pointer"
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      disabled={idx === editFields.length - 1}
                      onClick={() =>
                        swapFields(editFields, setEditFields, idx, 1)
                      }
                      className="rounded p-1 text-zinc-600 hover:text-zinc-300 disabled:opacity-20 disabled:cursor-default cursor-pointer"
                    >
                      <ArrowDown className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      setEditFields(editFields.filter((_, i) => i !== idx))
                    }
                    className="rounded p-1 text-zinc-600 hover:text-red-400 cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
            {availableEditKeys.length > 0 && (
              <Select
                onChange={(e) => {
                  if (e.target.value) {
                    setEditFields([
                      ...editFields,
                      {
                        key_name: e.target.value,
                        required: true,
                        default_value: "",
                      },
                    ]);
                    e.target.value = "";
                  }
                }}
              >
                <option value="">+ Add field...</option>
                {availableEditKeys.map((k) => (
                  <option key={k.id} value={k.name}>
                    {k.name} ({k.key_type})
                  </option>
                ))}
              </Select>
            )}
          </div>
          {editError && <p className="text-sm text-red-400">{editError}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setEditTarget(null)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={updateTemplate.isPending}>
              {updateTemplate.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}{" "}
              Save
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* Delete Template Dialog */}
      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Template"
      >
        <p className="text-sm text-zinc-400">
          Delete template{" "}
          <span className="font-semibold text-zinc-200">
            {deleteTarget?.name}
          </span>
          ? Existing credentials using this template will keep working.
        </p>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteTemplate.isPending}
          >
            {deleteTemplate.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}{" "}
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

// ── Credential Types Section ─────────────────────────────

function CredentialTypesCard() {
  const tz = useTimezone();
  const { canEdit, canDelete } = usePermissions();
  const { data: types, isLoading } = useCredentialTypes();
  const createType = useCreateCredentialType();
  const updateType = useUpdateCredentialType();
  const deleteType = useDeleteCredentialType();

  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDesc, setAddDesc] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!addName.trim()) return;
    await createType.mutateAsync({
      name: addName.trim(),
      description: addDesc.trim() || undefined,
    });
    setAddName("");
    setAddDesc("");
    setAddOpen(false);
  }

  async function handleUpdate(id: string) {
    if (!editName.trim()) return;
    await updateType.mutateAsync({
      id,
      data: {
        name: editName.trim(),
        description: editDesc.trim() || undefined,
      },
    });
    setEditingId(null);
  }

  function startEdit(t: CredentialType) {
    setEditingId(t.id);
    setEditName(t.name);
    setEditDesc(t.description ?? "");
  }

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Credential Types
            <Button
              size="sm"
              className="ml-auto gap-1.5"
              onClick={() => setAddOpen(true)}
            >
              <Plus className="h-3.5 w-3.5" /> Add Type
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {(types ?? []).length === 0 ? (
            <p className="text-sm text-zinc-500 py-8 text-center">
              No credential types defined.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(types ?? []).map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-mono text-sm">
                      {editingId === t.id ? (
                        <Input
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          className="h-7 text-sm"
                        />
                      ) : (
                        <Badge variant="default">{t.name}</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-zinc-400">
                      {editingId === t.id ? (
                        <Input
                          value={editDesc}
                          onChange={(e) => setEditDesc(e.target.value)}
                          className="h-7 text-sm"
                          placeholder="Description..."
                        />
                      ) : (
                        t.description || (
                          <span className="text-zinc-600">{"\u2014"}</span>
                        )
                      )}
                    </TableCell>
                    <TableCell className="text-zinc-500 text-xs">
                      {formatDate(t.created_at, tz)}
                    </TableCell>
                    <TableCell className="text-right">
                      {editingId === t.id ? (
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2 text-xs"
                            onClick={() => setEditingId(null)}
                          >
                            Cancel
                          </Button>
                          <Button
                            size="sm"
                            className="h-6 px-2 text-xs"
                            onClick={() => handleUpdate(t.id)}
                            disabled={updateType.isPending}
                          >
                            Save
                          </Button>
                        </div>
                      ) : (
                        <div className="flex items-center justify-end gap-1">
                          {canEdit("credential") && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 w-6 p-0"
                              onClick={() => startEdit(t)}
                              title="Edit"
                            >
                              <Pencil className="h-3 w-3" />
                            </Button>
                          )}
                          {canDelete("credential") && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 w-6 p-0 text-red-400 hover:text-red-300"
                              onClick={() => deleteType.mutate(t.id)}
                              title="Delete"
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          )}
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="New Credential Type"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ct-name">Name</Label>
            <Input
              id="ct-name"
              placeholder="e.g. snmpv3"
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ct-desc">
              Description{" "}
              <span className="text-zinc-500 font-normal">(optional)</span>
            </Label>
            <Input
              id="ct-desc"
              placeholder="e.g. SNMP version 3 credentials"
              value={addDesc}
              onChange={(e) => setAddDesc(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createType.isPending}>
              {createType.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Create
            </Button>
          </DialogFooter>
        </form>
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
          <TabTrigger value="types">Types</TabTrigger>
          <TabTrigger value="credential-keys">Credential Keys</TabTrigger>
          <TabTrigger value="templates">Templates</TabTrigger>
        </TabsList>
        <TabsContent value="credentials">
          <CredentialsCard />
        </TabsContent>
        <TabsContent value="types">
          <CredentialTypesCard />
        </TabsContent>
        <TabsContent value="credential-keys">
          <CredentialKeysCard />
        </TabsContent>
        <TabsContent value="templates">
          <CredentialTemplatesCard />
        </TabsContent>
      </Tabs>
    </div>
  );
}
