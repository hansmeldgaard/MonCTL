import { useState } from "react";
import { Plus, X } from "lucide-react";
import { Input } from "@/components/ui/input.tsx";
import { Button } from "@/components/ui/button.tsx";

interface KeyValueEditorProps {
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
}

export function KeyValueEditor({
  value,
  onChange,
  keyPlaceholder = "key",
  valuePlaceholder = "value",
}: KeyValueEditorProps) {
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  function handleAdd() {
    const k = newKey.trim();
    if (!k) return;
    onChange({ ...value, [k]: newValue.trim() });
    setNewKey("");
    setNewValue("");
  }

  function handleRemove(key: string) {
    const next = { ...value };
    delete next[key];
    onChange(next);
  }

  return (
    <div className="space-y-2">
      {Object.keys(value).length > 0 && (
        <div className="rounded-md border border-zinc-800 divide-y divide-zinc-800">
          {Object.entries(value).map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 px-3 py-2">
              <span className="text-xs font-mono text-zinc-300 flex-1">
                <span className="text-zinc-400">{k}</span>
                <span className="text-zinc-600 mx-1">=</span>
                <span className="text-zinc-200">{v}</span>
              </span>
              <button
                type="button"
                onClick={() => handleRemove(k)}
                className="rounded p-0.5 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Input
          placeholder={keyPlaceholder}
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleAdd();
            }
          }}
          className="flex-1 font-mono text-xs"
        />
        <Input
          placeholder={valuePlaceholder}
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleAdd();
            }
          }}
          className="flex-1 font-mono text-xs"
        />
        <Button type="button" size="sm" variant="secondary" onClick={handleAdd}>
          <Plus className="h-3.5 w-3.5" />
          Add
        </Button>
      </div>
    </div>
  );
}
