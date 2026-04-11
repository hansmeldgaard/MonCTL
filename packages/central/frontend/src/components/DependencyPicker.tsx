import { useState } from "react";
import { Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button.tsx";
import { Input } from "@/components/ui/input.tsx";
import { Select } from "@/components/ui/select.tsx";
import type { IncidentRule, IncidentRuleDependsOn } from "@/types/api.ts";

interface DependencyPickerProps {
  value: IncidentRuleDependsOn | null;
  onChange: (next: IncidentRuleDependsOn | null) => void;
  // All currently-enabled incident rules, excluding the one being edited
  // (a rule can't self-reference; phase 2d engine filters it at runtime
  // anyway but the picker should never offer it as an option).
  availableRules: IncidentRule[];
  currentRuleId?: string;
  disabled?: boolean;
}

/**
 * Mirrors `_validate_depends_on` in
 * packages/central/src/monctl_central/incidents/engine.py:185.
 * `value = null` is "no dependencies" — valid. Otherwise `rule_ids` must
 * be a non-empty list of UUID strings; `match_on` must be a (possibly
 * empty) list of non-empty label-key strings.
 */
export function validateDependsOn(
  value: IncidentRuleDependsOn | null,
): { ok: true } | { ok: false; error: string } {
  if (value === null) return { ok: true };
  if (!Array.isArray(value.rule_ids) || value.rule_ids.length === 0) {
    return {
      ok: false,
      error: "Select at least one parent rule, or clear dependencies.",
    };
  }
  if (!Array.isArray(value.match_on)) {
    return { ok: false, error: "match_on must be a list" };
  }
  for (const key of value.match_on) {
    if (!key || typeof key !== "string" || !key.trim()) {
      return {
        ok: false,
        error: "match_on keys cannot be empty",
      };
    }
  }
  return { ok: true };
}

export function DependencyPicker({
  value,
  onChange,
  availableRules,
  currentRuleId,
  disabled = false,
}: DependencyPickerProps) {
  const [newParentId, setNewParentId] = useState<string>("");
  const [newMatchKey, setNewMatchKey] = useState<string>("");

  const selectableRules = availableRules.filter(
    (r) => r.id !== currentRuleId && !(value?.rule_ids ?? []).includes(r.id),
  );

  const ruleName = (id: string): string => {
    const found = availableRules.find((r) => r.id === id);
    return found ? found.name : id;
  };

  const enable = () => {
    onChange({ rule_ids: [], match_on: [] });
  };

  const clearAll = () => {
    onChange(null);
    setNewParentId("");
    setNewMatchKey("");
  };

  const addParent = () => {
    if (!newParentId) return;
    const current = value ?? { rule_ids: [], match_on: [] };
    if (current.rule_ids.includes(newParentId)) return;
    onChange({
      ...current,
      rule_ids: [...current.rule_ids, newParentId],
    });
    setNewParentId("");
  };

  const removeParent = (id: string) => {
    if (!value) return;
    onChange({
      ...value,
      rule_ids: value.rule_ids.filter((r) => r !== id),
    });
  };

  const addMatchKey = () => {
    const key = newMatchKey.trim();
    if (!key) return;
    const current = value ?? { rule_ids: [], match_on: [] };
    if (current.match_on.includes(key)) return;
    onChange({
      ...current,
      match_on: [...current.match_on, key],
    });
    setNewMatchKey("");
  };

  const removeMatchKey = (key: string) => {
    if (!value) return;
    onChange({
      ...value,
      match_on: value.match_on.filter((k) => k !== key),
    });
  };

  const validation = validateDependsOn(value);

  // ── Empty state ──────────────────────────────────────────
  if (value === null) {
    return (
      <div className="space-y-3">
        <div className="rounded border border-dashed border-zinc-800 bg-zinc-900/40 px-4 py-6 text-center">
          <p className="text-sm text-zinc-400">No dependencies configured.</p>
          <p className="text-xs text-zinc-600 mt-1">
            Without dependencies, this rule fires independently of other rules.
            Add parent rules to suppress this rule's incidents under a
            higher-priority parent incident.
          </p>
          {!disabled && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={enable}
              className="mt-3"
            >
              <Plus className="h-3.5 w-3.5" />
              Enable dependencies
            </Button>
          )}
        </div>
      </div>
    );
  }

  // ── Editor ───────────────────────────────────────────────
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-xs text-zinc-500">
          This rule will be suppressed under any of the parent rules below when
          a parent incident exists with matching labels. A suppressed incident
          still tracks in the DB but won't trigger notifications in phase 4+ —
          the UI filters on <code>parent_incident_id IS NULL</code> to show
          primaries.
        </p>
        {!disabled && (
          <Button type="button" size="sm" variant="ghost" onClick={clearAll}>
            Clear
          </Button>
        )}
      </div>

      {/* Parent rules section */}
      <div className="space-y-2">
        <p className="text-[11px] uppercase tracking-wider text-zinc-500 font-medium">
          Parent rules
        </p>
        {value.rule_ids.length === 0 ? (
          <p className="text-xs text-zinc-600 italic">
            No parents yet — add one below.
          </p>
        ) : (
          <div className="rounded-md border border-zinc-800 divide-y divide-zinc-800">
            {value.rule_ids.map((id) => (
              <div
                key={id}
                className="flex items-center justify-between px-3 py-2"
              >
                <span className="text-xs text-zinc-200 font-medium">
                  {ruleName(id)}
                </span>
                {!disabled && (
                  <button
                    type="button"
                    onClick={() => removeParent(id)}
                    className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                    title="Remove parent"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {!disabled && (
          <div className="flex items-center gap-2">
            <Select
              value={newParentId}
              onChange={(e) => setNewParentId(e.target.value)}
              className="flex-1 text-xs"
            >
              <option value="">Select a parent rule…</option>
              {selectableRules.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </Select>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={addParent}
              disabled={!newParentId}
            >
              <Plus className="h-3.5 w-3.5" />
              Add
            </Button>
          </div>
        )}
      </div>

      {/* Match-on section */}
      <div className="space-y-2 border-t border-zinc-800 pt-5">
        <p className="text-[11px] uppercase tracking-wider text-zinc-500 font-medium">
          Match on labels
        </p>
        <p className="text-xs text-zinc-500">
          Only suppress when the parent and child incident have equal values for
          every label key listed here. Leave empty to suppress on any parent
          match (usually too broad). Typical choice:{" "}
          <code className="font-mono">device_id</code> or{" "}
          <code className="font-mono">device_name</code>.
        </p>
        {value.match_on.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {value.match_on.map((key) => (
              <span
                key={key}
                className="inline-flex items-center gap-1 rounded-full bg-zinc-800 pl-2.5 pr-1 py-0.5 text-xs text-zinc-200 font-mono"
              >
                {key}
                {!disabled && (
                  <button
                    type="button"
                    onClick={() => removeMatchKey(key)}
                    className="ml-0.5 rounded-full p-0.5 text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </span>
            ))}
          </div>
        )}
        {!disabled && (
          <div className="flex items-center gap-2">
            <Input
              value={newMatchKey}
              onChange={(e) => setNewMatchKey(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addMatchKey();
                }
              }}
              placeholder="device_name"
              className="flex-1 font-mono text-xs"
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={addMatchKey}
              disabled={!newMatchKey.trim()}
            >
              <Plus className="h-3.5 w-3.5" />
              Add key
            </Button>
          </div>
        )}
      </div>

      {!validation.ok && (
        <div className="rounded border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
          {validation.error}
        </div>
      )}
    </div>
  );
}
