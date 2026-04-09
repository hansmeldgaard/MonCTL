import { useId, useState } from "react";
import { Plus, X } from "lucide-react";
import { Input } from "@/components/ui/input.tsx";
import { Button } from "@/components/ui/button.tsx";
import { useLabelKeys, useLabelValues } from "@/api/hooks.ts";

interface LabelEditorProps {
  labels: Record<string, string>;
  onChange: (labels: Record<string, string>) => void;
  disabled?: boolean;
}

export function LabelEditor({ labels, onChange, disabled }: LabelEditorProps) {
  const { data: labelKeys } = useLabelKeys();
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const uid = useId();

  // Fetch suggested values for currently typed key
  const matchedKey = (labelKeys ?? []).find(
    (lk) => lk.key === newKey.trim().toLowerCase(),
  );
  const { data: suggestedValues } = useLabelValues(
    matchedKey ? matchedKey.key : null,
  );

  // Keys not already used in current labels
  const availableKeys = (labelKeys ?? []).filter((lk) => !(lk.key in labels));

  function handleAdd() {
    setError(null);
    const key = newKey.trim().toLowerCase();
    const val = newValue.trim();
    if (!key) {
      setError("Label key cannot be empty.");
      return;
    }
    if (!/^[a-z][a-z0-9_-]*$/.test(key)) {
      setError(
        "Key must be lowercase, start with a letter, only a-z, 0-9, hyphens, underscores.",
      );
      return;
    }
    if (key in labels) {
      setError(`Label "${key}" already exists.`);
      return;
    }
    onChange({ ...labels, [key]: val });
    setNewKey("");
    setNewValue("");
  }

  function handleRemove(key: string) {
    const next = { ...labels };
    delete next[key];
    onChange(next);
  }

  return (
    <div className="space-y-3 max-w-md">
      {/* Existing labels */}
      {Object.keys(labels).length > 0 ? (
        <div className="rounded-md border border-zinc-800 divide-y divide-zinc-800">
          {Object.entries(labels).map(([key, val]) => {
            const keyDef = (labelKeys ?? []).find((lk) => lk.key === key);
            const displayKey =
              keyDef?.show_description && keyDef?.description
                ? keyDef.description
                : key;
            const lColor = keyDef?.color;
            return (
              <div
                key={key}
                className="flex items-center gap-2 px-3 py-2 rounded-md"
                style={lColor ? { backgroundColor: `${lColor}10` } : undefined}
              >
                <span
                  className="text-xs font-mono flex-1 inline-flex items-center gap-1.5"
                  style={lColor ? { color: lColor } : undefined}
                >
                  <span
                    className={lColor ? "font-medium" : "text-zinc-400"}
                    title={
                      keyDef?.description
                        ? `${keyDef.description} (${key})`
                        : key
                    }
                  >
                    {displayKey}
                  </span>
                  <span className="text-zinc-600">=</span>
                  <span className={lColor ? "text-zinc-200" : "text-zinc-200"}>
                    {val}
                  </span>
                </span>
                {!disabled && (
                  <button
                    type="button"
                    onClick={() => handleRemove(key)}
                    className="rounded p-0.5 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                    title={`Remove label "${key}"`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-zinc-600">No labels set.</p>
      )}

      {/* Add new label */}
      {!disabled && (
        <>
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <Input
                placeholder="key"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAdd();
                  }
                }}
                className="font-mono text-xs"
                list={`${uid}-key-suggestions`}
              />
              <datalist id={`${uid}-key-suggestions`}>
                {availableKeys.map((lk) => (
                  <option key={lk.id} value={lk.key}>
                    {lk.description ?? lk.key}
                  </option>
                ))}
              </datalist>
            </div>
            <div className="flex-1">
              <Input
                placeholder="value"
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAdd();
                  }
                }}
                className="font-mono text-xs"
                list={`${uid}-value-suggestions`}
              />
              <datalist id={`${uid}-value-suggestions`}>
                {(suggestedValues ?? []).map((v) => (
                  <option key={v} value={v} />
                ))}
              </datalist>
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={handleAdd}
            >
              <Plus className="h-3.5 w-3.5" />
              Add
            </Button>
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
        </>
      )}
    </div>
  );
}
