import { useState, useEffect } from "react";
import { useField, validateAll } from "@/hooks/useFieldValidation.ts";
import { validateSlug, validateName, validateSemver } from "@/lib/validation.ts";
import {
  AppWindow, Binary, ChevronDown, ChevronRight, KeyRound, LayoutTemplate,
  Loader2, Lock, Monitor, Plug, Search, Tag, Unlock,
} from "lucide-react";
import { Dialog, DialogFooter } from "@/components/ui/dialog.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { useAvailableEntities, useCreatePack } from "@/api/hooks.ts";
import type { AvailableEntity } from "@/types/api.ts";
import { cn } from "@/lib/utils.ts";

interface CreatePackDialogProps {
  open: boolean;
  onClose: () => void;
}

const SECTION_CONFIG: { key: string; label: string; icon: React.ReactNode }[] = [
  { key: "apps", label: "Apps", icon: <AppWindow className="h-4 w-4" /> },
  { key: "credential_templates", label: "Credential Templates", icon: <KeyRound className="h-4 w-4" /> },
  { key: "snmp_oids", label: "SNMP OIDs", icon: <Binary className="h-4 w-4" /> },
  { key: "device_templates", label: "Device Templates", icon: <LayoutTemplate className="h-4 w-4" /> },
  { key: "device_categories", label: "Device Categories", icon: <Monitor className="h-4 w-4" /> },
  { key: "label_keys", label: "Label Keys", icon: <Tag className="h-4 w-4" /> },
  { key: "connectors", label: "Connectors", icon: <Plug className="h-4 w-4" /> },
  { key: "device_types", label: "Device Types", icon: <Search className="h-4 w-4" /> },
];

const EMPTY_SELECTED: Record<string, Set<string>> = {
  apps: new Set(),
  credential_templates: new Set(),
  snmp_oids: new Set(),
  device_templates: new Set(),
  device_categories: new Set(),
  label_keys: new Set(),
  connectors: new Set(),
  device_types: new Set(),
};

