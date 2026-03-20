import { useState, useMemo } from "react";
import { Plus, X, Package } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Select } from "@/components/ui/select.tsx";
import { usePythonModules, usePythonModuleDetail } from "@/api/hooks.ts";

interface ModulePickerProps {
  value: string[];
  onChange: (reqs: string[]) => void;
}

export function ModulePicker({ value, onChange }: ModulePickerProps) {
  const { data: modulesResp } = usePythonModules();
  const modules = modulesResp?.data ?? [];
  const [selectedModuleId, setSelectedModuleId] = useState("");
  const { data: moduleDetail } = usePythonModuleDetail(selectedModuleId || undefined);
  const [selectedVersion, setSelectedVersion] = useState("");

  // Parse existing requirements to track what's already added
  const existingNames = useMemo(() => {
    return new Set(
      value.map((r) => {
        // Extract package name from requirement specifier (e.g., "requests>=2.0" -> "requests")
        const match = r.match(/^([a-zA-Z0-9_-]+)/);
        return match ? match[1].toLowerCase() : r.toLowerCase();
      }),
    );
  }, [value]);

  const availableModules = useMemo(() => {
    if (!modules) return [];
    return modules.filter((m) => m.is_approved);
  }, [modules]);

  function handleAdd() {
    if (!moduleDetail || !selectedVersion) return;
    const reqString = `${moduleDetail.name}==${selectedVersion}`;
    onChange([...value, reqString]);
    setSelectedModuleId("");
    setSelectedVersion("");
  }

  function handleRemove(index: number) {
    onChange(value.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-3">
      {/* Add from registry */}
      <div className="flex items-end gap-2">
        <div className="flex-1 space-y-1">
          <label className="text-xs text-zinc-500">Module</label>
          <Select
            value={selectedModuleId}
            onChange={(e) => {
              setSelectedModuleId(e.target.value);
              setSelectedVersion("");
            }}
          >
            <option value="">Select a module...</option>
            {availableModules.map((m) => (
              <option key={m.id} value={m.id} disabled={existingNames.has(m.name.toLowerCase())}>
                {m.name} ({m.version_count} versions)
                {existingNames.has(m.name.toLowerCase()) ? " (added)" : ""}
              </option>
            ))}
          </Select>
        </div>
        {moduleDetail && moduleDetail.versions.length > 0 && (
          <div className="w-40 space-y-1">
            <label className="text-xs text-zinc-500">Version</label>
            <Select
              value={selectedVersion}
              onChange={(e) => setSelectedVersion(e.target.value)}
            >
              <option value="">Version...</option>
              {moduleDetail.versions.map((v) => (
                <option key={v.id} value={v.version}>
                  {v.version}
                  {v.is_verified ? " (verified)" : ""}
                </option>
              ))}
            </Select>
          </div>
        )}
        <Button
          size="sm"
          onClick={handleAdd}
          disabled={!selectedModuleId || !selectedVersion}
          className="gap-1"
        >
          <Plus className="h-3.5 w-3.5" />
          Add
        </Button>
      </div>

      {/* Selected requirements list */}
      {value.length > 0 ? (
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">Requirements ({value.length})</label>
          <div className="flex flex-wrap gap-1.5">
            {value.map((req, i) => (
              <Badge key={i} variant="default" className="gap-1 font-mono text-xs">
                {req}
                <button
                  onClick={() => handleRemove(i)}
                  className="rounded-full p-0.5 hover:bg-zinc-600 transition-colors cursor-pointer"
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-4 text-zinc-600">
          <Package className="h-5 w-5 mb-1" />
          <p className="text-xs">No requirements added</p>
        </div>
      )}
    </div>
  );
}