function toSlug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export function CreatePackDialog({ open, onClose }: CreatePackDialogProps) {
  const [step, setStep] = useState<1 | 2 | 3>(1);

  // Step 1: Metadata
  const packUidField = useField("", validateSlug);
  const nameField = useField("", validateName);
  const versionField = useField("1.0.0", validateSemver);
  const [description, setDescription] = useState("");
  const [author, setAuthor] = useState("");
  const [autoSlug, setAutoSlug] = useState(true);

  // Step 2: Entity selection
  const [selected, setSelected] = useState<Record<string, Set<string>>>(() =>
    Object.fromEntries(Object.entries(EMPTY_SELECTED).map(([k]) => [k, new Set<string>()])),
  );

  // Step 3: Submit
  const [error, setError] = useState<string | null>(null);

  const { data: available, isLoading: loadingEntities } = useAvailableEntities(open);
  const createPack = useCreatePack();

  // Reset on close
  useEffect(() => {
    if (!open) {
      setStep(1);
      packUidField.reset();
      nameField.reset();
      versionField.reset("1.0.0");
      setDescription("");
      setAuthor("");
      setAutoSlug(true);
      setSelected(
        Object.fromEntries(Object.entries(EMPTY_SELECTED).map(([k]) => [k, new Set<string>()])),
      );
      setError(null);
    }
  }, [open]);

  function handleNameChange(val: string) {
    nameField.setValue(val);
    if (autoSlug) packUidField.setValue(toSlug(val));
  }

  function toggleEntity(section: string, id: string) {
    setSelected((prev) => {
      const next = new Map(Object.entries(prev).map(([k, v]) => [k, new Set(v)]));
      const s = next.get(section)!;
      if (s.has(id)) s.delete(id);
      else s.add(id);
      return Object.fromEntries(next);
    });
  }

  function toggleAll(section: string, checked: boolean) {
    if (!available) return;
    setSelected((prev) => {
      const next = new Map(Object.entries(prev).map(([k, v]) => [k, new Set(v)]));
      const s = new Set<string>();
      if (checked) {
        for (const e of available[section] ?? []) s.add(e.id);
      }
      next.set(section, s);
      return Object.fromEntries(next);
    });
  }

  const canProceedStep1 = !validateSlug(packUidField.value) && !validateName(nameField.value) && !validateSemver(versionField.value);

  const totalSelected = Object.values(selected).reduce((sum, s) => sum + s.size, 0);

  function handleNext() {
    if (step === 1) {
      if (!validateAll(nameField, packUidField, versionField)) return;
      setStep(2);
      return;
    }
    else if (step === 2) setStep(3);
  }

  async function handleCreate() {
    setError(null);
    const entity_ids: Record<string, string[]> = {};
    for (const [section, ids] of Object.entries(selected)) {
      const arr = Array.from(ids);
      if (arr.length > 0) entity_ids[section] = arr;
    }

    if (Object.keys(entity_ids).length === 0) {
      setError("Select at least one entity to include in the pack.");
      return;
    }

    try {
      await createPack.mutateAsync({
        pack_uid: packUidField.value,
        name: nameField.value,
        version: versionField.value,
        description: description || undefined,
        author: author || undefined,
        entity_ids,
      });
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create pack");
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Create Pack" size="lg">
      {/* Stepper */}
      <div className="flex items-center gap-2 mb-6">
        {[
          { num: 1, label: "Metadata" },
          { num: 2, label: "Select Entities" },
          { num: 3, label: "Review" },
        ].map(({ num, label }) => (
          <div key={num} className="flex items-center gap-2">
            <div
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium",
                step >= num ? "bg-brand-600 text-white" : "bg-zinc-800 text-zinc-500",
              )}
            >
              {num}
            </div>
            <span className={cn("text-sm", step >= num ? "text-zinc-200" : "text-zinc-600")}>
              {label}
            </span>
            {num < 3 && <div className="h-px w-8 bg-zinc-700" />}
          </div>
        ))}
      </div>

      {/* Step 1: Metadata */}
      {step === 1 && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1">Name *</label>
            <input
              type="text"
              value={nameField.value}
              onChange={(e) => handleNameChange(e.target.value)}
              onBlur={nameField.onBlur}
              placeholder="e.g. SNMP Network Basics"
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-brand-500 focus:outline-none"
            />
            {nameField.error && <p className="text-xs text-red-400 mt-0.5">{nameField.error}</p>}
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1">Pack UID *</label>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={packUidField.value}
                onChange={(e) => { if (!autoSlug) packUidField.setValue(e.target.value); }}
                onBlur={packUidField.onBlur}
                readOnly={autoSlug}
                className={cn(
                  "flex-1 rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-brand-500 focus:outline-none",
                  autoSlug && "text-zinc-400",
                )}
              />
              <button
                type="button"
                onClick={() => setAutoSlug(!autoSlug)}
                className="rounded-md p-2 text-zinc-500 hover:text-zinc-300 hover:bg-zinc-700 transition-colors cursor-pointer"
                title={autoSlug ? "Unlock to edit manually" : "Lock to auto-generate"}
              >
                {autoSlug ? <Lock className="h-4 w-4" /> : <Unlock className="h-4 w-4" />}
              </button>
            </div>
            {packUidField.error && (
              <p className="mt-1 text-xs text-red-400">{packUidField.error}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1">Version *</label>
            <input
              type="text"
              value={versionField.value}
              onChange={(e) => versionField.setValue(e.target.value)}
              onBlur={versionField.onBlur}
              placeholder="1.0.0"
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-brand-500 focus:outline-none"
            />
            {versionField.error && (
              <p className="mt-1 text-xs text-red-400">{versionField.error}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-brand-500 focus:outline-none resize-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1">Author</label>
            <input
              type="text"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-brand-500 focus:outline-none"
            />
          </div>
        </div>
      )}

      {/* Step 2: Select Entities */}
      {step === 2 && (
        <div className="space-y-1 max-h-[28rem] overflow-y-auto pr-1">
          {loadingEntities ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
            </div>
          ) : (
            SECTION_CONFIG.map(({ key, label, icon }) => (
              <EntitySection
                key={key}
                title={label}
                icon={icon}
                entities={available?.[key] ?? []}
                selected={selected[key] ?? new Set()}
                onToggle={(id) => toggleEntity(key, id)}
                onToggleAll={(checked) => toggleAll(key, checked)}
              />
            ))
          )}
        </div>
      )}

      {/* Step 3: Review */}
      {step === 3 && (
        <div className="space-y-4">
          <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-800/50 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">Pack</span>
              <span className="text-sm font-medium text-zinc-100">{nameField.value}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">UID</span>
              <Badge variant="info">{packUidField.value}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">Version</span>
              <Badge variant="default">v{versionField.value}</Badge>
            </div>
            {author && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Author</span>
                <span className="text-sm text-zinc-300">{author}</span>
              </div>
            )}
            {description && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Description</span>
                <span className="text-sm text-zinc-300 text-right max-w-xs truncate">{description}</span>
              </div>
            )}
          </div>

          <div className="space-y-1">
            <h3 className="text-sm font-medium text-zinc-300 mb-2">Contents</h3>
            {SECTION_CONFIG.filter(({ key }) => (selected[key]?.size ?? 0) > 0).map(({ key, label, icon }) => (
              <div key={key} className="flex items-center gap-2 text-sm text-zinc-300">
                <span className="text-zinc-500">{icon}</span>
                <span>{selected[key].size} {label}</span>
              </div>
            ))}
            <div className="mt-2 pt-2 border-t border-zinc-800 text-sm text-zinc-400">
              Total: <span className="font-medium text-zinc-200">{totalSelected}</span> entities will be tagged with this pack.
            </div>
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>
      )}

      {/* Footer */}
      <DialogFooter>
        {step > 1 && (
          <Button variant="secondary" onClick={() => setStep((s) => (s - 1) as 1 | 2 | 3)}>
            Back
          </Button>
        )}
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        {step < 3 ? (
          <Button onClick={handleNext} disabled={step === 1 ? !canProceedStep1 : false}>
            Next
          </Button>
        ) : (
          <Button onClick={handleCreate} disabled={createPack.isPending || totalSelected === 0}>
            {createPack.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Create Pack
          </Button>
        )}
      </DialogFooter>
    </Dialog>
  );
}

// ── Entity Section ──────────────────────────────────────────

function EntitySection({
  title,
  icon,
  entities,
  selected,
  onToggle,
  onToggleAll,
}: {
  title: string;
  icon: React.ReactNode;
  entities: AvailableEntity[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (checked: boolean) => void;
}) {
  const selectedCount = entities.filter((e) => selected.has(e.id)).length;
  const [expanded, setExpanded] = useState(false);

  // Auto-expand if items are selected
  useEffect(() => {
    if (selectedCount > 0 && !expanded) setExpanded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (entities.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-zinc-600">
        <span>{icon}</span>
        <span>{title}</span>
        <span className="text-xs">(0 available)</span>
      </div>
    );
  }

  const allSelected = entities.length > 0 && entities.every((e) => selected.has(e.id));

  return (
    <div className="rounded-md border border-zinc-800">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-zinc-800/50 transition-colors cursor-pointer"
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-zinc-500" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-zinc-500" />
        )}
        <span className="text-zinc-500">{icon}</span>
        <span className="font-medium text-zinc-200">{title}</span>
        <Badge variant="info" className="ml-auto text-xs">
          {selectedCount}/{entities.length}
        </Badge>
        <label
          className="flex items-center gap-1 text-xs text-zinc-500 cursor-pointer"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={allSelected}
            onChange={(e) => onToggleAll(e.target.checked)}
            className="rounded border-zinc-600 bg-zinc-700 text-brand-600 focus:ring-brand-500 cursor-pointer"
          />
          All
        </label>
      </button>

      {expanded && (
        <div className="border-t border-zinc-800 px-3 py-1">
          {entities.map((entity) => (
            <label
              key={entity.id}
              className="flex items-center gap-3 rounded px-2 py-1.5 hover:bg-zinc-800/50 cursor-pointer"
            >
              <input
                type="checkbox"
                checked={selected.has(entity.id)}
                onChange={() => onToggle(entity.id)}
                className="rounded border-zinc-600 bg-zinc-700 text-brand-600 focus:ring-brand-500 cursor-pointer"
              />
              <span className="font-medium text-sm text-zinc-200">{entity.name}</span>
              {entity.description && (
                <span className="text-xs text-zinc-500 truncate max-w-xs">{entity.description}</span>
              )}
              {entity.pack_id && (
                <Badge className="ml-auto bg-amber-600/20 text-amber-400 text-xs shrink-0">
                  In another pack
                </Badge>
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
